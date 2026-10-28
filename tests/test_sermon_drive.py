"""Sermon library: filename parsing, Drive listing, and who can listen. No database and no network."""

import datetime
import json
import unittest

from app.utils.sermon_drive import (
    DriveReadError,
    can_listen,
    can_see,
    clean_edit,
    edit_view,
    extract_folder_id,
    folder_list_url,
    is_stale,
    parse_refresh_hours,
    parse_visibility,
    parse_drive_name,
    parse_folder_html,
    plan_sync,
    play_url,
    present,
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


if __name__ == '__main__':
    unittest.main()
