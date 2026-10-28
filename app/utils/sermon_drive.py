# Read a public Google Drive folder listing and shape it for the sermon pages.
# Media stays on Drive. Nothing here writes back to Drive or downloads a file.

from __future__ import annotations

import datetime
import html
import logging
import os
import re
import unicodedata

log = logging.getLogger('sermon_drive')

EDITORS = frozenset({'Staff', 'Admin', 'Owner'})
LEADERS = frozenset({'Admin', 'Owner'})
VISIBILITIES = ('public', 'members', 'leaders')
VISIBILITY_CHOICES = (
    ('public', 'Anyone'),
    ('members', 'Signed-in members'),
    ('leaders', 'Admin and Owner'),
)
VISIBILITY_LABELS = dict(VISIBILITY_CHOICES)
DEFAULT_VISIBILITY = 'public'

# How often a page view may read the Drive listing. 0 means staff refresh only.
REFRESH_CHOICES = (
    (168, 'Once a week'),
    (24, 'Once a day'),
    (8, 'Every 8 hours'),
    (0, 'Only when staff refresh'),
)
REFRESH_LABELS = {
    168: 'once a week',
    24: 'once a day',
    8: 'every 8 hours',
    0: 'only when staff refresh',
}
DEFAULT_REFRESH_HOURS = 168
FETCH_TIMEOUT = 12
MAX_DEPTH = 2
MAX_FOLDERS = 8
MAX_FILES = 400

_ID = re.compile(r'[A-Za-z0-9_-]{10,128}')
_DATE = re.compile(r'^(\d{4})-(\d{2})-(\d{2})$')
_NOTE = re.compile(r'\s*\(([^)]*)\)\s*$')
_MEDIA_EXT = re.compile(r'\.(mp3|m4a|wav|aac|ogg|mp4|webm|mov|mkv)$', re.I)
_PERSON_WORD = re.compile(r"^[A-Z][A-Za-z'’.\-]*$")
_YEAR = re.compile(r'^(19|20)\d{2}$')
_COMMENT_LIMIT = 2000
_NAME_LIMIT = 60

_BROWSER_UA = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
)

_schema_ready = False


class DriveReadError(Exception):
    """The folder listing could not be read. Carries no URL."""


class _Walk:
    def __init__(self, files, complete):
        self.files = files
        self.complete = complete


def with_drive_frame(csp):
    """Let the sermon page embed the Drive player. Other CSP rules stay as they are."""
    text = (csp or '').strip()
    if 'frame-src' in text:
        return text
    extra = "frame-src 'self' https://drive.google.com https://docs.google.com"
    if not text:
        return extra + ';'
    if not text.endswith(';'):
        text += ';'
    return f'{text} {extra};'


def play_url(file_id):
    """Browser player URL. This does not download the file."""
    if not _ID.fullmatch(file_id or ''):
        return None
    return f'https://drive.google.com/file/d/{file_id}/preview'


def folder_list_url(folder_id):
    """Server-side listing URL. Do not put this in a page."""
    if not _ID.fullmatch(folder_id or ''):
        return None
    return f'https://drive.google.com/embeddedfolderview?id={folder_id}'


def extract_folder_id(raw):
    """Accept a bare folder id or a Drive folder link. Return the id, or None."""
    text = (raw or '').strip().strip('"').strip("'")
    if not text or any(ch in text for ch in '\r\n\t\x00'):
        return None
    if _ID.fullmatch(text):
        return text
    if 'drive.google.com' not in text.lower():
        return None
    found = re.search(r'/folders/([A-Za-z0-9_-]{10,128})', text)
    if found:
        return found.group(1)
    if 'embeddedfolderview' in text:
        found = re.search(r'[?&]id=([A-Za-z0-9_-]{10,128})', text)
        if found:
            return found.group(1)
    return None


def valid_year(value):
    return bool(_YEAR.fullmatch(value or ''))


def _is_person(text):
    words = text.split()
    if not 2 <= len(words) <= 4:
        return False
    return all(_PERSON_WORD.match(word) for word in words)


def _speaker_from_segment(text):
    """A name, or 'Name and Name'. A topic after 'and' stays with the title."""
    if _is_person(text):
        return text, []
    if ' and ' not in text:
        return None, []
    sides = [side.strip() for side in text.split(' and ') if side.strip()]
    if len(sides) < 2 or not _is_person(sides[0]):
        return None, []
    if all(_is_person(side) for side in sides):
        return text, []
    rest = ' and '.join(sides[1:]).strip()
    return sides[0], ([rest] if rest else [])


def _valid_date(token):
    match = _DATE.match(token or '')
    if not match:
        return None
    year, month, day = (int(part) for part in match.groups())
    try:
        datetime.date(year, month, day)
    except ValueError:
        return None
    return f'{year:04d}-{month:02d}-{day:02d}'


def parse_drive_name(name):
    """Pull title, speaker, date, series, and a parenthetical note from a file name."""
    raw = (name or '').strip()
    stem = _MEDIA_EXT.sub('', raw).strip()
    note = ''
    noted = _NOTE.search(stem)
    if noted:
        note = noted.group(1).strip()
        stem = stem[:noted.start()].strip()
    parts = [part.strip() for part in stem.split(' - ') if part.strip()]
    series = None
    if len(parts) >= 3 and parts[1].lower() == 'message':
        series = parts[0][:160]
        parts = parts[2:]
    preached = None
    speaker = None
    title_parts = []
    for part in parts:
        if preached is None:
            parsed_date = _valid_date(part)
            if parsed_date:
                preached = parsed_date
                continue
        if speaker is None:
            found, extras = _speaker_from_segment(part)
            if found:
                speaker = found[:160]
                title_parts.extend(extras)
                continue
        title_parts.append(part)
    title = ' - '.join(title_parts).strip()
    if not title:
        title = speaker or stem or raw or 'Message'
    if title.islower():
        title = title.title()
    return {
        'title': title[:255],
        'speaker': speaker,
        'scripture': None,
        'summary': (note[:4000] or None),
        'series': series,
        'preached_on': preached,
    }


def parse_folder_html(page):
    """Read one embedded folder page. Raises DriveReadError if the page is not a listing."""
    if not page or 'flip-entries' not in page:
        raise DriveReadError()
    chunks = page.split('<div class="flip-entry"')
    entries = []
    for chunk in chunks[1:]:
        id_match = re.search(r'id="entry-([A-Za-z0-9_-]{10,128})"', chunk)
        title_match = re.search(r'class="flip-entry-title">([^<]*)</div>', chunk)
        if not id_match or not title_match:
            continue
        href_match = re.search(r'href="([^"]+)"', chunk)
        href = html.unescape(href_match.group(1)) if href_match else ''
        modified_match = re.search(
            r'class="flip-entry-last-modified"><div>([^<]*)</div>', chunk
        )
        mime_match = re.search(r'/type/([a-z0-9.+-]+/[a-z0-9.+-]+)', chunk, re.I)
        mime = mime_match.group(1).lower() if mime_match else ''
        alt_match = re.search(r'alt="([^"]*)"', chunk)
        alt = (alt_match.group(1) if alt_match else '').lower()
        is_folder = 'aria-label="Folder"' in chunk or '/drive/folders/' in href
        if is_folder:
            kind = 'folder'
        elif mime.startswith('audio/') or alt == 'audio':
            kind = 'audio'
        elif mime.startswith('video/') or alt == 'video':
            kind = 'video'
        else:
            kind = 'other'
        entries.append({
            'file_id': id_match.group(1),
            'name': html.unescape(title_match.group(1)).strip(),
            'kind': kind,
            'mime': mime or None,
            'modified': (modified_match.group(1).strip() if modified_match else ''),
        })
    if not entries and ('/file/d/' in page or '/drive/folders/' in page):
        raise DriveReadError()
    return entries


def walk_folder(root_id, fetch, max_depth=MAX_DEPTH, max_folders=MAX_FOLDERS, max_files=MAX_FILES):
    """Walk the folder and its year folders. Raises DriveReadError and returns nothing on failure."""
    if not _ID.fullmatch(root_id or ''):
        raise DriveReadError()
    files = []
    seen_folders = set()
    complete = True

    def visit(folder_id, depth):
        nonlocal complete
        if folder_id in seen_folders:
            return
        if len(seen_folders) >= max_folders:
            complete = False
            return
        if depth > max_depth:
            complete = False
            return
        seen_folders.add(folder_id)
        page = fetch(folder_id)
        for entry in parse_folder_html(page):
            if entry['kind'] == 'folder':
                visit(entry['file_id'], depth + 1)
                continue
            if entry['kind'] not in ('audio', 'video'):
                continue
            if len(files) >= max_files:
                complete = False
                continue
            entry['parent_folder_id'] = folder_id
            files.append(entry)

    visit(root_id, 0)
    return _Walk(files, complete)


def _count(value):
    try:
        count = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return count if count > 0 else 0


def _flag(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 1 if value else 0


def _viewer_role(logged_in, role):
    """A role only counts for someone who is signed in."""
    if not logged_in:
        return ''
    return role or ''


def can_listen(row, *, logged_in, role):
    role = _viewer_role(logged_in, role)
    editor = role in EDITORS
    if _flag(row.get('hidden')) or _flag(row.get('missing_on_drive')):
        return editor
    visibility = (row.get('visibility') or 'public').lower()
    if editor:
        return True
    if visibility == 'public':
        return True
    if visibility == 'members':
        return bool(logged_in)
    if visibility == 'leaders':
        return role in LEADERS
    return False


def can_see(row, *, logged_in, role):
    """Leaders-only, hidden, missing, and unknown locks stay off the page for everyone else."""
    role = _viewer_role(logged_in, role)
    if _flag(row.get('hidden')) or _flag(row.get('missing_on_drive')):
        return role in EDITORS
    visibility = (row.get('visibility') or 'public').lower()
    if visibility not in VISIBILITIES:
        return role in EDITORS
    if visibility == 'leaders':
        return can_listen(row, logged_in=logged_in, role=role)
    return True


def _preached_parts(value):
    if hasattr(value, 'isoformat'):
        iso = value.isoformat()[:10]
        label = value.strftime('%B %d, %Y').replace(' 0', ' ')
        return iso, label
    if not value:
        return '', ''
    iso = str(value)[:10]
    parsed = _valid_date(iso)
    if not parsed:
        return iso, iso
    year, month, day = (int(part) for part in parsed.split('-'))
    label = datetime.date(year, month, day).strftime('%B %d, %Y').replace(' 0', ' ')
    return parsed, label


def present(row, *, logged_in, role):
    """Card for a template. Folder ids are left out. The player URL is added only when they can listen."""
    role = _viewer_role(logged_in, role)
    listen = can_listen(row, logged_in=logged_in, role=role)
    visibility = (row.get('visibility') or 'public').lower()
    if visibility not in VISIBILITIES:
        visibility = 'public'
    iso, label = _preached_parts(row.get('preached_on'))
    if visibility == 'members' and not listen:
        lock = 'Sign in to listen'
    elif visibility == 'leaders':
        lock = 'This message is for church leaders.'
    elif _flag(row.get('hidden')) and not listen:
        lock = 'Hidden on this site.'
    else:
        lock = ''
    return {
        'id': row.get('id'),
        'title': row.get('title') or 'Message',
        'speaker': row.get('speaker') or '',
        'scripture': row.get('scripture') or '',
        'summary': row.get('summary') or '',
        'series': row.get('series') or '',
        'preached_on': iso,
        'preached_label': label,
        'kind': row.get('kind') or 'audio',
        'visibility': visibility,
        'hidden': bool(_flag(row.get('hidden'))),
        'missing': bool(_flag(row.get('missing_on_drive'))),
        'can_listen': listen,
        'can_edit': role in EDITORS,
        'comment_count': _count(row.get('comment_count')),
        'play_url': play_url(row.get('drive_file_id')) if listen else None,
        'lock_message': lock,
        'drive_name': (row.get('drive_name') or '') if role in EDITORS else '',
    }


def playlist_rows(rows, *, logged_in, role, year=''):
    """Messages this person can play, in library order. Locked rows stay out."""
    chosen = []
    for row in rows or []:
        if year and row_year(row) != year:
            continue
        if can_listen(row, logged_in=logged_in, role=role):
            chosen.append(row)
    return chosen


def playlist_spot(rows, item_id, *, logged_in, role, year=''):
    """Where this message sits in the play-all list. File ids are left out."""
    chosen = playlist_rows(rows, logged_in=logged_in, role=role, year=year)
    ids = []
    for row in chosen:
        try:
            ids.append(int(row.get('id')))
        except (TypeError, ValueError):
            continue
    try:
        current = int(item_id)
    except (TypeError, ValueError):
        return None
    if current not in ids:
        return None
    index = ids.index(current)
    return {
        'position': index + 1,
        'total': len(ids),
        'prev_id': ids[index - 1] if index else None,
        'next_id': ids[index + 1] if index + 1 < len(ids) else None,
        'year': year or '',
    }


def edit_view(row):
    """Edit form values. The Drive file id is not included."""
    iso, _label = _preached_parts(row.get('preached_on'))
    visibility = (row.get('visibility') or 'public').lower()
    if visibility not in VISIBILITIES:
        visibility = 'public'
    return {
        'id': row.get('id'),
        'drive_name': row.get('drive_name') or '',
        'title': row.get('title') or '',
        'speaker': row.get('speaker') or '',
        'scripture': row.get('scripture') or '',
        'summary': row.get('summary') or '',
        'series': row.get('series') or '',
        'preached_on': iso,
        'visibility': visibility,
        'hidden': bool(_flag(row.get('hidden'))),
        'missing': bool(_flag(row.get('missing_on_drive'))),
    }


def _clean_text(value, limit, keep_newlines=False):
    allowed_extra = '\n\t' if keep_newlines else ''
    chars = []
    for ch in str(value or ''):
        # Drop invisible format characters so a banned word cannot be split
        # around a zero-width space and still read as that word on the page.
        if unicodedata.category(ch) == 'Cf':
            continue
        if ch in allowed_extra or ch >= ' ':
            chars.append(ch)
    return ''.join(chars).strip()[:limit]


def clean_edit(form):
    """Validate a site-only edit. Returns (fields, errors)."""
    title = _clean_text(form.get('title'), 255)
    errors = []
    if not title:
        errors.append('A title is required.')
    visibility = (form.get('visibility') or '').strip().lower()
    if visibility not in VISIBILITIES:
        errors.append('Choose who can listen.')
        visibility = 'public'
    preached_raw = _clean_text(form.get('preached_on'), 10)
    preached = None
    if preached_raw:
        preached = _valid_date(preached_raw)
        if not preached:
            errors.append('Use a real date, or leave the date blank.')
    fields = {
        'title': title,
        'speaker': _clean_text(form.get('speaker'), 160) or None,
        'scripture': _clean_text(form.get('scripture'), 255) or None,
        'series': _clean_text(form.get('series'), 160) or None,
        'summary': _clean_text(form.get('summary'), 4000, keep_newlines=True) or None,
        'preached_on': preached,
        'visibility': visibility,
        'hidden': 1 if str(form.get('hidden') or '') == '1' else 0,
    }
    return fields, errors


def prepare_drive_comment(form, *, logged_in, account_name=''):
    """Clean a comment. Guests must leave a name. Members keep their account name.

    The returned fields are the name, the text, and an optional reply id.
    A posted user id or address is ignored.
    """
    from app.utils.helpers import CENSORED_WORD_MESSAGE, contains_censored_word, identity_spam_reason

    errors = []
    raw_comment = str(form.get('comment') or '')
    text = _clean_text(raw_comment, _COMMENT_LIMIT, keep_newlines=True)
    if not text:
        errors.append('Write a comment first.')
    elif len(raw_comment.strip()) > _COMMENT_LIMIT:
        errors.append('Keep the comment under 2000 characters.')
    parent_raw = _clean_text(form.get('parent_id'), 12)
    parent_id = None
    if parent_raw:
        if not parent_raw.isdigit() or int(parent_raw) <= 0:
            errors.append('That reply could not be matched to a comment.')
        else:
            parent_id = int(parent_raw)
    action = str(form.get('action') or 'comment').strip().lower()
    if action == 'reply' and parent_id is None:
        errors.append('That reply could not be matched to a comment.')
    if logged_in:
        name = _clean_text(account_name, _NAME_LIMIT) or 'Member'
    else:
        name = _clean_text(form.get('contributor_name'), _NAME_LIMIT)
        if not name:
            errors.append('Leave your name with the comment.')
        else:
            reason = identity_spam_reason(name)
            if reason:
                errors.append(reason)
    # Fold lookalike letters (fullwidth and similar) before the shared word list.
    # The stored comment stays the cleaned text. The page still escapes it.
    checked = unicodedata.normalize('NFKC', f'{name} {text}')
    if (text or name) and contains_censored_word(checked):
        errors.append(CENSORED_WORD_MESSAGE)
    return {'name': name, 'comment': text, 'parent_id': parent_id}, errors


def _comment_parent_ok(item_id, parent_id):
    """A reply can only sit under a top-level comment on this same message."""
    from app.models.db import get_db
    cur = get_db().cursor()
    cur.execute(
        """
        SELECT id FROM sermon_drive_comments
         WHERE id=%s AND item_id=%s AND parent_id IS NULL AND COALESCE(removed, 0) = 0
        """,
        (parent_id, item_id),
    )
    return cur.fetchone() is not None


def save_drive_comment(item_id, form, *, logged_in, account_name='', user_id=None, ip=None):
    """Store one comment. Returns (ok, errors). The Drive file is not changed."""
    from app.utils.comment_moderation import comment_throttle_message, insert_public_comment

    fields, errors = prepare_drive_comment(form, logged_in=logged_in, account_name=account_name)
    if errors:
        return False, errors
    try:
        if fields['parent_id'] is not None and not _comment_parent_ok(item_id, fields['parent_id']):
            return False, ['That reply could not be matched to a comment.']
        slow = comment_throttle_message(user_id, ip)
        if slow:
            return False, [slow]
        saved = insert_public_comment(
            'sermon_drive',
            item_id,
            fields['name'],
            fields['comment'],
            fields['parent_id'],
            ip=ip,
            user_id=user_id,
        )
    except Exception as exc:
        log.warning('sermon drive comment failed: %s', type(exc).__name__)
        saved = False
    if not saved:
        return False, ['That comment could not be posted.']
    return True, []


def drive_comment_thread(item_id, viewer_ip, viewer_user_id, *, for_moderator=False):
    """Comments this viewer is allowed to see. An empty list when the table cannot be read.

    Moderators also see shadowed and removed rows so they can restore them.
    The address is not included.
    """
    try:
        from app.utils.comment_moderation import (
            fetch_manager_comments,
            fetch_public_comments,
            map_comments_legacy,
        )
        if for_moderator:
            rows = fetch_manager_comments('sermon_drive', item_id)
        else:
            rows = fetch_public_comments('sermon_drive', item_id, viewer_ip, viewer_user_id)
        return map_comments_legacy(rows)
    except Exception as exc:
        log.warning('sermon drive comments failed: %s', type(exc).__name__)
        return []


def parse_visibility(raw):
    text = str(raw if raw is not None else '').strip().lower()
    if text not in VISIBILITY_LABELS:
        return None
    return text


def normalize_visibility(value):
    picked = parse_visibility(value)
    if picked is None:
        return DEFAULT_VISIBILITY
    return picked


def plan_sync(existing_by_id, seen_files, *, complete, default_visibility=DEFAULT_VISIBILITY):
    """Decide inserts and updates. Site-edited titles stay put. An incomplete walk does not mark rows missing."""
    upserts = []
    seen_ids = set()
    for item in seen_files:
        file_id = item['file_id']
        seen_ids.add(file_id)
        parsed = parse_drive_name(item.get('name') or '')
        base = {
            'drive_file_id': file_id,
            'parent_folder_id': item.get('parent_folder_id'),
            'drive_name': (item.get('name') or '')[:500],
            'mime_type': ((item.get('mime') or '')[:120] or None),
            'kind': item.get('kind') or 'audio',
            'drive_modified': ((item.get('modified') or '')[:40] or None),
            'missing_on_drive': 0,
        }
        old = existing_by_id.get(file_id)
        if old is None:
            base.update(parsed)
            base['visibility'] = normalize_visibility(default_visibility)
            base['site_edited'] = 0
            base['hidden'] = 0
            base['op'] = 'insert'
            base['refresh_details'] = True
        else:
            base['op'] = 'update'
            base['id'] = old.get('id')
            name_changed = (old.get('drive_name') or '') != (item.get('name') or '')
            if not _flag(old.get('site_edited')) and name_changed:
                base.update(parsed)
                base['refresh_details'] = True
            else:
                base['refresh_details'] = False
        upserts.append(base)
    missing_ids = []
    if complete:
        for file_id, old in existing_by_id.items():
            if file_id not in seen_ids:
                missing_ids.append(old.get('id'))
    return {'upserts': upserts, 'missing_ids': missing_ids}


def parse_refresh_hours(raw):
    """Return an allowed interval, or None when the choice is not one of the four."""
    text = str(raw if raw is not None else '').strip()
    if not text.isdigit():
        return None
    hours = int(text)
    if hours not in REFRESH_LABELS:
        return None
    return hours


def normalize_refresh_hours(value):
    picked = parse_refresh_hours(value)
    if picked is None:
        return DEFAULT_REFRESH_HOURS
    return picked


def is_stale(synced_at, *, refresh_hours=DEFAULT_REFRESH_HOURS, now=None):
    """True when a page view should read Drive. A saved library on a manual schedule stays put."""
    hours = normalize_refresh_hours(refresh_hours)
    if not synced_at:
        return True
    if hours == 0:
        return False
    if isinstance(synced_at, str):
        try:
            synced_at = datetime.datetime.fromisoformat(synced_at.replace('Z', ''))
        except ValueError:
            return True
    if getattr(synced_at, 'tzinfo', None) is not None:
        synced_at = synced_at.replace(tzinfo=None)
    now = now or datetime.datetime.now()
    if getattr(now, 'tzinfo', None) is not None:
        now = now.replace(tzinfo=None)
    return (now - synced_at).total_seconds() > hours * 3600


def row_year(row):
    preached = row.get('preached_on')
    if hasattr(preached, 'year'):
        return str(preached.year)
    if preached:
        return str(preached)[:4]
    return ''


def fetch_folder_html(folder_id, timeout=FETCH_TIMEOUT):
    url = folder_list_url(folder_id)
    if not url:
        raise DriveReadError()
    import urllib.request
    req = urllib.request.Request(url, headers={'User-Agent': _BROWSER_UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(2_000_000)
    except Exception:
        raise DriveReadError() from None
    return raw.decode('utf-8', 'replace')


def _lock_path():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'tmp'))
    os.makedirs(root, exist_ok=True)
    return os.path.join(root, 'sermon_drive_sync.lock')


def _acquire_lock():
    import fcntl
    handle = open(_lock_path(), 'a+')
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    return handle


def _release_lock(handle):
    import fcntl
    if handle is None:
        return
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def ensure_schema():
    global _schema_ready
    if _schema_ready:
        return
    from app.builddb.sermon_drive import create_tables
    from app.models.db import get_db
    db = get_db()
    cur = db.cursor()
    create_tables(cur)
    _schema_ready = True


def _source():
    from app.models.db import get_db
    cur = get_db().cursor()
    cur.execute(
        "SELECT id, folder_id, label, enabled, synced_at, refresh_hours, default_visibility "
        "FROM sermon_drive_sources WHERE enabled=1 ORDER BY id LIMIT 1"
    )
    return cur.fetchone()


def _apply_plan(source_id, plan):
    from app.models.db import get_db
    cur = get_db().cursor()
    now = datetime.datetime.now().replace(microsecond=0)
    for item in plan['upserts']:
        if item['op'] == 'insert':
            cur.execute(
                """
                INSERT INTO sermon_drive_items (
                    source_id, drive_file_id, parent_folder_id, drive_name, mime_type, kind,
                    drive_modified, title, speaker, scripture, summary, series, preached_on,
                    visibility, hidden, site_edited, missing_on_drive, synced_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s
                )
                """,
                (
                    source_id, item['drive_file_id'], item['parent_folder_id'], item['drive_name'],
                    item['mime_type'], item['kind'], item['drive_modified'], item['title'],
                    item['speaker'], item['scripture'], item['summary'], item['series'],
                    item['preached_on'], item['visibility'], item['hidden'], item['site_edited'],
                    item['missing_on_drive'], now,
                ),
            )
            continue
        if item['refresh_details']:
            cur.execute(
                """
                UPDATE sermon_drive_items
                   SET parent_folder_id=%s, drive_name=%s, mime_type=%s, kind=%s,
                       drive_modified=%s, title=%s, speaker=%s, scripture=%s, summary=%s,
                       series=%s, preached_on=%s, missing_on_drive=0, synced_at=%s
                 WHERE id=%s
                """,
                (
                    item['parent_folder_id'], item['drive_name'], item['mime_type'], item['kind'],
                    item['drive_modified'], item['title'], item['speaker'], item['scripture'],
                    item['summary'], item['series'], item['preached_on'], now, item['id'],
                ),
            )
        else:
            cur.execute(
                """
                UPDATE sermon_drive_items
                   SET parent_folder_id=%s, drive_name=%s, mime_type=%s, kind=%s,
                       drive_modified=%s, missing_on_drive=0, synced_at=%s
                 WHERE id=%s
                """,
                (
                    item['parent_folder_id'], item['drive_name'], item['mime_type'], item['kind'],
                    item['drive_modified'], now, item['id'],
                ),
            )
    missing_ids = [item_id for item_id in plan['missing_ids'] if item_id]
    if missing_ids:
        marks = ','.join(['%s'] * len(missing_ids))
        cur.execute(
            f"UPDATE sermon_drive_items SET missing_on_drive=1, synced_at=%s WHERE id IN ({marks})",
            [now, *missing_ids],
        )
    cur.execute(
        "UPDATE sermon_drive_sources SET synced_at=%s WHERE id=%s",
        (now, source_id),
    )


def sync_source(source, fetch=None):
    """Refresh one source. A failed read leaves existing rows, including site edits, alone."""
    fetch = fetch or fetch_folder_html
    handle = _acquire_lock()
    if handle is None:
        return {'ok': False, 'busy': True, 'count': None}
    try:
        try:
            walked = walk_folder(source['folder_id'], fetch)
        except DriveReadError:
            log.warning('sermon drive sync failed: %s', DriveReadError.__name__)
            return {'ok': False, 'busy': False, 'count': None}
        from app.models.db import get_db
        cur = get_db().cursor()
        cur.execute(
            "SELECT id, drive_file_id, drive_name, site_edited, missing_on_drive "
            "FROM sermon_drive_items WHERE source_id=%s",
            (source['id'],),
        )
        existing = {row['drive_file_id']: row for row in cur.fetchall()}
        plan = plan_sync(
            existing,
            walked.files,
            complete=walked.complete,
            default_visibility=normalize_visibility(source.get('default_visibility')),
        )
        _apply_plan(source['id'], plan)
        return {'ok': True, 'busy': False, 'count': len(walked.files)}
    except Exception as exc:
        log.warning('sermon drive sync failed: %s', type(exc).__name__)
        return {'ok': False, 'busy': False, 'count': None}
    finally:
        _release_lock(handle)


def maybe_sync():
    """Read Drive only when the saved schedule is due. The player itself is not a download."""
    try:
        ensure_schema()
        source = _source()
        if not source or not is_stale(
            source.get('synced_at'), refresh_hours=source.get('refresh_hours')
        ):
            return
        sync_source(source)
    except Exception as exc:
        log.warning('sermon drive sync failed: %s', type(exc).__name__)


def current_refresh_hours():
    try:
        ensure_schema()
        source = _source()
        if not source:
            return DEFAULT_REFRESH_HOURS
        return normalize_refresh_hours(source.get('refresh_hours'))
    except Exception as exc:
        log.warning('sermon drive schedule read failed: %s', type(exc).__name__)
        return DEFAULT_REFRESH_HOURS


def sync_now():
    try:
        ensure_schema()
        source = _source()
        if not source:
            return {'ok': False, 'busy': False, 'count': None}
        return sync_source(source)
    except Exception as exc:
        log.warning('sermon drive sync failed: %s', type(exc).__name__)
        return {'ok': False, 'busy': False, 'count': None}


def list_items():
    try:
        ensure_schema()
        source = _source()
        if not source:
            return []
        from app.models.db import get_db
        cur = get_db().cursor()
        cur.execute(
            """
            SELECT id, drive_file_id, parent_folder_id, drive_name, mime_type, kind,
                   drive_modified, title, speaker, scripture, summary, series,
                   preached_on, visibility, hidden, site_edited, missing_on_drive,
                   (SELECT COUNT(*) FROM sermon_drive_comments c
                     WHERE c.item_id = sermon_drive_items.id
                       AND COALESCE(c.removed, 0) = 0
                       AND COALESCE(c.shadowed, 0) = 0) AS comment_count
              FROM sermon_drive_items
             WHERE source_id=%s
             ORDER BY preached_on IS NULL, preached_on DESC, title ASC
            """,
            (source['id'],),
        )
        return list(cur.fetchall())
    except Exception as exc:
        log.warning('sermon drive list failed: %s', type(exc).__name__)
        return []


def get_item(item_id):
    try:
        ensure_schema()
        from app.models.db import get_db
        cur = get_db().cursor()
        cur.execute(
            """
            SELECT id, source_id, drive_file_id, parent_folder_id, drive_name, mime_type, kind,
                   drive_modified, title, speaker, scripture, summary, series,
                   preached_on, visibility, hidden, site_edited, missing_on_drive
              FROM sermon_drive_items
             WHERE id=%s
            """,
            (item_id,),
        )
        return cur.fetchone()
    except Exception as exc:
        log.warning('sermon drive read failed: %s', type(exc).__name__)
        return None


def save_item_details(item_id, form, user_id):
    """Store site fields only. The Drive file is not changed."""
    fields, errors = clean_edit(form)
    if errors:
        return False, errors
    try:
        ensure_schema()
        from app.models.db import get_db
        cur = get_db().cursor()
        cur.execute(
            """
            UPDATE sermon_drive_items
               SET title=%s, speaker=%s, scripture=%s, summary=%s, series=%s,
                   preached_on=%s, visibility=%s, hidden=%s, site_edited=1, updated_by=%s
             WHERE id=%s
            """,
            (
                fields['title'], fields['speaker'], fields['scripture'], fields['summary'],
                fields['series'], fields['preached_on'], fields['visibility'], fields['hidden'],
                user_id, item_id,
            ),
        )
        if cur.rowcount == 0:
            # rowcount is 0 when values did not change; confirm the row exists
            cur.execute("SELECT id FROM sermon_drive_items WHERE id=%s", (item_id,))
            if not cur.fetchone():
                return False, ['That message is not in the library.']
        return True, []
    except Exception as exc:
        log.warning('sermon drive save failed: %s', type(exc).__name__)
        return False, ['Those details could not be saved just now.']


def current_default_visibility():
    try:
        ensure_schema()
        source = _source()
        if not source:
            return DEFAULT_VISIBILITY
        return normalize_visibility(source.get('default_visibility'))
    except Exception as exc:
        log.warning('sermon drive default read failed: %s', type(exc).__name__)
        return DEFAULT_VISIBILITY


def save_default_visibility(raw):
    """Who new Drive messages start as. Existing messages are left alone."""
    visibility = parse_visibility(raw)
    if visibility is None:
        return 'bad', None
    try:
        ensure_schema()
        from app.models.db import get_db
        cur = get_db().cursor()
        cur.execute(
            "UPDATE sermon_drive_sources SET default_visibility=%s WHERE enabled=1",
            (visibility,),
        )
        return 'ok', visibility
    except Exception as exc:
        log.warning('sermon drive default save failed: %s', type(exc).__name__)
        return 'error', None


def apply_visibility_to_all(raw):
    """Set who can listen on every saved message. Titles and hidden flags stay."""
    visibility = parse_visibility(raw)
    if visibility is None:
        return 'bad', None
    try:
        ensure_schema()
        source = _source()
        if not source:
            return 'error', None
        from app.models.db import get_db
        cur = get_db().cursor()
        cur.execute(
            "UPDATE sermon_drive_items SET visibility=%s WHERE source_id=%s",
            (visibility, source['id']),
        )
        return 'ok', visibility
    except Exception as exc:
        log.warning('sermon drive visibility update failed: %s', type(exc).__name__)
        return 'error', None


def save_refresh_hours(raw):
    """Store the check schedule. Returns ('ok', hours), ('bad', None), or ('error', None)."""
    hours = parse_refresh_hours(raw)
    if hours is None:
        return 'bad', None
    try:
        ensure_schema()
        from app.models.db import get_db
        cur = get_db().cursor()
        cur.execute(
            "UPDATE sermon_drive_sources SET refresh_hours=%s WHERE enabled=1",
            (hours,),
        )
        return 'ok', hours
    except Exception as exc:
        log.warning('sermon drive schedule save failed: %s', type(exc).__name__)
        return 'error', None


def save_folder_id(raw):
    """Store a new folder id. The value is not returned for display."""
    folder_id = extract_folder_id(raw)
    if not folder_id:
        return False
    try:
        ensure_schema()
        from app.models.db import get_db
        cur = get_db().cursor()
        cur.execute(
            "SELECT id FROM sermon_drive_sources WHERE enabled=1 ORDER BY id LIMIT 1"
        )
        row = cur.fetchone()
        if row:
            cur.execute(
                "UPDATE sermon_drive_sources SET folder_id=%s, synced_at=NULL WHERE id=%s",
                (folder_id, row['id']),
            )
        else:
            from app.builddb.sermon_drive import SEED_LABEL
            cur.execute(
                "INSERT INTO sermon_drive_sources (folder_id, label, enabled) VALUES (%s, %s, 1)",
                (folder_id, SEED_LABEL),
            )
        return True
    except Exception as exc:
        log.warning('sermon drive folder save failed: %s', type(exc).__name__)
        return False
