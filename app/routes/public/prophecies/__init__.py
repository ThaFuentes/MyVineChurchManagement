# MYVINECHURCH.ONLINE/app/routes/public/prophecies/__init__.py
# Full path: MYVINECHURCH.ONLINE/app/routes/public/prophecies/__init__.py
# File name: __init__.py
# Brief, detailed purpose: Public Prophecies sub-blueprint initializer. Creates the prophecies_bp with correct url_prefix='/public-prophecies' (to avoid collision with the private 'prophecies' blueprint) and points to the dedicated public templates folder. Imports the views/routes so the main public/__init__.py can register it cleanly. Follows the exact modular public structure plan and Events gold standard (same fix we applied to public/events, public/dreams, and public/sermons).

from flask import Blueprint

prophecies_bp = Blueprint(
    'public_prophecies',
    __name__,
    url_prefix='/public-prophecies',          # ← CHANGED: prevents private blueprint from stealing the route (same fix used for public-events, public-dreams, and public-sermons)
    template_folder='../../../templates/public/prophecies',
    static_folder='../../../static'
)

# Import views/routes (next file we will rebuild)
from . import views

