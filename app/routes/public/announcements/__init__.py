# MYVINECHURCH.ONLINE/app/routes/public/announcements/__init__.py
# Full path: MYVINECHURCH.ONLINE/app/routes/public/announcements/__init__.py
# File name: __init__.py
# Brief, detailed purpose: Public Announcements sub-blueprint initializer. Creates the announcements_bp with correct url_prefix='/announcements' and points to the dedicated public templates folder. Imports the views/routes so the main public/__init__.py can register it cleanly. Follows the exact modular public structure plan.

from flask import Blueprint

announcements_bp = Blueprint(
    'public_announcements',
    __name__,
    url_prefix='/announcements',
    template_folder='../../../templates/public/announcements',
    static_folder='../../../static'
)

# Import views/routes (next file we will rebuild)
from . import views

print("✅ MYVINECHURCH.ONLINE public/announcements sub-blueprint initialized successfully (url_prefix='/announcements')")