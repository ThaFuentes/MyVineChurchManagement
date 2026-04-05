# app/routes/public/__init__.py
# Full path: MyVineChurch/app/routes/public/__init__.py
# File name: __init__.py
# Brief, detailed purpose: Public Blueprint Package Initializer – 100% MariaDB/pymysql compatible.
# • Creates the exact same Blueprint(name='public') as the old flat file (no url_prefix).
# • Automatically imports ALL modular files so every route registers instantly.
# • Zero functional change today – public dashboard, events, sermons, announcements, prayers, dreams, prophecies, donate page, potluck signup, server-side censorship all remain 100% identical.
# • Designed purely for future scaling: we can now safely add more public pages without touching app/__init__.py or main.py.

from flask import Blueprint

# ----------------------------------------------------------------------
# Blueprint definition (identical to old public.py)
# ----------------------------------------------------------------------
public_bp = Blueprint(
    'public',
    __name__
)

# ----------------------------------------------------------------------
# Import ALL modules – routes register automatically
# ----------------------------------------------------------------------
from . import views
from . import queries
from . import forms
from . import utils

# Re-export for easy import in app/__init__.py
__all__ = ['public_bp']