# MYVINECHURCH.ONLINE/app/routes/public/prophecies/__init__.py
# Full path: MYVINECHURCH.ONLINE/app/routes/public/prophecies/__init__.py
# File name: __init__.py
# Brief, detailed purpose: Public Prophecies sub-blueprint initializer. Creates the prophecies_bp with correct url_prefix='/prophecies' and points to the dedicated public templates folder. Imports the views/routes so the main public/__init__.py can register it cleanly. Follows the exact modular public structure plan.

from flask import Blueprint

prophecies_bp = Blueprint(
    'public_prophecies',
    __name__,
    url_prefix='/prophecies',
    template_folder='../../../templates/public/prophecies',
    static_folder='../../../static'
)

# Import views/routes (next file we will rebuild)
from . import views

print("✅ MYVINECHURCH.ONLINE public/prophecies sub-blueprint initialized successfully (url_prefix='/prophecies')")