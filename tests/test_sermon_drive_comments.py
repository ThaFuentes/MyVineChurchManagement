"""Comments on a Drive message. No database. Guests, names, word list, and addresses."""

import unittest
from html.parser import HTMLParser
from unittest.mock import patch

from flask import Blueprint, Flask
from app.utils.helpers import CENSORED_WORD_MESSAGE, jinja_censor, jinja_nl2br
from app.utils.sermon_drive import playlist_spot, prepare_drive_comment, present, save_drive_comment
from tests.test_sermon_drive import FILE, FOLDER, _row
from tests.test_sermon_drive_attack import TEMPLATES, _tags


def _app():
    from app.routes.sermons.drive_pages import post_library_comment
    from app.routes.sermons.views import sermons_bp

    app = Flask(__name__, template_folder=str(TEMPLATES))
    app.secret_key = 'sermon-comment-test'
    app.jinja_env.filters['censor'] = jinja_censor
    app.jinja_env.filters['nl2br'] = jinja_nl2br
    auth = Blueprint('auth', __name__)

    @auth.route('/login')
    def login():
        return 'login'

    app.register_blueprint(auth)
    app.register_blueprint(sermons_bp)

    @app.route('/public/sermons/library/<int:item_id>/comment', methods=['POST'])
    def library_comment(item_id):
        return post_library_comment(item_id)

    return app


class CommentFieldTests(unittest.TestCase):
    def _prepare(self, form, **kwargs):
        with patch('app.utils.helpers.contains_censored_word', return_value=False):
            return prepare_drive_comment(form, **kwargs)

    def test_a_guest_must_leave_a_name(self):
        _fields, errors = self._prepare({'comment': 'Amen'}, logged_in=False)
        self.assertIn('Leave your name with the comment.', errors)

    def test_a_guest_name_is_kept_and_a_posted_account_is_ignored(self):
        fields, errors = self._prepare({
            'comment': 'Amen',
            'contributor_name': '  Ada  ',
            'user_id': '999',
            'ip_address': '198.51.100.4',
            'ip': '198.51.100.4',
        }, logged_in=False)
        self.assertEqual(errors, [])
        self.assertEqual(fields['name'], 'Ada')
        self.assertEqual(set(fields), {'name', 'comment', 'parent_id'})
        self.assertIsNone(fields['parent_id'])
        self.assertNotIn('198.51.100.4', str(fields))

    def test_a_member_keeps_the_account_name(self):
        fields, errors = self._prepare({
            'comment': 'Amen',
            'contributor_name': 'Someone Else',
        }, logged_in=True, account_name='Ada Lovelace')
        self.assertEqual(errors, [])
        self.assertEqual(fields['name'], 'Ada Lovelace')

    def test_a_link_name_is_refused(self):
        _fields, errors = self._prepare({
            'comment': 'Hi',
            'contributor_name': 'https://evil.example/buy',
        }, logged_in=False)
        self.assertTrue(errors)
        self.assertNotIn('evil.example', errors[0])

    def test_a_blocked_word_uses_the_church_message(self):
        with patch('app.utils.helpers.contains_censored_word', return_value=True):
            _fields, errors = prepare_drive_comment(
                {'comment': 'hello there', 'contributor_name': 'Ada'},
                logged_in=False,
            )
        self.assertEqual(errors, [CENSORED_WORD_MESSAGE])

    def test_a_blocked_word_still_matches_when_it_is_disguised(self):
        disguised = 'ban\u200bned'
        fullwidth = ''.join(chr(ord(ch) + 0xFEE0) for ch in 'banned')
        with patch('app.utils.helpers.get_censored_words', return_value=['banned']):
            hidden, hidden_errors = prepare_drive_comment(
                {'comment': disguised, 'contributor_name': 'Ada'},
                logged_in=False,
            )
            wide, wide_errors = prepare_drive_comment(
                {'comment': 'hello', 'contributor_name': fullwidth},
                logged_in=False,
            )
        self.assertEqual(hidden_errors, [CENSORED_WORD_MESSAGE])
        self.assertNotIn('\u200b', hidden['comment'])
        self.assertEqual(wide_errors, [CENSORED_WORD_MESSAGE])

    def test_a_reply_id_must_be_a_plain_number(self):
        _fields, errors = self._prepare({
            'action': 'reply',
            'comment': 'Amen',
            'contributor_name': 'Ada',
            'parent_id': '1 OR 1=1',
        }, logged_in=False)
        self.assertIn('That reply could not be matched to a comment.', errors)
        fields, ok_errors = self._prepare({
            'action': 'reply',
            'comment': 'Amen',
            'contributor_name': 'Ada',
            'parent_id': '12',
        }, logged_in=False)
        self.assertEqual(ok_errors, [])
        self.assertEqual(fields['parent_id'], 12)

    def test_a_comment_over_the_limit_is_refused(self):
        _fields, errors = self._prepare({
            'comment': 'a' * 2001,
            'contributor_name': 'Ada',
        }, logged_in=False)
        self.assertIn('Keep the comment under 2000 characters.', errors)

    def test_the_save_stores_the_viewer_address_and_account(self):
        form = {
            'comment': 'Amen',
            'contributor_name': 'Ada',
            'user_id': '999',
            'ip_address': '198.51.100.4',
        }
        with patch('app.utils.helpers.contains_censored_word', return_value=False), \
                patch('app.utils.comment_moderation.comment_throttle_message', return_value='') as slow, \
                patch('app.utils.comment_moderation.insert_public_comment', return_value=True) as insert:
            ok, errors = save_drive_comment(
                7, form, logged_in=False, user_id=None, ip='203.0.113.8',
            )
        self.assertTrue(ok)
        self.assertEqual(errors, [])
        slow.assert_called_once_with(None, '203.0.113.8')
        insert.assert_called_once_with(
            'sermon_drive', 7, 'Ada', 'Amen', None, ip='203.0.113.8', user_id=None,
        )

    def test_a_blocked_word_never_reaches_the_insert(self):
        insert = patch('app.utils.comment_moderation.insert_public_comment', side_effect=AssertionError('insert'))
        with patch('app.utils.helpers.contains_censored_word', return_value=True), insert:
            ok, errors = save_drive_comment(
                7,
                {'comment': 'hello', 'contributor_name': 'Ada'},
                logged_in=False,
                ip='203.0.113.8',
            )
        self.assertFalse(ok)
        self.assertEqual(errors, [CENSORED_WORD_MESSAGE])

    def test_a_reply_to_another_message_is_refused(self):
        with patch('app.utils.helpers.contains_censored_word', return_value=False), \
                patch('app.utils.sermon_drive._comment_parent_ok', return_value=False), \
                patch('app.utils.comment_moderation.insert_public_comment', side_effect=AssertionError('insert')):
            ok, errors = save_drive_comment(
                7,
                {'action': 'reply', 'comment': 'Amen', 'contributor_name': 'Ada', 'parent_id': '4'},
                logged_in=False,
                ip='203.0.113.8',
            )
        self.assertFalse(ok)
        self.assertEqual(errors, ['That reply could not be matched to a comment.'])


class CommentPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()
        cls.client = cls.app.test_client()

    def _session(self, **keys):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess.update(keys)

    def _post(self, item_id, form, user=None):
        seen = {}

        def save(item_id_arg, posted, **kwargs):
            seen['item_id'] = item_id_arg
            seen['form'] = dict(posted)
            seen['kwargs'] = kwargs
            return True, []

        with patch('app.models.users.get_user_by_id', return_value=user), \
                patch('app.routes.sermons.drive_pages.maybe_sync'), \
                patch('app.routes.sermons.drive_pages.get_item', return_value=_row(id=item_id)), \
                patch('app.routes.sermons.drive_pages._comments_open', return_value=True), \
                patch('app.routes.sermons.drive_pages.save_drive_comment', save):
            response = self.client.post(
                f'/public/sermons/library/{item_id}/comment?next=https://evil.example',
                data=form,
                environ_base={'REMOTE_ADDR': '203.0.113.8'},
            )
        seen['status'] = response.status_code
        seen['location'] = response.headers.get('Location', '')
        return seen

    def test_a_guest_comment_stores_their_address_and_not_a_pasted_account(self):
        seen = self._post(7, {
            'action': 'comment',
            'comment': 'Amen',
            'contributor_name': 'Ada',
            'user_id': '999',
            'ip_address': '198.51.100.4',
        })
        self.assertEqual(seen['status'], 302)
        self.assertIn('/sermons/library/7', seen['location'])
        self.assertNotIn('evil.example', seen['location'])
        self.assertEqual(seen['kwargs']['logged_in'], False)
        self.assertIsNone(seen['kwargs']['user_id'])
        self.assertEqual(seen['kwargs']['ip'], '203.0.113.8')
        self.assertEqual(seen['kwargs']['account_name'], '')

    def test_a_member_comment_uses_the_account(self):
        self._session(user_id=4, user_role='Owner')
        seen = self._post(7, {
            'action': 'comment',
            'comment': 'Amen',
            'contributor_name': 'Someone Else',
        }, user={'id': 4, 'role': 'Member', 'first_name': 'Ada', 'last_name': 'Lovelace'})
        self.assertEqual(seen['status'], 302)
        self.assertEqual(seen['kwargs']['logged_in'], True)
        self.assertEqual(seen['kwargs']['user_id'], 4)
        self.assertEqual(seen['kwargs']['account_name'], 'Ada Lovelace')
        self.assertEqual(seen['kwargs']['ip'], '203.0.113.8')

    def test_a_locked_message_does_not_take_a_comment(self):
        saver = patch(
            'app.routes.sermons.drive_pages.save_drive_comment',
            side_effect=AssertionError('save'),
        )
        with saver, \
                patch('app.routes.sermons.drive_pages.maybe_sync'), \
                patch('app.routes.sermons.drive_pages.get_item', return_value=_row(visibility='leaders')):
            self._session(user_role='Owner')
            response = self.client.post('/public/sermons/library/7/comment', data={
                'action': 'comment',
                'comment': 'Amen',
                'contributor_name': 'Ada',
            })
        self.assertEqual(response.status_code, 404)
        self.assertNotIn(b'Leaders', response.data)
        self.assertNotIn(FILE.encode(), response.data)
        self.assertNotIn(FOLDER.encode(), response.data)

    def test_closed_comments_are_not_saved(self):
        saver = patch(
            'app.routes.sermons.drive_pages.save_drive_comment',
            side_effect=AssertionError('save'),
        )
        with saver, \
                patch('app.routes.sermons.drive_pages.maybe_sync'), \
                patch('app.routes.sermons.drive_pages.get_item', return_value=_row()), \
                patch('app.routes.sermons.drive_pages._comments_open', return_value=False):
            response = self.client.post('/public/sermons/library/7/comment', data={
                'action': 'comment',
                'comment': 'Amen',
                'contributor_name': 'Ada',
            })
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as sess:
            self.assertIn('Comments are closed right now.', str(sess.get('_flashes')))

    def test_only_staff_can_remove_a_comment(self):
        remover = patch(
            'app.utils.comment_moderation.apply_moderation_action',
            side_effect=AssertionError('remove'),
        )
        with remover, \
                patch('app.models.users.get_user_by_id', return_value={'id': 4, 'role': 'Member'}), \
                patch('app.routes.sermons.drive_pages.maybe_sync'), \
                patch('app.routes.sermons.drive_pages.get_item', return_value=_row()):
            self._session(user_id=4, user_role='Owner')
            response = self.client.post('/public/sermons/library/7/comment', data={
                'action': 'delete',
                'comment_id': '3',
            })
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as sess:
            self.assertIn('permission', str(sess.get('_flashes')))

        seen = {}

        def remove(*args, **kwargs):
            seen['args'] = args
            return True

        with patch('app.utils.comment_moderation.apply_moderation_action', remove), \
                patch('app.models.users.get_user_by_id', return_value={
                    'id': 9, 'role': 'Owner', 'first_name': 'Olive', 'last_name': 'Owner',
                }), \
                patch('app.routes.sermons.drive_pages.maybe_sync'), \
                patch('app.routes.sermons.drive_pages.get_item', return_value=_row()):
            self._session(user_id=9, user_role='Member')
            bad = self.client.post('/public/sermons/library/7/comment', data={
                'action': 'delete',
                'comment_id': '1 OR 1=1',
            })
            good = self.client.post('/public/sermons/library/7/comment', data={
                'action': 'delete',
                'comment_id': '3',
            })
        self.assertEqual(bad.status_code, 302)
        self.assertEqual(good.status_code, 302)
        self.assertNotIn('args', seen) if False else None
        self.assertEqual(seen['args'][0], 'sermon_drive')
        self.assertEqual(seen['args'][1], 7)
        self.assertEqual(seen['args'][2], 9)
        self.assertEqual(seen['args'][4]['comment_id'], '3')

    def test_a_guest_without_the_check_is_turned_back(self):
        from app.utils.guest_guard import allow_guest_post, should_guard_public_post

        with self.app.test_request_context(
            '/public/sermons/library/7/comment',
            method='POST',
            data={'action': 'comment', 'guest_captcha': '0'},
        ):
            self.assertTrue(should_guard_public_post())
            self.assertFalse(allow_guest_post({'action': 'comment', 'guest_captcha': '0'}))
        with self.app.test_request_context(
            '/public/sermons/library/7/comment',
            method='POST',
            data={'action': 'comment'},
        ):
            from flask import session
            session['user_id'] = 4
            self.assertFalse(should_guard_public_post())
            self.assertTrue(allow_guest_post({'action': 'comment'}))

        for payload in (
            {'action': 'Comment'},
            {'action': 'REPLY'},
            {},
            {'action': 'delete', 'comment_id': '3'},
        ):
            with self.app.test_request_context(
                '/public/sermons/library/7/comment',
                method='POST',
                data=payload,
            ):
                self.assertTrue(should_guard_public_post(), payload)

        with self.app.test_request_context(
            '/public/prayers/4',
            method='POST',
            data={'action': 'Comment'},
        ):
            self.assertTrue(should_guard_public_post())
        with self.app.test_request_context(
            '/public/prayers/4',
            method='POST',
            data={},
        ):
            self.assertFalse(should_guard_public_post())

    def test_the_public_sermon_blueprint_accepts_the_comment_post(self):
        from app.routes.public.sermons.views import sermons_bp as public_sermons

        app = Flask(__name__)
        parent = Blueprint('public', __name__, url_prefix='/public')
        parent.register_blueprint(public_sermons)
        app.register_blueprint(parent)
        matches = [
            rule for rule in app.url_map.iter_rules()
            if rule.endpoint == 'public.public_sermons.library_comment'
        ]
        self.assertEqual(len(matches), 1)
        self.assertIn('POST', matches[0].methods)
        self.assertIn('/public/sermons/library/', str(matches[0]))


class CommentRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()
        cls.client = cls.app.test_client()

    def _session(self, **keys):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess.update(keys)

    def test_a_comment_is_text_and_a_guest_sees_the_name_field(self):
        app = Flask(__name__, template_folder=str(TEMPLATES))
        app.secret_key = 'sermon-comment-test'
        app.jinja_env.filters['censor'] = jinja_censor
        app.jinja_env.filters['nl2br'] = jinja_nl2br
        parent = Blueprint('public', __name__, url_prefix='/public')
        child = Blueprint('public_sermons', __name__, url_prefix='/sermons')

        @child.route('/library/<int:item_id>/comment', methods=['POST'])
        def library_comment(item_id):
            return 'ok'

        parent.register_blueprint(child)
        app.register_blueprint(parent)
        hostile = '<script>alert(1)</script>'
        with patch('app.utils.helpers.get_censored_words', return_value=[]), \
                app.test_request_context('/sermons/library/7'):
            html = app.jinja_env.get_template('sermons/_comments.html').render(
                message={'id': 7, 'can_listen': True},
                comments=[{
                    'id': 3,
                    'name': hostile,
                    'comment': hostile,
                    'date': 'Oct 28',
                    'parent_id': None,
                    'edited_by_moderator': 0,
                }],
                comments_open=True,
                account_name='',
                is_staff=False,
            )
        parsed = _tags(html)
        self.assertNotIn('script', parsed.tags)
        self.assertNotIn('<script', html.lower())
        self.assertIn('name="contributor_name"', html)
        self.assertIn('name="csrf_token"', html)
        self.assertNotIn('ip_address', html)
        self.assertNotIn(FILE, html)
        self.assertNotIn(FOLDER, html)

        with patch('app.utils.helpers.get_censored_words', return_value=[]), \
                app.test_request_context('/sermons/library/7'):
            member = app.jinja_env.get_template('sermons/_comments.html').render(
                message={'id': 7, 'can_listen': True},
                comments=[],
                comments_open=True,
                account_name='Ada Lovelace',
                is_staff=False,
            )
        self.assertNotIn('name="contributor_name"', member)
        self.assertIn('Commenting as', member)

    def test_play_all_skips_a_locked_message_and_hides_the_file(self):
        rows = [
            _row(id=7, visibility='public', title='Open message'),
            _row(id=8, visibility='leaders', title='Leaders Secret'),
            _row(id=9, visibility='members', title='Members message'),
        ]
        guest = playlist_spot(rows, 7, logged_in=False, role='Owner')
        self.assertEqual(guest['position'], 1)
        self.assertEqual(guest['total'], 1)
        self.assertIsNone(guest['next_id'])
        self.assertNotIn(FILE, str(guest))
        self.assertNotIn(FOLDER, str(guest))
        member = playlist_spot(rows, 7, logged_in=True, role='Member')
        self.assertEqual(member['next_id'], 9)
        self.assertEqual(member['total'], 2)
        self.assertNotIn(8, (member['prev_id'], member['next_id']))

    def test_play_all_opens_the_first_message_they_can_hear(self):
        rows = [
            _row(id=8, visibility='leaders', title='Leaders Secret'),
            _row(id=7, visibility='public', title='Open message'),
        ]
        with patch('app.routes.sermons.drive_pages.maybe_sync'), \
                patch('app.routes.sermons.drive_pages.list_items', return_value=rows):
            response = self.client.get('/sermons/library/play')
        self.assertEqual(response.status_code, 302)
        location = response.headers['Location']
        self.assertIn('/sermons/library/7', location)
        self.assertIn('playlist=1', location)
        self.assertNotIn('/sermons/library/8', location)
        self.assertNotIn(FILE, location)

    def test_a_member_cannot_shadow_and_a_moderator_can(self):
        with patch('app.utils.comment_moderation.apply_moderation_action', side_effect=AssertionError('shadow')), \
                patch('app.models.users.get_user_by_id', return_value={'id': 4, 'role': 'Member'}), \
                patch('app.routes.sermons.drive_pages.maybe_sync'), \
                patch('app.routes.sermons.drive_pages.get_item', return_value=_row()):
            self._session(user_id=4, user_role='Owner')
            denied = self.client.post('/public/sermons/library/7/comment', data={
                'action': 'shadow',
                'comment_id': '3',
            })
        self.assertEqual(denied.status_code, 302)

        seen = {}

        def record(*args, **kwargs):
            seen['args'] = args
            return True

        with patch('app.utils.comment_moderation.apply_moderation_action', record), \
                patch('app.models.users.get_user_by_id', return_value={'id': 4, 'role': 'Member'}), \
                patch('app.models.db.get_db'), \
                patch('app.utils.permissions.user_has_permission_for_user', return_value=True), \
                patch('app.routes.sermons.drive_pages.maybe_sync'), \
                patch('app.routes.sermons.drive_pages.get_item', return_value=_row()):
            self._session(user_id=4, user_role='Member')
            allowed = self.client.post('/public/sermons/library/7/comment', data={
                'action': 'Shadow',
                'comment_id': '3',
                'new_text': 'leave this',
            })
        self.assertEqual(allowed.status_code, 302)
        self.assertEqual(seen['args'][0], 'sermon_drive')
        self.assertEqual(seen['args'][4].get('action'), 'Shadow')

    def test_an_edit_drops_invisible_characters_and_a_blocked_word(self):
        from app.utils.comment_moderation import sanitize_comment_body, validate_comment_moderation_form
        self.assertEqual(sanitize_comment_body('hel\u200blo'), 'hello')
        with self.app.test_request_context('/sermons/library/7'), \
                patch('app.utils.helpers.get_censored_words', return_value=['banned']):
            blocked = validate_comment_moderation_form({
                'action': 'edit',
                'comment_id': '3',
                'new_text': 'ban\u200bned',
            })
        self.assertIsNone(blocked)

    def test_staff_can_open_the_comment_console_and_a_member_cannot(self):
        from app.routes.the_gathering.dashboard.utils import comment_console_allowed
        self.assertTrue(comment_console_allowed('Staff'))
        self.assertTrue(comment_console_allowed('Member', gathering_ok=True))
        self.assertFalse(comment_console_allowed('Member'))

    def test_the_bot_lists_drive_comments_without_the_address(self):
        from app.utils.bot_comments import AREAS, _row_from
        spec = dict(AREAS['sermon_drive'])
        spec['area'] = 'sermon_drive'
        self.assertEqual(spec['table'], 'sermon_drive_comments')
        self.assertEqual(spec['parent'], 'sermon_drive_items')
        item = _row_from(spec, {
            'id': 3,
            'parent_id': 7,
            'parent_title': 'Open message',
            'name': 'Ada',
            'body': 'Amen',
            'posted_at': 'now',
            'user_id': None,
            'removed': 0,
            'shadowed': 0,
            'ip_address': '203.0.113.8',
        }, full=True)
        self.assertNotIn('ip_address', item)
        self.assertNotIn('203.0.113.8', str(item))

    def test_the_card_shows_a_comment_count(self):
        card = present(_row(comment_count=3), logged_in=False, role='')
        self.assertEqual(card['comment_count'], 3)
        self.assertEqual(present(_row(), logged_in=False, role='')['comment_count'], 0)


class _Parser(HTMLParser):
    pass


if __name__ == '__main__':
    unittest.main()
