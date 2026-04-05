# app/routes/donations/utils.py
# Full path: MyVineChurch/app/routes/donations/utils.py
# File name: utils.py
# Brief, detailed purpose: Utility functions and constants for the Donations module.
# • REQUIRED_ROLES and ADMIN_OWNER_ONLY constants
# • get_church_info() helper (moved from views.py for clean separation)
# • Keeps views.py thin and focused – all shared logic lives here.
# • 100% matches the original donations.py behavior.

from app.models.db import get_db
import pymysql


# ----------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------
REQUIRED_ROLES = ['Staff', 'Admin', 'Owner']
ADMIN_OWNER_ONLY = ['Admin', 'Owner']


# ----------------------------------------------------------------------
# Church Info Helper
# ----------------------------------------------------------------------
def get_church_info():
    """Fetch church details from settings table – used in templates and exports."""
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)
    cur.execute('''
        SELECT church_name, address, phone_number, pastor, tax_status 
        FROM settings LIMIT 1
    ''')
    row = cur.fetchone()
    return row or {}