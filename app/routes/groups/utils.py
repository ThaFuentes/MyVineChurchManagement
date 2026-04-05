# app/routes/groups/utils.py
# Full path: MyVineChurch/app/routes/groups/utils.py
# File name: utils.py
# Brief, detailed purpose: Utility functions and constants for the Groups module.
# • KNOWN_PERMISSIONS dictionary (central source of truth for all permissions in the application)
# • is_global_manager() and is_group_leader() helpers
# • Clean, reusable, and consistent with the rest of the app.
# • Designed for easy future growth (add new permission helpers, group validation, etc.)

import pymysql
from app.models.db import get_db


# ----------------------------------------------------------------------
# Known Permissions – FULLY EXPANDED
# ----------------------------------------------------------------------
KNOWN_PERMISSIONS = {
    # Core Content Creation/Moderation
    'create_announcements': 'Create and edit own announcements',
    'moderate_announcements': 'Delete or edit ANY announcement (moderation)',
    'create_events': 'Create and edit own events',
    'moderate_events': 'Delete or edit ANY event (moderation)',
    'manage_event_registration': 'Manage event registrations, fees, and ticketing',
    'upload_sermons': 'Upload and manage sermons',
    'moderate_sermons': 'Delete or edit ANY sermon or comment',
    'moderate_prayers': 'Delete or edit ANY prayer request or response',
    'moderate_dreams': 'Delete or edit ANY dream/vision or comment',
    'moderate_prophecies': 'Delete or edit ANY prophecy or comment',

    # Financial & Operational
    'view_donations': 'View donation records and reports (no editing)',
    'manage_donations': 'Full donation management (record, edit, delete – sensitive)',
    'manage_bills': 'Access and manage Recurring Bills (/bills/)',
    'manage_tickets': 'Full Ticket Manager access (/tickets/manage – create, assign, resolve any ticket)',
    'submit_tickets': 'Submit and view own support/event tickets (/tickets/)',

    # Member & Attendance Management
    'view_members': 'View the member directory',
    'manage_members': 'Edit member profiles, directory settings, and family links',
    'manage_family_links': 'Approve/reject family relationship requests (admin override)',
    'manage_attendance': 'Access Attendance Kiosk and full attendance records',

    # User & System Administration
    'manage_users': 'Create, edit, approve, or delete user accounts and roles',
    'manage_groups': 'Create/edit/delete permission groups and assign members',
    'send_emails': 'Use the email tool to send messages to members',
    'manage_settings': 'Access and change church settings (name, email config, themes, etc.)',
    'view_audit_logs': 'View the Change Records / audit log',
    'access_pastoral': 'Access to the private Pastoral Care section',

    # Add even more here as new features are built
}


# ----------------------------------------------------------------------
# Permission Helpers
# ----------------------------------------------------------------------
def is_global_manager():
    """True if user has global management rights (Staff/Admin/Owner)."""
    return session.get('user_role') in ['Staff', 'Admin', 'Owner']


def is_group_leader(group_id: int, user_id: int) -> bool:
    """True if user has role_in_group = 'leader' in the specific group."""
    if not user_id:
        return False
    db = get_db()
    cur = db.cursor()
    cur.execute("""
        SELECT 1 FROM user_groups
        WHERE group_id = %s AND user_id = %s AND role_in_group = 'leader'
    """, (group_id, user_id))
    return cur.fetchone() is not None