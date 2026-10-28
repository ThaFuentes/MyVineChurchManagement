# Sermon library pages. The Drive folder id stays on the server.

from flask import abort, flash, redirect, render_template, request, session, url_for

from app.utils.decorators import login_required, role_required
from app.utils.sermon_drive import (
    EDITORS,
    REFRESH_CHOICES,
    REFRESH_LABELS,
    VISIBILITY_CHOICES,
    VISIBILITY_LABELS,
    apply_visibility_to_all,
    can_listen,
    can_see,
    clean_edit,
    playlist_rows,
    playlist_spot,
    current_default_visibility,
    current_refresh_hours,
    drive_comment_thread,
    edit_view,
    get_item,
    list_items,
    maybe_sync,
    present,
    save_drive_comment,
    row_year,
    save_default_visibility,
    save_folder_id,
    save_item_details,
    save_refresh_hours,
    sync_now,
    valid_year,
    with_drive_frame,
)
from .utils import STAFF_ROLES


def _viewer():
    """Signed-in flag, the account role, and the account row.

    A role left in the session with no login does not count. If the account
    cannot be read, the page still loads and staff tools stay off.
    """
    user_id = session.get('user_id')
    if not user_id:
        return False, '', None
    try:
        from app.models.users import get_user_by_id
        user = get_user_by_id(user_id)
    except Exception:
        return True, '', None
    if not user or user.get('is_banned') or user.get('banned'):
        return False, '', None
    return True, user.get('role') or '', user


def _account_name(user):
    if not user:
        return 'Member'
    first = (user.get('first_name') or '').strip()
    last = (user.get('last_name') or '').strip()
    full = f'{first} {last}'.strip()
    return full or (user.get('username') or '').strip() or 'Member'


def _can_moderate_comments(role, user_id):
    """Staff, Admin, Owner, or a member who was given comment moderation."""
    if role in EDITORS:
        return True
    if not user_id:
        return False
    try:
        from app.models.db import get_db
        from app.utils.permissions import user_has_permission_for_user
        cur = get_db().cursor()
        keys = ('moderate_content', 'moderate_site', 'moderate_sermons')
        return any(user_has_permission_for_user(cur, int(user_id), role, key) for key in keys)
    except Exception:
        return False


def _comment_console_url(allowed):
    if not allowed:
        return ''
    try:
        return url_for('the_gathering.dashboard.moderation_queue')
    except Exception:
        return ''


def _comments_open():
    """The church comment switch, plus the visitor rule for guests."""
    try:
        from app.utils.comment_moderation import public_comments_enabled
        from app.utils.community_participation import can_interact_community
        return bool(public_comments_enabled()) and bool(can_interact_community('sermons'))
    except Exception:
        return bool(session.get('user_id'))


def render_library():
    maybe_sync()
    year = (request.args.get('year') or '').strip()
    if year and not valid_year(year):
        year = ''
    logged_in, role, _user = _viewer()
    rows = []
    years = []
    seen_years = set()
    for row in list_items():
        if not can_see(row, logged_in=logged_in, role=role):
            continue
        item_year = row_year(row)
        if item_year and item_year not in seen_years:
            seen_years.add(item_year)
            years.append(item_year)
        if year and item_year != year:
            continue
        rows.append(present(row, logged_in=logged_in, role=role))
    years.sort(reverse=True)
    template = 'sermons/library.html' if logged_in else 'public/sermons/library.html'
    can_moderate_comments = _can_moderate_comments(
        role, session.get('user_id') if logged_in else None,
    )
    playable = [item for item in rows if item.get('can_listen')]
    has_video = any(item.get('kind') == 'video' for item in playable)
    playlist_url = ''
    if playable:
        playlist_url = url_for('sermons.library_play', year=year) if year else url_for('sermons.library_play')
    return render_template(
        template,
        messages=rows,
        years=years,
        active_year=year,
        is_staff=role in EDITORS,
        is_owner=role == 'Owner',
        can_moderate_comments=can_moderate_comments,
        comment_console_url=_comment_console_url(role in EDITORS or can_moderate_comments),
        playlist_url=playlist_url,
        playlist_label='Watch / listen to all' if has_video else 'Listen to all',
        refresh_hours=current_refresh_hours(),
        refresh_choices=REFRESH_CHOICES,
        default_visibility=current_default_visibility(),
        visibility_choices=VISIBILITY_CHOICES,
    )


def library_listen(item_id):
    # Same schedule as the library page. A play does not read Drive every time.
    maybe_sync()
    row = get_item(item_id)
    logged_in, role, user = _viewer()
    if not row or not can_see(row, logged_in=logged_in, role=role):
        abort(404)
    can_play = can_listen(row, logged_in=logged_in, role=role)
    account_id = user.get('id') if user else None
    can_moderate = _can_moderate_comments(role, account_id)
    year = (request.args.get('year') or '').strip()
    if year and not valid_year(year):
        year = ''
    playlist = None
    if request.args.get('playlist') == '1' and can_play:
        playlist = playlist_spot(list_items(), item_id, logged_in=logged_in, role=role, year=year)
    template = 'sermons/listen.html' if logged_in else 'public/sermons/listen.html'
    return render_template(
        template,
        message=present(row, logged_in=logged_in, role=role),
        comments=drive_comment_thread(
            item_id,
            request.remote_addr,
            account_id,
            for_moderator=can_moderate,
        ) if can_play else [],
        comments_open=_comments_open() and can_play,
        account_name=_account_name(user) if logged_in else '',
        is_staff=role in EDITORS,
        can_moderate=can_moderate,
        comment_console_url=_comment_console_url(can_moderate),
        playlist=playlist,
    )


def library_play():
    """Open the first message this person can play, and keep going from there."""
    maybe_sync()
    year = (request.args.get('year') or '').strip()
    if year and not valid_year(year):
        year = ''
    logged_in, role, _user = _viewer()
    chosen = playlist_rows(list_items(), logged_in=logged_in, role=role, year=year)
    if not chosen:
        flash('There is nothing to play yet.', 'info')
        return redirect(url_for('sermons.sermons'))
    return redirect(url_for(
        'sermons.library_listen',
        item_id=int(chosen[0]['id']),
        playlist=1,
        year=year or None,
    ))


def post_library_comment(item_id):
    """Save a comment or remove one. Guests reach this from the public sermon path."""
    from app.utils.comment_moderation import apply_moderation_action

    maybe_sync()
    row = get_item(item_id)
    logged_in, role, user = _viewer()
    if not row or not can_listen(row, logged_in=logged_in, role=role):
        abort(404)
    keep_playlist = request.form.get('playlist') == '1' or request.args.get('playlist') == '1'
    year = (request.form.get('year') or request.args.get('year') or '').strip()
    if year and not valid_year(year):
        year = ''
    back = url_for(
        'sermons.library_listen',
        item_id=item_id,
        playlist=1 if keep_playlist else None,
        year=year or None,
    )
    action = (request.form.get('action') or 'comment').strip().lower()
    if action in ('delete', 'edit', 'shadow', 'unshadow', 'restore'):
        account_id = user.get('id') if user else None
        if not _can_moderate_comments(role, account_id):
            flash('You do not have permission to remove that comment.', 'error')
            return redirect(back)
        apply_moderation_action(
            'sermon_drive',
            item_id,
            account_id,
            _account_name(user),
            request.form,
        )
        return redirect(back)
    if action not in ('comment', 'reply'):
        flash('That comment could not be posted.', 'error')
        return redirect(back)
    if not _comments_open():
        flash('Comments are closed right now.', 'error')
        return redirect(back)
    ok, errors = save_drive_comment(
        item_id,
        request.form,
        logged_in=logged_in,
        account_name=_account_name(user) if logged_in else '',
        user_id=session.get('user_id') if logged_in else None,
        ip=request.remote_addr,
    )
    for err in errors:
        flash(err, 'error')
    if ok:
        flash('Comment posted.', 'success')
    return redirect(back)


@login_required
@role_required(STAFF_ROLES)
def library_edit(item_id):
    row = get_item(item_id)
    if not row:
        abort(404)
    if request.method == 'POST':
        ok, errors = save_item_details(item_id, request.form, session.get('user_id'))
        for err in errors:
            flash(err, 'error')
        if ok:
            flash('Message details saved on this site.', 'success')
            return redirect(url_for('sermons.library_listen', item_id=item_id))
        fields, _ignored = clean_edit(request.form)
        form_row = dict(row)
        form_row.update(fields)
        form_row['preached_on'] = (request.form.get('preached_on') or '').strip()[:10]
        message = edit_view(form_row)
    else:
        message = edit_view(row)
    return render_template('sermons/library_edit.html', message=message)


@login_required
@role_required(STAFF_ROLES)
def library_refresh():
    result = sync_now()
    if result.get('ok'):
        count = result.get('count') or 0
        flash(f'Library updated. {count} messages.', 'success')
    elif result.get('busy'):
        flash('The library is already refreshing. Reload in a moment.', 'info')
    else:
        flash(
            'The Drive folder could not be read just now. Try again in a little while.',
            'error',
        )
    return redirect(url_for('sermons.sermons'))


@login_required
@role_required(STAFF_ROLES)
def library_schedule():
    status, hours = save_refresh_hours(request.form.get('refresh_hours'))
    if status == 'ok':
        flash(f'Drive will be checked {REFRESH_LABELS[hours]}.', 'success')
    elif status == 'error':
        flash('That schedule could not be saved just now.', 'error')
    else:
        flash('Choose how often to check Drive.', 'error')
    return redirect(url_for('sermons.sermons'))


@login_required
@role_required(STAFF_ROLES)
def library_default_visibility():
    status, visibility = save_default_visibility(request.form.get('visibility'))
    if status == 'ok':
        flash(
            f'New messages from Drive will start as {VISIBILITY_LABELS[visibility]}. '
            'Messages already here are unchanged.',
            'success',
        )
    elif status == 'error':
        flash('That default could not be saved just now.', 'error')
    else:
        flash('Choose who can listen to new messages.', 'error')
    return redirect(url_for('sermons.sermons'))


@login_required
@role_required(STAFF_ROLES)
def library_visibility_all():
    status, visibility = apply_visibility_to_all(request.form.get('visibility'))
    if status == 'ok':
        flash(f'Every message is now set to {VISIBILITY_LABELS[visibility]}.', 'success')
    elif status == 'error':
        flash('The library could not be updated just now.', 'error')
    else:
        flash('Choose who can listen.', 'error')
    return redirect(url_for('sermons.sermons'))


@login_required
@role_required(['Owner'])
def library_source():
    if save_folder_id(request.form.get('folder') or ''):
        flash('Message folder saved. Refresh the library to read it.', 'success')
    else:
        flash('Paste a Google Drive folder link or folder id.', 'error')
    return redirect(url_for('sermons.sermons'))


def allow_drive_player(response):
    """Add the Drive player to the sermon-page policy after the app sets its header."""
    path = request.path or ''
    if path != '/sermons' and not path.startswith('/sermons/'):
        return response
    response.headers['Content-Security-Policy'] = with_drive_frame(
        response.headers.get('Content-Security-Policy', '')
    )
    return response


def register(bp):
    @bp.record_once
    def _player_header(state):
        # Registered before the app security header, so this runs after it.
        state.app.after_request(allow_drive_player)

    bp.add_url_rule('/library/play', 'library_play', library_play, methods=['GET'])
    bp.add_url_rule('/library/<int:item_id>', 'library_listen', library_listen, methods=['GET'])
    bp.add_url_rule(
        '/library/<int:item_id>/edit', 'library_edit', library_edit, methods=['GET', 'POST']
    )
    bp.add_url_rule('/library/refresh', 'library_refresh', library_refresh, methods=['POST'])
    bp.add_url_rule('/library/schedule', 'library_schedule', library_schedule, methods=['POST'])
    bp.add_url_rule(
        '/library/default-visibility',
        'library_default_visibility',
        library_default_visibility,
        methods=['POST'],
    )
    bp.add_url_rule(
        '/library/visibility-all',
        'library_visibility_all',
        library_visibility_all,
        methods=['POST'],
    )
    bp.add_url_rule('/library/source', 'library_source', library_source, methods=['POST'])
