# Read a public Google Drive folder listing and shape it for the sermon pages.
# Playback stays on Drive. Nothing here writes back to Drive.
# A person who may save can store one copy outside the web folder.

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


def download_url(file_id, confirm=None):
    """One Drive download URL built from a file id. Never a link from a page."""
    if not _ID.fullmatch(file_id or ''):
        return None
    import urllib.parse
    query = {'export': 'download', 'id': file_id}
    if confirm is not None:
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', confirm):
            return None
        query['confirm'] = confirm
    return 'https://drive.google.com/uc?' + urllib.parse.urlencode(query)


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


SORTS = ('date', 'speaker', 'folder')
SORT_CHOICES = (
    ('date', 'Date'),
    ('speaker', 'Speaker'),
    ('folder', 'Folder'),
)


def parse_sort(value):
    text = str(value or '').strip().lower()
    if text in SORTS:
        return text
    return 'date'


def speaker_key(value):
    """Fold a speaker name so Tim and tim are one person, and Tim Lien is not."""
    text = _clean_text(value, 160)
    if not text:
        return None
    text = unicodedata.normalize('NFKC', text)
    text = re.sub(r'\s+', ' ', text).strip().casefold()
    return text or None


def speaker_match(name, names):
    """Exact saved spelling only. names maps a folded name to a speaker id."""
    key = speaker_key(name)
    if not key:
        return None
    return (names or {}).get(key)


def _when_text(row):
    preached = row.get('preached_on')
    if hasattr(preached, 'isoformat'):
        return preached.isoformat()[:10]
    if preached:
        return str(preached)[:10]
    return ''


def sort_rows(rows, sort='date'):
    """Date is newest first. Speaker and folder group those names, then newest first."""
    chosen = parse_sort(sort)
    items = list(rows or [])

    def title(row):
        return (row.get('title') or '').casefold()

    def speaker(row):
        return (row.get('speaker_label') or row.get('speaker') or '').casefold()

    def folder(row):
        return (row.get('source_label') or '').casefold()

    items.sort(key=title)
    items.sort(key=_when_text, reverse=True)
    if chosen == 'speaker':
        items.sort(key=speaker)
    elif chosen == 'folder':
        items.sort(key=folder)
    return items


def plan_speaker_form(form, accounts):
    """Read the edit form. A member id counts only when it is in accounts.

    accounts maps a real user id to the name we show. Returns (choice, errors).
    """
    raw_speaker = str(form.get('speaker_id') if form.get('speaker_id') is not None else '').strip()
    raw_user = str(form.get('speaker_user') if form.get('speaker_user') is not None else '').strip()
    speaker_id = int(raw_speaker) if raw_speaker.isdigit() and int(raw_speaker) > 0 else None
    user_id = int(raw_user) if raw_user.isdigit() and int(raw_user) > 0 else None
    if raw_speaker and speaker_id is None:
        return None, ['Choose a speaker from the list.']
    if raw_user and user_id is None:
        return None, ['Choose a member from the list.']
    if user_id and user_id not in (accounts or {}):
        return None, ['Choose a member from the list.']
    name = _clean_text(form.get('speaker'), 160)
    name_key = speaker_key(name)
    if not speaker_id and not user_id and not name_key:
        return {'clear': True}, []
    return {
        'clear': False,
        'speaker_id': speaker_id,
        'user_id': user_id,
        'account_name': (accounts or {}).get(user_id) if user_id else None,
        'name': name if name_key else None,
        'name_key': name_key,
    }, []


def decide_speaker(choice, speakers):
    """Pick the speaker row to use. Does not write. Returns (decision, error)."""
    if not choice or choice.get('clear'):
        return {'action': 'clear'}, None
    by_id = {}
    by_user = {}
    by_name = {}
    for person in speakers or []:
        by_id[int(person['id'])] = person
        if person.get('user_id'):
            by_user[int(person['user_id'])] = person
        for key in person.get('names') or []:
            by_name[key] = person
    selected = by_id.get(choice.get('speaker_id')) if choice.get('speaker_id') else None
    if choice.get('speaker_id') and selected is None:
        return None, 'Choose a speaker from the list.'
    account = by_user.get(choice.get('user_id')) if choice.get('user_id') else None
    named = by_name.get(choice.get('name_key')) if choice.get('name_key') else None
    add_names = []
    if choice.get('name') and choice.get('name_key'):
        add_names.append((choice['name'], choice['name_key']))
    if choice.get('account_name'):
        account_key = speaker_key(choice['account_name'])
        if account_key:
            add_names.append((choice['account_name'], account_key))
    if choice.get('user_id'):
        if selected and selected.get('user_id') and int(selected['user_id']) != int(choice['user_id']):
            return None, 'That speaker is already linked to another account.'
        if named and named.get('user_id') and int(named['user_id']) != int(choice['user_id']):
            return None, 'That name is already linked to another account.'
        display = choice.get('account_name') or (selected or named or {}).get('display_name') or 'Speaker'
        if account and selected and int(account['id']) != int(selected['id']):
            return {
                'action': 'combine',
                'into_id': int(account['id']),
                'speaker_id': int(selected['id']),
                'user_id': int(choice['user_id']),
                'display_name': display,
                'add_names': add_names,
            }, None
        if account and named and int(named['id']) != int(account['id']):
            return {
                'action': 'combine',
                'into_id': int(account['id']),
                'speaker_id': int(named['id']),
                'user_id': int(choice['user_id']),
                'display_name': display,
                'add_names': add_names,
            }, None
        if account:
            return {
                'action': 'use',
                'speaker_id': int(account['id']),
                'user_id': int(choice['user_id']),
                'display_name': display,
                'add_names': add_names,
            }, None
        target = selected or named
        if target:
            return {
                'action': 'link',
                'speaker_id': int(target['id']),
                'user_id': int(choice['user_id']),
                'display_name': display,
                'add_names': add_names,
            }, None
        return {
            'action': 'create',
            'user_id': int(choice['user_id']),
            'display_name': display,
            'add_names': add_names,
        }, None
    if selected:
        if named and int(named['id']) != int(selected['id']):
            return None, 'That name already belongs to another speaker. Combine them on the Speakers page.'
        return {
            'action': 'use',
            'speaker_id': int(selected['id']),
            'user_id': int(selected['user_id']) if selected.get('user_id') else None,
            'display_name': selected.get('display_name') or choice.get('name') or 'Speaker',
            'add_names': add_names,
        }, None
    if named:
        return {
            'action': 'use',
            'speaker_id': int(named['id']),
            'user_id': int(named['user_id']) if named.get('user_id') else None,
            'display_name': named.get('display_name') or choice.get('name') or 'Speaker',
            'add_names': [],
        }, None
    return {
        'action': 'create',
        'user_id': None,
        'display_name': choice.get('name') or 'Speaker',
        'add_names': add_names,
    }, None


def plan_combine(dest, source):
    """Move one speaker onto another. Two different accounts stay apart."""
    if not dest or not source:
        return None, 'Choose two different speakers.'
    try:
        dest_id = int(dest.get('id'))
        source_id = int(source.get('id'))
    except (TypeError, ValueError):
        return None, 'Choose two different speakers.'
    if dest_id == source_id:
        return None, 'Choose two different speakers.'
    dest_user = dest.get('user_id')
    source_user = source.get('user_id')
    if dest_user and source_user and int(dest_user) != int(source_user):
        return None, 'Those names are already on two different accounts.'
    return {'into': dest_id, 'speaker_id': source_id}, None


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


def _folder_closed(row):
    """A hidden Drive folder leaves the library. Rows with no folder flag stay open."""
    if 'source_enabled' not in row:
        return False
    return not _flag(row.get('source_enabled'))


def can_listen(row, *, logged_in, role):
    role = _viewer_role(logged_in, role)
    editor = role in EDITORS
    if _folder_closed(row):
        return editor
    if _flag(row.get('hidden')):
        return editor
    # A missing Drive file stays staff-only unless a host copy was saved.
    if _flag(row.get('missing_on_drive')) and not local_copy_name(row):
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
    if _folder_closed(row):
        return role in EDITORS
    if _flag(row.get('hidden')):
        return role in EDITORS
    if _flag(row.get('missing_on_drive')) and not local_copy_name(row):
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
    missing = bool(_flag(row.get('missing_on_drive')))
    copied = local_copy_name(row) is not None
    if visibility == 'members' and not listen:
        lock = 'Sign in to listen'
    elif visibility == 'leaders':
        lock = 'This message is for church leaders.'
    elif _flag(row.get('hidden')) and not listen:
        lock = 'Hidden on this site.'
    else:
        lock = ''
    # The Drive player is only for a file that is still on Drive.
    # A saved copy is played by this site, and only after Drive no longer has it.
    return {
        'id': row.get('id'),
        'title': row.get('title') or 'Message',
        'scripture': row.get('scripture') or '',
        'summary': row.get('summary') or '',
        'series': row.get('series') or '',
        'preached_on': iso,
        'preached_label': label,
        'kind': row.get('kind') or 'audio',
        'speaker': row.get('speaker_label') or row.get('speaker') or '',
        'source_label': row.get('source_label') or '',
        'visibility': visibility,
        'hidden': bool(_flag(row.get('hidden'))),
        'missing': missing,
        'has_copy': copied,
        'local_play': bool(listen and missing and copied),
        'can_listen': listen,
        'can_edit': role in EDITORS,
        'comment_count': _count(row.get('comment_count')),
        'play_url': play_url(row.get('drive_file_id')) if listen and not missing else None,
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


def playlist_spot(rows, item_id, *, logged_in, role, year='', sort='date'):
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
        'sort': parse_sort(sort),
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
        'speaker': row.get('speaker_label') or row.get('speaker') or '',
        'speaker_id': row.get('speaker_id') or '',
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
                # A speaker the site already linked is not replaced by the file name.
                if old.get('speaker_id'):
                    base['speaker'] = old.get('speaker')
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


def _sources():
    from app.models.db import get_db
    cur = get_db().cursor()
    cur.execute(
        "SELECT id, folder_id, label, enabled, synced_at, refresh_hours, default_visibility "
        "FROM sermon_drive_sources WHERE enabled=1 ORDER BY label, id"
    )
    return list(cur.fetchall())


def _source():
    rows = _sources()
    return rows[0] if rows else None


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
            "SELECT id, drive_file_id, drive_name, site_edited, missing_on_drive, speaker, speaker_id "
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
        _attach_known_speakers(cur, source['id'])
        return {'ok': True, 'busy': False, 'count': len(walked.files)}
    except Exception as exc:
        log.warning('sermon drive sync failed: %s', type(exc).__name__)
        return {'ok': False, 'busy': False, 'count': None}
    finally:
        _release_lock(handle)


def maybe_sync():
    """Read each Drive folder only when its schedule is due. A play is not a download."""
    try:
        ensure_schema()
        for source in _sources():
            if not is_stale(source.get('synced_at'), refresh_hours=source.get('refresh_hours')):
                continue
            result = sync_source(source)
            if result.get('busy'):
                return
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
        sources = _sources()
        if not sources:
            return {'ok': False, 'busy': False, 'count': None}
        total = 0
        failed = False
        for source in sources:
            result = sync_source(source)
            if result.get('busy'):
                return {'ok': False, 'busy': True, 'count': total or None}
            if not result.get('ok'):
                failed = True
                continue
            total += result.get('count') or 0
        return {'ok': not failed, 'busy': False, 'count': total}
    except Exception as exc:
        log.warning('sermon drive sync failed: %s', type(exc).__name__)
        return {'ok': False, 'busy': False, 'count': None}


def list_items(sort='date'):
    try:
        ensure_schema()
        if not _sources():
            return []
        from app.models.db import get_db
        cur = get_db().cursor()
        cur.execute(
            """
            SELECT i.id, i.drive_file_id, i.parent_folder_id, i.drive_name, i.mime_type, i.kind,
                   i.drive_modified, i.title, i.speaker, i.scripture, i.summary, i.series,
                   i.preached_on, i.visibility, i.hidden, i.site_edited, i.missing_on_drive,
                   i.local_name, i.speaker_id,
                   s.label AS source_label,
                   sp.display_name AS speaker_label,
                   (SELECT COUNT(*) FROM sermon_drive_comments c
                     WHERE c.item_id = i.id
                       AND COALESCE(c.removed, 0) = 0
                       AND COALESCE(c.shadowed, 0) = 0) AS comment_count
              FROM sermon_drive_items i
              JOIN sermon_drive_sources s ON s.id = i.source_id AND s.enabled = 1
              LEFT JOIN sermon_speakers sp ON sp.id = i.speaker_id
            """
        )
        return sort_rows(list(cur.fetchall()), sort)
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
            SELECT i.id, i.source_id, i.drive_file_id, i.parent_folder_id, i.drive_name,
                   i.mime_type, i.kind, i.drive_modified, i.title, i.speaker, i.scripture,
                   i.summary, i.series, i.preached_on, i.visibility, i.hidden, i.site_edited,
                   i.missing_on_drive, i.local_name, i.speaker_id,
                   s.label AS source_label, s.enabled AS source_enabled,
                   sp.display_name AS speaker_label
              FROM sermon_drive_items i
              LEFT JOIN sermon_drive_sources s ON s.id = i.source_id
              LEFT JOIN sermon_speakers sp ON sp.id = i.speaker_id
             WHERE i.id=%s
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
        speaker_id, speaker_name, speaker_errors, changed = _apply_form_speaker(cur, form)
        if speaker_errors:
            return False, speaker_errors
        if changed:
            # A clear drops the name and the link. A chosen speaker uses the display name.
            fields['speaker'] = speaker_name if speaker_id else None
        else:
            cur.execute(
                "SELECT speaker, speaker_id FROM sermon_drive_items WHERE id=%s",
                (item_id,),
            )
            current = cur.fetchone() or {}
            if isinstance(current, dict):
                fields['speaker'] = current.get('speaker')
                speaker_id = current.get('speaker_id')
            elif current:
                fields['speaker'] = current[0]
                speaker_id = current[1]
            else:
                fields['speaker'] = None
                speaker_id = None
        cur.execute(
            """
            UPDATE sermon_drive_items
               SET title=%s, speaker=%s, speaker_id=%s, scripture=%s, summary=%s, series=%s,
                   preached_on=%s, visibility=%s, hidden=%s, site_edited=1, updated_by=%s
             WHERE id=%s
            """,
            (
                fields['title'], fields['speaker'], speaker_id, fields['scripture'], fields['summary'],
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
        if not _sources():
            return 'error', None
        from app.models.db import get_db
        cur = get_db().cursor()
        cur.execute(
            """
            UPDATE sermon_drive_items i
              JOIN sermon_drive_sources s ON s.id = i.source_id AND s.enabled = 1
               SET i.visibility=%s
            """,
            (visibility,),
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


def save_folder_id(raw, label=None):
    """Add a Drive folder, or rename it when that folder is already saved.

    Other folders stay. The id is not returned for display.
    """
    folder_id = extract_folder_id(raw)
    if not folder_id:
        return False
    cleaned = _clean_text(label, 120) if label else ''
    try:
        ensure_schema()
        from app.models.db import get_db
        cur = get_db().cursor()
        cur.execute(
            "SELECT id, label FROM sermon_drive_sources WHERE folder_id=%s LIMIT 1",
            (folder_id,),
        )
        row = cur.fetchone()
        if row:
            next_label = cleaned or (row.get('label') if isinstance(row, dict) else None) or 'Messages'
            cur.execute(
                "UPDATE sermon_drive_sources SET label=%s, enabled=1 WHERE id=%s",
                (next_label, row.get('id') if isinstance(row, dict) else row[0]),
            )
        else:
            from app.builddb.sermon_drive import SEED_LABEL
            cur.execute(
                "INSERT INTO sermon_drive_sources (folder_id, label, enabled) VALUES (%s, %s, 1)",
                (folder_id, cleaned or SEED_LABEL),
            )
        return True
    except Exception as exc:
        log.warning('sermon drive folder save failed: %s', type(exc).__name__)
        return False


# One saved copy lives outside the site folder. The page never prints this path.
MAX_COPY_BYTES = 200 * 1024 * 1024
_HTML_READ = 256 * 1024
_COPY_TIMEOUT = 90
_COPY_NAME = re.compile(r'^(\d{1,10})\.(mp3|m4a|wav|aac|ogg|mp4|webm|mov|mkv)$')
_CONFIRM_RE = re.compile(br'confirm(?:=|" value=")([A-Za-z0-9_-]{1,80})')
_DOWNLOAD_HOSTS = frozenset({
    'drive.google.com',
    'docs.google.com',
    'drive.usercontent.google.com',
})
_MIME_EXT = {
    'audio/mpeg': 'mp3',
    'audio/mp3': 'mp3',
    'audio/mpeg3': 'mp3',
    'audio/x-mpeg': 'mp3',
    'audio/mp4': 'm4a',
    'audio/x-m4a': 'm4a',
    'audio/m4a': 'm4a',
    'audio/aac': 'aac',
    'audio/x-aac': 'aac',
    'audio/wav': 'wav',
    'audio/x-wav': 'wav',
    'audio/wave': 'wav',
    'audio/ogg': 'ogg',
    'application/ogg': 'ogg',
    'video/mp4': 'mp4',
    'application/mp4': 'mp4',
    'video/webm': 'webm',
    'video/quicktime': 'mov',
    'video/x-matroska': 'mkv',
}
_REDIRECTS = frozenset({301, 302, 303, 307, 308})


class CopyError(Exception):
    """A host copy could not be saved. The code is safe to show as a status."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


class _Remote:
    def __init__(self, status, location='', content_type='', body=None):
        self.status = status
        self.location = location or ''
        self.content_type = content_type or ''
        self.body = body


def local_copy_name(row):
    """Stored file name for this row, or None. Not a path and not a Drive id."""
    if not row:
        return None
    name = str(row.get('local_name') or '')
    match = _COPY_NAME.fullmatch(name)
    if not match:
        return None
    try:
        stem = str(int(row.get('id')))
    except (TypeError, ValueError):
        return None
    if match.group(1) != stem:
        return None
    return name


def _app_root():
    return os.path.realpath(os.path.join(os.path.dirname(__file__), '..', '..'))


def backup_root():
    """Directory for saved messages. Refuses the site folder and the public web root."""
    raw = (os.environ.get('SERMON_BACKUP_DIR') or '').strip()
    if raw:
        path = os.path.realpath(os.path.expanduser(raw))
    else:
        path = os.path.realpath(os.path.join(
            os.path.expanduser('~'), '.config', 'poweredbytop', 'sermon-copies',
        ))
    root = _app_root()
    home = os.path.realpath(os.path.expanduser('~'))
    try:
        inside_site = os.path.commonpath([path, root]) == root
    except ValueError:
        inside_site = False
    if inside_site or path in (root, os.path.realpath('/'), home):
        raise CopyError('place')
    return path


def ensure_backup_root():
    path = backup_root()
    os.makedirs(path, mode=0o700, exist_ok=True)
    if not os.path.isdir(path):
        raise CopyError('error')
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    return path


def open_local_copy(row):
    """Absolute path of a saved copy, or None. A name that leaves the folder is refused."""
    name = local_copy_name(row)
    if not name:
        return None
    try:
        root = os.path.realpath(backup_root())
    except CopyError:
        return None
    if not os.path.isdir(root):
        return None
    path = os.path.realpath(os.path.join(root, name))
    try:
        if os.path.commonpath([root, path]) != root:
            return None
    except ValueError:
        return None
    if not os.path.isfile(path):
        return None
    return path


def _unlink(path):
    try:
        if path and os.path.lexists(path):
            os.remove(path)
    except OSError:
        pass


def _host_ok(hostname):
    host = (hostname or '').lower().rstrip('.')
    if not host or host in _DOWNLOAD_HOSTS:
        return host in _DOWNLOAD_HOSTS
    return host.endswith('.googleusercontent.com')


def _url_ok(url):
    if not url or len(url) > 2000 or any(ch in url for ch in '\r\n\t\x00 '):
        return False
    import urllib.parse
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'https' or parsed.username or parsed.password:
        return False
    if parsed.port not in (None, 443):
        return False
    return _host_ok(parsed.hostname)


def _content_type(value):
    return (value or '').split(';', 1)[0].strip().lower()


def _is_html_type(value):
    return _content_type(value) in (
        'text/html', 'application/xhtml+xml', 'text/plain', 'text/xml', 'application/xml',
    )


def _sniff_html(head):
    sample = (head or b'').lstrip()[:32].lower()
    return sample.startswith((b'<!doctype', b'<html', b'<head', b'<body', b'<?xml'))


def _copy_extension(content_type, drive_name):
    ctype = _content_type(content_type)
    if ctype in _MIME_EXT:
        return _MIME_EXT[ctype]
    match = _MEDIA_EXT.search(drive_name or '')
    name_ext = match.group(1).lower() if match else ''
    if ctype in ('application/octet-stream', 'binary/octet-stream', 'application/binary', ''):
        return name_ext or None
    if ctype.startswith('audio/') or ctype.startswith('video/'):
        return name_ext or None
    return None


def _confirm_token(blob):
    found = _CONFIRM_RE.search(blob or b'')
    if not found:
        return None
    try:
        return found.group(1).decode('ascii')
    except UnicodeError:
        return None


def _consume(body, dest, limit, html_cap):
    total = 0
    head = b''
    htmlish = html_cap
    with open(dest, 'wb') as handle:
        while True:
            block = body.read(65536)
            if not block:
                break
            if len(head) < 1024:
                head += block[:1024 - len(head)]
                if _sniff_html(head):
                    htmlish = True
            cap = _HTML_READ if htmlish else limit
            if total + len(block) > cap:
                if htmlish:
                    room = cap - total
                    if room > 0:
                        handle.write(block[:room])
                        total += room
                    break
                raise CopyError('large')
            handle.write(block)
            total += len(block)
    return total, head, htmlish or _sniff_html(head)


def _urllib_transport(url, timeout=_COPY_TIMEOUT):
    import urllib.error
    import urllib.request
    opener = urllib.request.OpenerDirector()
    opener.add_handler(urllib.request.HTTPHandler())
    opener.add_handler(urllib.request.HTTPSHandler())
    opener.add_handler(urllib.request.HTTPErrorProcessor())
    opener.add_handler(urllib.request.HTTPDefaultErrorHandler())
    req = urllib.request.Request(url, headers={'User-Agent': _BROWSER_UA})
    try:
        resp = opener.open(req, timeout=timeout)
    except urllib.error.HTTPError as exc:
        location = exc.headers.get('Location') if exc.headers is not None else ''
        code = exc.code
        exc.close()
        if code in _REDIRECTS:
            return _Remote(code, location=location or '')
        if code == 404:
            raise CopyError('gone')
        raise CopyError('error')
    except CopyError:
        raise
    except Exception:
        raise CopyError('error') from None
    headers = resp.headers
    getter = getattr(headers, 'get_content_type', None)
    ctype = getter() if getter else (headers.get('Content-Type') if headers else '')
    return _Remote(getattr(resp, 'status', 200) or 200, content_type=ctype or '', body=resp)


def pull_drive_file(file_id, directory, row_id, drive_name, *, transport, limit=MAX_COPY_BYTES):
    """Save one Drive file as {row id}.{ext} inside directory. The Drive name is not a path."""
    if not _ID.fullmatch(str(file_id or '')):
        raise CopyError('error')
    try:
        stem = str(int(row_id))
    except (TypeError, ValueError):
        raise CopyError('error')
    if not re.fullmatch(r'\d{1,10}', stem):
        raise CopyError('error')
    import urllib.parse
    directory = os.path.realpath(directory)
    partial = os.path.join(directory, f'.{stem}.partial')
    url = download_url(file_id)
    confirm_tried = False
    hops = 0
    try:
        while hops < 5:
            hops += 1
            if not url or not _url_ok(url):
                raise CopyError('blocked')
            remote = transport(url)
            status = int(getattr(remote, 'status', 0) or 0)
            if status in _REDIRECTS:
                url = urllib.parse.urljoin(url, (getattr(remote, 'location', '') or '').strip())
                continue
            if status == 404:
                raise CopyError('gone')
            if status != 200 or getattr(remote, 'body', None) is None:
                raise CopyError('error')
            try:
                total, head, htmlish = _consume(
                    remote.body, partial, limit, _is_html_type(remote.content_type),
                )
            finally:
                closer = getattr(remote.body, 'close', None)
                if closer:
                    closer()
            if htmlish or _sniff_html(head) or _is_html_type(remote.content_type):
                token = None
                try:
                    with open(partial, 'rb') as handle:
                        token = _confirm_token(handle.read(_HTML_READ))
                except OSError:
                    token = None
                _unlink(partial)
                if confirm_tried:
                    raise CopyError('html')
                confirm_tried = True
                url = download_url(file_id, confirm=token or 't')
                continue
            ext = _copy_extension(remote.content_type, drive_name)
            if not ext or total <= 0:
                _unlink(partial)
                raise CopyError('type' if not ext else 'error')
            final_name = f'{stem}.{ext}'
            os.chmod(partial, 0o600)
            os.replace(partial, os.path.join(directory, final_name))
            return final_name, total
        raise CopyError('blocked')
    except CopyError:
        _unlink(partial)
        raise
    except Exception:
        _unlink(partial)
        log.warning('sermon copy read failed: %s', 'error')
        raise CopyError('error') from None


def _acquire_copy_lock(directory):
    import fcntl
    path = os.path.join(directory, '.copy.lock')
    handle = open(path, 'a+')
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return handle


def _count_value(row):
    if not row:
        return 0
    if isinstance(row, dict):
        value = row.get('n')
    else:
        value = row[0]
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


_UNSAVED_COLUMNS = (
    'id', 'visibility', 'hidden', 'missing_on_drive', 'local_name', 'source_enabled',
)


def _as_unsaved(row):
    if not row:
        return None
    if isinstance(row, dict):
        return row
    return dict(zip(_UNSAVED_COLUMNS, row))


def _unsaved_rows():
    """Enabled-folder messages with no host copy. The Drive file id is not selected."""
    ensure_schema()
    if not _sources():
        return []
    from app.models.db import get_db
    cur = get_db().cursor()
    cur.execute(
        """
        SELECT i.id, i.visibility, i.hidden, i.missing_on_drive, i.local_name,
               s.enabled AS source_enabled
          FROM sermon_drive_items i
          JOIN sermon_drive_sources s ON s.id = i.source_id AND s.enabled = 1
         WHERE (i.local_name IS NULL OR i.local_name = '')
           AND COALESCE(i.missing_on_drive, 0) = 0
         ORDER BY i.preached_on IS NULL, i.preached_on DESC, i.id ASC
        """
    )
    return [_as_unsaved(row) for row in (cur.fetchall() or [])]


def first_copyable_id(rows, allowed=None):
    """First unsaved row this person may already hear. Others are skipped."""
    for row in rows or []:
        item = _as_unsaved(row)
        if not item:
            continue
        if allowed is not None:
            try:
                keep = allowed(item)
            except Exception:
                keep = False
            if not keep:
                continue
        try:
            return int(item.get('id'))
        except (TypeError, ValueError):
            continue
    return None


def unsaved_count(allowed=None):
    """How many Drive messages this person may save. Missing Drive rows are skipped."""
    try:
        rows = _unsaved_rows()
    except Exception as exc:
        log.warning('sermon copy count failed: %s', type(exc).__name__)
        return 0
    if allowed is None:
        return len(rows)
    total = 0
    for row in rows:
        try:
            if allowed(row):
                total += 1
        except Exception:
            continue
    return total


def _record_copy(item_id, name, nbytes, user_id):
    if local_copy_name({'id': item_id, 'local_name': name}) != name:
        return False
    try:
        saved_by = int(user_id) if user_id else None
    except (TypeError, ValueError):
        saved_by = None
    try:
        ensure_schema()
        from app.models.db import get_db
        cur = get_db().cursor()
        now = datetime.datetime.now().replace(microsecond=0)
        cur.execute(
            """
            UPDATE sermon_drive_items
               SET local_name=%s, local_bytes=%s, local_saved_at=%s, local_saved_by=%s
             WHERE id=%s
            """,
            (name, int(nbytes), now, saved_by, item_id),
        )
        if cur.rowcount == 0:
            cur.execute('SELECT id FROM sermon_drive_items WHERE id=%s', (item_id,))
            if not cur.fetchone():
                return False
        return True
    except Exception as exc:
        log.warning('sermon copy record failed: %s', type(exc).__name__)
        return False


def save_item_copy(item_id, user_id, *, transport=None):
    """Store one message. Returns a short status. Does not read the folder listing."""
    row = get_item(item_id)
    if not row:
        return 'missing'
    if local_copy_name(row) and open_local_copy(row):
        return 'already'
    file_id = row.get('drive_file_id') or ''
    if not _ID.fullmatch(str(file_id)):
        return 'error'
    try:
        directory = ensure_backup_root()
    except CopyError as exc:
        return exc.code
    except Exception as exc:
        log.warning('sermon copy folder failed: %s', type(exc).__name__)
        return 'error'
    handle = _acquire_copy_lock(directory)
    if handle is None:
        return 'busy'
    final_name = None
    try:
        opener = transport or _urllib_transport
        final_name, nbytes = pull_drive_file(
            file_id,
            directory,
            row.get('id'),
            row.get('drive_name') or '',
            transport=opener,
        )
        if not _record_copy(row.get('id'), final_name, nbytes, user_id):
            _unlink(os.path.join(directory, final_name))
            return 'error'
        return 'saved'
    except CopyError as exc:
        return exc.code
    except Exception as exc:
        log.warning('sermon copy failed: %s', type(exc).__name__)
        if final_name:
            _unlink(os.path.join(directory, final_name))
        return 'error'
    finally:
        _release_lock(handle)


def save_next_copy(user_id, *, transport=None, allowed=None):
    """Save the next message this person may already hear. One file.

    allowed receives one unsaved row and returns true when that person can listen.
    Without it, the first unsaved row is used.
    """
    try:
        item_id = first_copyable_id(_unsaved_rows(), allowed)
    except Exception as exc:
        log.warning('sermon copy next failed: %s', type(exc).__name__)
        return 'error', None
    if not item_id:
        return 'none', 0
    status = save_item_copy(item_id, user_id, transport=transport)
    return status, unsaved_count(allowed)


def _account_label(row):
    first = (row.get('first_name') or '').strip()
    last = (row.get('last_name') or '').strip()
    full = f'{first} {last}'.strip()
    return (full or (row.get('username') or '').strip() or 'Member')[:160]


def _accounts(cur):
    """Approved accounts by id. Email is not selected."""
    try:
        cur.execute(
            """
            SELECT id, first_name, last_name, username
              FROM users
             WHERE COALESCE(needs_approval, 0) = 0
               AND COALESCE(is_shadow_banned, 0) = 0
             ORDER BY first_name, last_name, id
             LIMIT 400
            """
        )
    except Exception as exc:
        log.warning('sermon speaker accounts failed: %s', type(exc).__name__)
        return {}
    found = {}
    for row in cur.fetchall():
        try:
            found[int(row['id'])] = _account_label(row)
        except (TypeError, ValueError, KeyError):
            continue
    return found


def list_accounts():
    try:
        ensure_schema()
        from app.models.db import get_db
        return [{'id': user_id, 'name': name} for user_id, name in _accounts(get_db().cursor()).items()]
    except Exception as exc:
        log.warning('sermon speaker accounts failed: %s', type(exc).__name__)
        return []


def _speaker_index(cur):
    cur.execute("SELECT id, display_name, user_id FROM sermon_speakers ORDER BY display_name, id")
    people = []
    by_id = {}
    for row in cur.fetchall():
        person = {
            'id': int(row['id']),
            'display_name': row.get('display_name') or '',
            'user_id': int(row['user_id']) if row.get('user_id') else None,
            'names': [],
        }
        people.append(person)
        by_id[person['id']] = person
    cur.execute("SELECT speaker_id, name_key FROM sermon_speaker_names")
    for row in cur.fetchall():
        person = by_id.get(int(row['speaker_id']))
        if person and row.get('name_key'):
            person['names'].append(row['name_key'])
    return people


def list_speakers():
    """Speakers for the staff page. Account ids are left off the page."""
    try:
        ensure_schema()
        from app.models.db import get_db
        cur = get_db().cursor()
        people = _speaker_index(cur)
        cur.execute(
            """
            SELECT speaker_id, COUNT(*) AS n
              FROM sermon_drive_items
             WHERE speaker_id IS NOT NULL
             GROUP BY speaker_id
            """
        )
        counts = {}
        for row in cur.fetchall():
            counts[int(row['speaker_id'])] = _count_value({'n': row.get('n')})
        accounts = _accounts(cur)
        cur.execute("SELECT speaker_id, name FROM sermon_speaker_names ORDER BY name")
        labels = {}
        for row in cur.fetchall():
            labels.setdefault(int(row['speaker_id']), []).append(row.get('name') or '')
        out = []
        for person in people:
            out.append({
                'id': person['id'],
                'display_name': person['display_name'],
                'names': [name for name in labels.get(person['id'], []) if name],
                'messages': counts.get(person['id'], 0),
                'account_name': accounts.get(person['user_id'], '') if person.get('user_id') else '',
                'linked': bool(person.get('user_id')),
            })
        return out
    except Exception as exc:
        log.warning('sermon speakers failed: %s', type(exc).__name__)
        return []


def _add_speaker_name(cur, speaker_id, name, name_key):
    cur.execute(
        "SELECT speaker_id FROM sermon_speaker_names WHERE name_key=%s",
        (name_key,),
    )
    row = cur.fetchone()
    if row:
        owner = int(row.get('speaker_id') if isinstance(row, dict) else row[0])
        return owner == int(speaker_id)
    cur.execute(
        "INSERT INTO sermon_speaker_names (speaker_id, name, name_key) VALUES (%s, %s, %s)",
        (int(speaker_id), (name or '')[:160], name_key[:160]),
    )
    return True


def _remember_display(cur, speaker_id, display):
    cur.execute(
        "UPDATE sermon_drive_items SET speaker=%s WHERE speaker_id=%s",
        (display[:160], int(speaker_id)),
    )
    key = speaker_key(display)
    if key:
        return _add_speaker_name(cur, speaker_id, display, key)
    return True


def _execute_speaker(cur, decision):
    """Apply one decide_speaker result. Returns (speaker id, display name, errors)."""
    action = (decision or {}).get('action')
    if action in (None, 'clear', 'unchanged'):
        return None, None, []
    display = ((decision.get('display_name') or 'Speaker').strip() or 'Speaker')[:160]
    if action == 'create':
        cur.execute(
            "INSERT INTO sermon_speakers (display_name, user_id) VALUES (%s, %s)",
            (display, decision.get('user_id')),
        )
        speaker_id = int(cur.lastrowid)
    elif action == 'combine':
        into_id = int(decision['into_id'])
        source_id = int(decision['speaker_id'])
        cur.execute(
            "SELECT name, name_key FROM sermon_speaker_names WHERE speaker_id=%s",
            (source_id,),
        )
        for row in list(cur.fetchall()):
            if not _add_speaker_name(cur, into_id, row.get('name'), row.get('name_key')):
                return None, None, ['That name already belongs to another speaker. Combine them on the Speakers page.']
        cur.execute("DELETE FROM sermon_speaker_names WHERE speaker_id=%s", (source_id,))
        cur.execute(
            "UPDATE sermon_drive_items SET speaker_id=%s WHERE speaker_id=%s",
            (into_id, source_id),
        )
        cur.execute("DELETE FROM sermon_speakers WHERE id=%s", (source_id,))
        speaker_id = into_id
        cur.execute(
            "UPDATE sermon_speakers SET display_name=%s, user_id=%s WHERE id=%s",
            (display, decision.get('user_id'), speaker_id),
        )
    else:
        speaker_id = int(decision['speaker_id'])
        if action == 'link' or decision.get('user_id'):
            cur.execute(
                "UPDATE sermon_speakers SET display_name=%s, user_id=%s WHERE id=%s",
                (display, decision.get('user_id'), speaker_id),
            )
    for name, key in decision.get('add_names') or []:
        if not key:
            continue
        if not _add_speaker_name(cur, speaker_id, name, key):
            return None, None, ['That name already belongs to another speaker. Combine them on the Speakers page.']
    if not _remember_display(cur, speaker_id, display):
        return None, None, ['That name already belongs to another speaker. Combine them on the Speakers page.']
    return speaker_id, display, []


def _apply_form_speaker(cur, form):
    """Returns speaker id, display name, errors, and whether the form asked to change it."""
    if not any(key in form for key in ('speaker', 'speaker_id', 'speaker_user')):
        return None, None, [], False
    choice, errors = plan_speaker_form(form, _accounts(cur))
    if errors:
        return None, None, errors, True
    decision, error = decide_speaker(choice, _speaker_index(cur))
    if error:
        return None, None, [error], True
    if decision.get('action') == 'clear':
        return None, None, [], True
    speaker_id, display, apply_errors = _execute_speaker(cur, decision)
    if apply_errors:
        return None, None, apply_errors, True
    return speaker_id, display, [], True


def _speaker_result(cur, form):
    speaker_id, _display, errors, _changed = _apply_form_speaker(cur, form)
    if errors:
        return errors[0]
    if not speaker_id:
        return 'Choose a speaker from the list.'
    return None


def add_speaker_name(speaker_id, name):
    """Add a spelling to a speaker. The same spelling cannot belong to two people."""
    if not str(speaker_id or '').strip().isdigit():
        return 'Choose a speaker from the list.'
    if not speaker_key(name):
        return 'Type a name.'
    try:
        ensure_schema()
        from app.models.db import get_db
        return _speaker_result(get_db().cursor(), {'speaker_id': speaker_id, 'speaker': name})
    except Exception as exc:
        log.warning('sermon speaker name failed: %s', type(exc).__name__)
        return 'error'


def create_speaker(name):
    """Save a person who is not a member yet. The spelling can be linked later."""
    if not speaker_key(name):
        return 'Type a name.'
    try:
        ensure_schema()
        from app.models.db import get_db
        return _speaker_result(get_db().cursor(), {
            'speaker': name,
            'speaker_id': '',
            'speaker_user': '',
        })
    except Exception as exc:
        log.warning('sermon speaker create failed: %s', type(exc).__name__)
        return 'error'


def link_speaker_account(speaker_id, user_id):
    """Tie a speaker to an account. Messages under that speaker stay with them."""
    if not str(speaker_id or '').strip().isdigit():
        return 'Choose a speaker from the list.'
    if not str(user_id or '').strip().isdigit():
        return 'Choose a member from the list.'
    try:
        ensure_schema()
        from app.models.db import get_db
        return _speaker_result(
            get_db().cursor(),
            {'speaker_id': speaker_id, 'speaker_user': user_id},
        )
    except Exception as exc:
        log.warning('sermon speaker link failed: %s', type(exc).__name__)
        return 'error'


def unlink_speaker_account(speaker_id):
    """Remove the account link. Names and messages stay on the speaker."""
    if not str(speaker_id or '').strip().isdigit():
        return 'Choose a speaker from the list.'
    try:
        ensure_schema()
        from app.models.db import get_db
        cur = get_db().cursor()
        cur.execute(
            "UPDATE sermon_speakers SET user_id=NULL WHERE id=%s",
            (int(speaker_id),),
        )
        if cur.rowcount == 0:
            cur.execute("SELECT id FROM sermon_speakers WHERE id=%s", (int(speaker_id),))
            if not cur.fetchone():
                return 'Choose a speaker from the list.'
        return None
    except Exception as exc:
        log.warning('sermon speaker unlink failed: %s', type(exc).__name__)
        return 'error'


def combine_speakers(into_id, speaker_id):
    """Move one speaker, including every spelling and message, onto another."""
    raw_into = str(into_id or '').strip()
    raw_source = str(speaker_id or '').strip()
    if not raw_into.isdigit() or not raw_source.isdigit() or int(raw_into) == int(raw_source):
        return 'Choose two different speakers.'
    try:
        ensure_schema()
        from app.models.db import get_db
        cur = get_db().cursor()
        people = {person['id']: person for person in _speaker_index(cur)}
        try:
            dest = people.get(int(into_id))
            source = people.get(int(speaker_id))
        except (TypeError, ValueError):
            dest = source = None
        _plan, error = plan_combine(dest, source)
        if error:
            return error
        display = dest.get('display_name') or 'Speaker'
        user_id = dest.get('user_id') or source.get('user_id')
        if user_id and not dest.get('user_id'):
            display = _accounts(cur).get(int(user_id)) or display
        _speaker, _name, errors = _execute_speaker(cur, {
            'action': 'combine',
            'into_id': dest['id'],
            'speaker_id': source['id'],
            'user_id': user_id,
            'display_name': display,
            'add_names': [],
        })
        if errors:
            return errors[0]
        return None
    except Exception as exc:
        log.warning('sermon speaker combine failed: %s', type(exc).__name__)
        return 'error'


def list_sources():
    """Folder labels for the owner. The Drive folder id is not included."""
    try:
        ensure_schema()
        from app.models.db import get_db
        cur = get_db().cursor()
        cur.execute(
            """
            SELECT s.id, s.label, s.enabled,
                   (SELECT COUNT(*) FROM sermon_drive_items i WHERE i.source_id = s.id) AS messages
              FROM sermon_drive_sources s
             ORDER BY s.label, s.id
            """
        )
        found = []
        for row in cur.fetchall():
            found.append({
                'id': int(row['id']),
                'label': row.get('label') or 'Messages',
                'enabled': bool(int(row.get('enabled') or 0)),
                'messages': _count_value({'n': row.get('messages')}),
            })
        return found
    except Exception as exc:
        log.warning('sermon drive folders failed: %s', type(exc).__name__)
        return []


def save_source(source_id, label, enabled):
    """Rename a folder or hide it. Hidden folders leave the library. Copies stay."""
    raw_id = str(source_id or '').strip()
    if not raw_id.isdigit():
        return 'bad'
    cleaned = _clean_text(label, 120)
    if not cleaned:
        return 'bad'
    flag = str(enabled if enabled is not None else '').strip()
    if flag not in ('0', '1'):
        return 'bad'
    try:
        ensure_schema()
        from app.models.db import get_db
        cur = get_db().cursor()
        cur.execute(
            "UPDATE sermon_drive_sources SET label=%s, enabled=%s WHERE id=%s",
            (cleaned, int(flag), int(raw_id)),
        )
        if cur.rowcount == 0:
            cur.execute("SELECT id FROM sermon_drive_sources WHERE id=%s", (int(raw_id),))
            if not cur.fetchone():
                return 'missing'
        return 'ok'
    except Exception as exc:
        log.warning('sermon drive folder update failed: %s', type(exc).__name__)
        return 'error'


def _attach_known_speakers(cur, source_id):
    """When a file name already matches a saved spelling, keep that speaker."""
    cur.execute(
        """
        SELECT id, speaker
          FROM sermon_drive_items
         WHERE source_id=%s
           AND speaker_id IS NULL
           AND speaker IS NOT NULL
           AND speaker != ''
        """,
        (source_id,),
    )
    rows = list(cur.fetchall())
    if not rows:
        return
    cur.execute(
        """
        SELECT n.name_key, n.speaker_id, s.display_name
          FROM sermon_speaker_names n
          JOIN sermon_speakers s ON s.id = n.speaker_id
        """
    )
    names = {}
    displays = {}
    for row in cur.fetchall():
        speaker_id = int(row['speaker_id'])
        names[row.get('name_key') or ''] = speaker_id
        displays[speaker_id] = row.get('display_name') or ''
    for row in rows:
        speaker_id = speaker_match(row.get('speaker'), names)
        if not speaker_id:
            continue
        cur.execute(
            """
            UPDATE sermon_drive_items
               SET speaker_id=%s, speaker=%s
             WHERE id=%s AND speaker_id IS NULL
            """,
            (speaker_id, displays.get(speaker_id) or row.get('speaker'), row['id']),
        )
