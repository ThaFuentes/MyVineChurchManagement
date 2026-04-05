# app/routes/groups/queries.py
# Full path: MyVineChurch/app/routes/groups/queries.py
# File name: queries.py
# Brief, detailed purpose: All database queries and operations for the Groups module.
# • Pure data-access layer – no Flask routes, no templates, no flash messages.
# • Every function name and signature from the original groups.py is preserved exactly.
# • 100% original behavior preserved.

import pymysql
import json
from flask import session   # ← Added so is_global_manager() works (was missing)
from app.models.db import get_db
from .utils import KNOWN_PERMISSIONS


# ----------------------------------------------------------------------
# Permission Helpers (exact same as original)
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


# ----------------------------------------------------------------------
# Fetch groups with details (exact same signature as original)
# ----------------------------------------------------------------------
def fetch_groups_with_details(cur, base_sql, params=[], current_user_id=None):
    cur.execute(base_sql, params)
    groups = cur.fetchall()  # List of dicts (DictCursor)

    global_manager = is_global_manager()

    for group in groups:
        # Member count
        cur.execute("SELECT COUNT(*) AS member_count FROM user_groups WHERE group_id = %s", (group['id'],))
        row = cur.fetchone()
        group['member_count'] = row['member_count'] if row else 0

        # Member details
        cur.execute("""
            SELECT u.id AS user_id, u.first_name, u.last_name, u.username, ug.role_in_group
            FROM user_groups ug
            JOIN users u ON ug.user_id = u.id
            WHERE ug.group_id = %s
            ORDER BY u.last_name, u.first_name
        """, (group['id'],))
        group['members'] = cur.fetchall()

        # Parse permissions
        perms_json = group.get('permissions') or '[]'
        permission_list = json.loads(perms_json)
        group['permission_list'] = permission_list
        group['permission_labels'] = [
            KNOWN_PERMISSIONS.get(p, p.replace('_', ' ').title()) for p in permission_list
        ]

        # Can current user manage this group?
        group['can_manage'] = global_manager or (current_user_id and is_group_leader(group['id'], current_user_id))

    return groups


# ----------------------------------------------------------------------
# List Groups
# ----------------------------------------------------------------------
def get_groups_list(is_logged_in=False, role=None, user_id=None):
    sql = """
        SELECT g.*, u.username AS creator_name
        FROM groups g
        LEFT JOIN users u ON u.id = g.created_by
    """
    params = []

    if not is_logged_in or role not in ['Admin', 'Owner', 'Staff']:
        sql += " WHERE g.visibility = 'public'"

    sql += " ORDER BY g.name"

    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)
    return fetch_groups_with_details(cur, sql, params, user_id)


# ----------------------------------------------------------------------
# Search Groups
# ----------------------------------------------------------------------
def search_groups(query, visibility_filter='all', is_logged_in=False, role=None, user_id=None):
    sql = """
        SELECT g.*, u.username AS creator_name
        FROM groups g
        LEFT JOIN users u ON u.id = g.created_by
    """
    where_clauses = []
    params = []

    if query:
        where_clauses.append("(g.name LIKE %s OR g.description LIKE %s)")
        params += [f'%{query}%', f'%{query}%']

    if visibility_filter != 'all':
        where_clauses.append("g.visibility = %s")
        params.append(visibility_filter)

    if not is_logged_in or role not in ['Admin', 'Owner', 'Staff']:
        where_clauses.append("g.visibility = 'public'")

    if where_clauses:
        sql += " WHERE " + " AND ".join(where_clauses)

    sql += " ORDER BY g.name"

    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)
    return fetch_groups_with_details(cur, sql, params, user_id)


# ----------------------------------------------------------------------
# CRUD Operations (exact same as original)
# ----------------------------------------------------------------------
def create_group(name, description, visibility, permissions, user_id):
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute("""
            INSERT INTO groups (name, description, visibility, permissions, created_by, updated_by)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (name, description, visibility, permissions, user_id, user_id))
        group_id = cur.lastrowid

        # Auto-add creator as leader
        cur.execute("""
            INSERT INTO user_groups (user_id, group_id, role_in_group, assigned_by)
            VALUES (%s, %s, 'leader', %s)
        """, (user_id, group_id, user_id))

        db.commit()
        return group_id
    except Exception:
        db.rollback()
        raise


def update_group(group_id, name, description, visibility, permissions, user_id):
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute("""
            UPDATE groups
            SET name = %s, description = %s, visibility = %s, permissions = %s, updated_by = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (name, description, visibility, permissions, user_id, group_id))
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise


def delete_group(group_id):
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute("DELETE FROM groups WHERE id = %s", (group_id,))
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise


def assign_user_to_group(group_id, target_user_id, role_in_group, assigned_by):
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute("""
            INSERT INTO user_groups (user_id, group_id, role_in_group, assigned_by)
            VALUES (%s, %s, %s, %s)
        """, (target_user_id, group_id, role_in_group, assigned_by))
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise


def remove_user_from_group(group_id, user_id):
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute("DELETE FROM user_groups WHERE group_id = %s AND user_id = %s", (group_id, user_id))
        db.commit()
        return cur.rowcount > 0
    except Exception:
        db.rollback()
        raise


def update_user_role_in_group(group_id, user_id, new_role):
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute("""
            UPDATE user_groups
            SET role_in_group = %s
            WHERE group_id = %s AND user_id = %s
        """, (new_role, group_id, user_id))
        db.commit()
        return cur.rowcount > 0
    except Exception:
        db.rollback()
        raise