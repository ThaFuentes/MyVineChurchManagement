# app/models/pastoral/shared.py
# Full path: WebChurchMan/app/models/pastoral/shared.py
# File name: shared.py
# Brief, detailed purpose:
#   Shared / cross-cutting helper functions used across multiple Pastoral Area sub-modules.
#   Currently contains only the core permission check: is_in_pastoral_group().
#   More shared utilities can be added here later (e.g. common visibility helpers,
#   date formatting for pastoral views, team member counts, permission checks, etc.).
#   Uses DictCursor for consistency where needed.
#   Parameterized queries for MariaDB / PyMySQL safety.

import pymysql
from app.models.db import get_db


# ----------------------------------------------------------------------
# Pastoral Group Membership Check
# ----------------------------------------------------------------------
def is_in_pastoral_group(user_id):
    """
    Determine if the given user is a member of the 'Pastoral Group'.

    This is the primary gatekeeper for access to the entire Pastoral Area.
    Uses the general groups/user_groups tables (exact name match: 'Pastoral Group').

    Args:
        user_id (int or None): User ID from session (can be None)

    Returns:
        bool: True if the user is in the Pastoral Group, False otherwise
    """
    if not user_id:
        return False

    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    cur.execute("""
        SELECT 1
        FROM groups g
        JOIN user_groups ug ON g.id = ug.group_id
        WHERE g.name = 'Pastoral Group'
          AND ug.user_id = %s
        LIMIT 1
    """, (user_id,))

    return cur.fetchone() is not None