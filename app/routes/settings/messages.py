# Sermon library settings. Staff, Admin, and Owner. The sermon page stays for listening.

from flask import flash, redirect, render_template, session, url_for

from app.utils.sermon_drive import (
    REFRESH_CHOICES,
    VISIBILITY_CHOICES,
    current_default_visibility,
    current_refresh_hours,
    list_sources,
    may_set_sermon_privacy,
    unsaved_count,
)

from . import settings_bp


@settings_bp.route('/messages', methods=['GET'])
def messages():
    from app.routes.sermons.drive_pages import _can_keep_copy, _copy_listener, _viewer

    _logged_in, role, user = _viewer()
    if role not in ('Staff', 'Admin', 'Owner'):
        flash('You do not have permission to edit message settings.', 'error')
        return redirect(url_for('settings.general'))
    account_id = user.get('id') if user else None
    can_keep = _can_keep_copy(role, account_id)
    return render_template(
        'settings/messages.html',
        refresh_hours=current_refresh_hours(),
        refresh_choices=REFRESH_CHOICES,
        default_visibility=current_default_visibility(),
        visibility_choices=VISIBILITY_CHOICES,
        folders=list_sources() if role == 'Owner' else [],
        is_owner=role == 'Owner',
        is_staff=True,
        can_keep_copy=can_keep,
        can_set_privacy=may_set_sermon_privacy(account_id, role),
        unsaved_count=unsaved_count(_copy_listener(True, role)) if can_keep else 0,
    )
