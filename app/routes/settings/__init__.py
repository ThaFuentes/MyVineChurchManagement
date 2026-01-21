# app/routes/settings/__init__.py
# Full path: myvinechurchonline/app/routes/settings/__init__.py
# File name: __init__.py
# Brief, detailed purpose: Settings blueprint factory + shared utilities.
# Registers sub-module routes. Contains all shared constants, encryption, permission system, and loaders.
# No direct routes here except root redirect.
# FULL REBUILD: Added timezone sub-module import and permission entry.
#          All existing functionality preserved exactly.

from flask import Blueprint, redirect, url_for, session, flash, current_app
from app.utils.decorators import login_required
from app.utils.helpers import contains_censored_word
from app.models.db import get_db
from app.models.log import log_change
from werkzeug.utils import secure_filename
from cryptography.fernet import Fernet
import os
import json
import pymysql

settings_bp = Blueprint('settings', __name__, url_prefix='/settings')

# ----------------------------------------------------------------------
# Constants & Shared Paths
# ----------------------------------------------------------------------
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
DONATIONS_FOLDER = os.path.join('static', 'uploads', 'donations')

# Encryption setup (same as original)
key_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'config_key.bin')
env_key = os.environ.get('ENCRYPTION_KEY')
if env_key:
    key = env_key.encode()
elif os.path.exists(key_path):
    with open(key_path, 'rb') as f:
        key = f.read()
else:
    key = Fernet.generate_key()
    with open(key_path, 'wb') as f:
        f.write(key)

cipher = Fernet(key)

def encrypt(text: str) -> str:
    return cipher.encrypt(text.encode()).decode() if text else ''

def decrypt(token: str) -> str:
    if not token:
        return ''
    try:
        return cipher.decrypt(token.encode()).decode()
    except Exception:
        return ''

def allowed_file(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ----------------------------------------------------------------------
# Permission System
# ----------------------------------------------------------------------
SECTION_PERMISSIONS = {
    'general': 'settings.general',
    'email': 'settings.email',
    'ai': 'settings.ai',
    'online_giving': 'settings.online_giving',
    'censored_words': 'settings.censored_words',
    'ticket_managers': 'settings.ticket_managers',
    'timezone': 'settings.timezone',  # ← ADDED: Permission entry for timezone section (Admin/Owner always allowed)
}

def has_section_permission(section: str) -> bool:
    if session.get('user_role') in ['Admin', 'Owner']:
        return True
    try:
        perms = json.loads(session.get('settings_permissions', '[]'))
    except (json.JSONDecodeError, TypeError):
        perms = []
    return SECTION_PERMISSIONS.get(section) in perms

def can_view_settings() -> bool:
    if session.get('user_role') in ['Admin', 'Owner']:
        return True
    try:
        perms = json.loads(session.get('settings_permissions', '[]'))
    except (json.JSONDecodeError, TypeError):
        perms = []
    return bool(perms)

# ----------------------------------------------------------------------
# Global Access Control
# ----------------------------------------------------------------------
@settings_bp.before_request
@login_required
def restrict_to_authorized():
    if not can_view_settings():
        flash('You do not have permission to access settings.', 'error')
        return redirect(url_for('dashboard.dashboard'))

# ----------------------------------------------------------------------
# Shared Loaders
# ----------------------------------------------------------------------
def load_settings():
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)
    cur.execute("SELECT * FROM settings WHERE id = 1")
    row = cur.fetchone()
    return row or {}

def load_online_options():
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)
    cur.execute("SELECT * FROM online_donation_options ORDER BY sort_order ASC")
    return cur.fetchall()

def load_email_accounts():
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)
    cur.execute("SELECT * FROM email_accounts ORDER BY is_default DESC, name ASC")
    accounts = cur.fetchall()
    for acc in accounts:
        acc['outgoing_username_dec'] = decrypt(acc.get('outgoing_username', ''))
        acc['incoming_username_dec'] = decrypt(acc.get('incoming_username', ''))
    return accounts

# ----------------------------------------------------------------------
# Root Redirect
# ----------------------------------------------------------------------
@settings_bp.route('/')
def index():
    return redirect(url_for('settings.general'))

# Import sub-modules to register their routes (exactly how existing pages work)
from . import general
from . import email
from . import ai
from . import online_giving
from . import censored_words
from . import ticket_managers
from . import timezone  # ← ADDED: Registers the timezone route (same pattern as ai, general, etc.)