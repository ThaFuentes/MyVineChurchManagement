# app/routes/members/utils.py
# Full path: MyVineChurch/app/routes/members/utils.py
# File name: utils.py
# Brief, detailed purpose: Utility functions and constants for the Members module.
# • REQUIRED_ROLES constant
# • current_user_id() helper for logging and ownership
# • Role permission helpers (get_allowed_roles)
# • Temporary password generator (used when adding new members)
# • 100% matches the original members.py helpers and logic.

from flask import session
import random
import string


# ----------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------
REQUIRED_ROLES = ['Staff', 'Admin', 'Owner']


# ----------------------------------------------------------------------
# User Helpers
# ----------------------------------------------------------------------
def current_user_id():
    """Return current logged-in user ID for logging and ownership."""
    return session.get('user_id')


# ----------------------------------------------------------------------
# Role Permission Helpers
# ----------------------------------------------------------------------
def get_allowed_roles(current_role):
    """Return list of roles the current user is allowed to assign to new members."""
    allowed = ['Member']
    if current_role in ['Staff', 'Admin', 'Owner']:
        allowed.append('Staff')
    if current_role in ['Admin', 'Owner']:
        allowed.append('Admin')
    if current_role == 'Owner':
        allowed.append('Owner')
    return allowed


# ----------------------------------------------------------------------
# Password Helpers
# ----------------------------------------------------------------------
def generate_temporary_password(length=12):
    """Generate a secure temporary password for new members."""
    characters = string.ascii_letters + string.digits
    return ''.join(random.choices(characters, k=length))


# ----------------------------------------------------------------------
# Future Growth Placeholders
# ----------------------------------------------------------------------
# These can be expanded when you add more member features (export, bulk import, etc.)
def get_default_member_role():
    """Default role for new members."""
    return 'Member'