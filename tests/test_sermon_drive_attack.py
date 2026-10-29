"""Throw bad links, locked rows, and form posts at the sermon library.

No database and no network. These tests fail when a check lets something through.
"""

import json
import os
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, Mock, patch

from flask import Flask, Blueprint
from jinja2 import ChoiceLoader, DictLoader, FileSystemLoader

from app.utils.helpers import jinja_censor, jinja_nl2br
from app.utils.sermon_drive import (
    DriveReadError,
    apply_visibility_to_all,
    can_listen,
    can_see,
    clean_edit,
    extract_folder_id,
    fetch_folder_html,
    folder_list_url,
    parse_folder_html,
    parse_refresh_hours,
    parse_visibility,
    plan_sync,
    play_url,
    present,
    save_default_visibility,
    save_folder_id,
    save_item_details,
    save_refresh_hours,
    walk_folder,
    with_drive_frame,
)
from tests.test_sermon_drive import FILE, FOLDER, CHILD, _entry, _page, _row

TEMPLATES = Path(__file__).resolve().parents[1] / 'app' / 'templates'
HOSTILE_TITLE = '<script>alert(1)</script>'
HOSTILE_ATTR = '"><img src=x onerror=alert(1)>'
POISON_LOCK = "public' OR 1=1"
POISON_HOURS = '1 OR 1=1'
POISON_LINK = 'javascript:alert(1)'


class _Tags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []
        self.iframe = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        if tag == 'iframe':
            self.iframe.append(dict(attrs))


def _tags(document):
    parser = _Tags()
    parser.feed(document)
    return parser


def _library_app():
    import app.routes.sermons.views  # noqa: F401  (register drive routes on the sermon blueprint)
    from app.routes.sermons.views import sermons_bp

    app = Flask(__name__, template_folder=str(TEMPLATES))
    app.secret_key = 'sermon-attack-test'
    app.jinja_env.filters['censor'] = jinja_censor
    app.jinja_env.filters['nl2br'] = jinja_nl2br
    app.jinja_loader = ChoiceLoader([
        DictLoader({'base.html': '{% block content %}{% endblock %}\n'}),
        FileSystemLoader(str(TEMPLATES)),
    ])
    auth = Blueprint('auth', __name__)

    @auth.route('/login')
    def login():
        return 'login'

    @auth.route('/logout')
    def logout():
        return 'logout'

    app.register_blueprint(auth)
    app.register_blueprint(sermons_bp)
    settings = Blueprint('settings', __name__, url_prefix='/settings')

    @settings.route('/messages')
    def messages():
        return 'messages'

    church = Blueprint('church', __name__)

    @church.route('/u/<username>')
    def member_page(username):
        return username

    app.register_blueprint(settings)
    app.register_blueprint(church)
    return app


class LinkAndPlayerTests(unittest.TestCase):
    def test_a_pasted_link_cannot_choose_where_the_server_connects(self):
        samples = [
            f'https://evil.example/folders/{FOLDER}?x=https://drive.google.com',
            f'https://drive.google.com.evil.example/folders/{FOLDER}',
            f'https://drive.google.com@evil.example/folders/{FOLDER}',
            f'http://drive.google.com/drive/folders/{FOLDER}',
            f'https://drive.google.com/drive/folders/{FOLDER}?usp=sharing',
            f'javascript:alert(1)//drive.google.com/folders/{FOLDER}',
            f'https://user:pass@drive.google.com/drive/folders/{FOLDER}',
        ]
        for raw in samples:
            folder_id = extract_folder_id(raw)
            if folder_id is None:
                continue
            url = folder_list_url(folder_id)
            self.assertEqual(url, f'https://drive.google.com/embeddedfolderview?id={folder_id}')
            self.assertNotIn('evil.example', url)
            self.assertNotIn('@', url)
            self.assertNotIn('javascript', url)
            self.assertNotIn('export=download', url)

    def test_hostile_folder_text_is_rejected(self):
        rejected = [
            POISON_LINK,
            'data:text/html,hello',
            'file:///etc/passwd',
            f'https://127.0.0.1/folders/{FOLDER}',
            f'https://evil.example/folders/{FOLDER}',
            f'{FOLDER}\r\nSet-Cookie: a=b',
            f'{FOLDER}\nhttps://drive.google.com',
            f'{FOLDER[:12]}\t{FOLDER[12:]}',
            f'{FOLDER}\x00{FOLDER}',
            'short',
            '',
            None,
        ]
        for raw in rejected:
            self.assertIsNone(extract_folder_id(raw), raw)

    def test_a_bad_folder_id_never_opens_a_connection(self):
        opener = Mock(side_effect=AssertionError('network'))
        with patch('urllib.request.urlopen', opener):
            for raw in ('127.0.0.1', 'localhost', POISON_LINK, '../etc/passwd', 'A' * 9, FILE + '"'):
                with self.assertRaises(DriveReadError):
                    fetch_folder_html(raw)
        opener.assert_not_called()

    def test_the_player_url_stays_on_the_preview_path(self):
        self.assertEqual(play_url(FILE), f'https://drive.google.com/file/d/{FILE}/preview')
        for bad in (
            '../etc/passwd',
            'short',
            FILE + '"',
            FILE + "'",
            FILE + ' ',
            FILE + '\n',
            FILE + '/preview',
            POISON_LINK,
            'https://evil.example/' + FILE,
            'А' * 16,
        ):
            self.assertIsNone(play_url(bad), bad)

    def test_a_script_in_the_listing_is_not_stored_as_markup(self):
        with self.assertRaises(DriveReadError):
            parse_folder_html(_page(_entry(FILE, HOSTILE_TITLE, 'audio')))
        parsed = parse_folder_html(_page(_entry(FILE, '&lt;script&gt;alert(1)&lt;/script&gt;', 'audio')))
        self.assertEqual(parsed[0]['name'], HOSTILE_TITLE)
        self.assertEqual(parsed[0]['file_id'], FILE)

    def test_a_walk_only_follows_folder_ids(self):
        seen = []

        def fetch(folder_id):
            seen.append(folder_id)
            self.assertRegex(folder_id, r'\A[A-Za-z0-9_-]{10,128}\Z')
            if folder_id == FOLDER:
                evil = (
                    f'<div class="flip-entry" id="entry-{CHILD}">'
                    f'<a href="https://evil.example/drive/folders/{CHILD}?x=drive.google.com">'
                    f'<div aria-label="Folder"></div>'
                    f'<div class="flip-entry-title">Year.mp3</div></a></div>'
                    f'<div class="flip-entry" id="entry-bad id!!">'
                    f'<a href="javascript:alert(1)"><div class="flip-entry-title">Nope.mp3</div></a></div>'
                )
                return _page(evil)
            return _page(_entry(FILE, 'Song.mp3', 'audio'))

        walk = walk_folder(FOLDER, fetch)
        self.assertEqual(seen, [FOLDER, CHILD])
        self.assertEqual([item['file_id'] for item in walk.files], [FILE])
        self.assertNotIn('evil.example', json.dumps(walk.files))

    def test_the_player_policy_is_added_only_on_sermon_pages(self):
        from flask import Response
        from app.routes.sermons.drive_pages import allow_drive_player

        app = Flask(__name__)
        base = "default-src 'self';"
        with app.test_request_context('/sermons/library/7'):
            opened = allow_drive_player(Response('ok', headers={'Content-Security-Policy': base}))
            policy = opened.headers['Content-Security-Policy']
            self.assertIn('https://drive.google.com', policy)
            self.assertIn('https://docs.google.com', policy)
            self.assertNotIn('*', policy)
        with app.test_request_context('/sermons/library/7'):
            locked = allow_drive_player(Response('ok', headers={'Content-Security-Policy': "frame-src 'none';"}))
            self.assertEqual(locked.headers['Content-Security-Policy'], "frame-src 'none';")
        for path in ('/settings', '/public/sermons', '/sermons-extra', '/'):
            with app.test_request_context(path):
                left = allow_drive_player(Response('ok', headers={'Content-Security-Policy': base}))
                self.assertNotIn('drive.google.com', left.headers['Content-Security-Policy'])
        self.assertNotIn('*', with_drive_frame(base))


class LockTests(unittest.TestCase):
    def _blob(self, card):
        return json.dumps(card)

    def test_a_role_without_a_login_does_not_unlock_a_message(self):
        for role in ('Staff', 'Admin', 'Owner', 'admin', 'ADMIN'):
            for row in (
                _row(visibility='leaders', title='Leaders Secret'),
                _row(hidden=1, title='Hidden Secret'),
                _row(missing_on_drive=1, title='Missing Secret'),
            ):
                self.assertFalse(can_see(row, logged_in=False, role=role))
                self.assertFalse(can_listen(row, logged_in=False, role=role))
                card = present(row, logged_in=False, role=role)
                self.assertIsNone(card['play_url'])
                self.assertFalse(card['can_edit'])
                blob = self._blob(card)
                self.assertNotIn(FILE, blob)
                self.assertNotIn(FOLDER, blob)

    def test_a_signed_in_owner_can_still_preview(self):
        row = _row(visibility='leaders', hidden=0)
        card = present(row, logged_in=True, role='Owner')
        self.assertTrue(card['can_listen'])
        self.assertTrue(card['play_url'].endswith('/preview'))
        self.assertNotIn(FOLDER, self._blob(card))

    def test_a_public_message_still_plays_for_a_guest(self):
        card = present(_row(), logged_in=False, role='Owner')
        self.assertTrue(card['can_listen'])
        self.assertTrue(card['play_url'].endswith('/preview'))

    def test_lookalike_roles_do_not_count_as_staff(self):
        row = _row(visibility='leaders')
        for role in ('admin', 'ADMIN', 'owner', 'Owner ', 'Staff '):
            self.assertFalse(can_listen(row, logged_in=True, role=role), role)
            self.assertFalse(can_see(row, logged_in=True, role=role), role)

    def test_an_unknown_lock_is_staff_only(self):
        row = _row(visibility=POISON_LOCK, title='Poisoned lock')
        self.assertFalse(can_see(row, logged_in=False, role=''))
        self.assertFalse(can_see(row, logged_in=True, role='Member'))
        self.assertFalse(can_listen(row, logged_in=True, role='Member'))
        guest = present(row, logged_in=False, role='Owner')
        self.assertIsNone(guest['play_url'])
        self.assertNotIn(FILE, self._blob(guest))
        self.assertNotIn(POISON_LOCK, guest['visibility'])
        self.assertTrue(can_see(row, logged_in=True, role='Admin'))

    def test_a_poisoned_default_is_stored_as_anyone(self):
        seen = [{
            'file_id': FILE,
            'name': '2026-03-08 - Sharing.mp3',
            'kind': 'audio',
            'mime': 'audio/mpeg',
            'modified': 'Mar 8',
            'parent_folder_id': FOLDER,
        }]
        item = plan_sync({}, seen, complete=True, default_visibility=POISON_LOCK)['upserts'][0]
        self.assertEqual(item['visibility'], 'public')
        self.assertIsNone(parse_visibility(POISON_LOCK))
        self.assertIsNone(parse_visibility('secret'))
        self.assertEqual(parse_visibility(' PUBLIC '), 'public')


class FormTests(unittest.TestCase):
    def test_an_edit_cannot_change_drive_fields(self):
        fields, errors = clean_edit({
            'title': 'Hello\x00<script>',
            'speaker': 'Ada',
            'visibility': POISON_LOCK,
            'preached_on': "9999-99-99' OR 1=1",
            'hidden': '1 OR 1=1',
            'drive_file_id': FILE,
            'parent_folder_id': FOLDER,
            'site_edited': '0',
            'folder': FOLDER,
            'updated_by': '999',
            'id': '1',
        })
        self.assertIn('Choose who can listen.', errors)
        self.assertIn('Use a real date, or leave the date blank.', errors)
        self.assertEqual(fields['title'], 'Hello<script>')
        self.assertNotIn('\x00', fields['title'])
        self.assertEqual(fields['visibility'], 'public')
        self.assertEqual(fields['hidden'], 0)
        self.assertEqual(
            set(fields),
            {'title', 'speaker', 'scripture', 'series', 'summary', 'preached_on', 'visibility', 'hidden'},
        )
        self.assertNotIn(FILE, json.dumps(fields))
        self.assertNotIn(FOLDER, json.dumps(fields))

    def test_rejected_settings_never_reach_the_database(self):
        db = Mock(side_effect=AssertionError('db'))
        with patch('app.models.db.get_db', db):
            ok, errors = save_item_details(7, {
                'title': 'Hello',
                'visibility': POISON_LOCK,
                'drive_file_id': FILE,
            }, 4)
            self.assertFalse(ok)
            self.assertIn('Choose who can listen.', errors)
            self.assertEqual(save_refresh_hours(POISON_HOURS), ('bad', None))
            self.assertEqual(save_refresh_hours('168.0'), ('bad', None))
            self.assertEqual(save_refresh_hours('8e0'), ('bad', None))
            self.assertEqual(save_refresh_hours('-1'), ('bad', None))
            self.assertEqual(save_refresh_hours('999999'), ('bad', None))
            self.assertEqual(save_refresh_hours('8\n168'), ('bad', None))
            self.assertEqual(parse_refresh_hours('00'), 0)
            self.assertEqual(save_default_visibility(POISON_LOCK), ('bad', None))
            self.assertEqual(apply_visibility_to_all(POISON_LOCK), ('bad', None))
            self.assertFalse(save_folder_id(POISON_LINK))
            self.assertFalse(save_folder_id(f'{FOLDER}\r\nhttps://evil.example'))
            self.assertFalse(save_folder_id('https://evil.example/folders/' + FOLDER))
        db.assert_not_called()


class PageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _library_app()
        cls.client = cls.app.test_client()

    def _session(self, **keys):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess.update(keys)

    def _grab_library(self, rows, user):
        captured = {}

        def grab(name, **kwargs):
            captured['name'] = name
            captured['kwargs'] = kwargs
            return 'ok'

        with patch('app.models.users.get_user_by_id', return_value=user) as lookup, \
                patch('app.routes.sermons.drive_pages.maybe_sync'), \
                patch('app.routes.sermons.drive_pages.list_items', return_value=rows), \
                patch('app.routes.sermons.drive_pages.current_refresh_hours', return_value=168), \
                patch('app.routes.sermons.drive_pages.current_default_visibility', return_value='public'), \
                patch('app.routes.sermons.drive_pages.render_template', grab):
            response = self.client.get('/sermons/?year=2024<script>')
        captured['status'] = response.status_code
        captured['lookup'] = lookup
        return captured

    def test_a_logged_out_owner_role_sees_the_public_library(self):
        rows = [
            _row(title='Open message'),
            _row(id=8, visibility='leaders', title='Leaders Secret'),
            _row(id=9, visibility=POISON_LOCK, title='Poisoned lock'),
        ]
        self._session(user_role='Owner')
        captured = self._grab_library(rows, user={'id': 4, 'role': 'Owner'})
        self.assertEqual(captured['status'], 200)
        self.assertEqual(captured['name'], 'public/sermons/library.html')
        self.assertFalse(captured['kwargs']['is_staff'])
        self.assertFalse(captured['kwargs']['is_owner'])
        self.assertEqual(captured['kwargs']['active_year'], '')
        titles = [item['title'] for item in captured['kwargs']['messages']]
        self.assertEqual(titles, ['Open message'])
        self.assertFalse(captured['lookup'].called)
        self.assertNotIn('Leaders Secret', json.dumps(captured['kwargs']))
        self.assertNotIn('<script', json.dumps(captured['kwargs']))
        self.assertNotIn(FOLDER, json.dumps(captured['kwargs']))

    def test_the_account_role_wins_over_the_session_role(self):
        rows = [
            _row(visibility='members', title='Members message'),
            _row(id=8, visibility='leaders', title='Leaders Secret'),
        ]
        self._session(user_id=4, user_role='Owner')
        captured = self._grab_library(rows, user={'id': 4, 'role': 'Member'})
        self.assertEqual(captured['name'], 'sermons/library.html')
        self.assertFalse(captured['kwargs']['is_staff'])
        self.assertFalse(captured['kwargs']['is_owner'])
        titles = [item['title'] for item in captured['kwargs']['messages']]
        self.assertEqual(titles, ['Members message'])
        self.assertTrue(captured['kwargs']['messages'][0]['can_listen'])
        self.assertNotIn(FILE, json.dumps([
            item for item in captured['kwargs']['messages'] if item['title'] != 'Members message'
        ]))

    def test_a_banned_account_is_treated_as_a_guest(self):
        self._session(user_id=4, user_role='Owner')
        captured = self._grab_library(
            [_row(visibility='leaders', title='Leaders Secret'), _row(title='Open message')],
            user={'id': 4, 'role': 'Owner', 'is_banned': 1},
        )
        self.assertEqual(captured['name'], 'public/sermons/library.html')
        self.assertEqual([item['title'] for item in captured['kwargs']['messages']], ['Open message'])

    def test_a_database_miss_keeps_the_page_up_without_staff_tools(self):
        def boom(_user_id):
            raise RuntimeError('database')

        rows = [
            _row(visibility='members', title='Members message'),
            _row(id=8, visibility='leaders', title='Leaders Secret'),
        ]
        self._session(user_id=4, user_role='Owner')
        captured = self._grab_library(rows, user=None)
        self.assertEqual(captured['name'], 'public/sermons/library.html')
        self.assertFalse(captured['kwargs']['is_staff'])

        captured_down = {}

        def grab(name, **kwargs):
            captured_down['name'] = name
            captured_down['kwargs'] = kwargs
            return 'ok'

        with patch('app.models.users.get_user_by_id', boom), \
                patch('app.routes.sermons.drive_pages.maybe_sync'), \
                patch('app.routes.sermons.drive_pages.list_items', return_value=rows), \
                patch('app.routes.sermons.drive_pages.current_refresh_hours', return_value=168), \
                patch('app.routes.sermons.drive_pages.current_default_visibility', return_value='public'), \
                patch('app.routes.sermons.drive_pages.render_template', grab):
            response = self.client.get('/sermons/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(captured_down['name'], 'sermons/library.html')
        self.assertFalse(captured_down['kwargs']['is_staff'])
        self.assertEqual(
            [item['title'] for item in captured_down['kwargs']['messages']],
            ['Members message'],
        )
        self.assertTrue(captured_down['kwargs']['messages'][0]['can_listen'])

    def test_a_locked_listen_page_does_not_reveal_the_title(self):
        secret = 'Leaders Secret Title'
        row = _row(visibility='leaders', title=secret)
        with patch('app.routes.sermons.drive_pages.maybe_sync'), \
                patch('app.routes.sermons.drive_pages.get_item', return_value=row) as getter, \
                patch('app.routes.sermons.drive_pages.render_template', side_effect=AssertionError('rendered')):
            self._session(user_role='Owner')
            response = self.client.get('/sermons/library/7')
        self.assertEqual(response.status_code, 404)
        self.assertNotIn(secret.encode(), response.data)
        self.assertNotIn(FILE.encode(), response.data)
        self.assertNotIn(FOLDER.encode(), response.data)
        getter.assert_called_once_with(7)

        with patch('app.models.users.get_user_by_id', return_value={'id': 4, 'role': 'Member'}), \
                patch('app.routes.sermons.drive_pages.maybe_sync'), \
                patch('app.routes.sermons.drive_pages.get_item', return_value=row), \
                patch('app.routes.sermons.drive_pages.render_template', side_effect=AssertionError('rendered')):
            self._session(user_id=4, user_role='Owner')
            response = self.client.get('/sermons/library/7')
        self.assertEqual(response.status_code, 404)
        self.assertNotIn(secret.encode(), response.data)

    def test_a_real_owner_still_gets_the_player(self):
        captured = {}

        def grab(name, **kwargs):
            captured['message'] = kwargs['message']
            return 'player'

        row = _row(visibility='leaders')
        with patch('app.models.users.get_user_by_id', return_value={'id': 4, 'role': 'Owner'}), \
                patch('app.routes.sermons.drive_pages.maybe_sync'), \
                patch('app.routes.sermons.drive_pages.get_item', return_value=row), \
                patch('app.routes.sermons.drive_pages.drive_comment_thread', return_value=[]), \
                patch('app.routes.sermons.drive_pages.render_template', grab):
            self._session(user_id=4, user_role='Member')
            response = self.client.get('/sermons/library/7')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(captured['message']['play_url'].endswith('/preview'))
        self.assertNotIn(FOLDER, json.dumps(captured['message']))

    def test_a_non_number_id_never_reaches_the_lookup(self):
        getter = Mock(side_effect=AssertionError('lookup'))
        with patch('app.routes.sermons.drive_pages.get_item', getter):
            for path in (
                '/sermons/library/1%20OR%201%3D1',
                '/sermons/library/1;drop',
                '/sermons/library/-1',
                '/sermons/library/7%20OR%201/edit',
            ):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 404, path)
        getter.assert_not_called()

    def test_listeners_cannot_post_library_changes(self):
        saver = Mock(side_effect=AssertionError('save'))
        targets = {
            '/sermons/library/visibility-all': {'visibility': POISON_LOCK},
            '/sermons/library/default-visibility': {'visibility': POISON_LOCK},
            '/sermons/library/schedule': {'refresh_hours': POISON_HOURS},
            '/sermons/library/source': {'folder': POISON_LINK},
            '/sermons/library/source-update': {'source_id': '1', 'label': 'X', 'enabled': '1'},
            '/sermons/library/speakers': {'action': 'link', 'speaker_id': '1', 'speaker_user': '9'},
            '/sermons/library/speakers/add': {'speaker': 'Amy Grace'},
            '/sermons/library/refresh': {},
            '/sermons/library/7/edit': {'title': 'x', 'visibility': 'public', 'drive_file_id': FILE},
        }
        with patch('app.utils.decorators.log_change'), \
                patch('app.utils.decorators.get_user_by_id', return_value={'id': 4, 'role': 'Member'}), \
                patch('app.routes.sermons.drive_pages.apply_visibility_to_all', saver), \
                patch('app.routes.sermons.drive_pages.save_default_visibility', saver), \
                patch('app.routes.sermons.drive_pages.save_refresh_hours', saver), \
                patch('app.routes.sermons.drive_pages.save_folder_id', saver), \
                patch('app.routes.sermons.drive_pages.save_source', saver), \
                patch('app.routes.sermons.drive_pages.sync_now', saver), \
                patch('app.routes.sermons.drive_pages.save_item_details', saver), \
                patch('app.routes.sermons.drive_pages.link_speaker_account', saver), \
                patch('app.routes.sermons.drive_pages.add_speaker_name', saver), \
                patch('app.routes.sermons.drive_pages.create_speaker', saver), \
                patch('app.routes.sermons.drive_pages.combine_speakers', saver), \
                patch('app.routes.sermons.drive_pages.unlink_speaker_account', saver):
            for path, form in targets.items():
                self._session()
                guest = self.client.post(path, data=form)
                self.assertEqual(guest.status_code, 302, path)
                self.assertIn('/login', guest.headers['Location'])
                self._session(user_id=4, user_role='Owner')
                member = self.client.post(path, data=form)
                self.assertEqual(member.status_code, 403, path)
        saver.assert_not_called()

    def test_an_admin_cannot_change_the_folder(self):
        saver = Mock(return_value=True)
        with patch('app.utils.decorators.log_change') as logged, \
                patch('app.utils.decorators.get_user_by_id', return_value={'id': 4, 'role': 'Admin'}), \
                patch('app.routes.sermons.drive_pages.save_folder_id', saver):
            self._session(user_id=4, user_role='Owner')
            response = self.client.post('/sermons/library/source', data={'folder': FOLDER, 'next': 'https://evil.example'})
        self.assertEqual(response.status_code, 403)
        saver.assert_not_called()
        logged.assert_called()

    def test_staff_posts_are_rejected_before_a_write_and_stay_on_this_site(self):
        db = Mock(side_effect=AssertionError('db'))
        with patch('app.utils.decorators.get_user_by_id', return_value={'id': 4, 'role': 'Staff'}), \
                patch('app.models.db.get_db', db):
            self._session(user_id=4, user_role='Member')
            schedule = self.client.post(
                '/sermons/library/schedule?next=https://evil.example',
                data={'refresh_hours': POISON_HOURS},
            )
            default = self.client.post(
                '/sermons/library/default-visibility',
                data={'visibility': POISON_LOCK},
            )
            bulk = self.client.post(
                '/sermons/library/visibility-all',
                data={'visibility': POISON_LOCK},
            )
        db.assert_not_called()
        for response, expected in (
            (schedule, 'Choose how often to check Drive.'),
            (default, 'Choose who can listen to new messages.'),
            (bulk, 'Choose who can listen.'),
        ):
            self.assertEqual(response.status_code, 302)
            self.assertNotIn('evil.example', response.headers['Location'])
            self.assertIn('/settings/messages', response.headers['Location'])
            with self.client.session_transaction() as sess:
                self.assertIn(expected, str(sess.get('_flashes')))

        folder_saver = Mock(return_value=False)
        with patch('app.utils.decorators.get_user_by_id', return_value={'id': 9, 'role': 'Owner'}), \
                patch('app.routes.sermons.drive_pages.save_folder_id', folder_saver), \
                patch('app.models.db.get_db', side_effect=AssertionError('db')):
            self._session(user_id=9, user_role='Member')
            response = self.client.post('/sermons/library/source', data={'folder': POISON_LINK})
        self.assertEqual(response.status_code, 302)
        folder_saver.assert_called_once_with(POISON_LINK)
        self.assertNotIn('evil.example', response.headers['Location'])

    def test_an_edit_saves_the_signed_in_account_not_the_posted_id(self):
        seen = {}

        def fake_save(item_id, form, user_id):
            seen['item_id'] = item_id
            seen['form'] = dict(form)
            seen['user_id'] = user_id
            return True, []

        with patch('app.utils.decorators.get_user_by_id', return_value={'id': 4, 'role': 'Owner'}), \
                patch('app.routes.sermons.drive_pages.save_item_details', fake_save), \
                patch('app.routes.sermons.drive_pages.get_item', return_value=_row()):
            self._session(user_id=4, user_role='Member')
            response = self.client.post('/sermons/library/7/edit', data={
                'title': 'Hello',
                'visibility': 'members',
                'drive_file_id': FILE,
                'updated_by': '999',
                'folder': FOLDER,
            })
        self.assertEqual(response.status_code, 302)
        self.assertIn('/sermons/library/7', response.headers['Location'])
        self.assertNotIn('evil.example', response.headers['Location'])
        self.assertEqual(seen['item_id'], 7)
        self.assertEqual(seen['user_id'], 4)
        self.assertEqual(seen['form']['updated_by'], '999')


class RenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _library_app()

    def _render(self, template, **kwargs):
        with patch('app.utils.helpers.get_censored_words', return_value=[]), \
                self.app.test_request_context('/sermons'):
            return self.app.jinja_env.get_template(template).render(**kwargs)

    def test_a_script_title_is_text_on_the_card_and_in_the_player(self):
        card = present(_row(title=HOSTILE_TITLE, speaker=HOSTILE_ATTR, summary=HOSTILE_TITLE), logged_in=False, role='')
        html = self._render(
            'sermons/_library_cards.html',
            messages=[card],
            years=[],
            active_year='',
        )
        parsed = _tags(html)
        self.assertNotIn('script', parsed.tags)
        self.assertNotIn('img', parsed.tags)
        self.assertNotIn('<script', html.lower())
        self.assertNotIn('<img', html.lower())
        self.assertIn('&lt;script&gt;', html)
        self.assertNotIn(FOLDER, html)

        playing = present(_row(title=HOSTILE_ATTR), logged_in=True, role='Member')
        body = self._render('sermons/_listen_body.html', message=playing)
        parsed_body = _tags(body)
        self.assertEqual(parsed_body.iframe[0]['src'], f'https://drive.google.com/file/d/{FILE}/preview')
        self.assertEqual(parsed_body.iframe[0].get('referrerpolicy'), 'no-referrer')
        self.assertNotIn('script', parsed_body.tags)
        self.assertNotIn('img', parsed_body.tags)
        self.assertNotIn('export=download', body)
        self.assertNotIn(FOLDER, body)

        locked = present(_row(visibility='members', title=HOSTILE_TITLE), logged_in=False, role='Owner')
        locked_html = self._render(
            'sermons/_library_cards.html',
            messages=[locked],
            years=[],
            active_year='',
        )
        self.assertNotIn('iframe', _tags(locked_html).tags)
        self.assertNotIn(FILE, locked_html)
        self.assertNotIn(FOLDER, locked_html)
        self.assertNotIn('<script', locked_html.lower())

    def test_the_edit_form_escapes_drive_text_and_omits_ids(self):
        from app.utils.sermon_drive import edit_view
        row = _row(title=HOSTILE_ATTR, drive_name=HOSTILE_TITLE, summary=HOSTILE_TITLE, speaker=HOSTILE_ATTR)
        html = self._render('sermons/library_edit.html', message=edit_view(row))
        parsed = _tags(html)
        self.assertNotIn('script', parsed.tags)
        self.assertNotIn('img', parsed.tags)
        self.assertNotIn('<script', html.lower())
        self.assertNotIn(FILE, html)
        self.assertNotIn(FOLDER, html)
        self.assertIn('name="csrf_token"', html)

    def test_staff_forms_carry_a_token_and_an_empty_folder_field(self):
        from app.utils.sermon_drive import REFRESH_CHOICES, VISIBILITY_CHOICES
        shared = dict(
            messages=[],
            years=[],
            active_year='',
            refresh_hours=168,
            refresh_choices=REFRESH_CHOICES,
            default_visibility='public',
            visibility_choices=VISIBILITY_CHOICES,
            people=[{'key': 'amy grace', 'label': 'Amy Grace'}],
            search_query='',
            active_who='',
        )
        library = self._render('sermons/library.html', is_staff=True, is_owner=True, **shared)
        self.assertNotIn('name="folder"', library)
        self.assertNotIn('How often to read Drive', library)
        self.assertIn('Message from', library)
        self.assertIn('Search messages', library)
        self.assertIn('Amy Grace', library)
        self.assertIn('name="csrf_token"', library)
        self.assertNotIn(FOLDER, library)

        owner = self._render(
            'sermons/_message_settings.html',
            is_owner=True,
            can_keep_copy=True,
            unsaved_count=1,
            **shared,
        )
        self.assertGreaterEqual(owner.count('name="csrf_token"'), 5)
        self.assertIn('name="folder"', owner)
        self.assertIn('value=""', owner)
        self.assertNotIn(FOLDER, owner)
        self.assertIn('How often to read Drive', owner)
        staff = self._render('sermons/_message_settings.html', is_owner=False, can_keep_copy=False, **shared)
        self.assertNotIn('name="folder"', staff)
        self.assertGreaterEqual(staff.count('name="csrf_token"'), 3)


class TokenTests(unittest.TestCase):
    def test_a_missing_or_forged_token_is_not_accepted(self):
        from poweredbytop.core.security import classify_csrf_token

        app = Flask(__name__)
        app.secret_key = 'sermon-attack-test'
        with app.test_request_context(
            '/sermons/library/visibility-all',
            method='POST',
            headers={'Origin': 'https://evil.example'},
        ):
            missing_ok, missing_reason, missing_meta = classify_csrf_token(None)
            forged_ok, forged_reason, _forged_meta = classify_csrf_token(POISON_LOCK)
            signed_ok, signed_reason, _signed_meta = classify_csrf_token('abc:1:deadbeef')
        self.assertFalse(missing_ok)
        self.assertEqual(missing_reason, 'missing')
        self.assertFalse(missing_meta['same_origin'])
        self.assertFalse(forged_ok)
        self.assertNotEqual(forged_reason, 'disabled')
        self.assertFalse(signed_ok)
        self.assertEqual(signed_reason, 'bad_signature')

        with app.test_request_context(
            '/sermons/library/schedule',
            method='POST',
            headers={'Origin': 'http://localhost'},
        ):
            ok, reason, meta = classify_csrf_token('   ')
        self.assertFalse(ok)
        self.assertEqual(reason, 'missing')
        self.assertTrue(meta['same_origin'])


class HostCopyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _library_app()
        cls.client = cls.app.test_client()

    def _session(self, **keys):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess.update(keys)

    def test_opening_the_library_does_not_download(self):
        with patch('app.utils.sermon_drive.pull_drive_file', side_effect=AssertionError('downloaded')), \
                patch('app.routes.sermons.drive_pages.maybe_sync'), \
                patch('app.routes.sermons.drive_pages.list_items', return_value=[_row()]), \
                patch('app.routes.sermons.drive_pages.current_refresh_hours', return_value=168), \
                patch('app.routes.sermons.drive_pages.current_default_visibility', return_value='public'), \
                patch('app.routes.sermons.drive_pages.render_template', return_value='ok'):
            self._session()
            response = self.client.get('/sermons/')
        self.assertEqual(response.status_code, 200)

    def test_a_guest_and_a_plain_member_cannot_save(self):
        saver = Mock(side_effect=AssertionError('saved'))
        with patch('app.routes.sermons.drive_pages.save_item_copy', saver), \
                patch('app.routes.sermons.drive_pages.save_next_copy', saver):
            self._session()
            guest = self.client.post('/sermons/library/7/copy', data={'drive_file_id': FILE, 'user_id': '1'})
            guest_next = self.client.post('/sermons/library/copy-next', data={'drive_file_id': FILE})
        self.assertEqual(guest.status_code, 302)
        self.assertIn('/login', guest.headers['Location'])
        self.assertEqual(guest_next.status_code, 302)
        self.assertIn('/login', guest_next.headers['Location'])
        saver.assert_not_called()

        with patch('app.routes.sermons.drive_pages.save_item_copy', saver), \
                patch('app.models.users.get_user_by_id', return_value={'id': 4, 'role': 'Member'}), \
                patch('app.models.db.get_db', return_value=Mock()), \
                patch('app.utils.permissions.user_has_permission_for_user', return_value=False):
            self._session(user_id=4, user_role='Owner')
            denied = self.client.post('/sermons/library/7/copy', data={'drive_file_id': FILE, 'user_id': '999'})
        self.assertEqual(denied.status_code, 403)
        self.assertNotIn(FILE.encode(), denied.data)
        saver.assert_not_called()

    def test_staff_can_save_and_a_member_with_sermon_permission_can(self):
        saver = Mock(return_value='saved')
        with patch('app.routes.sermons.drive_pages.save_item_copy', saver), \
                patch('app.routes.sermons.drive_pages.get_item', return_value=_row(
                    visibility='leaders', hidden=1, source_enabled=0,
                )), \
                patch('app.models.users.get_user_by_id', return_value={'id': 4, 'role': 'Staff'}), \
                patch('app.utils.permissions.user_has_permission_for_user', side_effect=AssertionError('key')):
            self._session(user_id=4, user_role='Member')
            response = self.client.post('/sermons/library/7/copy', data={
                'drive_file_id': FILE,
                'user_id': '999',
                'next': 'https://evil.example',
            })
        self.assertEqual(response.status_code, 302)
        self.assertIn('/sermons/library/7', response.headers['Location'])
        self.assertNotIn('evil.example', response.headers['Location'])
        self.assertNotIn(FILE, response.headers['Location'])
        saver.assert_called_once_with(7, 4)

        saver.reset_mock()
        saver.return_value = 'saved'
        allowed = {}

        def permit(_cur, user_id, role, key):
            allowed['user_id'] = user_id
            allowed['role'] = role
            allowed.setdefault('keys', []).append(key)
            return key == 'upload_sermons'

        with patch('app.routes.sermons.drive_pages.save_next_copy', return_value=('saved', 2)) as nxt, \
                patch('app.models.users.get_user_by_id', return_value={'id': 8, 'role': 'Member'}), \
                patch('app.models.db.get_db', return_value=Mock()), \
                patch('app.utils.permissions.user_has_permission_for_user', permit):
            self._session(user_id=8, user_role='Staff')
            response = self.client.post('/sermons/library/copy-next', data={'drive_file_id': FILE})
        self.assertEqual(response.status_code, 302)
        self.assertIn('/settings/messages', response.headers['Location'])
        self.assertNotIn(FILE, response.headers['Location'])
        nxt.assert_called_once_with(8, allowed=ANY)
        self.assertEqual(allowed['user_id'], 8)
        self.assertEqual(allowed['role'], 'Member')
        self.assertIn('upload_sermons', allowed['keys'])

    def test_a_permitted_member_saves_only_a_message_they_can_hear(self):
        saver = Mock(return_value='saved')

        def permit(_cur, user_id, role, key):
            return role == 'Member' and key == 'upload_sermons'

        with patch('app.routes.sermons.drive_pages.save_item_copy', saver), \
                patch('app.routes.sermons.drive_pages.get_item', return_value=_row()), \
                patch('app.models.users.get_user_by_id', return_value={'id': 8, 'role': 'Member'}), \
                patch('app.models.db.get_db', return_value=Mock()), \
                patch('app.utils.permissions.user_has_permission_for_user', permit):
            self._session(user_id=8, user_role='Staff')
            allowed = self.client.post('/sermons/library/7/copy', data={'drive_file_id': FILE})
        self.assertEqual(allowed.status_code, 302)
        self.assertIn('/sermons/library/7', allowed.headers['Location'])
        saver.assert_called_once_with(7, 8)

        for extra in (
            {'visibility': 'leaders'},
            {'hidden': 1},
            {'source_enabled': 0},
        ):
            saver.reset_mock()
            with patch('app.routes.sermons.drive_pages.save_item_copy', saver), \
                    patch('app.routes.sermons.drive_pages.get_item', return_value=_row(**extra)), \
                    patch('app.models.users.get_user_by_id', return_value={'id': 8, 'role': 'Member'}), \
                    patch('app.models.db.get_db', return_value=Mock()), \
                    patch('app.utils.permissions.user_has_permission_for_user', permit):
                self._session(user_id=8, user_role='Staff')
                denied = self.client.post('/sermons/library/7/copy', data={'drive_file_id': FILE})
            self.assertEqual(denied.status_code, 404)
            self.assertNotIn(FILE.encode(), denied.data)
            saver.assert_not_called()

    def test_the_next_copy_skips_a_message_the_member_cannot_hear(self):
        from app.utils.sermon_drive import first_copyable_id
        rows = [
            {'id': 1, 'visibility': 'leaders', 'hidden': 0, 'missing_on_drive': 0,
             'local_name': '', 'source_enabled': 1},
            {'id': 2, 'visibility': 'public', 'hidden': 1, 'missing_on_drive': 0,
             'local_name': '', 'source_enabled': 1},
            {'id': 3, 'visibility': 'public', 'hidden': 0, 'missing_on_drive': 0,
             'local_name': '', 'source_enabled': 0},
            {'id': 'nope', 'visibility': 'public', 'hidden': 0, 'missing_on_drive': 0,
             'local_name': '', 'source_enabled': 1},
            {'id': 4, 'visibility': 'members', 'hidden': 0, 'missing_on_drive': 0,
             'local_name': '', 'source_enabled': 1},
        ]

        def member(row):
            return can_listen(row, logged_in=True, role='Member')

        def staff(row):
            return can_listen(row, logged_in=True, role='Staff')

        self.assertEqual(first_copyable_id(rows, member), 4)
        self.assertEqual(first_copyable_id(rows, staff), 1)
        self.assertIsNone(first_copyable_id(rows[:3], member))
        self.assertEqual(first_copyable_id(rows, None), 1)

    def test_the_saved_file_plays_only_when_drive_is_missing(self):
        payload = b'ID3-local-audio'
        self._session()
        with tempfile.TemporaryDirectory() as folder:
            with open(os.path.join(folder, '7.mp3'), 'wb') as handle:
                handle.write(payload)
            os.symlink('/etc/passwd', os.path.join(folder, '8.mp3'))
            env = patch.dict(os.environ, {'SERMON_BACKUP_DIR': folder})
            with env, patch('app.routes.sermons.drive_pages.get_item', return_value=_row(
                missing_on_drive=1, local_name='7.mp3',
            )):
                played = self.client.get('/sermons/library/7/copy')
            self.assertEqual(played.status_code, 200)
            self.assertEqual(played.data, payload)
            played.close()
            self.assertNotIn(FILE.encode(), played.data)
            self.assertNotIn(folder.encode(), played.data)
            disposition = played.headers.get('Content-Disposition', '')
            self.assertIn('message.mp3', disposition)
            self.assertNotIn(FILE, disposition)
            self.assertNotIn(folder, disposition)

            with env, patch('app.routes.sermons.drive_pages.get_item', return_value=_row(
                missing_on_drive=0, local_name='7.mp3',
            )):
                still_on_drive = self.client.get('/sermons/library/7/copy')
            self.assertEqual(still_on_drive.status_code, 404)
            self.assertNotIn(payload, still_on_drive.data)

            with env, patch('app.routes.sermons.drive_pages.get_item', return_value=_row(
                visibility='members', missing_on_drive=1, local_name='7.mp3',
            )):
                guest = self.client.get('/sermons/library/7/copy')
            self.assertEqual(guest.status_code, 404)
            self.assertNotIn(payload, guest.data)

            with env, \
                    patch('app.models.users.get_user_by_id', return_value={'id': 4, 'role': 'Member'}), \
                    patch('app.routes.sermons.drive_pages.get_item', return_value=_row(
                        visibility='members', missing_on_drive=1, local_name='7.mp3',
                    )):
                self._session(user_id=4, user_role='Owner')
                member = self.client.get('/sermons/library/7/copy')
            self.assertEqual(member.status_code, 200)
            self.assertEqual(member.data, payload)
            member.close()

            with env, patch('app.routes.sermons.drive_pages.get_item', return_value=_row(
                id=8, missing_on_drive=1, local_name='8.mp3',
            )):
                escaped = self.client.get('/sermons/library/8/copy')
            self.assertEqual(escaped.status_code, 404)
            self.assertNotIn(b'root:', escaped.data)

    def test_the_player_uses_the_copy_without_the_drive_id(self):
        from app.utils.sermon_drive import REFRESH_CHOICES, VISIBILITY_CHOICES
        card = present(_row(missing_on_drive=1, local_name='7.mp3'), logged_in=False, role='')
        with patch('app.utils.helpers.get_censored_words', return_value=[]), \
                self.app.test_request_context('/sermons/library/7'):
            html = self.app.jinja_env.get_template('sermons/_listen_body.html').render(message=card)
        self.assertIn('<audio', html)
        self.assertIn('/sermons/library/7/copy', html)
        self.assertNotIn('<iframe', html)
        self.assertNotIn('export=download', html)
        self.assertNotIn(FILE, html)
        self.assertNotIn(FOLDER, html)
        self.assertNotIn('local_name', html)

        staff = present(_row(), logged_in=True, role='Staff')
        with patch('app.utils.helpers.get_censored_words', return_value=[]), \
                self.app.test_request_context('/sermons/library/7'):
            form = self.app.jinja_env.get_template('sermons/_listen_body.html').render(
                message=staff, can_keep=True,
            )
        self.assertIn('Save a copy on this server', form)
        self.assertIn('name="csrf_token"', form)
        self.assertNotIn('export=download', form)
        self.assertIn('/sermons/library/7/copy', form)

        shared = dict(
            messages=[card],
            years=[],
            active_year='',
            refresh_hours=168,
            refresh_choices=REFRESH_CHOICES,
            default_visibility='public',
            visibility_choices=VISIBILITY_CHOICES,
            can_keep_copy=True,
            unsaved_count=3,
            is_staff=True,
            is_owner=False,
        )
        with patch('app.utils.helpers.get_censored_words', return_value=[]), \
                self.app.test_request_context('/sermons/'):
            library = self.app.jinja_env.get_template('sermons/library.html').render(**shared)
            settings = self.app.jinja_env.get_template('sermons/_message_settings.html').render(**shared)
        self.assertNotIn('Save the next copy', library)
        self.assertIn('Search messages', library)
        self.assertIn('Save the next copy', settings)
        self.assertIn('3 messages still need a copy', settings)
        self.assertNotIn(FILE, library)
        self.assertNotIn(FOLDER, library)
        self.assertNotIn('export=download', library)
        self.assertNotIn(FILE, settings)
        self.assertNotIn('export=download', settings)


class FolderAndSpeakerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _library_app()
        cls.client = cls.app.test_client()

    def _session(self, **keys):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess.update(keys)

    def test_a_poison_sort_stays_on_date_order(self):
        seen = {}

        def grab(name, **kwargs):
            seen['sort'] = kwargs.get('active_sort')
            seen['url'] = kwargs.get('playlist_url') or ''
            return 'ok'

        with patch('app.routes.sermons.drive_pages.maybe_sync'), \
                patch('app.routes.sermons.drive_pages.list_items', return_value=[_row()]) as items, \
                patch('app.routes.sermons.drive_pages.current_refresh_hours', return_value=168), \
                patch('app.routes.sermons.drive_pages.current_default_visibility', return_value='public'), \
                patch('app.routes.sermons.drive_pages.render_template', grab):
            self._session()
            response = self.client.get('/sermons/?sort=%3Cscript%3Ealert(1)%3C/script%3E')
        self.assertEqual(response.status_code, 200)
        called = items.call_args
        self.assertEqual(called.args[0] if called.args else called.kwargs['sort'], 'date')
        self.assertEqual(seen['sort'], 'date')
        self.assertNotIn('script', seen['url'])
        self.assertNotIn('<script', json.dumps(seen))

        with patch('app.routes.sermons.drive_pages.maybe_sync'), \
                patch('app.routes.sermons.drive_pages.list_items', return_value=[_row()]):
            dropped = self.client.get('/sermons/library/play?sort=speaker%22%3E%3Cscript%3E')
            kept = self.client.get('/sermons/library/play?sort=speaker')
        self.assertNotIn('script', dropped.headers['Location'])
        self.assertNotIn('sort=', dropped.headers['Location'])
        self.assertIn('sort=speaker', kept.headers['Location'])
        self.assertIn('playlist=1', kept.headers['Location'])
        self.assertNotIn(FILE, kept.headers['Location'])

    def test_a_folder_name_is_saved_with_the_id_and_other_folders_stay(self):
        from app.utils.sermon_drive import list_sources, save_folder_id
        saver = Mock(return_value=True)
        with patch('app.utils.decorators.get_user_by_id', return_value={'id': 9, 'role': 'Owner'}), \
                patch('app.routes.sermons.drive_pages.save_folder_id', saver):
            self._session(user_id=9, user_role='Member')
            response = self.client.post(
                '/sermons/library/source',
                data={'folder': FOLDER, 'label': 'Guest night'},
            )
        self.assertEqual(response.status_code, 302)
        saver.assert_called_once_with(FOLDER, 'Guest night')
        self.assertNotIn(FOLDER, response.headers['Location'])

        cur = _Cursor()
        db = SimpleNamespace(cursor=lambda: cur)
        with patch('app.utils.sermon_drive.ensure_schema'), \
                patch('app.models.db.get_db', return_value=db):
            self.assertTrue(save_folder_id(FOLDER, '<script>Guest'))
        inserts = [params for sql, params in cur.calls if 'INSERT INTO sermon_drive_sources' in sql]
        self.assertEqual(inserts[0][0], FOLDER)
        self.assertIn('Guest', inserts[0][1])
        self.assertFalse(any('enabled=0' in sql.replace(' ', '') for sql, _params in cur.calls))

        listed = _Cursor(alls=[[{
            'id': 3, 'label': 'Sunday', 'enabled': 1, 'messages': 4, 'folder_id': FOLDER,
        }]])
        with patch('app.utils.sermon_drive.ensure_schema'), \
                patch('app.models.db.get_db', return_value=SimpleNamespace(cursor=lambda: listed)):
            folders = list_sources()
        self.assertEqual(folders[0]['label'], 'Sunday')
        self.assertNotIn('folder_id', folders[0])
        self.assertNotIn(FOLDER, json.dumps(folders))

    def test_bad_folder_and_speaker_ids_never_reach_the_database(self):
        from app.utils.sermon_drive import add_speaker_name, apply_visibility_to_all, save_source
        db = Mock(side_effect=AssertionError('db'))
        with patch('app.models.db.get_db', db):
            self.assertEqual(save_source('1 OR 1', 'Sunday', '1'), 'bad')
            self.assertEqual(save_source('1', '', '1'), 'bad')
            self.assertEqual(save_source('1', 'Sunday', '2'), 'bad')
            self.assertEqual(add_speaker_name('1 OR 1', 'Tim'), 'Choose a speaker from the list.')
            self.assertEqual(add_speaker_name('1', '   '), 'Type a name.')
        db.assert_not_called()

        cur = _Cursor()
        with patch('app.utils.sermon_drive.ensure_schema'), \
                patch('app.utils.sermon_drive._sources', return_value=[{'id': 1}, {'id': 2}]), \
                patch('app.models.db.get_db', return_value=SimpleNamespace(cursor=lambda: cur)):
            self.assertEqual(apply_visibility_to_all('members'), ('ok', 'members'))
        sql, params = cur.calls[-1]
        self.assertIn('s.enabled = 1', sql)
        self.assertEqual(params, ('members',))
        self.assertNotIn(FOLDER, sql)

    def test_speakers_are_staff_only_and_the_page_hides_account_mail(self):
        with patch('app.routes.sermons.drive_pages.list_speakers', side_effect=AssertionError('list')), \
                patch('app.routes.sermons.drive_pages.list_accounts', side_effect=AssertionError('accounts')):
            self._session()
            guest = self.client.get('/sermons/library/speakers')
        self.assertEqual(guest.status_code, 302)
        self.assertIn('/login', guest.headers['Location'])

        with patch('app.utils.decorators.log_change'), \
                patch('app.utils.decorators.get_user_by_id', return_value={'id': 4, 'role': 'Member'}), \
                patch('app.routes.sermons.drive_pages.create_speaker', side_effect=AssertionError('create')):
            self._session(user_id=4, user_role='Owner')
            member = self.client.post('/sermons/library/speakers', data={'action': 'create', 'speaker': 'Tim'})
        self.assertEqual(member.status_code, 403)

        people = [{
            'id': 1,
            'display_name': HOSTILE_TITLE,
            'names': ['Tim', 'Tim Lien'],
            'messages': 2,
            'account_name': '',
            'linked': False,
        }]
        with patch('app.utils.decorators.get_user_by_id', return_value={'id': 4, 'role': 'Staff'}), \
                patch('app.utils.helpers.get_censored_words', return_value=[]), \
                patch('app.routes.sermons.drive_pages.list_speakers', return_value=people), \
                patch('app.routes.sermons.drive_pages.list_accounts', return_value=[{'id': 9, 'name': 'Tim Lien'}]):
            self._session(user_id=4, user_role='Member')
            page = self.client.get('/sermons/library/speakers')
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'Tim Lien', page.data)
        self.assertIn(b'&lt;script&gt;', page.data)
        self.assertNotIn(b'<script', page.data.lower())
        self.assertNotIn(b'email', page.data.lower())
        self.assertNotIn(FOLDER.encode(), page.data)
        self.assertNotIn(b'user_id', page.data)

        db = Mock(side_effect=AssertionError('db'))
        with patch('app.utils.decorators.get_user_by_id', return_value={'id': 4, 'role': 'Staff'}), \
                patch('app.models.db.get_db', db):
            self._session(user_id=4, user_role='Member')
            bad = self.client.post('/sermons/library/speakers', data={
                'action': 'link',
                'speaker_id': '1',
                'speaker_user': '9 OR 1',
            })
        db.assert_not_called()
        self.assertEqual(bad.status_code, 302)
        self.assertIn('/sermons/library/speakers', bad.headers['Location'])
        self.assertNotIn('script', bad.headers['Location'])
        with self.client.session_transaction() as sess:
            self.assertIn('Choose a member from the list.', str(sess.get('_flashes')))

    def test_only_the_owner_can_rename_or_hide_a_folder(self):
        saver = Mock(return_value='ok')
        with patch('app.utils.decorators.log_change'), \
                patch('app.utils.decorators.get_user_by_id', return_value={'id': 4, 'role': 'Staff'}), \
                patch('app.routes.sermons.drive_pages.save_source', saver):
            self._session(user_id=4, user_role='Owner')
            staff = self.client.post('/sermons/library/source-update', data={
                'source_id': '1', 'label': 'Sunday', 'enabled': '0',
            })
        self.assertEqual(staff.status_code, 403)
        saver.assert_not_called()

        with patch('app.utils.decorators.get_user_by_id', return_value={'id': 9, 'role': 'Owner'}), \
                patch('app.routes.sermons.drive_pages.save_source', saver):
            self._session(user_id=9, user_role='Member')
            owner = self.client.post('/sermons/library/source-update', data={
                'source_id': '1', 'label': 'Sunday', 'enabled': '0', 'folder': FOLDER,
            })
        self.assertEqual(owner.status_code, 302)
        saver.assert_called_once_with('1', 'Sunday', '0')
        self.assertNotIn(FOLDER, owner.headers['Location'])

    def test_the_edit_form_offers_speakers_without_mail_or_folder_ids(self):
        captured = {}

        def grab(name, **kwargs):
            captured['name'] = name
            captured['speakers'] = kwargs['speakers']
            captured['accounts'] = kwargs['accounts']
            return 'ok'

        with patch('app.utils.decorators.get_user_by_id', return_value={'id': 4, 'role': 'Staff'}), \
                patch('app.routes.sermons.drive_pages.get_item', return_value=_row(speaker_id=1)), \
                patch('app.routes.sermons.drive_pages.list_speakers', return_value=[{
                    'id': 1, 'display_name': 'Tim', 'names': ['Tim'], 'messages': 1,
                    'account_name': '', 'linked': False,
                }]), \
                patch('app.routes.sermons.drive_pages.list_accounts', return_value=[
                    {'id': 9, 'name': 'Tim Lien'},
                ]), \
                patch('app.routes.sermons.drive_pages.render_template', grab):
            self._session(user_id=4, user_role='Member')
            response = self.client.get('/sermons/library/7/edit')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(captured['name'], 'sermons/library_edit.html')
        self.assertNotIn('user_id', captured['speakers'][0])
        self.assertNotIn('email', json.dumps(captured['accounts']))
        self.assertNotIn(FOLDER, json.dumps(captured))
        self.assertNotIn(FILE, json.dumps(captured))


class LibraryFinderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _library_app()
        cls.client = cls.app.test_client()

    def _session(self, **keys):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess.update(keys)

    def _rows(self):
        return [
            _row(id=1, title='Hope', speaker='Christopher Fuentes', scripture='John 3'),
            _row(id=2, title='Evening', speaker='Tim Lien', scripture='Psalm 23'),
            _row(id=3, title='Welcome', speaker='Leo', scripture=''),
            _row(id=4, title='Leaders night', speaker='Tim', visibility='leaders'),
        ]

    def test_message_from_is_exact_and_search_stays_on_the_card(self):
        seen = {}

        def grab(name, **kwargs):
            seen['name'] = name
            seen['titles'] = [item['title'] for item in kwargs['messages']]
            seen['who'] = kwargs.get('active_who')
            seen['people'] = [person['label'] for person in kwargs.get('people') or []]
            seen['q'] = kwargs.get('search_query')
            return 'ok'

        rows = self._rows()
        with patch('app.routes.sermons.drive_pages.maybe_sync'), \
                patch('app.routes.sermons.drive_pages.list_items', return_value=rows), \
                patch('app.routes.sermons.drive_pages.render_template', grab):
            self._session()
            one = self.client.get('/sermons/?who=christopher%20fuentes')
            self.assertEqual(one.status_code, 200)
            self.assertEqual(seen['titles'], ['Hope'])
            self.assertEqual(seen['who'], 'christopher fuentes')
            self.assertEqual(seen['people'], ['Christopher Fuentes', 'Leo', 'Tim Lien'])
            self.assertNotIn('Tim', seen['people'])

            self.client.get('/sermons/?who=tim')
            self.assertEqual(seen['titles'], ['Hope', 'Evening', 'Welcome'])
            self.assertEqual(seen['who'], '')

            self.client.get('/sermons/?q=john')
            self.assertEqual(seen['titles'], ['Hope'])
            self.assertEqual(seen['q'], 'john')
        with patch('app.utils.helpers.get_censored_words', return_value=[]), \
                self.app.test_request_context('/sermons/'):
            html = self.app.jinja_env.get_template('sermons/_library_finder.html').render(
                search_query='<script>alert(1)', people=[], is_staff=False,
            )
        self.assertNotIn('<script', html.lower())
        self.assertIn('&lt;script&gt;', html)

    def test_a_share_is_a_page_link_and_not_the_drive_file(self):
        from app.utils.sermon_drive import share_message_link

        made = Mock(return_value=3)
        with patch('app.models.social.post_throttle_message', return_value=''), \
                patch('app.models.social.create_post', made), \
                patch('app.utils.helpers.contains_censored_word', return_value=False), \
                patch('app.models.db.get_db', side_effect=AssertionError('db')):
            ok, _note = share_message_link(
                4, 7, 'Hope', 'Christopher Fuentes', 'Loved this', '/sermons/library/7',
            )
            blocked, _why = share_message_link(
                4, 7, 'Hope', 'Christopher Fuentes', 'nope',
                f'https://drive.google.com/uc?export=download&id={FILE}',
            )
        self.assertTrue(ok)
        self.assertFalse(blocked)
        made.assert_called_once()
        args = made.call_args.args
        self.assertEqual(args[4], '/sermons/library/7')
        self.assertNotIn(FILE, json.dumps(args))
        self.assertNotIn('export=download', json.dumps(args))
        self.assertNotIn('drive.google.com', json.dumps(args))

        with patch('app.models.users.get_user_by_id', return_value={'id': 4, 'role': 'Member', 'username': 'amy'}), \
                patch('app.routes.sermons.drive_pages.get_item', return_value=_row(visibility='leaders')), \
                patch('app.routes.sermons.drive_pages.share_message_link', side_effect=AssertionError('shared')):
            self._session(user_id=4, user_role='Owner')
            denied = self.client.post('/sermons/library/7/share', data={
                'note': 'hi', 'drive_file_id': FILE, 'url': 'https://evil.example',
            })
        self.assertEqual(denied.status_code, 404)
        self.assertNotIn(FILE.encode(), denied.data)

        shared = Mock(return_value=(True, 'Shared to your page. The message still plays from Drive.'))
        with patch('app.models.users.get_user_by_id', return_value={
            'id': 4, 'role': 'Member', 'username': 'amy',
        }), \
                patch('app.routes.sermons.drive_pages.get_item', return_value=_row()), \
                patch('app.routes.sermons.drive_pages.share_message_link', shared):
            self._session(user_id=4, user_role='Member')
            posted = self.client.post('/sermons/library/7/share', data={
                'note': 'Loved this', 'drive_file_id': FILE,
            })
        self.assertEqual(posted.status_code, 302)
        self.assertIn('/u/amy', posted.headers['Location'])
        self.assertNotIn(FILE, posted.headers['Location'])
        self.assertNotIn('evil.example', posted.headers['Location'])
        shared.assert_called_once()
        self.assertEqual(shared.call_args.args[5], '/sermons/library/7')
        self.assertNotIn(FILE, json.dumps(shared.call_args.args))


class ListenCounterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _library_app()
        cls.client = cls.app.test_client()

    def _session(self, **keys):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess.update(keys)

    def test_opening_the_player_counts_that_account_once(self):
        recorded = Mock(return_value=True)
        counted = Mock(return_value=3)
        captured = {}

        def grab(name, **kwargs):
            captured['listen_count'] = kwargs.get('listen_count')
            captured['message'] = kwargs.get('message')
            return 'player'

        with patch('app.models.users.get_user_by_id', return_value={'id': 4, 'role': 'Member'}), \
                patch('app.routes.sermons.drive_pages.maybe_sync'), \
                patch('app.routes.sermons.drive_pages.get_item', return_value=_row()), \
                patch('app.routes.sermons.drive_pages.drive_comment_thread', return_value=[]), \
                patch('app.routes.sermons.drive_pages.record_listen', recorded), \
                patch('app.routes.sermons.drive_pages.listen_count', counted), \
                patch('app.routes.sermons.drive_pages.render_template', grab):
            self._session(user_id=4, user_role='Owner')
            response = self.client.get('/sermons/library/7?user_id=999')
        self.assertEqual(response.status_code, 200)
        recorded.assert_called_once_with(7, 4, '127.0.0.1')
        counted.assert_called_once_with(7)
        self.assertEqual(captured['listen_count'], 3)
        self.assertNotIn('999', json.dumps(recorded.call_args.args))
        self.assertTrue(captured['message']['play_url'].endswith('/preview'))
        self.assertNotIn(FOLDER, json.dumps(captured['message']))

        recorded.reset_mock()
        counted.reset_mock()
        with patch('app.routes.sermons.drive_pages.maybe_sync'), \
                patch('app.routes.sermons.drive_pages.get_item', return_value=_row()), \
                patch('app.routes.sermons.drive_pages.drive_comment_thread', return_value=[]), \
                patch('app.routes.sermons.drive_pages.record_listen', recorded), \
                patch('app.routes.sermons.drive_pages.listen_count', counted), \
                patch('app.routes.sermons.drive_pages.render_template', grab):
            self._session()
            guest = self.client.get('/sermons/library/7?user_id=4')
        self.assertEqual(guest.status_code, 200)
        recorded.assert_called_once_with(7, None, '127.0.0.1')

        recorded.reset_mock()
        with patch('app.models.users.get_user_by_id', return_value={'id': 9, 'role': 'Staff'}), \
                patch('app.routes.sermons.drive_pages.maybe_sync'), \
                patch('app.routes.sermons.drive_pages.get_item', return_value=_row(hidden=1)), \
                patch('app.routes.sermons.drive_pages.drive_comment_thread', return_value=[]), \
                patch('app.routes.sermons.drive_pages.record_listen', recorded), \
                patch('app.routes.sermons.drive_pages.listen_count', return_value=1), \
                patch('app.routes.sermons.drive_pages.render_template', return_value='player'):
            self._session(user_id=9, user_role='Member')
            staff = self.client.get('/sermons/library/7')
        self.assertEqual(staff.status_code, 200)
        recorded.assert_called_once_with(7, 9, '127.0.0.1')

    def test_a_locked_page_does_not_count_and_the_library_does_not_record(self):
        recorded = Mock(side_effect=AssertionError('recorded'))
        with patch('app.models.users.get_user_by_id', return_value={'id': 4, 'role': 'Member'}), \
                patch('app.routes.sermons.drive_pages.maybe_sync'), \
                patch('app.routes.sermons.drive_pages.get_item', return_value=_row(visibility='leaders')), \
                patch('app.routes.sermons.drive_pages.record_listen', recorded):
            self._session(user_id=4, user_role='Owner')
            denied = self.client.get('/sermons/library/7?user_id=4')
        self.assertEqual(denied.status_code, 404)
        recorded.assert_not_called()

        recorded = Mock(side_effect=AssertionError('recorded'))
        captured = {}

        def grab(name, **kwargs):
            captured['counts'] = [item.get('listen_count') for item in kwargs['messages']]
            return 'ok'

        rows = [_row(title='Hope'), _row(id=8, title='Evening')]
        with patch('app.routes.sermons.drive_pages.maybe_sync'), \
                patch('app.routes.sermons.drive_pages.list_items', return_value=rows), \
                patch('app.routes.sermons.drive_pages.listen_counts', return_value={7: 2}), \
                patch('app.routes.sermons.drive_pages.record_listen', recorded), \
                patch('app.routes.sermons.drive_pages.render_template', grab):
            self._session()
            listed = self.client.get('/sermons/')
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(captured['counts'], [2, 0])
        recorded.assert_not_called()

    def test_the_count_is_a_number_on_the_card_and_the_player(self):
        card = present(_row(title='Hope'), logged_in=False, role='')
        card['listen_count'] = 2
        with patch('app.utils.helpers.get_censored_words', return_value=[]), \
                self.app.test_request_context('/sermons/'):
            html = self.app.jinja_env.get_template('sermons/_library_cards.html').render(
                messages=[card], years=[], active_year='',
            )
            card['listen_count'] = 1
            one = self.app.jinja_env.get_template('sermons/_library_cards.html').render(
                messages=[card], years=[], active_year='',
            )
            card['listen_count'] = 0
            quiet = self.app.jinja_env.get_template('sermons/_library_cards.html').render(
                messages=[card], years=[], active_year='',
            )
            playing = present(_row(title='Hope'), logged_in=True, role='Member')
            body = self.app.jinja_env.get_template('sermons/_listen_body.html').render(
                message=playing, listen_count=4,
            )
            first = self.app.jinja_env.get_template('sermons/_listen_body.html').render(
                message=playing, listen_count=0,
            )
        self.assertIn('2 people started listening', html)
        self.assertIn('1 person started listening', one)
        self.assertNotIn('started listening', quiet)
        self.assertIn('4 people started listening', body)
        self.assertIn('Be the first to listen', first)
        self.assertIn(f'https://drive.google.com/file/d/{FILE}/preview', body)
        self.assertNotIn('export=download', body)
        for page in (html, one, quiet, body, first):
            self.assertNotIn(FOLDER, page)
            self.assertNotIn('export=download', page)
            self.assertNotIn('listener_key', page)
        for page in (html, one, quiet):
            self.assertNotIn(FILE, page)


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


if __name__ == '__main__':
    unittest.main()
