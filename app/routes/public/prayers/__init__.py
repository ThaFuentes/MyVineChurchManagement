# MYVINECHURCH.ONLINE/app/routes/public/prayers/__init__.py
# Full path: MYVINECHURCH.ONLINE/app/routes/public/prayers/__init__.py
# File name: __init__.py
# Brief, detailed purpose: Public Prayers sub-blueprint initializer. Creates the prayers_bp with correct url_prefix='/prayers' and points to the dedicated public templates folder. Imports the views/routes so the main public/__init__.py can register it cleanly. Follows the exact modular public structure plan.

from flask import Blueprint

prayers_bp = Blueprint(
    'public_prayers',
    __name__,
    url_prefix='/prayers',
    template_folder='../../../templates/public/prayers',
    static_folder='../../../static'
)

# Import views/routes (next file we will rebuild)
from . import views

print("✅ MYVINECHURCH.ONLINE public/prayers sub-blueprint initialized successfully (url_prefix='/prayers')")