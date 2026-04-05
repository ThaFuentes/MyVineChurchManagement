# app/__init__.py
# Full path: WebChurchMan/app/__init__.py
# File name: __init__.py
# Brief, detailed purpose: Flask application factory for MYVINECHURCH.ONLINE.
#   - Loads .env + MariaDB configuration
#   - Initializes DB schema silently on first request
#   - Registers all blueprints (core + pastoral + modular packages)
#   - Injects global settings, Jinja filters, and template context processors
#   - Handles smart root redirect and initial Owner setup enforcement
#   - Fully supports package-style blueprints (sermons/, tickets/, dreams/, etc.)

from flask import Flask, g, session, redirect, url_for, request, render_template, flash
from markupsafe import Markup
from datetime import datetime
import os
import importlib

# Load environment variables from project root
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))


# ──────────────────────────────────────────────────────────────────────────────
# Core model & utility imports
# ──────────────────────────────────────────────────────────────────────────────
from app.builddb.builddb import build_all
from .models.db import close_db
from .models.owner import owner_exists
from .models.settings import get_settings
from app.utils.helpers import censor_text
from app.models.pastoral.shared import is_in_pastoral_group
from app.utils.decorators import user_has_permission


def create_app():
    """
    Create and configure the Flask application instance.
    Returns fully initialized app ready for WSGI / development server.
    """
    # Static folder (absolute path for reliability)
    static_folder = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'static'))
    app = Flask(__name__, static_folder=static_folder)

    # ──────────────────────────────────────────────────────────────────────────────
    # Configuration (pulled from .env – fallback values for dev safety)
    # ──────────────────────────────────────────────────────────────────────────────
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or 'dev-insecure-change-this-immediately-2026'

    # MariaDB / PyMySQL connection settings
    app.config['MYSQL_HOST']     = os.environ.get('MYSQL_HOST', 'localhost')
    app.config['MYSQL_USER']     = os.environ.get('MYSQL_USER', 'churchuser')
    app.config['MYSQL_PASSWORD'] = os.environ.get('MYSQL_PASSWORD', '')
    app.config['MYSQL_DATABASE'] = os.environ.get('MYSQL_DATABASE', 'church_management')
    app.config['MYSQL_PORT']     = int(os.environ.get('MYSQL_PORT', 3306))

    # Fernet encryption key (for email credentials, etc.)
    app.config['FERNET_KEY'] = os.environ.get('FERNET_KEY')

    # File upload & export directories (persistent)
    app.config['UPLOAD_FOLDER'] = os.path.abspath(os.path.join(app.root_path, '..', 'uploads'))
    app.config['EXPORT_FOLDER'] = os.path.abspath(os.path.join(app.root_path, '..', 'export'))
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(app.config['EXPORT_FOLDER'], exist_ok=True)

    # Max upload size (32 MB)
    app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024

    # Close DB connection at end of each request
    app.teardown_appcontext(close_db)

    # ──────────────────────────────────────────────────────────────────────────────
    # Silent DB schema initialization (runs once on first request)
    # ──────────────────────────────────────────────────────────────────────────────
    with app.app_context():
        build_all(verbose=False)   # False = silent in production

    # ──────────────────────────────────────────────────────────────────────────────
    # Global settings (available in g on every request)
    # ──────────────────────────────────────────────────────────────────────────────
    @app.before_request
    def load_global_settings():
        g.settings = get_settings()

    # ──────────────────────────────────────────────────────────────────────────────
    # Custom Jinja filters
    # ──────────────────────────────────────────────────────────────────────────────
    @app.template_filter('nl2br')
    def nl2br_filter(value: str) -> Markup:
        if not value:
            return Markup('')
        return Markup(value.replace('\n', '<br>\n'))

    app.jinja_env.filters['censor'] = censor_text

    @app.template_filter('relative_time')
    def relative_time_filter(value):
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
            return f"{int(seconds//60)} minute{'s' if int(seconds//60) != 1 else ''} ago"
        elif seconds < 86400:
            return f"{int(seconds//3600)} hour{'s' if int(seconds//3600) != 1 else ''} ago"
        elif seconds < 2592000:
            return f"{int(seconds//86400)} day{'s' if int(seconds//86400) != 1 else ''} ago"
        elif seconds < 31536000:
            return f"{int(seconds//2592000)} month{'s' if int(seconds//2592000) != 1 else ''} ago"
        else:
            return f"{int(seconds//31536000)} year{'s' if int(seconds//31536000) != 1 else ''} ago"

    @app.template_filter('escape_js')
    def escape_js_filter(value):
        if not value:
            return ''
        value = str(value)
        for old, new in [('\\', '\\\\'), ("'", "\\'"), ('"', '\\"'), ('\n', '\\n'), ('\r', '\\r'), ('\t', '\\t')]:
            value = value.replace(old, new)
        return value

    # ──────────────────────────────────────────────────────────────────────────────
    # Template context processors
    # ──────────────────────────────────────────────────────────────────────────────
    @app.context_processor
    def inject_permissions():
        """Expose user_has_permission helper to all templates."""
        return dict(user_has_permission=user_has_permission)

    @app.context_processor
    def inject_pastoral_access():
        """Expose in_pastoral_group check to templates."""
        return dict(in_pastoral_group=is_in_pastoral_group(session.get('user_id')))

    # ──────────────────────────────────────────────────────────────────────────────
    # Blueprint Registration
    # ──────────────────────────────────────────────────────────────────────────────
    # Required core blueprints – fail loud if missing
    required_blueprints = ['auth', 'dashboard', 'public']
    for name in required_blueprints:
        module = importlib.import_module(f'app.routes.{name}')
        blueprint = getattr(module, f'{name}_bp')
        app.register_blueprint(blueprint)

    # Pastoral area – always registered
    from app.routes.pastoral import pastoral_bp
    app.register_blueprint(pastoral_bp)

    # Optional / modularized features (package-style folders)
    # Already converted: sermons, tickets, dreams
    # Next candidates: profile (family), members, prayers, prophecies, announcements, public
    optional_blueprints = [
        'announcements', 'attendance', 'bills', 'donations', 'dreams', 'events',
        'groups', 'inventory', 'log', 'members', 'prayers', 'profile', 'prophecies',
        'settings', 'sermons', 'tickets', 'emailer'
    ]

    for name in optional_blueprints:
        try:
            module = importlib.import_module(f'app.routes.{name}')
            blueprint = getattr(module, f'{name}_bp')
            app.register_blueprint(blueprint)
        except (ImportError, AttributeError):
            pass  # Feature not yet converted – silent skip

    # ──────────────────────────────────────────────────────────────────────────────
    # Root Route & Smart Redirect
    # ──────────────────────────────────────────────────────────────────────────────
    @app.route('/')
    def index():
        """Root redirect: logged-in → private dashboard, guests → public welcome."""
        if session.get('user_id'):
            return redirect(url_for('dashboard.dashboard'))
        return redirect(url_for('public.public_dashboard'))

    # ──────────────────────────────────────────────────────────────────────────────
    # Owner Registration Enforcement (skip public/auth/static routes)
    # ──────────────────────────────────────────────────────────────────────────────
    @app.before_request
    def enforce_owner_registration():
        if (request.path.startswith('/static/') or
            request.blueprint in ['public', None] or
            (request.endpoint and request.endpoint.startswith('auth.'))):
            return

        if not owner_exists():
            flash('Initial setup required – please register the first Owner.', 'info')
            return redirect(url_for('auth.register'))

    # ──────────────────────────────────────────────────────────────────────────────
    # Error Handlers
    # ──────────────────────────────────────────────────────────────────────────────
    @app.errorhandler(404)
    def page_not_found(e):
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def internal_error(e):
        return render_template('errors/500.html'), 500

    return app