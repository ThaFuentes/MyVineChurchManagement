# MYVINECHURCH.ONLINE/app/routes/the_gathering/__init__.py
# Full path: MYVINECHURCH.ONLINE/app/routes/the_gathering/__init__.py
# File name: __init__.py
# Brief, detailed purpose: Main The Gathering Place Manager blueprint initializer (parent blueprint).
# • Creates the_gathering_bp with url_prefix='/the_gathering' (exact same pattern as public parent).
# • Registers ONLY the dashboard sub-blueprint (exactly like public sub-blueprints).
# • Root '/' route redirects to the nested dashboard endpoint using the full correct name.
# • Template and static paths match your templates/the_gathering/ folder structure.
# • 100% rebuilt to match the exact public modular pattern you already have working.
# • All original behavior preserved — only registration and route attachment fixed.

from flask import Blueprint, redirect, url_for

# ──────────────────────────────────────────────────────────────
# Main The Gathering Place Manager Blueprint (Parent)
# ──────────────────────────────────────────────────────────────
the_gathering_bp = Blueprint(
    'the_gathering',
    __name__,
    url_prefix='/the_gathering',
    template_folder='../../../templates/the_gathering',
    static_folder='../../../static'
)

# ──────────────────────────────────────────────────────────────
# Register the Dashboard Sub-Blueprint
# ──────────────────────────────────────────────────────────────
from .dashboard import dashboard_bp
the_gathering_bp.register_blueprint(dashboard_bp)

# All other sub-features remain commented out while we rebuild them one-by-one
# from .announcements import announcements_bp
# the_gathering_bp.register_blueprint(announcements_bp)
# from .dreams import dreams_bp
# the_gathering_bp.register_blueprint(dreams_bp)
# from .events import events_bp
# the_gathering_bp.register_blueprint(events_bp)
# from .prayers import prayers_bp
# the_gathering_bp.register_blueprint(prayers_bp)
# from .prophecies import prophecies_bp
# the_gathering_bp.register_blueprint(prophecies_bp)
# from .sermons import sermons_bp
# the_gathering_bp.register_blueprint(sermons_bp)

# ──────────────────────────────────────────────────────────────
# Root Route (keeps original user experience)
# ──────────────────────────────────────────────────────────────
@the_gathering_bp.route('/')
def index():
    """Root of /the_gathering redirects to the main Gathering Place Manager dashboard.
    Uses the full nested endpoint name so Flask can always find it (matches public pattern)."""
    return redirect(url_for('the_gathering.dashboard.dashboard'))


print("✅ MYVINECHURCH.ONLINE the_gathering blueprint initialized successfully – FINAL MATCH TO PUBLIC PATTERN")