# MYVINECHURCH.ONLINE/app/routes/public/prayers/__init__.py
# Full path: MYVINECHURCH.ONLINE/app/routes/public/prayers/__init__.py
# File name: __init__.py
# Brief, detailed purpose: Public Prayers sub-blueprint initializer.
# • CHANGED: url_prefix='/public-prayers' (unique prefix) to prevent the private 'prayers' blueprint
#   (registered first in app/__init__.py) from stealing the /prayers/ route and forcing guests to login.
# • All other public sub-blueprints already use unique prefixes or were fixed the same way.
# • Template and static paths unchanged. Views will be updated next (one file at a time).

from flask import Blueprint

prayers_bp = Blueprint(
    'public_prayers',
    __name__,
    url_prefix='/public-prayers',          # ← THIS IS THE FIX
    template_folder='../../../templates/public/prayers',
    static_folder='../../../static'
)

# Import views/routes
from . import views

