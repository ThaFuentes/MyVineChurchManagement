# MYVINECHURCH.ONLINE/app/routes/public/announcements/__init__.py
# Full path: MYVINECHURCH.ONLINE/app/routes/public/announcements/__init__.py
# File name: __init__.py
# Brief, detailed purpose: Public Announcements sub-blueprint initializer. Creates the announcements_bp with correct url_prefix='/public-announcements' (to avoid collision with the private 'announcements' blueprint) and points to the dedicated public templates folder. Imports the views/routes so the main public/__init__.py can register it cleanly. Follows the exact modular public structure plan and Events gold standard (same fix we applied to public/events, public/dreams, public/sermons, and public/prophecies).

from flask import Blueprint

announcements_bp = Blueprint(
    'public_announcements',
    __name__,
    url_prefix='/public-announcements',          # ← CHANGED: prevents private blueprint from stealing the route (same fix used for all other public sections)
    template_folder='../../../templates/public/announcements',
    static_folder='../../../static'
)

# Import views/routes (next file we will rebuild)
from . import views

print("✅ MYVINECHURCH.ONLINE public/announcements sub-blueprint initialized successfully (url_prefix='/public-announcements' — route conflict fixed)")