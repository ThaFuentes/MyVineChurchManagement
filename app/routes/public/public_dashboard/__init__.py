# MYVINECHURCH.ONLINE/app/routes/public/public_dashboard/__init__.py
# Full path: MYVINECHURCH.ONLINE/app/routes/public/public_dashboard/__init__.py
# File name: __init__.py
# Brief, detailed purpose: Public Dashboard sub-blueprint initializer (rich social-media style feed on home page).
# Creates the dashboard_bp with NO url_prefix (root routes / and /public) and points to the shared public templates folder.
# Imports the views so the main public/__init__.py can register it cleanly. Follows the exact modular public structure plan.

from flask import Blueprint

dashboard_bp = Blueprint(
    'public_dashboard',
    __name__,
    # No url_prefix – this blueprint serves the root homepage
    template_folder='../../../templates/public',
    static_folder='../../../static'
)

# Import views/routes (next file we will rebuild)
from . import views

print("✅ MYVINECHURCH.ONLINE public/public_dashboard sub-blueprint initialized successfully (root homepage routes)")