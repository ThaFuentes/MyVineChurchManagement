# MYVINECHURCH.ONLINE/app/routes/public/public_dashboard/__init__.py
# Full path: MYVINECHURCH.ONLINE/app/routes/public/public_dashboard/__init__.py
# File name: __init__.py
# Brief, detailed purpose: Public Dashboard sub-blueprint initializer (rich social-media style feed on home page).
# Creates the dashboard_bp with NO url_prefix (serves root routes / and /public) and points to the shared public templates folder.
# Imports the views so the main public/__init__.py can register it cleanly. Follows the exact modular public structure plan.
# This is the central homepage that will reuse all our existing public_xxx queries with smart priority ordering.
# FIXED: template_folder changed to '../../templates/public' to stop overshooting the templates folder.

from flask import Blueprint

dashboard_bp = Blueprint(
    'public_dashboard',
    __name__,
    # No url_prefix – this blueprint serves the root homepage
    # Updated path: from app/routes/public/public_dashboard/ → app/templates/public
    # (two levels up instead of three to match your folder structure)
    template_folder='../../templates/public',
    static_folder='../../static'
)

# Import views/routes (next file we will rebuild)
from . import views

print("✅ MYVINECHURCH.ONLINE public/public_dashboard sub-blueprint initialized successfully (root homepage routes - path fixed)")