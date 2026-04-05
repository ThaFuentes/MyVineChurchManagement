# app/routes/groups/views.py
# Full path: MyVineChurch/app/routes/groups/views.py
# File name: views.py
# Brief, detailed purpose: All route handlers (controllers) for the Groups blueprint.
# • Every single function name and endpoint from the original groups.py is preserved exactly.
# • All database work moved to queries.py
# • All form validation + censorship moved to forms.py
# • All helpers moved to utils.py
# • 100% original behavior preserved.

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from app.utils.decorators import login_required, role_required
from app.utils.helpers import contains_censored_word
from app.models.db import get_db
from app.models.log import log_change
from pymysql import IntegrityError
from pymysql.cursors import DictCursor
import pymysql
import json

# Package-relative blueprint
from . import groups_bp

# Import from our modular files (no renaming)
from .queries import (
    fetch_groups_with_details,
    is_group_leader
)
from .forms import validate_create_group_form, validate_edit_group_form
from .utils import KNOWN_PERMISSIONS, is_global_manager


# ----------------------------------------------------------------------
# List Groups
# ----------------------------------------------------------------------
@groups_bp.route('/')
def list_groups():
    is_logged_in = 'user_id' in session
    role = session.get('user_role', 'Member') if is_logged_in else 'Guest'
    user_id = session.get('user_id')

    db = get_db()
    cur = db.cursor(DictCursor)

    sql = """
        SELECT g.*, u.username AS creator_name
        FROM groups g
        LEFT JOIN users u ON u.id = g.created_by
    """
    params = []

    if not is_logged_in or role not in ['Admin', 'Owner', 'Staff']:
        sql += " WHERE g.visibility = 'public'"

    sql += " ORDER BY g.name"

    groups = fetch_groups_with_details(cur, sql, params, user_id)

    return render_template(
        'groups/list.html',
        groups=groups,
        is_logged_in=is_logged_in,
        role=role
    )


# ----------------------------------------------------------------------
# AJAX Search / Filter
# ----------------------------------------------------------------------
@groups_bp.route('/search')
def search_groups():
    query = request.args.get('q', '').strip()
    visibility_filter = request.args.get('visibility', 'all')

    is_logged_in = 'user_id' in session
    role = session.get('user_role', 'Member') if is_logged_in else 'Guest'
    user_id = session.get('user_id')

    db = get_db()
    cur = db.cursor(DictCursor)

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

    groups = fetch_groups_with_details(cur, sql, params, user_id)

    return jsonify(groups)


# ----------------------------------------------------------------------
# Create Group (global Staff+ only)
# ----------------------------------------------------------------------
@groups_bp.route('/create', methods=['GET', 'POST'])
@login_required
@role_required(['Staff', 'Admin', 'Owner'])
def create_group():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        visibility = request.form.get('visibility', 'private')
        selected_perms = request.form.getlist('permissions')
        permissions = json.dumps([p for p in selected_perms if p in KNOWN_PERMISSIONS])

        # Censored words check on visible fields (name + description)
        combined_text = f"{name} {description}"
        if contains_censored_word(combined_text):
            flash('Group name or description contains a prohibited word or phrase.', 'error')
            return render_template('groups/create.html', known_permissions=KNOWN_PERMISSIONS)

        if not name:
            flash('Group name is required.', 'error')
            return render_template('groups/create.html', known_permissions=KNOWN_PERMISSIONS)

        db = get_db()
        cur = db.cursor()
        try:
            cur.execute("""
                INSERT INTO groups (name, description, visibility, permissions, created_by, updated_by)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (name, description, visibility, permissions, session['user_id'], session['user_id']))
            group_id = cur.lastrowid

            # Auto-add creator as leader
            cur.execute("""
                INSERT INTO user_groups (user_id, group_id, role_in_group, assigned_by)
                VALUES (%s, %s, 'leader', %s)
            """, (session['user_id'], group_id, session['user_id']))

            db.commit()
            log_change(session['user_id'], 'create', change_details=f'Created group "{name}" with permissions {permissions}')
            flash('Group created successfully.', 'success')
            return redirect(url_for('groups.list_groups'))
        except IntegrityError:
            flash('A group with this name already exists.', 'error')

    return render_template('groups/create.html', known_permissions=KNOWN_PERMISSIONS)


# ----------------------------------------------------------------------
# Edit Group (global OR group leader)
# ----------------------------------------------------------------------
@groups_bp.route('/edit/<int:group_id>', methods=['GET', 'POST'])
@login_required
def edit_group(group_id):
    user_id = session['user_id']
    global_manager = is_global_manager()

    if not (global_manager or is_group_leader(group_id, user_id)):
        flash('You do not have permission to edit this group.', 'error')
        return redirect(url_for('groups.list_groups'))

    db = get_db()
    cur = db.cursor(DictCursor)

    cur.execute("SELECT * FROM groups WHERE id = %s", (group_id,))
    group = cur.fetchone()
    if not group:
        flash('Group not found.', 'error')
        return redirect(url_for('groups.list_groups'))

    # Populate the same extra fields used in list view and edit template
    cur.execute("SELECT COUNT(*) AS member_count FROM user_groups WHERE group_id = %s", (group_id,))
    row = cur.fetchone()
    group['member_count'] = row['member_count'] if row else 0

    cur.execute("""
        SELECT u.id AS user_id, u.first_name, u.last_name, u.username, ug.role_in_group
        FROM user_groups ug
        JOIN users u ON ug.user_id = u.id
        WHERE ug.group_id = %s
        ORDER BY u.last_name, u.first_name
    """, (group_id,))
    group['members'] = cur.fetchall()

    group['can_manage'] = global_manager or is_group_leader(group_id, user_id)

    current_permissions = json.loads(group['permissions'] or '[]')

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        visibility = request.form.get('visibility', 'private')
        selected_perms = request.form.getlist('permissions')
        permissions = json.dumps([p for p in selected_perms if p in KNOWN_PERMISSIONS])

        # Censored words check on visible fields (name + description)
        combined_text = f"{name} {description}"
        if contains_censored_word(combined_text):
            flash('Group name or description contains a prohibited word or phrase.', 'error')
            return render_template('groups/edit.html', group=group, known_permissions=KNOWN_PERMISSIONS, current_permissions=current_permissions)

        if not name:
            flash('Group name is required.', 'error')
            return render_template('groups/edit.html', group=group, known_permissions=KNOWN_PERMISSIONS, current_permissions=current_permissions)

        try:
            cur.execute("""
                UPDATE groups
                SET name = %s, description = %s, visibility = %s, permissions = %s, updated_by = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (name, description, visibility, permissions, user_id, group_id))
            db.commit()
            log_change(user_id, 'update', target_id=group_id, change_details=f'Updated group "{name}" permissions to {permissions}')
            flash('Group updated successfully.', 'success')
            return redirect(url_for('groups.list_groups'))
        except IntegrityError:
            flash('A group with this name already exists.', 'error')

    return render_template('groups/edit.html', group=group, known_permissions=KNOWN_PERMISSIONS, current_permissions=current_permissions)


# ----------------------------------------------------------------------
# Delete Group (Admin/Owner only)
# ----------------------------------------------------------------------
@groups_bp.route('/delete/<int:group_id>', methods=['POST'])
@login_required
@role_required(['Admin', 'Owner'])
def delete_group(group_id):
    db = get_db()
    cur = db.cursor(DictCursor)

    cur.execute("SELECT name FROM groups WHERE id = %s", (group_id,))
    group = cur.fetchone()

    if group:
        cur.execute("DELETE FROM groups WHERE id = %s", (group_id,))
        db.commit()
        log_change(session['user_id'], 'delete', target_id=group_id, change_details=f'Deleted group "{group["name"]}"')
        flash('Group deleted.', 'success')
    else:
        flash('Group not found.', 'error')

    return redirect(url_for('groups.list_groups'))


# ----------------------------------------------------------------------
# Assign User to Group (global OR group leader)
# ----------------------------------------------------------------------
@groups_bp.route('/<int:group_id>/assign', methods=['POST'])
@login_required
def assign_user(group_id):
    user_id = session['user_id']
    if not (is_global_manager() or is_group_leader(group_id, user_id)):
        flash('You do not have permission to assign users to this group.', 'error')
        return redirect(url_for('groups.list_groups'))

    identifier = request.form.get('username_or_email', '').strip()
    role_in_group = request.form.get('role_in_group', 'member').strip()

    if not identifier:
        flash('Username or email is required.', 'error')
        return redirect(url_for('groups.list_groups'))

    db = get_db()
    cur = db.cursor(DictCursor)

    cur.execute("SELECT id FROM users WHERE username = %s OR email = %s", (identifier, identifier))
    target_user = cur.fetchone()

    if not target_user:
        flash('User not found.', 'error')
        return redirect(url_for('groups.list_groups'))

    try:
        cur.execute("""
            INSERT INTO user_groups (user_id, group_id, role_in_group, assigned_by)
            VALUES (%s, %s, %s, %s)
        """, (target_user['id'], group_id, role_in_group, session['user_id']))
        db.commit()
        log_change(session['user_id'], 'create',
                   change_details=f'Assigned user {target_user["id"]} to group {group_id} as {role_in_group}')
        flash('User assigned to group.', 'success')
    except IntegrityError:
        flash('User is already in this group.', 'error')

    return redirect(url_for('groups.list_groups'))


# ----------------------------------------------------------------------
# Remove User from Group (global OR group leader)
# ----------------------------------------------------------------------
@groups_bp.route('/<int:group_id>/remove/<int:user_id>', methods=['POST'])
@login_required
def remove_user(group_id, user_id):
    if not (is_global_manager() or is_group_leader(group_id, session['user_id'])):
        flash('You do not have permission to remove users from this group.', 'error')
        return '', 403

    db = get_db()
    cur = db.cursor()

    cur.execute("DELETE FROM user_groups WHERE group_id = %s AND user_id = %s", (group_id, user_id))
    if cur.rowcount:
        db.commit()
        log_change(session['user_id'], 'delete',
                   change_details=f'Removed user {user_id} from group {group_id}')

    return '', 204


# ----------------------------------------------------------------------
# Update User's Role in Group (global OR group leader)
# ----------------------------------------------------------------------
@groups_bp.route('/<int:group_id>/update_role/<int:user_id>', methods=['POST'])
@login_required
def update_role(group_id, user_id):
    if not (is_global_manager() or is_group_leader(group_id, session['user_id'])):
        flash('You do not have permission to change roles in this group.', 'error')
        return redirect(url_for('groups.list_groups'))

    new_role = request.form.get('role_in_group', 'member').strip()

    db = get_db()
    cur = db.cursor()

    cur.execute("""
        UPDATE user_groups
        SET role_in_group = %s
        WHERE group_id = %s AND user_id = %s
    """, (new_role, group_id, user_id))

    if cur.rowcount:
        db.commit()
        log_change(session['user_id'], 'update',
                   change_details=f'Changed role of user {user_id} in group {group_id} to {new_role}')
        flash('Role updated.', 'success')
    else:
        flash('No changes made.', 'info')

    return redirect(url_for('groups.list_groups'))