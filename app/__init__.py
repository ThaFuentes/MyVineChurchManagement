# app/__init__.py
# Full path: WebChurchMan/app/__init__.py
# File name: __init__.py
# Brief, detailed purpose:
#   Flask application factory – rebuilt for reliability, modularity, and production safety.
#   Core responsibilities:
#     - Loads .env and configures MariaDB connection
#     - Initializes DB schema silently on first request
#     - Registers all core + known blueprints (required fail loud, optional silent)
#     - Injects global settings into g
#     - Adds custom Jinja filters: nl2br, censor, relative_time
#     - Injects permission helpers into template context
#     - Enforces initial Owner registration (skips public/auth/static routes)
#     - Smart root redirect: logged-in → dashboard, else → public
#     - Basic 404/500 error handlers
#   All pastoral features are explicitly registered and always available.

from flask import Flask, g, session, redirect, url_for, request, render_template, flash
from markupsafe import Markup
from datetime import datetime
import os
import importlib

# Load .env from project root
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

# Core utilities & models
from app.builddb.builddb import build_all
from .models.db import close_db
from .models.owner import owner_exists
from .models.settings import get_settings
from app.utils.helpers import censor_text
from app.models.pastoral.shared import is_in_pastoral_group
from app.utils.decorators import user_has_permission


def create_app():
    """
    Application factory for WebChurchMan – full rebuild.

    Returns:
        Flask: Fully configured application instance
    """
    # Static folder path (absolute for reliability)
    static_folder = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'static'))
    app = Flask(__name__, static_folder=static_folder)

    # Configuration from .env
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or 'dev-insecure-change-this-immediately-2026'

    # MariaDB connection settings
    app.config['MYSQL_HOST'] = os.environ.get('MYSQL_HOST', 'localhost')
    app.config['MYSQL_USER'] = os.environ.get('MYSQL_USER', 'churchuser')
    app.config['MYSQL_PASSWORD'] = os.environ.get('MYSQL_PASSWORD', '')
    app.config['MYSQL_DATABASE'] = os.environ.get('MYSQL_DATABASE', 'church_management')
    app.config['MYSQL_PORT'] = int(os.environ.get('MYSQL_PORT', 3306))

    # File upload/export folders (persistent storage)
    app.config['UPLOAD_FOLDER'] = os.path.abspath(os.path.join(app.root_path, '..', 'uploads'))
    app.config['EXPORT_FOLDER'] = os.path.abspath(os.path.join(app.root_path, '..', 'export'))
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(app.config['EXPORT_FOLDER'], exist_ok=True)

    # File upload size limit (32MB default)
    app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024

    # Teardown DB connection at end of each request
    app.teardown_appcontext(close_db)

    # Silent DB schema initialization on first request
    with app.app_context():
        build_all(verbose=False)  # False = silent in production

    # --------------------------------------------------------------------------
    # Global Settings (available in g on every request)
    # --------------------------------------------------------------------------
    @app.before_request
    def load_global_settings():
        g.settings = get_settings()

    # --------------------------------------------------------------------------
    # Custom Jinja Filters
    # --------------------------------------------------------------------------
    @app.template_filter('nl2br')
    def nl2br_filter(value: str) -> Markup:
        """Convert newlines to <br> tags safely."""
        if not value:
            return Markup('')
        return Markup(value.replace('\n', '<br>\n'))

    app.jinja_env.filters['censor'] = censor_text

    @app.template_filter('relative_time')
    def relative_time_filter(value):
        """Human-readable relative time (e.g. '2 hours ago')."""
        if not value:
            return 'never'

        now = datetime.utcnow()
        if hasattr(value, 'tzinfo') and value.tzinfo:
            now = now.replace(tzinfo=value.tzinfo)

        diff = now - value
        seconds = diff.total_seconds()

        if seconds < 60:
            return 'just now'
        elif seconds < 3600:
            m = int(seconds // 60)
            return f"{m} minute{'s' if m != 1 else ''} ago"
        elif seconds < 86400:
            h = int(seconds // 3600)
            return f"{h} hour{'s' if h != 1 else ''} ago"
        elif seconds < 2592000:
            d = int(seconds // 86400)
            return f"{d} day{'s' if d != 1 else ''} ago"
        elif seconds < 31536000:
            mo = int(seconds // 2592000)
            return f"{mo} month{'s' if mo != 1 else ''} ago"
        else:
            y = int(seconds // 31536000)
            return f"{y} year{'s' if y != 1 else ''} ago"

    # --------------------------------------------------------------------------
    # Template Context Processors
    # --------------------------------------------------------------------------
    @app.context_processor
    def inject_permissions():
        """Make user_has_permission available in all templates."""
        return dict(user_has_permission=user_has_permission)

    @app.context_processor
    def inject_pastoral_access():
        """Expose in_pastoral_group check to templates."""
        return dict(in_pastoral_group=is_in_pastoral_group(session.get('user_id')))

    # --------------------------------------------------------------------------
    # Blueprint Registration
    # --------------------------------------------------------------------------
    # Required core blueprints – fail loud if missing (dev safety)
    required_blueprints = [
        ('auth', 'auth_bp'),
        ('dashboard', 'dashboard_bp'),
        ('public', 'public_bp'),
    ]

    for module_name, bp_name in required_blueprints:
        try:
            module = importlib.import_module(f'app.routes.{module_name}')
            blueprint = getattr(module, bp_name)
            app.register_blueprint(blueprint)
        except (ImportError, AttributeError) as e:
            raise ImportError(f"Required blueprint '{module_name}' failed to load: {e}")

    # Pastoral Area – always registered (core to rebuild)
    from app.routes.pastoral import pastoral_bp
    app.register_blueprint(pastoral_bp)

    # Known optional/feature blueprints – register if present, silent fail otherwise
    known_optional = [
        'announcements', 'attendance', 'bills', 'donations', 'dreams', 'events',
        'groups', 'inventory', 'log', 'members', 'prayers', 'profile', 'prophecies',
        'settings', 'sermons', 'tickets'
    ]

    for mod in known_optional:
        try:
            module = importlib.import_module(f'app.routes.{mod}')
            bp_name = f'{mod}_bp'  # Consistent naming convention
            blueprint = getattr(module, bp_name)
            app.register_blueprint(blueprint)
        except (ImportError, AttributeError):
            pass  # Feature not yet implemented – no crash

    # --------------------------------------------------------------------------
    # Root Route & Smart Redirect
    # --------------------------------------------------------------------------
    @app.route('/')
    def index():
        """Root redirect: logged-in users → dashboard, guests → public welcome."""
        if session.get('user_id'):
            return redirect(url_for('dashboard.dashboard'))
        return redirect(url_for('public.public_dashboard'))

    # --------------------------------------------------------------------------
    # Owner Registration Enforcement
    # --------------------------------------------------------------------------
    @app.before_request
    def enforce_owner_registration():
        """Redirect to registration if no Owner exists (skip public/auth/static)."""
        if request.path.startswith('/static/'):
            return

        if request.blueprint in ['public', None]:
            return

        if request.endpoint and request.endpoint.startswith('auth.'):
            return

        if not owner_exists():
            flash('Initial setup required – please register the first Owner.', 'info')
            return redirect(url_for('auth.register'))

    # --------------------------------------------------------------------------
    # Error Handlers
    # --------------------------------------------------------------------------
    @app.errorhandler(404)
    def page_not_found(e):
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def internal_error(e):
        return render_template('errors/500.html'), 500

    return app