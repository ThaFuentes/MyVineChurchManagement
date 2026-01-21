# app/utils/decorators.py
# Full path: WebChurchMan/app/utils/decorators.py
# File name: decorators.py
# Brief, detailed purpose: Custom Flask route decorators for authentication, role-based access control (RBAC),
#                          and group membership validation. All decorators are lightweight, auditable,
#                          and integrate with existing models (users, groups, log).
# Features:
#   - login_required: Redirects to login if not authenticated.
#   - role_required: Flexible – accepts *roles or list, Owner bypasses all role checks.
#   - group_required: Requires membership in ALL specified groups (single or list).
#   - user_has_permission: Template-safe permission check (role-based for now).
#   - Unauthorized attempts logged via log_change() for audit trail.
#   - No bloat – focused, reusable, consistent with project standards.

from functools import wraps
from flask import session, flash, redirect, url_for, request, abort
from app.models.users import get_user_by_id   # ← FIXED: users (plural)
from app.models.groups import check_user_in_group
from app.models.log import log_change


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'error')
            return redirect(url_for('auth.login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function


def role_required(*roles):
    if len(roles) == 1 and isinstance(roles[0], list):
        allowed_roles = roles[0]
    else:
        allowed_roles = list(roles)

    def decorator(f):
        @wraps(f)
        @login_required
        def decorated_function(*args, **kwargs):
            user_id = session.get('user_id')
            user = get_user_by_id(user_id)
            if not user:
                abort(403)

            user_role = user.get('role', 'Member')

            if user_role == 'Owner':
                return f(*args, **kwargs)

            if user_role not in allowed_roles:
                flash('You do not have permission to access this page.', 'error')
                log_change(
                    user_id=user_id,
                    action='unauthorized_access_attempt',
                    details=f"Denied: role '{user_role}' lacks access to {request.path} (required: {allowed_roles})"
                )
                abort(403)

            return f(*args, **kwargs)
        return decorated_function
    return decorator


def group_required(groups):
    required_groups = [groups] if isinstance(groups, str) else groups

    def decorator(f):
        @wraps(f)
        @login_required
        def decorated_function(*args, **kwargs):
            user_id = session.get('user_id')

            for group in required_groups:
                if not check_user_in_group(user_id, group):
                    flash(f'Membership in "{group}" is required.', 'error')
                    log_change(
                        user_id=user_id,
                        action='unauthorized_group_access_attempt',
                        details=f"Denied: missing group '{group}' for path {request.path}"
                    )
                    abort(403)

            return f(*args, **kwargs)
        return decorated_function
    return decorator


def user_has_permission(permission: str) -> bool:
    """
    Template-safe permission check (role-based).
    Used in __init__.py context processor.
    """
    if 'user_id' not in session:
        return False

    user = get_user_by_id(session['user_id'])
    if not user:
        return False

    role = user.get('role', 'Member')

    permissions_map = {
        'Owner': ['manage_all', 'view_all', 'edit_all', 'delete_all', 'pastoral_all'],
        'Admin': ['manage_all', 'view_all', 'edit_all', 'pastoral_all'],
        'Staff': ['view_all', 'edit_content', 'pastoral_view'],
        'Member': ['view_public', 'submit_content']
    }

    return permission in permissions_map.get(role, [])