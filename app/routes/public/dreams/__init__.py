# MYVINECHURCH.ONLINE/app/routes/public/dreams/__init__.py
# Full path: MYVINECHURCH.ONLINE/app/routes/public/dreams/__init__.py
# File name: __init__.py
# Brief, detailed purpose: Public Dreams & Visions sub-blueprint initializer. Creates the dreams_bp with correct url_prefix='/public-dreams' (to avoid collision with the private 'dreams' blueprint) and points to the dedicated public templates folder. Imports the views/routes so the main public/__init__.py can register it cleanly. Follows the exact modular public structure plan and Events gold standard.

from flask import Blueprint

dreams_bp = Blueprint(
    'public_dreams',
    __name__,
    url_prefix='/public-dreams',          # ← CHANGED: prevents private blueprint from stealing the route (same fix used for public-events)
    template_folder='../../../templates/public/dreams',
    static_folder='../../../static'
)

# Import views/routes (next file we will rebuild)
from . import views

