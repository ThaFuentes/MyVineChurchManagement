"""Owner-parity checks for the church bot. No MariaDB."""

import json
import unittest
import unittest.mock

from app.utils import bot_guard as guard
from app.utils.bot_comments import reply_comment
from app.utils.bot_policy import call_map, help_payload, new_session_material, writes_blocked
from tests.test_bot_access import _Clock, hash_key


class GuardTests(unittest.TestCase):
    def test_reads_drop_secrets_and_member_passwords(self):
        clean = guard.redact({
            "name": "Pat",
            "password": "secret",
            "smtp_pass": "mail",
            "nested": {"api_key": "k", "title": "Hello"},
        })
        self.assertEqual(clean, {"name": "Pat", "nested": {"title": "Hello"}})
        member = guard.public_member({
            "id": 4,
            "email": "pat@example.com",
            "role": "Member",
            "password": "hashed",
            "checkin_pin": "1234",
        })
        self.assertEqual(member["email"], "pat@example.com")
        self.assertNotIn("password", member)
        self.assertNotIn("checkin_pin", member)

    def test_owner_self_and_role_stay_blocked(self):
        owner = guard.member_write_block({"id": 1, "role": "Owner"}, {"email": "new@example.com"}, 2)
        self.assertEqual(owner[0], "owner_protected")
        self_edit = guard.member_write_block({"id": 2, "role": "Admin"}, {"role": "Member"}, 2)
        self.assertEqual(self_edit[0], "self_edit")
        promoted = guard.member_write_block({"id": 3, "role": "Member"}, {"role": "Owner"}, 2)
        self.assertEqual(promoted[0], "owner_protected")
        bad = guard.member_write_block({"id": 3, "role": "Member"}, {"role": "Pastor"}, 2)
        self.assertEqual(bad[0], "role")
        self.assertIsNone(guard.member_write_block({"id": 3, "role": "Member"}, {"phone": "555"}, 2))

    def test_event_range_and_hard_confirm(self):
        self.assertIsNone(guard.event_range_problem("2026-10-25", "09:00", None, None))
        self.assertIn("later", guard.event_range_problem("2026-10-25", "09:00", "2026-10-24", "09:00"))
        wants, err = guard.confirm_delete({}, 8)
        self.assertFalse(wants)
        self.assertIsNone(err)
        wants, err = guard.confirm_delete({"confirm": "DELETE 7"}, 8)
        self.assertTrue(wants)
        self.assertIn("DELETE 8", err)
        wants, err = guard.confirm_delete({"confirm": "DELETE 8"}, 8)
        self.assertTrue(wants)
        self.assertIsNone(err)

    def test_a_censored_reply_is_refused_before_it_is_saved(self):
        with unittest.mock.patch(
            "app.utils.bot_comments.comment_blocked",
            return_value="That comment uses a word the church blocks.",
        ):
            out = reply_comment("post", 1, "hello", {"user_id": 2, "name": "Pat"})
        self.assertFalse(out["ok"])
        self.assertEqual(out["status"], 400)
        self.assertEqual(out["code"], "censored")

    def test_comment_rate_and_master_switch(self):
        self.assertFalse(guard.over_comment_rate(29, 30))
        self.assertTrue(guard.over_comment_rate(30, 30))
        self.assertTrue(writes_blocked({"bot_writes_off": True, "posts": True}))
        self.assertFalse(writes_blocked({"posts": True}))

    def test_help_names_the_grant_and_keeps_office_moderation(self):
        blocked = {row["path"]: row for row in call_map({}, blocked_why="admin_grant")}
        self.assertFalse(blocked["/api/bot/help"]["allowed"])
        self.assertEqual(blocked["/api/bot/members"]["why"], "admin_grant")
        office = {row["path"]: row for row in help_payload({"office": True})["calls"]}
        moderate = office["/api/bot/content/<kind>/<id>/moderate"]
        self.assertTrue(moderate["allowed"])
        self.assertNotIn("also", moderate)
        off = {row["path"]: row for row in call_map({})}
        self.assertEqual(off["/api/bot/content/<kind>/<id>/moderate"]["why"], "moderation")
        self.assertFalse(off["/api/bot/sermons/<id>/delete"]["allowed"])


class ParityRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from flask import Flask
        from app.routes.bot_access import bot_access_bp
        cls.app = Flask(__name__)
        cls.app.config["SECRET_KEY"] = "bot-parity-tests"
        cls.app.register_blueprint(bot_access_bp)

    def setUp(self):
        from app.utils import bot_store as store
        self.store = store
        self.db = _Clock()
        self.raw = "mvos_church_bot_key_test_value_123456"
        self.db.keys[1] = {
            "id": 1,
            "name": "Helper",
            "key_hash": hash_key(self.raw),
            "key_prefix": self.raw[:14],
            "active": 1,
            "controls_json": "{}",
            "created_by": 1,
            "email": "keys@example.com",
            "twofa_email": "codes@example.com",
            "twofa_hash": None,
            "twofa_expires": None,
            "twofa_attempts": 0,
            "session_hash": None,
            "session_expires": None,
            "prev_key_hash": None,
            "prev_key_expires": None,
            "created_at": self.db.now,
            "updated_at": self.db.now,
        }
        self._patch = unittest.mock.patch.object(store, "_cur", self.db.cursor)
        self._patch.start()
        self.client = self.app.test_client()

    def tearDown(self):
        self._patch.stop()
        if self.db.unhandled:
            self.fail("unhandled SQL:\n" + "\n".join(self.db.unhandled))

    def _session(self, controls):
        raw, digest, _prefix = new_session_material()
        self.assertTrue(self.store.open_session(1, digest, "vine"))
        self.db.keys[1]["controls_json"] = json.dumps(controls)
        return {"Authorization": "Bearer " + raw}

    def _owner(self):
        self.db.users[2] = {"role": "Owner"}
        self.db.voices.append({
            "id": 1,
            "key_id": 1,
            "voice_type": "user",
            "user_id": 2,
            "label": None,
            "username": "pat",
            "first_name": "Pat",
            "last_name": "Owner",
        })

    def test_sermon_switch_off_names_the_switch(self):
        header = self._session({})
        res = self.client.post("/api/bot/sermons", headers=header, json={"title": "Hope"})
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.get_json()["missing"], ["sermon_builder"])
        self.assertEqual(res.get_json()["code"], "switch_off")

    def test_sermon_remove_uses_the_shared_check(self):
        self._owner()
        header = self._session({"sermon_builder": True})
        saved = {"ok": True, "data": {"id": 9, "hidden": True}, "log": {
            "action": "bot_sermon_delete", "detail": "Hidden.", "target_type": "pastoral_sermons", "target_id": 9,
        }}
        with unittest.mock.patch("app.utils.bot_content.delete_content", return_value=saved) as remove:
            res = self.client.post("/api/bot/sermons/9/delete", headers=header, json={})
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        self.assertEqual(remove.call_args.args[0], "pastoral_sermons")
        self.assertFalse(remove.call_args.args[3])

    def test_master_switch_blocks_writes_and_leaves_reads(self):
        header = self._session({"bot_writes_off": True, "members": True})
        blocked = self.client.post("/api/bot/members", headers=header, json={"first_name": "A", "last_name": "B"})
        self.assertEqual(blocked.status_code, 423)
        self.assertEqual(blocked.get_json()["code"], "bot_writes_off")
        self.assertEqual(blocked.get_json()["missing"], ["bot_writes_off"])
        listed = {"ok": True, "data": {"members": [], "count": 0}}
        with unittest.mock.patch("app.utils.bot_members.list_members", return_value=listed):
            opened = self.client.get("/api/bot/members", headers=header)
        self.assertEqual(opened.status_code, 200, opened.get_data(as_text=True))

    def test_members_and_events_name_the_switch_or_run(self):
        closed = self._session({})
        missing = self.client.get("/api/bot/members", headers=closed)
        self.assertEqual(missing.status_code, 403)
        self.assertEqual(missing.get_json()["missing"], ["members"])
        events = self.client.post("/api/bot/events", headers=closed, json={"event_name": "Potluck"})
        self.assertEqual(events.get_json()["missing"], ["events"])
        mail = self.client.post("/api/bot/events/3/email", headers=closed, json={"subject": "Hi"})
        self.assertEqual(mail.status_code, 403)
        self.assertEqual(mail.get_json()["missing"], ["comms_send"])
        header = self._session({"members": True, "events": True})
        created = {"ok": True, "data": {"event_id": 3}, "log": {
            "action": "bot_event_create", "detail": "Potluck", "target_type": "event", "target_id": 3,
        }}
        with unittest.mock.patch("app.utils.bot_events.create_event", return_value=created) as make:
            res = self.client.post("/api/bot/events", headers=header, json={"event_name": "Potluck", "event_date": "2026-11-01"})
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        self.assertEqual(make.call_args.args[1]["event_name"], "Potluck")

    def test_post_edit_and_comment_reply(self):
        header = self._session({"posts": True, "comments": True})
        edited = {"ok": True, "data": {"post_id": 4}, "log": {
            "action": "bot_post_edit", "detail": "Hope", "target_type": "community_post", "target_id": 4,
            "snapshot": {"id": 4, "before": {"title": "Old"}, "after": {"title": "Hope"}},
        }}
        with unittest.mock.patch("app.utils.bot_content.edit_post", return_value=edited):
            res = self.client.post("/api/bot/posts/4", headers=header, json={"title": "Hope"})
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        self.assertIn("log_id", res.get_json()["data"])
        replied = {"ok": True, "data": {"comment_id": 8}, "log": {
            "action": "bot_comment_reply", "detail": "Amen", "target_type": "post_comments", "target_id": 8,
        }}
        with unittest.mock.patch("app.utils.bot_comments.reply_comment", return_value=replied) as reply:
            sent = self.client.post("/api/bot/comments/post/4", headers=header, json={"body": "Amen"})
        self.assertEqual(sent.status_code, 200, sent.get_data(as_text=True))
        self.assertEqual(reply.call_args.args[0], "post")
        for _number in range(30):
            self.db.logs.append({
                "id": 100 + _number,
                "key_id": 1,
                "action": "bot_comment_reply",
                "ok": True,
                "detail": "Amen",
                "created_at": self.db.now,
            })
        limited = self.client.post("/api/bot/comments/post/4", headers=header, json={"body": "Again"})
        self.assertEqual(limited.status_code, 429)
        self.assertEqual(limited.get_json()["code"], "rate_limit")

    def test_moderation_uses_either_switch(self):
        closed = self._session({})
        denied = self.client.post("/api/bot/content/post/4/moderate", headers=closed, json={"action": "hide"})
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(denied.get_json()["missing"], ["moderation"])
        header = self._session({"office": True})
        done = {"ok": True, "data": {"kind": "post", "id": 4, "action": "hide"}, "log": {
            "action": "bot_moderate", "detail": "hide post 4", "target_type": "community_posts", "target_id": 4,
        }}
        with unittest.mock.patch("app.utils.bot_content.moderate", return_value=done) as act:
            res = self.client.post("/api/bot/content/post/4/moderate", headers=header, json={"action": "hide"})
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        self.assertEqual(act.call_args.args[0], "post")
