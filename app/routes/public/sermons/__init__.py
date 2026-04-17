# MYVINECHURCH.ONLINE/app/routes/public/sermons/__init__.py
# Full path: MYVINECHURCH.ONLINE/app/routes/public/sermons/__init__.py
# File name: __init__.py
# Brief, detailed purpose: Public Sermons sub-blueprint initializer. Creates the sermons_bp with correct url_prefix='/public-sermons' (to avoid collision with the private 'sermons' blueprint) and points to the dedicated public templates folder. Imports the views/routes so the main public/__init__.py can register it cleanly. Follows the exact modular public structure plan and Events gold standard (same fix we applied to public/events and public/dreams).

from flask import Blueprint

sermons_bp = Blueprint(
    'public_sermons',
    __name__,
    url_prefix='/public-sermons',          # ← CHANGED: prevents private blueprint from stealing the route (same fix used for public-events and public-dreams)
    template_folder='../../../templates/public/sermons',
    static_folder='../../../static'
)

# Import views/routes
from . import views

print("✅ MYVINECHURCH.ONLINE public/sermons sub-blueprint initialized successfully (url_prefix='/public-sermons' — route conflict fixed)")