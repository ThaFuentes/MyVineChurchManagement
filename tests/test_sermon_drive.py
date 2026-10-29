"""Sermon library: filename parsing, Drive listing, and who can listen. No database and no network."""

import datetime
import io
import json
import os
import tempfile
import unittest
import urllib.parse
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.utils.sermon_drive import (
    CopyError,
    DriveReadError,
    backup_root,
    can_listen,
    can_see,
    clean_edit,
    download_url,
    edit_view,
    extract_folder_id,
    folder_list_url,
    is_stale,
    local_copy_name,
    parse_refresh_hours,
    parse_visibility,
    merge_named_people,
    parse_drive_name,
    people_from_rows,
    row_matches_library,
    parse_folder_html,
    plan_sync,
    play_url,
    present,
    pull_drive_file,
    save_item_copy,
    walk_folder,
    with_drive_frame,
)


FOLDER = 'FolderSecretKeyAAAAAAAAAA'
FILE = 'FileSecretKeyBBBBBBBBBBBB'
OTHER = 'OtherSecretKeyCCCCCCCCCC'
CHILD = 'ChildFolderKeyDDDDDDDDDD'


def _entry(file_id, title, kind, modified='Mar 8'):
    if kind == 'folder':
        href = f'https://drive.google.com/drive/folders/{file_id}'
        icon = '<div aria-label="Folder" class="icon-color-1"></div>'
    elif kind == 'pdf':
        href = f'https://drive.google.com/file/d/{file_id}/view?usp=drive_web'
        icon = '<img src="https://drive-thirdparty.googleusercontent.com/128/type/application/pdf" alt="PDF"/>'
    else:
        href = f'https://drive.google.com/file/d/{file_id}/view?usp=drive_web'
        mime = 'audio/mpeg' if kind == 'audio' else 'video/mp4'
        alt = 'Audio' if kind == 'audio' else 'Video'
        icon = f'<img src="https://drive-thirdparty.googleusercontent.com/128/type/{mime}" alt="{alt}"/>'
    return (
        f'<div class="flip-entry" id="entry-{file_id}" tabindex="0" role="link">'
        f'<div class="flip-entry-info"><a href="{href}" target="_blank">'
        f'{icon}<div class="flip-entry-title">{title}</div></a></div>'
        f'<div class="flip-entry-last-modified"><div>{modified}</div></div></div>'
    )


def _page(*entries):
    return '<div id="flip-contents"><div class="flip-entries">' + ''.join(entries) + '</div></div>'


def _row(**extra):
    base = {
        'id': 7,
        'drive_file_id': FILE,
        'parent_folder_id': FOLDER,
        'drive_name': 'Vineyard Odessa - Message - 2024-07-07 - Clara Wiggins.mp3',
        'kind': 'audio',
        'title': 'Clara Wiggins',
        'speaker': 'Clara Wiggins',
        'scripture': '',
        'summary': '',
        'series': 'Vineyard Odessa',
        'preached_on': datetime.date(2024, 7, 7),
        'visibility': 'public',
        'hidden': 0,
        'missing_on_drive': 0,
    }
    base.update(extra)
    return base


class ParseNameTests(unittest.TestCase):
    def test_speaker_when_the_file_has_no_separate_title(self):
        parsed = parse_drive_name('Vineyard Odessa - Message - 2024-07-07 - Clara Wiggins.mp3')
        self.assertEqual(parsed['series'], 'Vineyard Odessa')
        self.assertEqual(parsed['preached_on'], '2024-07-07')
        self.assertEqual(parsed['speaker'], 'Clara Wiggins')
        self.assertEqual(parsed['title'], 'Clara Wiggins')
        self.assertIsNone(parsed['summary'])

    def test_three_word_speaker(self):
        parsed = parse_drive_name('Vineyard Odessa - Message - 2024-10-20 - Mary Ann Lien.mp3')
        self.assertEqual(parsed['speaker'], 'Mary Ann Lien')
        self.assertEqual(parsed['title'], 'Mary Ann Lien')

    def test_title_after_the_speaker(self):
        parsed = parse_drive_name(
            'Vineyard Odessa - Message - 2026-06-14 - Leo Free - Today is Holy.mp3'
        )
        self.assertEqual(parsed['speaker'], 'Leo Free')
        self.assertEqual(parsed['title'], 'Today is Holy')
        self.assertEqual(parsed['preached_on'], '2026-06-14')
        self.assertEqual(parsed['series'], 'Vineyard Odessa')

    def test_parenthetical_note_becomes_the_summary(self):
        parsed = parse_drive_name(
            'Vineyard Odessa - Message - 2024-08-11 - Christopher Lien (end cut off).mp3'
        )
        self.assertEqual(parsed['speaker'], 'Christopher Lien')
        self.assertEqual(parsed['summary'], 'end cut off')
        self.assertEqual(parsed['preached_on'], '2024-08-11')

    def test_date_and_a_one_word_title(self):
        parsed = parse_drive_name('2026-03-08 - Sharing.mp3')
        self.assertEqual(parsed['preached_on'], '2026-03-08')
        self.assertEqual(parsed['title'], 'Sharing')
        self.assertIsNone(parsed['speaker'])
        self.assertIsNone(parsed['series'])

    def test_plain_stem_when_there_is_no_date(self):
        parsed = parse_drive_name('prayer for evelyn.mp3')
        self.assertEqual(parsed['title'], 'Prayer For Evelyn')
        self.assertIsNone(parsed['preached_on'])
        self.assertIsNone(parsed['speaker'])

    def test_two_speakers_and_a_topic_after_and(self):
        both = parse_drive_name(
            'Vineyard Odessa - Message - 2023-02-19 - Tim Lien and Josh Villasenor.mp3'
        )
        self.assertEqual(both['speaker'], 'Tim Lien and Josh Villasenor')
        self.assertEqual(both['title'], 'Tim Lien and Josh Villasenor')
        topic = parse_drive_name(
            'Vineyard Odessa - Message - 2023-10-01 - Tim Lien and sharing.mp3'
        )
        self.assertEqual(topic['speaker'], 'Tim Lien')
        self.assertEqual(topic['title'], 'Sharing')


class ListingTests(unittest.TestCase):
    def test_audio_video_and_folders_and_skips_other_files(self):
        page = _page(
            _entry(CHILD, '2024', 'folder', '1/14/25'),
            _entry(FILE, '2026-03-08 - Sharing.mp3', 'audio', 'Mar 8'),
            _entry(OTHER, 'clip.mp4', 'video', '1/12/25'),
            _entry('PdfSecretKeyEEEEEEEEEEEE', 'notes.pdf', 'pdf'),
        )
        entries = parse_folder_html(page)
        kinds = {item['file_id']: item['kind'] for item in entries}
        self.assertEqual(kinds[CHILD], 'folder')
        self.assertEqual(kinds[FILE], 'audio')
        self.assertEqual(kinds[OTHER], 'video')
        self.assertEqual(kinds['PdfSecretKeyEEEEEEEEEEEE'], 'other')
        sharing = next(item for item in entries if item['file_id'] == FILE)
        self.assertEqual(sharing['name'], '2026-03-08 - Sharing.mp3')
        self.assertEqual(sharing['modified'], 'Mar 8')
        self.assertEqual(sharing['mime'], 'audio/mpeg')

    def test_broken_page_is_an_error(self):
        with self.assertRaises(DriveReadError):
            parse_folder_html('<html><a href="https://drive.google.com/file/d/x">nope</a></html>')

    def test_walks_year_folders_and_skips_pdfs(self):
        pages = {
            FOLDER: _page(
                _entry(CHILD, '2024', 'folder'),
                _entry(FILE, '2026-03-08 - Sharing.mp3', 'audio'),
                _entry('PdfSecretKeyEEEEEEEEEEEE', 'notes.pdf', 'pdf'),
            ),
            CHILD: _page(_entry(OTHER, 'Vineyard Odessa - Message - 2024-07-07 - Clara Wiggins.mp3', 'audio')),
        }
        walked = walk_folder(FOLDER, pages.get)
        ids = {item['file_id'] for item in walked.files}
        self.assertEqual(ids, {FILE, OTHER})
        self.assertTrue(walked.complete)
        child_file = next(item for item in walked.files if item['file_id'] == OTHER)
        self.assertEqual(child_file['parent_folder_id'], CHILD)

    def test_a_failed_folder_read_raises(self):
        def fetch(_folder_id):
            raise DriveReadError()

        with self.assertRaises(DriveReadError):
            walk_folder(FOLDER, fetch)

    def test_player_url_is_a_preview(self):
        url = play_url(FILE)
        self.assertTrue(url.endswith('/preview'))
        self.assertNotIn('export=download', url)
        self.assertIsNone(play_url('../etc/passwd'))
        self.assertIsNone(play_url('short'))
        listing = folder_list_url(FOLDER)
        self.assertIn('embeddedfolderview?id=', listing)
        self.assertNotIn('export=download', listing)

    def test_player_is_allowed_without_replacing_the_other_rules(self):
        policy = with_drive_frame("default-src 'self'; frame-ancestors 'self';")
        self.assertIn("default-src 'self'", policy)
        self.assertIn('https://drive.google.com', policy)
        self.assertIn('frame-src', policy)
        self.assertNotIn(FOLDER, policy)
        again = with_drive_frame(policy)
        self.assertEqual(again, policy)

    def test_the_player_header_is_added_after_the_app_policy(self):
        from flask import Blueprint, Flask

        import app.routes.sermons.views  # load the sermon routes before the page module
        from app.routes.sermons.drive_pages import register

        app = Flask(__name__)
        bp = Blueprint('sermons_hdr', __name__, url_prefix='/sermons')

        @bp.route('/ping')
        def ping():
            return 'ok'

        register(bp)
        app.register_blueprint(bp)

        @app.route('/other')
        def other():
            return 'no'

        @app.after_request
        def app_policy(response):
            response.headers['Content-Security-Policy'] = "default-src 'self'; frame-ancestors 'self';"
            return response

        client = app.test_client()
        sermon = client.get('/sermons/ping')
        policy = sermon.headers['Content-Security-Policy']
        self.assertIn("default-src 'self'", policy)
        self.assertIn('https://drive.google.com', policy)
        self.assertNotIn('drive.google.com', client.get('/other').headers['Content-Security-Policy'])


class SyncPlanTests(unittest.TestCase):
    def test_new_file_is_public_and_parsed(self):
        seen = [{
            'file_id': FILE,
            'name': 'Vineyard Odessa - Message - 2026-06-14 - Leo Free - Today is Holy.mp3',
            'kind': 'audio',
            'mime': 'audio/mpeg',
            'modified': 'Jun 14',
            'parent_folder_id': FOLDER,
        }]
        plan = plan_sync({}, seen, complete=True)
        item = plan['upserts'][0]
        self.assertEqual(item['op'], 'insert')
        self.assertEqual(item['visibility'], 'public')
        self.assertEqual(item['site_edited'], 0)
        self.assertEqual(item['title'], 'Today is Holy')
        self.assertEqual(item['speaker'], 'Leo Free')
        self.assertEqual(plan['missing_ids'], [])

    def test_new_file_uses_the_saved_default(self):
        seen = [{
            'file_id': FILE,
            'name': '2026-03-08 - Sharing.mp3',
            'kind': 'audio',
            'mime': 'audio/mpeg',
            'modified': 'Mar 8',
            'parent_folder_id': FOLDER,
        }]
        plan = plan_sync({}, seen, complete=True, default_visibility='leaders')
        self.assertEqual(plan['upserts'][0]['visibility'], 'leaders')
        existing = {
            FILE: {'id': 4, 'drive_file_id': FILE, 'drive_name': 'old.mp3', 'site_edited': 0}
        }
        updated = plan_sync(existing, seen, complete=True, default_visibility='members')['upserts'][0]
        self.assertEqual(updated['op'], 'update')
        self.assertNotIn('visibility', updated)
        self.assertIsNone(parse_visibility('secret'))
        self.assertEqual(parse_visibility('members'), 'members')

    def test_site_edits_survive_a_renamed_file(self):
        existing = {
            FILE: {
                'id': 3,
                'drive_file_id': FILE,
                'drive_name': 'old.mp3',
                'site_edited': 1,
            }
        }
        seen = [{
            'file_id': FILE,
            'name': 'Vineyard Odessa - Message - 2024-07-07 - Clara Wiggins.mp3',
            'kind': 'audio',
            'mime': 'audio/mpeg',
            'modified': 'Jul 7',
            'parent_folder_id': CHILD,
        }]
        plan = plan_sync(existing, seen, complete=True)
        item = plan['upserts'][0]
        self.assertEqual(item['op'], 'update')
        self.assertFalse(item['refresh_details'])
        self.assertNotIn('title', item)
        self.assertEqual(item['drive_name'], seen[0]['name'])

    def test_unedited_row_picks_up_a_new_file_name(self):
        existing = {
            FILE: {
                'id': 3,
                'drive_file_id': FILE,
                'drive_name': 'old.mp3',
                'site_edited': 0,
            }
        }
        seen = [{
            'file_id': FILE,
            'name': '2026-03-08 - Sharing.mp3',
            'kind': 'audio',
            'mime': 'audio/mpeg',
            'modified': 'Mar 8',
            'parent_folder_id': FOLDER,
        }]
        item = plan_sync(existing, seen, complete=True)['upserts'][0]
        self.assertTrue(item['refresh_details'])
        self.assertEqual(item['title'], 'Sharing')

    def test_missing_rows_stay_when_the_walk_is_incomplete(self):
        existing = {FILE: {'id': 9, 'drive_file_id': FILE, 'drive_name': 'keep.mp3', 'site_edited': 1}}
        plan = plan_sync(existing, [], complete=False)
        self.assertEqual(plan['missing_ids'], [])

    def test_a_full_walk_marks_files_that_were_not_seen(self):
        existing = {FILE: {'id': 9, 'drive_file_id': FILE, 'drive_name': 'keep.mp3', 'site_edited': 1}}
        plan = plan_sync(existing, [], complete=True)
        self.assertEqual(plan['missing_ids'], [9])


class ListenGateTests(unittest.TestCase):
    def _blob(self, card):
        return json.dumps(card)

    def test_anyone_can_play_a_public_message(self):
        card = present(_row(), logged_in=False, role='')
        self.assertTrue(card['can_listen'])
        self.assertTrue(card['play_url'].endswith('/preview'))
        blob = self._blob(card)
        self.assertNotIn(FOLDER, blob)
        self.assertNotIn('parent_folder_id', card)
        self.assertNotIn('drive_file_id', card)
        self.assertNotIn('export=download', blob)

    def test_guests_see_a_members_message_without_the_player(self):
        card = present(_row(visibility='members'), logged_in=False, role='')
        self.assertTrue(can_see(_row(visibility='members'), logged_in=False, role=''))
        self.assertFalse(card['can_listen'])
        self.assertIsNone(card['play_url'])
        blob = self._blob(card)
        self.assertNotIn(FILE, blob)
        self.assertNotIn(FOLDER, blob)
        self.assertEqual(card['lock_message'], 'Sign in to listen')

    def test_a_signed_in_member_can_play_a_members_message(self):
        card = present(_row(visibility='members'), logged_in=True, role='Member')
        self.assertTrue(card['can_listen'])
        self.assertTrue(card['play_url'].endswith('/preview'))

    def test_leaders_messages_are_hidden_from_members(self):
        row = _row(visibility='leaders')
        self.assertFalse(can_see(row, logged_in=False, role=''))
        self.assertFalse(can_see(row, logged_in=True, role='Member'))
        self.assertFalse(can_listen(row, logged_in=True, role='Member'))
        card = present(row, logged_in=True, role='Member')
        self.assertIsNone(card['play_url'])
        self.assertNotIn(FILE, self._blob(card))

    def test_staff_can_preview_a_leaders_message(self):
        row = _row(visibility='leaders')
        for role in ('Staff', 'Admin', 'Owner'):
            self.assertTrue(can_see(row, logged_in=True, role=role))
            card = present(row, logged_in=True, role=role)
            self.assertTrue(card['can_listen'])
            self.assertTrue(card['play_url'].endswith('/preview'))
            self.assertNotIn(FOLDER, self._blob(card))

    def test_hidden_and_missing_are_staff_only(self):
        for flag in ('hidden', 'missing_on_drive'):
            row = _row(**{flag: 1})
            self.assertFalse(can_see(row, logged_in=False, role=''))
            self.assertFalse(can_see(row, logged_in=True, role='Member'))
            self.assertTrue(can_see(row, logged_in=True, role='Staff'))
            self.assertTrue(can_listen(row, logged_in=True, role='Admin'))


class EditTests(unittest.TestCase):
    def test_folder_link_and_bare_id(self):
        self.assertEqual(extract_folder_id(FOLDER), FOLDER)
        self.assertEqual(
            extract_folder_id(f'https://drive.google.com/drive/folders/{FOLDER}?usp=sharing'),
            FOLDER,
        )
        self.assertEqual(
            extract_folder_id(f'https://drive.google.com/embeddedfolderview?id={FOLDER}'),
            FOLDER,
        )
        self.assertIsNone(extract_folder_id('javascript:alert(1)'))
        self.assertIsNone(extract_folder_id(f'https://evil.example/folders/{FOLDER}'))
        self.assertIsNone(extract_folder_id(f'https://drive.google.com/file/d/{FILE}/view'))
        self.assertIsNone(extract_folder_id(''))

    def test_clean_edit_keeps_site_fields_only(self):
        fields, errors = clean_edit({
            'title': '  Today is Holy ',
            'speaker': 'Leo Free',
            'scripture': 'John 3',
            'series': 'Vineyard Odessa',
            'summary': 'A note',
            'preached_on': '2026-06-14',
            'visibility': 'members',
            'hidden': '1',
        })
        self.assertEqual(errors, [])
        self.assertEqual(fields['title'], 'Today is Holy')
        self.assertEqual(fields['visibility'], 'members')
        self.assertEqual(fields['hidden'], 1)
        self.assertEqual(fields['preached_on'], '2026-06-14')
        self.assertNotIn('drive_file_id', fields)
        self.assertNotIn(FOLDER, json.dumps(fields))

    def test_clean_edit_rejects_a_bad_lock_and_a_bad_date(self):
        _fields, errors = clean_edit({'title': '', 'visibility': 'secret', 'preached_on': '2024-13-40'})
        self.assertIn('A title is required.', errors)
        self.assertIn('Choose who can listen.', errors)
        self.assertIn('Use a real date, or leave the date blank.', errors)

    def test_edit_view_omits_drive_ids(self):
        view = edit_view(_row())
        blob = json.dumps(view)
        self.assertNotIn(FOLDER, blob)
        self.assertNotIn(FILE, blob)
        self.assertEqual(view['drive_name'], _row()['drive_name'])
        self.assertEqual(view['preached_on'], '2024-07-07')

    def test_schedule_matches_a_weekly_upload(self):
        now = datetime.datetime(2026, 10, 28, 12, 0, 0)
        self.assertTrue(is_stale(None, refresh_hours=168, now=now))
        self.assertFalse(is_stale(now - datetime.timedelta(days=3), refresh_hours=168, now=now))
        self.assertTrue(is_stale(now - datetime.timedelta(days=8), refresh_hours=168, now=now))
        self.assertFalse(is_stale(now - datetime.timedelta(hours=2), refresh_hours=8, now=now))
        self.assertTrue(is_stale(now - datetime.timedelta(hours=9), refresh_hours=8, now=now))
        self.assertFalse(is_stale(now - datetime.timedelta(days=30), refresh_hours=0, now=now))
        self.assertTrue(is_stale(None, refresh_hours=0, now=now))
        self.assertEqual(parse_refresh_hours('168'), 168)
        self.assertEqual(parse_refresh_hours('0'), 0)
        self.assertIsNone(parse_refresh_hours('3'))
        self.assertIsNone(parse_refresh_hours('weekly'))


def _remote(status=200, location='', content_type='audio/mpeg', payload=b''):
    body = io.BytesIO(payload) if status == 200 else None
    return SimpleNamespace(status=status, location=location, content_type=content_type, body=body)


class HostCopyTests(unittest.TestCase):
    def test_a_missing_file_with_a_saved_copy_still_plays_for_listeners(self):
        row = _row(missing_on_drive=1, local_name='7.mp3')
        self.assertTrue(can_see(row, logged_in=False, role=''))
        card = present(row, logged_in=False, role='')
        self.assertTrue(card['can_listen'])
        self.assertTrue(card['local_play'])
        self.assertTrue(card['has_copy'])
        self.assertIsNone(card['play_url'])
        blob = json.dumps(card)
        self.assertNotIn(FILE, blob)
        self.assertNotIn(FOLDER, blob)
        self.assertNotIn('local_name', card)
        self.assertNotIn('/', blob)

    def test_a_wrong_stored_name_does_not_count_as_a_copy(self):
        missing = _row(missing_on_drive=1, local_name='../7.mp3')
        self.assertIsNone(local_copy_name(missing))
        self.assertFalse(can_listen(missing, logged_in=False, role=''))
        self.assertIsNone(local_copy_name(_row(missing_on_drive=1, local_name='07.mp3')))
        self.assertIsNone(local_copy_name(_row(id=8, missing_on_drive=1, local_name='7.mp3')))
        hidden = _row(hidden=1, missing_on_drive=1, local_name='7.mp3')
        self.assertFalse(can_see(hidden, logged_in=False, role=''))
        self.assertFalse(can_listen(hidden, logged_in=True, role='Member'))
        self.assertTrue(can_listen(hidden, logged_in=True, role='Staff'))

    def test_the_download_link_is_only_the_drive_file(self):
        url = download_url(FILE)
        self.assertTrue(url.startswith('https://drive.google.com/uc?'))
        self.assertIn(f'id={FILE}', url)
        self.assertNotIn('evil', url)
        self.assertIsNone(download_url('../etc/passwd'))
        self.assertIsNone(download_url(FILE, confirm='https://evil.example'))
        confirmed = download_url(FILE, confirm='abc123')
        self.assertIn('confirm=abc123', confirmed)
        self.assertTrue(confirmed.startswith('https://drive.google.com/uc?'))

    def test_copies_are_refused_inside_the_site_folder(self):
        inside = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'app', 'uploads'))
        with patch.dict(os.environ, {'SERMON_BACKUP_DIR': inside}):
            with self.assertRaises(CopyError) as caught:
                backup_root()
        self.assertEqual(caught.exception.code, 'place')

    def test_an_html_page_is_not_stored(self):
        calls = []
        page = b'<html><a href="https://evil.example/x">confirm=abc123</a></html>'

        def transport(url):
            calls.append(url)
            if 'confirm=' in url:
                return _remote(content_type='text/html', payload=b'<html>no audio</html>')
            return _remote(content_type='text/html', payload=page)

        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(CopyError) as caught:
                pull_drive_file(FILE, folder, 7, 'talk.mp3', transport=transport)
            self.assertEqual(caught.exception.code, 'html')
            self.assertEqual(os.listdir(folder), [])
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(urllib.parse.urlsplit(url).hostname == 'drive.google.com' for url in calls))
        self.assertIn('confirm=abc123', calls[1])
        self.assertNotIn('evil.example', calls[1])

    def test_a_redirect_off_drive_is_not_followed(self):
        locations = (
            'https://evil.example/secret.mp3',
            'https://drive.google.com.evil.example/file.mp3',
            'https://drive.google.com@evil.example/file.mp3',
            'http://drive.google.com/uc?export=download&id=' + FILE,
            'file:///etc/passwd',
            'https://127.0.0.1/file.mp3',
        )
        with tempfile.TemporaryDirectory() as folder:
            for location in locations:
                calls = []

                def transport(url, location=location):
                    calls.append(url)
                    return _remote(status=302, location=location)

                with self.assertRaises(CopyError) as caught:
                    pull_drive_file(FILE, folder, 7, 'talk.mp3', transport=transport)
                self.assertEqual(caught.exception.code, 'blocked', location)
                self.assertEqual(calls, [download_url(FILE)], location)
                self.assertEqual(os.listdir(folder), [], location)

    def test_a_media_file_is_stored_under_the_row_id(self):
        payload = b'ID3' + b'\x00' * 32
        calls = []

        def transport(url):
            calls.append(url)
            host = urllib.parse.urlsplit(url).hostname or ''
            if host.endswith('.googleusercontent.com'):
                return _remote(content_type='application/octet-stream', payload=payload)
            return _remote(status=302, location='https://doc-0s.googleusercontent.com/download?id=1')

        with tempfile.TemporaryDirectory() as folder:
            name, size = pull_drive_file(
                FILE, folder, 7, '../../not-a-path.mp3', transport=transport,
            )
            self.assertEqual(name, '7.mp3')
            self.assertEqual(size, len(payload))
            self.assertEqual(os.listdir(folder), ['7.mp3'])
            with open(os.path.join(folder, name), 'rb') as handle:
                self.assertEqual(handle.read(), payload)
        self.assertEqual(len(calls), 2)
        self.assertNotIn('not-a-path', name)
        self.assertNotIn(FILE, name)

    def test_an_oversize_file_and_a_picture_are_not_stored(self):
        with tempfile.TemporaryDirectory() as folder:
            def big(_url):
                return _remote(content_type='audio/mpeg', payload=b'0123456789abcdef')

            with self.assertRaises(CopyError) as caught:
                pull_drive_file(FILE, folder, 7, 'talk.mp3', transport=big, limit=8)
            self.assertEqual(caught.exception.code, 'large')

            def picture(_url):
                return _remote(content_type='image/jpeg', payload=b'\xff\xd8\xff' + b'x' * 20)

            with self.assertRaises(CopyError) as caught:
                pull_drive_file(FILE, folder, 7, 'talk.mp3', transport=picture)
            self.assertEqual(caught.exception.code, 'type')
            self.assertEqual(os.listdir(folder), [])

    def test_a_bad_file_id_is_not_downloaded(self):
        transport = Mock(side_effect=AssertionError('network'))
        with tempfile.TemporaryDirectory() as folder, \
                patch.dict(os.environ, {'SERMON_BACKUP_DIR': folder}), \
                patch('app.utils.sermon_drive.get_item', return_value=_row(drive_file_id='../etc/passwd')):
            self.assertEqual(save_item_copy(7, 4, transport=transport), 'error')
            self.assertEqual(os.listdir(folder), [])
        transport.assert_not_called()


class _Cursor:
    def __init__(self, ones=None, alls=None):
        self.ones = list(ones or [])
        self.alls = list(alls or [])
        self.calls = []
        self.rowcount = 1
        self.lastrowid = 15

    def execute(self, sql, params=None):
        self.calls.append((' '.join(sql.split()), params))

    def fetchone(self):
        if self.ones:
            return self.ones.pop(0)
        return None

    def fetchall(self):
        if self.alls:
            return self.alls.pop(0)
        return []


class SpeakerAndSortTests(unittest.TestCase):
    def _save(self, form, cur):
        from app.utils.sermon_drive import save_item_details
        db = SimpleNamespace(cursor=lambda: cur)
        with patch('app.utils.sermon_drive.ensure_schema'), \
                patch('app.models.db.get_db', return_value=db):
            return save_item_details(7, form, 4)

    def _update(self, cur):
        return [params for sql, params in cur.calls if 'site_edited=1' in sql]

    def test_tim_is_not_tim_lien(self):
        from app.utils.sermon_drive import speaker_key, speaker_match
        self.assertEqual(speaker_key('  Tim  '), 'tim')
        self.assertEqual(speaker_key('Tim Lien'), 'tim lien')
        self.assertNotEqual(speaker_key('Tim'), speaker_key('Tim Lien'))
        self.assertEqual(speaker_match('tim', {'tim': 1}), 1)
        self.assertIsNone(speaker_match('Tim Lien', {'tim': 1}))

    def test_a_typed_name_links_only_when_the_account_is_chosen(self):
        from app.utils.sermon_drive import decide_speaker, plan_speaker_form, speaker_key
        tim = {'id': 1, 'display_name': 'Tim', 'user_id': None, 'names': ['tim']}
        choice, errors = plan_speaker_form(
            {'speaker': 'Tim Lien', 'speaker_id': '', 'speaker_user': ''}, {},
        )
        self.assertEqual(errors, [])
        decision, error = decide_speaker(choice, [tim])
        self.assertIsNone(error)
        self.assertEqual(decision['action'], 'create')
        self.assertIsNone(decision['user_id'])

        choice, errors = plan_speaker_form(
            {'speaker': 'Tim', 'speaker_id': '1', 'speaker_user': '9'},
            {9: 'Tim Lien'},
        )
        self.assertEqual(errors, [])
        decision, error = decide_speaker(choice, [tim])
        self.assertIsNone(error)
        self.assertEqual(decision['action'], 'link')
        self.assertEqual(decision['speaker_id'], 1)
        self.assertEqual(decision['user_id'], 9)
        self.assertEqual(decision['display_name'], 'Tim Lien')
        self.assertIn(('Tim', 'tim'), decision['add_names'])
        self.assertIn(('Tim Lien', speaker_key('Tim Lien')), decision['add_names'])

        lien = {'id': 2, 'display_name': 'Tim Lien', 'user_id': 9, 'names': ['tim lien']}
        decision, error = decide_speaker(choice, [tim, lien])
        self.assertIsNone(error)
        self.assertEqual(decision['action'], 'combine')
        self.assertEqual(decision['into_id'], 2)
        self.assertEqual(decision['speaker_id'], 1)

    def test_unknown_ids_and_two_accounts_are_rejected(self):
        from app.utils.sermon_drive import plan_combine, plan_speaker_form
        _choice, errors = plan_speaker_form({'speaker_id': '1 OR 1=1', 'speaker_user': ''}, {})
        self.assertEqual(errors, ['Choose a speaker from the list.'])
        _choice, errors = plan_speaker_form({'speaker_user': '99'}, {1: 'Ada'})
        self.assertEqual(errors, ['Choose a member from the list.'])
        _choice, errors = plan_speaker_form({'speaker_id': '0'}, {})
        self.assertEqual(errors, ['Choose a speaker from the list.'])
        _plan, error = plan_combine({'id': 1, 'user_id': 2}, {'id': 3, 'user_id': 4})
        self.assertEqual(error, 'Those names are already on two different accounts.')
        _plan, error = plan_combine({'id': 1, 'user_id': 2}, {'id': 1, 'user_id': 2})
        self.assertEqual(error, 'Choose two different speakers.')
        plan, error = plan_combine({'id': 1, 'user_id': None}, {'id': 3, 'user_id': 9})
        self.assertIsNone(error)
        self.assertEqual(plan['into'], 1)

    def test_sort_is_newest_first_and_groups_names_and_folders(self):
        from app.utils.sermon_drive import parse_sort, sort_rows
        self.assertEqual(parse_sort('<script>'), 'date')
        self.assertEqual(parse_sort('SPEAKER'), 'speaker')
        rows = [
            {'id': 1, 'title': 'B', 'preached_on': None, 'speaker': 'Tim', 'source_label': 'Guest'},
            {'id': 2, 'title': 'A', 'preached_on': '2020-01-01', 'speaker': 'Ada', 'source_label': 'Sunday'},
            {
                'id': 3, 'title': 'C', 'preached_on': '2024-05-01',
                'speaker': 'Tim', 'speaker_label': 'Tim Lien', 'source_label': 'Sunday',
            },
        ]
        self.assertEqual([row['id'] for row in sort_rows(rows, 'date')], [3, 2, 1])
        self.assertEqual([row['id'] for row in sort_rows(rows, 'speaker')], [2, 1, 3])
        self.assertEqual([row['id'] for row in sort_rows(rows, 'folder')], [1, 3, 2])
        self.assertEqual([row['id'] for row in sort_rows(rows, 'nope')], [3, 2, 1])

    def test_a_linked_speaker_is_not_replaced_by_the_file_name(self):
        existing = {FILE: {
            'id': 9,
            'drive_file_id': FILE,
            'drive_name': 'old.mp3',
            'site_edited': 0,
            'speaker': 'Tim Lien',
            'speaker_id': 3,
        }}
        seen = [{
            'file_id': FILE,
            'name': '2024-01-02 - Ada Stone - Other.mp3',
            'kind': 'audio',
            'parent_folder_id': FOLDER,
        }]
        item = plan_sync(existing, seen, complete=True)['upserts'][0]
        self.assertEqual(item['speaker'], 'Tim Lien')

    def test_cards_use_the_account_name_and_the_folder_label(self):
        card = present({
            **_row(),
            'speaker': 'Tim',
            'speaker_label': 'Tim Lien',
            'source_label': 'Sunday',
            'local_name': '7.mp3',
            'user_id': 9,
        }, logged_in=False, role='')
        self.assertEqual(card['speaker'], 'Tim Lien')
        self.assertEqual(card['source_label'], 'Sunday')
        self.assertNotIn('local_name', card)
        self.assertNotIn('user_id', card)
        self.assertNotIn('drive_file_id', card)
        self.assertTrue(card['play_url'].endswith('/preview'))

    def test_a_hidden_folder_stays_off_the_public_page(self):
        closed = _row(source_enabled=0)
        self.assertFalse(can_see(closed, logged_in=False, role=''))
        self.assertFalse(can_listen(closed, logged_in=True, role='Member'))
        self.assertTrue(can_see(closed, logged_in=True, role='Staff'))
        self.assertTrue(can_listen(closed, logged_in=True, role='Owner'))
        self.assertTrue(can_see(_row(), logged_in=False, role=''))

    def test_saving_a_new_name_stores_the_speaker_id(self):
        cur = _Cursor()
        ok, errors = self._save({
            'title': 'Hello',
            'visibility': 'public',
            'speaker': 'Tim',
            'speaker_id': '',
            'speaker_user': '',
        }, cur)
        self.assertTrue(ok, errors)
        updates = self._update(cur)
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0][1], 'Tim')
        self.assertEqual(updates[0][2], 15)

    def test_a_blank_speaker_clears_the_link(self):
        cur = _Cursor()
        ok, errors = self._save({
            'title': 'Hello',
            'visibility': 'public',
            'speaker': '',
            'speaker_id': '',
            'speaker_user': '',
        }, cur)
        self.assertTrue(ok, errors)
        updates = self._update(cur)
        self.assertEqual(updates[0][1], None)
        self.assertEqual(updates[0][2], None)

    def test_a_form_without_speaker_fields_keeps_the_saved_speaker(self):
        cur = _Cursor(ones=[{'speaker': 'Kept', 'speaker_id': 4}])
        ok, errors = self._save({'title': 'Hello', 'visibility': 'public'}, cur)
        self.assertTrue(ok, errors)
        updates = self._update(cur)
        self.assertEqual(updates[0][1], 'Kept')
        self.assertEqual(updates[0][2], 4)

    def test_a_bad_member_id_does_not_write_the_message(self):
        cur = _Cursor()
        ok, errors = self._save({
            'title': 'Hello',
            'visibility': 'public',
            'speaker': 'Tim',
            'speaker_id': '',
            'speaker_user': 'nope',
        }, cur)
        self.assertFalse(ok)
        self.assertIn('Choose a member from the list.', errors)
        self.assertFalse(any('site_edited=1' in sql for sql, _params in cur.calls))


class MessageFromTests(unittest.TestCase):
    def test_names_stay_exact_and_an_added_name_joins_the_list(self):
        rows = [
            {'speaker': 'Christopher Fuentes', 'title': 'Hope', 'scripture': 'John 3'},
            {'speaker_label': 'Tim Lien', 'speaker': 'Tim', 'title': 'Evening'},
            {'speaker': 'Leo', 'title': 'Welcome'},
        ]
        people = people_from_rows(rows)
        self.assertEqual(
            [person['label'] for person in people],
            ['Christopher Fuentes', 'Leo', 'Tim Lien'],
        )
        self.assertTrue(row_matches_library(rows[0], who='christopher fuentes', query='john'))
        self.assertFalse(row_matches_library(rows[1], who='tim'))
        self.assertTrue(row_matches_library(rows[1], who='tim lien'))
        added = merge_named_people(people, [{'display_name': 'Amy Grace'}])
        self.assertIn('Amy Grace', [person['label'] for person in added])
        self.assertEqual(
            [person['label'] for person in merge_named_people(added, [{'display_name': 'Amy Grace'}])].count('Amy Grace'),
            1,
        )


class ListenCountTests(unittest.TestCase):
    def test_each_person_is_counted_once_and_the_address_is_not_stored(self):
        from app.utils.sermon_drive import listen_counts, listener_key, record_listen

        self.assertEqual(listener_key(4, '203.0.113.9'), 'u:4')
        self.assertEqual(listener_key('4', '203.0.113.9'), 'u:4')
        guest = listener_key(None, '203.0.113.9')
        self.assertEqual(guest, listener_key(0, '203.0.113.9'))
        self.assertTrue(guest.startswith('g:'))
        self.assertEqual(len(guest), 34)
        self.assertNotIn('203.0.113.9', guest)
        self.assertIsNone(listener_key(None, None))
        self.assertIsNone(listener_key(None, ''))
        self.assertIsNone(listener_key(None, 'not an ip'))
        self.assertIsNone(listener_key(None, '203.0.113.9\n1'))
        self.assertIsNone(listener_key('', 'x'))
        self.assertIsNone(listener_key(None, '12'))

        cur = _Cursor(alls=[[{'item_id': 7, 'n': 2}]])
        db = SimpleNamespace(cursor=lambda: cur, commit=Mock())
        with patch('app.utils.sermon_drive.ensure_schema'), \
                patch('app.models.db.get_db', return_value=db):
            self.assertTrue(record_listen(7, 4, '203.0.113.9'))
            self.assertTrue(record_listen(7, None, '203.0.113.9'))
            self.assertFalse(record_listen(7, None, None))
            totals = listen_counts([7, 'nope', None])
        self.assertEqual(totals, {7: 2})
        joined = json.dumps(cur.calls)
        self.assertNotIn('203.0.113.9', joined)
        inserts = [params for sql, params in cur.calls if 'INSERT IGNORE' in sql]
        self.assertEqual(inserts, [(7, 'u:4'), (7, guest)])
        self.assertEqual(len(inserts), 2)

        closed = Mock(side_effect=KeyError('MYSQL_HOST'))
        with patch('app.models.db.get_db', closed):
            self.assertEqual(listen_counts([]), {})
            self.assertEqual(listen_counts([7]), {})
            self.assertFalse(record_listen(7, 4, '203.0.113.9'))
        self.assertEqual(closed.call_count, 2)


if __name__ == '__main__':
    unittest.main()
