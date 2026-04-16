# MYVINECHURCH.ONLINE/app/routes/public/sermons/__init__.py
# Full path: MYVINECHURCH.ONLINE/app/routes/public/sermons/__init__.py
# File name: __init__.py
# Brief, detailed purpose: Public Sermons sub-blueprint initializer. Creates the sermons_bp with correct url_prefix='/sermons' and points to the dedicated public templates folder. Imports the views/routes so the main public/__init__.py can register it cleanly. Follows the exact modular public structure plan.

from flask import Blueprint

sermons_bp = Blueprint(
    'public_sermons',
    __name__,
    url_prefix='/sermons',
    template_folder='../../../templates/public/sermons',
    static_folder='../../../static'
)

# Import views/routes (next file we will rebuild)
from . import views

print("✅ MYVINECHURCH.ONLINE public/sermons sub-blueprint initialized successfully (url_prefix='/sermons')")