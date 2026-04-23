# MYVINECHURCH.ONLINE/app/routes/public/__init__.py
# Full path: MYVINECHURCH.ONLINE/app/routes/public/__init__.py
# File name: __init__.py
# Brief, detailed purpose: Main public blueprint package initializer. Creates the core public_bp and registers ALL feature-specific sub-blueprints (public_dashboard, dreams, events, announcements, prophecies, sermons, prayers, etc.) following the clean modular sub-folder structure. This replaces the old temporary giant public/views.py and enforces public-only access with automatic logged-in redirection to private views where required.

from flask import Blueprint

# ──────────────────────────────────────────────────────────────
# Main public blueprint (root-level, no extra prefix)
# ──────────────────────────────────────────────────────────────
public_bp = Blueprint(
    'public',
    __name__,
    template_folder='../templates/public',
    static_folder='../static'
)

# ──────────────────────────────────────────────────────────────
# Register all public feature sub-blueprints
# (Each sub-module defines its own bp in its __init__.py)
# ──────────────────────────────────────────────────────────────

# Public Dashboard (rich feed on / and /public) – root routes
from .public_dashboard import dashboard_bp
public_bp.register_blueprint(dashboard_bp)

# Announcements
from .announcements import announcements_bp
public_bp.register_blueprint(announcements_bp)

# Dreams & Visions
from .dreams import dreams_bp
public_bp.register_blueprint(dreams_bp)

# Events (potluck, signups, comments.html)
from .events import events_bp
public_bp.register_blueprint(events_bp)

# Prayers
from .prayers import prayers_bp
public_bp.register_blueprint(prayers_bp)

# Prophecies
from .prophecies import prophecies_bp
public_bp.register_blueprint(prophecies_bp)

# Sermons
from .sermons import sermons_bp
public_bp.register_blueprint(sermons_bp)

print("✅ MYVINECHURCH.ONLINE public routes structure initialized – all sub-blueprints registered successfully")