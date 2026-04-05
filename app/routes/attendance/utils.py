# app/routes/attendance/utils.py
# Full path: MyVineChurch/app/routes/attendance/utils.py
# File name: utils.py
# Brief, detailed purpose: Utility functions and constants for the Attendance module.
# • REQUIRED_ROLES constant
# • Secure kiosk token generation + expiration
# • Keeps views.py, queries.py, and forms.py clean and focused
# • Ready for future growth (add report helpers, timezone tools, etc.)

from datetime import datetime, timedelta
import secrets


# ----------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------
REQUIRED_ROLES = ['Staff', 'Admin', 'Owner']


# ----------------------------------------------------------------------
# Kiosk Helpers
# ----------------------------------------------------------------------
def generate_kiosk_token():
    """Generate secure random token for kiosk sessions."""
    return secrets.token_urlsafe(32)


def get_kiosk_expiration():
    """Return expiration datetime (8 hours from now)."""
    return datetime.now() + timedelta(hours=8)