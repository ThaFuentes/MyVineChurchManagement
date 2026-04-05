# app/routes/auth/__init__.py
# Full path: MyVineChurch/app/routes/auth/__init__.py
# File name: __init__.py
# Brief, detailed purpose: Auth Blueprint Package Initializer – 100% MariaDB/pymysql compatible.
# • Creates the exact same Blueprint(name='auth') as the old flat file (no url_prefix).
# • Automatically imports all modular files so every route registers instantly.
# • Zero functional change today – login, logout, register, password reset, forgot username, root redirect, censorship, Owner creation, pending/banned checks all remain 100% identical.
# • Designed purely for future scaling: we can now safely split into views.py, queries.py, forms.py, utils.py without touching app/__init__.py or main.py.

from flask import Blueprint

# ----------------------------------------------------------------------
# Blueprint definition (identical to old auth.py)
# ----------------------------------------------------------------------
auth_bp = Blueprint('auth', __name__)

# ----------------------------------------------------------------------
# Import route modules (they will define all the @auth_bp.route handlers)
# ----------------------------------------------------------------------
# We do ONE file at a time per your instructions → next we will build views.py
from . import views
# from . import queries
# from . import forms
# from . import utils

# Optional: re-export for easy import in app/__init__.py
__all__ = ['auth_bp']