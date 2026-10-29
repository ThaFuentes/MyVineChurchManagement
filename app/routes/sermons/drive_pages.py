# Sermon library pages. The Drive folder id stays on the server.

from flask import abort, flash, redirect, render_template, request, send_file, session, url_for

from app.utils.decorators import login_required, role_required
from app.utils.sermon_drive import (
    EDITORS,
    REFRESH_CHOICES,
    REFRESH_LABELS,
    SORT_CHOICES,
    VISIBILITY_CHOICES,
    VISIBILITY_LABELS,
    add_speaker_name,
    apply_visibility_to_all,
    can_listen,
    can_see,
    clean_edit,
    combine_speakers,
    create_speaker,
    playlist_rows,
    playlist_spot,
    current_default_visibility,
    current_refresh_hours,
    drive_comment_thread,
    edit_view,
    get_item,
    link_speaker_account,
    list_accounts,
    list_items,
    list_sources,
    list_speakers,
    maybe_sync,
    open_local_copy,
    parse_sort,
    present,
    save_drive_comment,
    save_item_copy,
    save_next_copy,
    save_source,
    unlink_speaker_account,
    unsaved_count,
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


def _can_keep_copy(role, user_id):
    """Staff, Admin, and Owner, or a member given sermon upload or moderation.

    Saving fills the server disk, so a plain member account cannot do it.
    """
    if role in EDITORS:
        return True
    if role != 'Member' or not user_id:
        return False
    try:
        from app.models.db import get_db
        from app.utils.permissions import user_has_permission_for_user
        cur = get_db().cursor()
        keys = ('upload_sermons', 'moderate_sermons')
        return any(user_has_permission_for_user(cur, int(user_id), role, key) for key in keys)
    except Exception:
        return False


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


def _requested_sort():
    return parse_sort(request.values.get('sort'))


def _sort_kw(sort):
    """Leave the default date order off the URL."""
    chosen = parse_sort(sort)
    if chosen == 'date':
        return None
    return chosen


_SPEAKER_NOTES = frozenset({
    'Choose a speaker from the list.',
    'Choose a member from the list.',
    'That speaker is already linked to another account.',
    'That name is already linked to another account.',
    'That name already belongs to another speaker. Combine them on the Speakers page.',
    'Choose two different speakers.',
    'Those names are already on two different accounts.',
    'Type a name.',
})


def render_library():
    maybe_sync()
    year = (request.args.get('year') or '').strip()
    if year and not valid_year(year):
        year = ''
    sort = _requested_sort()
    logged_in, role, _user = _viewer()
    rows = []
    years = []
    seen_years = set()
    for row in list_items(sort):
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
    account_id = session.get('user_id') if logged_in else None
    can_moderate_comments = _can_moderate_comments(role, account_id)
    can_keep_copy = _can_keep_copy(role, account_id)
    playable = [item for item in rows if item.get('can_listen')]
    has_video = any(item.get('kind') == 'video' for item in playable)
    playlist_url = ''
    if playable:
        playlist_url = url_for(
            'sermons.library_play',
            year=year or None,
            sort=_sort_kw(sort),
        )
    return render_template(
        template,
        messages=rows,
        years=years,
        active_year=year,
        active_sort=sort,
        sort_choices=SORT_CHOICES,
        is_staff=role in EDITORS,
        is_owner=role == 'Owner',
        can_moderate_comments=can_moderate_comments,
        comment_console_url=_comment_console_url(role in EDITORS or can_moderate_comments),
        playlist_url=playlist_url,
        playlist_label='Watch / listen to all' if has_video else 'Listen to all',
        can_keep_copy=can_keep_copy,
        unsaved_count=unsaved_count(_copy_listener(logged_in, role)) if can_keep_copy else 0,
        refresh_hours=current_refresh_hours(),
        refresh_choices=REFRESH_CHOICES,
        default_visibility=current_default_visibility(),
        visibility_choices=VISIBILITY_CHOICES,
        folders=list_sources() if role == 'Owner' else [],
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
    sort = _requested_sort()
    if request.args.get('playlist') == '1' and can_play:
        playlist = playlist_spot(
            list_items(sort),
            item_id,
            logged_in=logged_in,
            role=role,
            year=year,
            sort=sort,
        )
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
        can_keep=_can_keep_copy(role, account_id),
    )


def library_play():
    """Open the first message this person can play, and keep going from there."""
    maybe_sync()
    year = (request.args.get('year') or '').strip()
    if year and not valid_year(year):
        year = ''
    sort = _requested_sort()
    logged_in, role, _user = _viewer()
    chosen = playlist_rows(list_items(sort), logged_in=logged_in, role=role, year=year)
    if not chosen:
        flash('There is nothing to play yet.', 'info')
        return redirect(url_for('sermons.sermons'))
    return redirect(url_for(
        'sermons.library_listen',
        item_id=int(chosen[0]['id']),
        playlist=1,
        year=year or None,
        sort=_sort_kw(sort),
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
        sort=_sort_kw(_requested_sort()),
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
    return render_template(
        'sermons/library_edit.html',
        message=message,
        speakers=list_speakers(),
        accounts=list_accounts(),
    )


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
            'A Drive folder could not be read just now. Try again in a little while.',
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
    raw = request.form.get('folder') or ''
    label = request.form.get('label') or ''
    # An empty name stays a one-argument save. A name is the site label only.
    saved = save_folder_id(raw, label) if label else save_folder_id(raw)
    if saved:
        flash('Message folder saved. Refresh the library to read it.', 'success')
    else:
        flash('Paste a Google Drive folder link or folder id.', 'error')
    return redirect(url_for('sermons.sermons'))


@login_required
@role_required(['Owner'])
def library_source_update():
    status = save_source(
        request.form.get('source_id'),
        request.form.get('label'),
        request.form.get('enabled'),
    )
    if status == 'ok':
        flash('Folder updated.', 'success')
    elif status == 'missing':
        flash('That folder is not on this site.', 'error')
    elif status == 'bad':
        flash('Choose a folder and a name.', 'error')
    else:
        flash('That folder could not be updated just now.', 'error')
    return redirect(url_for('sermons.sermons'))


def _flash_speaker(status):
    if status is None:
        flash('Speaker saved.', 'success')
        return
    if status in _SPEAKER_NOTES:
        flash(status, 'error')
        return
    flash('That speaker could not be saved just now.', 'error')


@login_required
@role_required(STAFF_ROLES)
def library_speakers():
    if request.method == 'POST':
        action = (request.form.get('action') or '').strip()
        if action == 'create':
            status = create_speaker(request.form.get('speaker'))
        elif action == 'add_name':
            status = add_speaker_name(request.form.get('speaker_id'), request.form.get('speaker'))
        elif action == 'link':
            status = link_speaker_account(
                request.form.get('speaker_id'),
                request.form.get('speaker_user'),
            )
        elif action == 'unlink':
            status = unlink_speaker_account(request.form.get('speaker_id'))
        elif action == 'combine':
            status = combine_speakers(request.form.get('into_id'), request.form.get('speaker_id'))
        else:
            status = 'Choose a speaker from the list.'
        _flash_speaker(status)
        return redirect(url_for('sermons.library_speakers'))
    return render_template(
        'sermons/speakers.html',
        speakers=list_speakers(),
        accounts=list_accounts(),
    )


_COPY_MESSAGES = {
    'saved': ('Saved one copy on this server.', 'success'),
    'already': ('That message already has a copy on this server.', 'info'),
    'none': ('Every message already has a copy on this server.', 'info'),
    'missing': ('That message is not in the library.', 'error'),
    'gone': ('Drive no longer has that file, so a copy could not be saved.', 'error'),
    'html': ('Drive sent a page instead of the audio, so nothing was stored.', 'error'),
    'large': ('That file is larger than this site will store.', 'error'),
    'blocked': ('Drive sent the file to a place this site will not follow.', 'error'),
    'type': ('That file is not audio or video, so it was not stored.', 'error'),
    'place': ('Copies stay outside the site folder, so this one was not saved.', 'error'),
    'busy': ('A copy is already being saved. Try again in a moment.', 'info'),
    'error': ('That copy could not be saved just now.', 'error'),
}
_COPY_TYPES = {
    'mp3': 'audio/mpeg',
    'm4a': 'audio/mp4',
    'aac': 'audio/aac',
    'wav': 'audio/wav',
    'ogg': 'audio/ogg',
    'mp4': 'video/mp4',
    'webm': 'video/webm',
    'mov': 'video/quicktime',
    'mkv': 'video/webm',
}


def _flash_copy(status, left=None):
    if status == 'saved' and left:
        flash(f'Saved one copy on this server. {left} still need a copy.', 'success')
        return
    if status == 'saved' and left == 0:
        flash('Saved one copy on this server. Every message now has a copy.', 'success')
        return
    text, category = _COPY_MESSAGES.get(status, _COPY_MESSAGES['error'])
    flash(text, category)


def _back_to_listen(item_id):
    year = (request.form.get('year') or '').strip()
    if year and not valid_year(year):
        year = ''
    return redirect(url_for(
        'sermons.library_listen',
        item_id=item_id,
        playlist=1 if request.form.get('playlist') == '1' else None,
        year=year or None,
        sort=_sort_kw(_requested_sort()),
    ))


def _keeper():
    """The signed-in account, when that account is allowed to store a copy."""
    logged_in, role, user = _viewer()
    account_id = user.get('id') if user else None
    if not logged_in or not _can_keep_copy(role, account_id):
        abort(403)
    return account_id, logged_in, role


def _copy_listener(logged_in, role):
    """True only for a message this person can already play."""
    def allowed(row):
        return can_listen(row, logged_in=logged_in, role=role)
    return allowed


def library_copy(item_id):
    """Play a saved copy for someone who can already listen. Only after Drive is missing it."""
    row = get_item(item_id)
    logged_in, role, _user = _viewer()
    if not row or not can_listen(row, logged_in=logged_in, role=role):
        abort(404)
    try:
        missing = int(row.get('missing_on_drive') or 0)
    except (TypeError, ValueError):
        missing = 1 if row.get('missing_on_drive') else 0
    if not missing:
        abort(404)
    path = open_local_copy(row)
    if not path:
        abort(404)
    ext = path.rsplit('.', 1)[-1].lower()
    return send_file(
        path,
        mimetype=_COPY_TYPES.get(ext, 'application/octet-stream'),
        conditional=True,
        download_name=f'message.{ext}',
        max_age=0,
    )


@login_required
def library_copy_save(item_id):
    """Store one message this person can already hear. Guests are sent to login."""
    account_id, logged_in, role = _keeper()
    row = get_item(item_id)
    if not row or not can_listen(row, logged_in=logged_in, role=role):
        abort(404)
    _flash_copy(save_item_copy(item_id, account_id))
    return _back_to_listen(item_id)


@login_required
def library_copy_next():
    """Store the next message this person can already hear. One file per click."""
    account_id, logged_in, role = _keeper()
    status, left = save_next_copy(
        account_id,
        allowed=_copy_listener(logged_in, role),
    )
    _flash_copy(status, left)
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
    bp.add_url_rule('/library/speakers', 'library_speakers', library_speakers, methods=['GET', 'POST'])
    bp.add_url_rule(
        '/library/source-update', 'library_source_update', library_source_update, methods=['POST']
    )
    bp.add_url_rule('/library/copy-next', 'library_copy_next', library_copy_next, methods=['POST'])
    bp.add_url_rule('/library/<int:item_id>/copy', 'library_copy', library_copy, methods=['GET'])
    bp.add_url_rule(
        '/library/<int:item_id>/copy', 'library_copy_save', library_copy_save, methods=['POST']
    )
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
