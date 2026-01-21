# myvinechurchonline/app/utils/permissions.py
# Full path: myvinechurchonline/app/utils/permissions.py
# File name: permissions.py
# Brief, detailed purpose: Central helper to check if current user has a specific permission.
# Checks global high roles first (Staff/Admin/Owner always have all permissions), then user's groups.
# Fully compatible with current MariaDB/pymysql setup (%s placeholders, DictCursor via get_db).
# Used both in routes (guards) and templates (via context processor inject_permissions in __init__.py).

from flask import session
from app.models.db import get_db
import json
import pymysql

def user_has_permission(permission_key: str) -> bool:
    """
    Return True if the current user has the specified permission.
    - Staff/Admin/Owner: always True (global override)
    - Otherwise: check if permission_key exists in any of the user's group permissions JSON arrays
    """
    user_id = session.get('user_id')
    if not user_id:
        return False

    # Global high roles have all permissions
    if session.get('user_role') in ['Staff', 'Admin', 'Owner']:
        return True

    try:
        db = get_db()
        cur = db.cursor(pymysql.cursors.DictCursor)

        cur.execute("""
            SELECT g.permissions
            FROM groups g
            JOIN user_groups ug ON ug.group_id = g.id
            WHERE ug.user_id = %s
        """, (user_id,))
        rows = cur.fetchall()

        for row in rows:
            perms_json = row['permissions'] or '[]'
            perms = json.loads(perms_json)
            if permission_key in perms:
                return True

    except Exception as e:
        # On any DB error, default to False (safe denial)
        print(f"Permission check error: {e}")
        return False

    return False