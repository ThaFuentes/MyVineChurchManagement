# MYVINECHURCH.ONLINE/app/routes/public/events/__init__.py
# Full path: MYVINECHURCH.ONLINE/app/routes/public/events/__init__.py
# File name: __init__.py
# Brief, detailed purpose: Public Events sub-blueprint initializer. Creates the events_bp with correct url_prefix='/events' and points to the dedicated public templates folder. Imports the views/routes (and will later include forms) so the main public/__init__.py can register it cleanly. Follows the exact modular public structure plan.

from flask import Blueprint

events_bp = Blueprint(
    'public_events',
    __name__,
    url_prefix='/events',
    template_folder='../../../templates/public/events',
    static_folder='../../../static'
)

# Import views/routes (next file we will rebuild)
from . import views

print("✅ MYVINECHURCH.ONLINE public/events sub-blueprint initialized successfully (url_prefix='/events')")