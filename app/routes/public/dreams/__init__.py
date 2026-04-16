# MYVINECHURCH.ONLINE/app/routes/public/dreams/__init__.py
# Full path: MYVINECHURCH.ONLINE/app/routes/public/dreams/__init__.py
# File name: __init__.py
# Brief, detailed purpose: Public Dreams & Visions sub-blueprint initializer. Creates the dreams_bp with correct url_prefix='/dreams' and points to the dedicated public templates folder. Imports the views/routes so the main public/__init__.py can register it cleanly. Follows the exact modular public structure plan.

from flask import Blueprint

dreams_bp = Blueprint(
    'public_dreams',
    __name__,
    url_prefix='/dreams',
    template_folder='../../../templates/public/dreams',
    static_folder='../../../static'
)

# Import views/routes (next file we will rebuild)
from . import views

print("✅ MYVINECHURCH.ONLINE public/dreams sub-blueprint initialized successfully (url_prefix='/dreams')")