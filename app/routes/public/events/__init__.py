# MYVINECHURCH.ONLINE/app/routes/public/events/__init__.py
# Full path: MYVINECHURCH.ONLINE/app/routes/public/events/__init__.py
# File name: __init__.py
# Brief, detailed purpose: Public Events sub-blueprint initializer.
# • CHANGED: url_prefix='/public-events' (unique prefix) to prevent the private 'events' blueprint
#   (registered first in app/__init__.py) from stealing the /events/ route and forcing guests to login.
# • All other public sub-blueprints already use unique prefixes or were fixed the same way.
# • Template and static paths unchanged. Views will be updated next (one file at a time).

from flask import Blueprint

events_bp = Blueprint(
    'public_events',
    __name__,
    url_prefix='/public-events',          # ← THIS IS THE FIX
    template_folder='../../../templates/public/events',
    static_folder='../../../static'
)

# Import views/routes
from . import views

print("✅ MYVINECHURCH.ONLINE public/events sub-blueprint initialized successfully (url_prefix='/public-events')")