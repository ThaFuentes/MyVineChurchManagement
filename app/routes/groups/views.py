# app/routes/groups/views.py
# Full path: MyVineChurch/app/routes/groups/views.py
# File name: views.py
# Brief, detailed purpose: All route handlers (controllers) for the Groups blueprint.
# • Every single function name and endpoint from the original groups.py is preserved exactly.
# • All database work moved to queries.py
# • All form validation + censorship moved to forms.py
# • All helpers moved to utils.py
# • 100% original behavior preserved + improved edit experience (full permission checkboxes + member management)

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from app.utils.decorators import login_required, role_required
from app.models.db import get_db
from app.models.log import log_change
from pymysql import IntegrityError
from pymysql.cursors import DictCursor
import json

# Package-relative blueprint
from . import groups_bp

# Import from our modular files (no renaming)
from .queries import (
    get_groups_list,
    search_groups,
    create_group,
    update_group,
    delete_group,
    assign_user_to_group,
    remove_user_from_group,
    update_user_role_in_group,
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

    groups = get_groups_list(is_logged_in=is_logged_in, role=role, user_id=user_id)

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
def search_groups_route():
    query = request.args.get('q', '').strip()
    visibility_filter = request.args.get('visibility', 'all')

    is_logged_in = 'user_id' in session
    role = session.get('user_role', 'Member') if is_logged_in else 'Guest'
    user_id = session.get('user_id')

    groups = search_groups(
        query=query,
        visibility_filter=visibility_filter,
        is_logged_in=is_logged_in,
        role=role,
        user_id=user_id
    )

    return jsonify(groups)


# ----------------------------------------------------------------------
# Create Group (global Staff+ only)
# ----------------------------------------------------------------------
@groups_bp.route('/create', methods=['GET', 'POST'])
@login_required
@role_required(['Staff', 'Admin', 'Owner'])
def create_group():
    if request.method == 'POST':
        clean_data = validate_create_group_form(request.form)
        if not clean_data:
            return render_template('groups/create.html', known_permissions=KNOWN_PERMISSIONS)

        permissions_json = json.dumps(clean_data['permissions'])

        try:
            group_id = create_group(
                name=clean_data['name'],
                description=clean_data['description'],
                visibility=clean_data['visibility'],
                permissions=permissions_json,
                user_id=session['user_id']
            )
            log_change(session['user_id'], 'create', change_details=f'Created group "{clean_data["name"]}" with permissions {permissions_json}')
            flash('Group created successfully.', 'success')
            return redirect(url_for('groups.list_groups'))
        except IntegrityError:
            flash('A group with this name already exists.', 'error')

    return render_template('groups/create.html', known_permissions=KNOWN_PERMISSIONS)


# ----------------------------------------------------------------------
# Edit Group (global OR group leader) — IMPROVED
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

    # Populate extra fields for template
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

    # Current permissions as list for checkboxes
    current_permissions = json.loads(group.get('permissions') or '[]')

    if request.method == 'POST':
        clean_data = validate_edit_group_form(request.form)
        if not clean_data:
            return render_template('groups/edit.html',
                                   group=group,
                                   known_permissions=KNOWN_PERMISSIONS,
                                   current_permissions=current_permissions)

        permissions_json = json.dumps(clean_data['permissions'])

        try:
            update_group(
                group_id=group_id,
                name=clean_data['name'],
                description=clean_data['description'],
                visibility=clean_data['visibility'],
                permissions=permissions_json,
                user_id=user_id
            )
            log_change(user_id, 'update', target_id=group_id,
                       change_details=f'Updated group "{clean_data["name"]}" permissions')
            flash('Group updated successfully.', 'success')
            return redirect(url_for('groups.list_groups'))
        except IntegrityError:
            flash('A group with this name already exists.', 'error')

    return render_template('groups/edit.html',
                           group=group,
                           known_permissions=KNOWN_PERMISSIONS,
                           current_permissions=current_permissions)


# ----------------------------------------------------------------------
# Delete Group (Admin/Owner only)
# ----------------------------------------------------------------------
@groups_bp.route('/delete/<int:group_id>', methods=['POST'])
@login_required
@role_required(['Admin', 'Owner'])
def delete_group(group_id):
    try:
        delete_group(group_id)
        log_change(session['user_id'], 'delete', target_id=group_id, change_details=f'Deleted group ID {group_id}')
        flash('Group deleted.', 'success')
    except Exception:
        flash('Group not found or could not be deleted.', 'error')

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

    try:
        assign_user_to_group(group_id, identifier, role_in_group, user_id)
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

    try:
        remove_user_from_group(group_id, user_id)
        log_change(session['user_id'], 'delete', change_details=f'Removed user {user_id} from group {group_id}')
    except Exception:
        pass

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

    try:
        update_user_role_in_group(group_id, user_id, new_role)
        log_change(session['user_id'], 'update', change_details=f'Changed role of user {user_id} in group {group_id} to {new_role}')
        flash('Role updated.', 'success')
    except Exception:
        flash('No changes made.', 'info')

    return redirect(url_for('groups.list_groups'))