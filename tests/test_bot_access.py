"""Rules for the church bot. No database."""

import unittest
import unittest.mock

from app.utils.bot_comments import AREAS as COMMENT_AREAS
from app.utils.bot_comments import area_names
from app.utils.bot_policy import (
    CLOSED,
    READ_ABOUT,
    READS,
    SWITCHES,
    default_controls,
    hash_key,
    help_payload,
    new_key_material,
    normalize_controls,
    assigned_people,
    office_blocked,
    church_save,
    resolve_bot_post,
    resolve_sermon_user,
    resolve_voice,
    switch_on,
    undo_label,
    undo_plan,
    validate_post,
)
from app.utils.bot_sermon_common import may_see_illustration_notes, visible_sermon_filter
from app.utils.bot_sermons import as_html, assignments_with_speaker, verse_span


class BotPolicyTests(unittest.TestCase):
    def test_switches_start_off(self):
        controls = default_controls()
        self.assertTrue(controls)
        self.assertFalse(any(controls.values()))
        self.assertEqual(set(controls), {row["id"] for row in SWITCHES})

    def test_unknown_switch_is_dropped(self):
        controls = normalize_controls({"posts": True, "passwords": True, "child_checkin": 1})
        self.assertTrue(controls["posts"])
        self.assertNotIn("passwords", controls)
        self.assertNotIn("child_checkin", controls)
        self.assertFalse(controls["security"])

    def test_church_voice_needs_an_author_and_a_grant(self):
        missing, err = resolve_voice("church", [])
        self.assertIsNone(missing)
        self.assertIn("church", err)
        bare, err = resolve_voice("church", [{"voice_type": "church", "user_id": None}])
        self.assertIsNone(bare)
        self.assertIn("author", err)
        voice, err = resolve_voice("church", [{"voice_type": "church", "user_id": 4}])
        self.assertIsNone(err)
        self.assertEqual(voice["posted_as"], "church")
        self.assertEqual(voice["user_id"], 4)

    def test_several_people_and_the_church_can_be_attached(self):
        voices = [
            {"voice_type": "church", "user_id": 2},
            {"voice_type": "user", "user_id": 8},
            {"voice_type": "user", "user_id": 9},
        ]
        church, _err = resolve_voice("church", voices)
        one, _err = resolve_voice("user:8", voices)
        other, err = resolve_voice("user:3", voices)
        self.assertEqual(church["as"], "church")
        self.assertEqual(one["posted_as"], "member")
        self.assertEqual(one["user_id"], 8)
        self.assertIsNone(other)
        self.assertIn("cannot post as that person", err)

    def test_sermon_builder_uses_the_assigned_person(self):
        voices = [
            {"voice_type": "church", "user_id": 2},
            {"voice_type": "user", "user_id": 8},
        ]
        person, err = resolve_sermon_user(None, voices, 1)
        self.assertIsNone(err)
        self.assertEqual(person["user_id"], 8)
        self.assertEqual(person["as"], "user:8")
        self.assertEqual(assigned_people(voices), [8])
        church, err = resolve_sermon_user("church", voices, 1)
        self.assertIsNone(church)
        self.assertIn("church wall", err)
        other, err = resolve_sermon_user("user:3", voices, 1)
        self.assertIsNone(other)
        self.assertIn("only as the account", err)
        named, err = resolve_sermon_user("user:8", voices, 1)
        self.assertIsNone(err)
        self.assertEqual(named["user_id"], 8)

    def test_owner_picks_one_account_and_an_admin_stays_that_admin(self):
        many = [
            {"voice_type": "user", "user_id": 8},
            {"voice_type": "user", "user_id": 9},
        ]
        person, err = resolve_sermon_user("user:9", many, 1)
        self.assertIsNone(person)
        self.assertIn("one account", err)
        untouched, err = resolve_sermon_user(None, [{"voice_type": "church", "user_id": 2}], 419)
        self.assertIsNone(untouched)
        self.assertIn("has not chosen", err)
        voices = [
            {"voice_type": "user", "user_id": 4},
            {"voice_type": "church", "user_id": 1},
        ]
        blocked, err = resolve_sermon_user(None, voices, 1, role="Admin", admin_granted=False)
        self.assertIsNone(blocked)
        self.assertIn("not allowed", err)
        allowed, err = resolve_sermon_user(None, voices, 1, role="Admin", admin_granted=True)
        self.assertEqual(allowed["user_id"], 4)
        church, err = resolve_bot_post("church", voices, role="Admin", admin_granted=True)
        self.assertIsNone(err)
        self.assertEqual(church["as"], "church")
        self.assertEqual(church["user_id"], 1)
        missing, err = resolve_bot_post("church", [{"voice_type": "user", "user_id": 4}], role="Admin", admin_granted=True)
        self.assertIsNone(missing)
        self.assertIn("church", err.lower())
        staff, err = resolve_bot_post("church", voices, role="Member", admin_granted=True)
        self.assertIsNone(staff)
        self.assertIn("church", err.lower())
        other, err = resolve_bot_post("user:1", voices, role="Admin", admin_granted=True)
        self.assertIsNone(other)
        self.assertIn("only as the account", err)
        own, err = resolve_bot_post("", voices, role="Admin", admin_granted=True)
        self.assertEqual(own["user_id"], 4)
        self.assertEqual(own["posted_as"], "member")
        wall, err = resolve_bot_post("church", voices, role="Owner", admin_granted=True)
        self.assertIsNone(err)
        self.assertEqual(wall["as"], "church")
        self.assertIn("not allowed", office_blocked("Admin", False))
        self.assertIsNone(office_blocked("Admin", True))
        self.assertIsNone(office_blocked("Owner", False))
        self.assertIn("only for an owner", office_blocked("Staff", True))
        frag, params = visible_sermon_filter(8)
        self.assertIn("created_by = %s", frag)
        self.assertEqual(params[:2], [8, 8])
        self.assertFalse(may_see_illustration_notes(8, 3, staff=False))
        self.assertTrue(may_see_illustration_notes(8, 8, staff=False))
        self.assertTrue(may_see_illustration_notes(1, 3, staff=True))

    def test_church_author_stays_when_the_owner_is_chosen(self):
        kept, author, note = church_save("Admin", "Owner", 4, 1, False, None)
        self.assertTrue(kept)
        self.assertEqual(author, 1)
        self.assertIsNone(note)
        kept, author, note = church_save("Owner", None, 1, None, True, None)
        self.assertTrue(kept)
        self.assertEqual(author, 1)
        self.assertIsNone(note)
        kept, author, note = church_save("Admin", None, 4, None, True, None)
        self.assertFalse(kept)
        self.assertIsNone(author)
        self.assertIn("owner", note)
        kept, author, note = church_save("Admin", "Member", 4, 8, True, None)
        self.assertFalse(kept)
        self.assertIn("owner", note)
        kept, author, note = church_save("Owner", "Member", 1, 8, True, None)
        self.assertTrue(kept)
        self.assertEqual(author, 8)

    def test_verse_needs_a_body_and_reverse_is_soft(self):
        bad, err = validate_post("verse", "Psalm 23", "", "public")
        self.assertIsNone(bad)
        self.assertIn("body", err)
        good, err = validate_post("verse", "", "The Lord is my shepherd.", "nope")
        self.assertIsNone(err)
        self.assertEqual(good["kind"], "verse")
        self.assertEqual(good["title"], "Verse")
        self.assertEqual(good["visibility"], "public")
        self.assertEqual(undo_plan("post.create", False), "hide")
        self.assertEqual(undo_plan("post.create", True), "show")
        self.assertIsNone(undo_plan("denied", False))

    def test_help_lists_live_calls_and_keeps_secrets_out(self):
        payload = help_payload({"posts": True, "security": False}, [
            {"voice_type": "church", "user_id": 2, "label": "Church"},
            {"voice_type": "user", "user_id": 8, "label": "Ada"},
        ])
        text = "\n".join(payload["lines"])
        self.assertIn("GET /api/bot/help", text)
        self.assertIn("POST /api/bot/posts", text)
        self.assertIn("GET /api/bot/security", text)
        self.assertIn("GET /api/bot/read/members", text)
        self.assertIn("[on]", text)
        self.assertIn("[off]", text)
        self.assertEqual(payload["voices"][0]["as"], "church")
        self.assertEqual(payload["voices"][1]["as"], "user:8")
        joined = " ".join(payload["closed"])
        self.assertIn("check-in", joined)
        self.assertIn("Deleting", joined)
        for sql in READS.values():
            lowered = sql.lower()
            self.assertTrue(lowered.startswith("select "))
            self.assertIn("limit %s", lowered)
            self.assertNotIn("password", lowered)
            self.assertNotIn("checkin_pin", lowered)
            self.assertNotIn("account_number", lowered)
            self.assertNotIn("encrypted_", lowered)
        read_ids = {row["id"] for row in SWITCHES if row["kind"] == "read"}
        self.assertEqual(read_ids, set(READS))

    def test_key_material_and_reverse_needs_no_switch(self):
        raw, digest, prefix = new_key_material()
        self.assertTrue(raw.startswith("mvos_"))
        self.assertEqual(digest, hash_key(raw))
        self.assertEqual(prefix, raw[:14])
        self.assertTrue(switch_on({"posts": "on"}, "posts"))
        calls = {row["path"]: row for row in help_payload({})["calls"]}
        self.assertIsNone(calls["/api/bot/reverse"]["switch"])
        self.assertTrue(calls["/api/bot/reverse"]["allowed"])
        self.assertFalse(calls["/api/bot/posts"]["allowed"])

    def test_pipeline_lets_the_bot_through_without_replacing_csrf(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        security = (root / "poweredbytop" / "core" / "security.py").read_text()
        store = (root / "app" / "utils" / "bot_store.py").read_text()
        self.assertIn('path.startswith("/api/bot/")', security)
        self.assertIn("CSRF_PROTECTION", security)
        self.assertIn("removed_at", store)
        self.assertNotIn("delete_post", store)
        self.assertNotIn("DELETE FROM community_posts", store)
        self.assertTrue(CLOSED)

    def test_sermon_desk_undo_and_calls(self):
        self.assertFalse(default_controls()["sermon_builder"])
        self.assertEqual(undo_plan("sermon.create", False), "hide")
        self.assertEqual(undo_plan("sermon.create", True), "show")
        self.assertEqual(undo_plan("sermon.update", False), "restore")
        self.assertEqual(undo_plan("sermon.update", True), "reapply")
        self.assertEqual(undo_plan("section.add", False), "hide")
        self.assertEqual(undo_plan("illustration.hide", False), "hide")
        self.assertEqual(undo_plan("illustration.hide", True), "show")
        self.assertEqual(undo_plan("sermon.hide", False), "hide")
        self.assertEqual(undo_plan("section.hide", False), "hide")
        self.assertEqual(undo_plan("section.reorder", False), "restore")
        self.assertEqual(undo_plan("section.reorder", True), "reapply")
        self.assertIsNone(undo_plan("illustration.download", False))
        self.assertEqual(undo_plan("lineup.set", False), "restore")
        self.assertEqual(undo_label("lineup.set", False), "Undo")
        self.assertEqual(undo_label("lineup.set", True), "Redo")
        self.assertEqual(undo_label("sermon.create", False), "Hide")
        off = "\n".join(help_payload({})["lines"])
        on = "\n".join(help_payload({"sermon_builder": True})["lines"])
        for path in (
            "GET /api/bot/sermons",
            "POST /api/bot/sermons",
            "POST /api/bot/illustrations",
            "POST /api/bot/illustrations/<id>/hide",
            "GET /api/bot/illustrations/<id>/download",
            "POST /api/bot/sermons/<id>/hide",
            "POST /api/bot/sermons/<id>/sections/reorder",
            "GET /api/bot/vault",
            "GET /api/bot/verses",
            "GET /api/bot/lineup",
            "POST /api/bot/lineup",
        ):
            self.assertIn(path, on)
        self.assertIn("GET /api/bot/sermons [off]", off)
        self.assertIn("GET /api/bot/sermons [on]", on)
        self.assertIn("the owner chose", on)
        self.assertNotIn("more than one person", on)
        self.assertIn("GET /api/bot/comments [off]", off)
        self.assertIn("GET /api/bot/desks [off]", off)
        self.assertIn("GET /api/bot/groups [off]", off)
        self.assertIn("POST /api/bot/worship/team [off]", off)
        self.assertIn("POST /api/bot/donations [off]", off)
        self.assertIn("POST /api/bot/attendance [off]", off)
        office_on = "\n".join(help_payload({"office": True})["lines"])
        self.assertIn("POST /api/bot/groups/<id>/members [on]", office_on)
        self.assertIn("POST /api/bot/accounting/expenses [on]", office_on)
        self.assertIn("GET /api/bot/desk/<area> [on]", office_on)
        self.assertIn("remove=true", office_on)
        self.assertIn("worship lyrics", office_on)
        self.assertEqual(undo_plan("desk.update", False), "restore")
        self.assertEqual(undo_plan("desk.hide", True), "reapply")
        self.assertIsNone(undo_plan("desk.create", False))
        self.assertFalse(default_controls()["comments"])
        self.assertFalse(default_controls()["office"])
        self.assertEqual(undo_plan("group.role", False), "restore")
        self.assertEqual(undo_plan("group.remove", True), "reapply")
        self.assertEqual(undo_plan("worship.defaults", False), "restore")
        self.assertEqual(undo_plan("attendance.checkin", False), "restore")
        self.assertEqual(undo_plan("bill.update", True), "reapply")
        self.assertIsNone(undo_plan("donation.create", False))
        self.assertIsNone(undo_plan("expense.create", False))
        self.assertIsNone(undo_plan("worship.song", False))
        self.assertEqual(
            set(area_names()),
            {"event", "sermon", "prayer", "dream", "prophecy", "announcement", "photo", "post", "ticket"},
        )
        for spec in COMMENT_AREAS.values():
            self.assertNotIn("ip", spec["text_col"])
            self.assertNotIn("password", spec["table"])
        self.assertEqual(as_html("John 3:16"), "<p>John 3:16</p>")
        self.assertIn("&lt;script&gt;", as_html("<script>alert(1)</script>"))
        self.assertTrue(as_html("<p>Already</p>").startswith("<p>Already"))
        self.assertEqual(verse_span(30, 28), (28, 30))
        self.assertIsNone(verse_span(1, 41))
        roles = assignments_with_speaker(
            [
                {"role_name": "Minister", "user_id": 2, "guest_name": None},
                {"role_name": "Greeter", "user_id": 5, "guest_name": "Pat"},
            ],
            9,
            "Guest Pat",
            True,
        )
        self.assertEqual(roles[0]["user_id"], 9)
        self.assertIsNone(roles[0]["guest_name"])
        self.assertEqual(roles[1]["user_id"], 5)
        added = assignments_with_speaker(
            [{"role_name": "Greeter", "user_id": 5, "guest_name": None}],
            None,
            "Pat",
            True,
        )
        self.assertEqual(added[-1]["role_name"], "Minister")
        self.assertEqual(added[-1]["guest_name"], "Pat")
        self.assertIsNone(added[-1]["user_id"])

    def test_two_inboxes_and_mail_stay_apart(self):
        from app.utils.bot_login import api_mail_problem, twofa_mail_problem
        from app.utils.bot_policy import (
            TWOFA_TTL_SECONDS,
            api_key_mail,
            inbox_problem,
            new_session_material,
            new_twofa_material,
            twofa_key_mail,
        )
        self.assertIn("different", inbox_problem("a@b.co", "a@b.co"))
        self.assertIn("API key", inbox_problem("nope", "two@example.com"))
        self.assertIsNone(inbox_problem("keys@example.com", "codes@example.com"))
        subject, body = api_key_mail("Helper", "mvos_testkey", "https://myvinechurch.online")
        self.assertIn("API key", subject)
        self.assertIn("api_key: mvos_testkey", body)
        self.assertIn("expires: never", body)
        self.assertNotIn("twofa_key:", body)
        self.assertNotIn("codes@example.com", body)
        self.assertIsNone(api_mail_problem(body, "codes@example.com"))
        raw, digest, prefix = new_twofa_material()
        self.assertTrue(raw.startswith("mvos_2fa_"))
        self.assertEqual(prefix, raw[:18])
        self.assertEqual(digest, hash_key(raw))
        subject, twofa_body = twofa_key_mail("Helper", raw, "https://myvinechurch.online")
        self.assertIn("2FA", subject)
        self.assertIn(f"twofa_key: {raw}", twofa_body)
        self.assertIn("expires_in: 3600", twofa_body)
        self.assertNotIn("api_key:", twofa_body)
        self.assertNotIn("keys@example.com", twofa_body)
        self.assertNotIn("mvos_testkey", twofa_body)
        self.assertIsNone(twofa_mail_problem(twofa_body, "keys@example.com"))
        self.assertEqual(TWOFA_TTL_SECONDS, 3600)
        session, _session_digest, session_prefix = new_session_material()
        self.assertTrue(session.startswith("mvos_s_"))
        self.assertEqual(session_prefix, session[:16])
        lines = "\n".join(help_payload({})["lines"])
        self.assertIn("POST /api/bot/login ", lines)
        self.assertIn("POST /api/bot/login/exchange", lines)
        self.assertIn("POST /api/bot/password-reset", lines)
        self.assertIn("X-Bot-2FA", lines)
        self.assertIn("1 hour", lines)
        sign = help_payload({})["sign_in"]
        self.assertIn("Does not expire", sign["api_key"])
        self.assertEqual(sign["twofa_header"], "X-Bot-2FA")
        self.assertEqual(sign["expires_in"], 3600)
        present = {
            "step": "twofa",
            "sent": True,
            "expires_in": 3600,
            "message": "A 2FA key was emailed to the other inbox.",
        }
        self.assertNotIn(raw, str(present))

    def test_owner_pages_mail_keys_and_keep_them_off_the_screen(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        routes = (root / "app/routes/bot_access.py").read_text()
        page = (root / "app/templates/settings/bot_access.html").read_text()
        usage = (root / "app/templates/settings/bot_usage.html").read_text()
        nav = (root / "app/templates/settings/base_settings.html").read_text()
        login = (root / "app/utils/bot_login.py").read_text()
        self.assertNotIn("bot_issued_key", routes)
        self.assertNotIn("issue_key", routes)
        self.assertIn("find_session", routes)
        self.assertIn('"/api/bot/login"', routes)
        self.assertIn('"/api/bot/login/exchange"', routes)
        self.assertIn('"/api/bot/password-reset"', routes)
        self.assertIn('"/settings/bot-access/usage"', routes)
        self.assertIn("That is the API key", routes)
        self.assertNotIn("issued_key", page)
        self.assertNotIn("Copy this key", page)
        self.assertIn('name="twofa_email"', page)
        self.assertIn('name="switch_bot_writes_off"', page)
        self.assertIn("High risk. Stays on until you turn it off.", page)
        self.assertIn('name="act_as"', page)
        self.assertIn('name="admin_grant"', page)
        self.assertIn("only as that admin", page)
        self.assertNotIn('name="voice_user"', page)
        self.assertIn("Bot usage", page)
        self.assertIn('!= "Owner"', routes)
        self.assertIn("bot_name", usage)
        self.assertIn('name="next" value="usage"', usage)
        self.assertIn("bot_access.usage", nav)
        self.assertIn("api_mail_problem", login)
        self.assertNotIn("return raw", login)

    def test_sermon_desk_does_not_hard_delete(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        names = (
            "app/utils/bot_sermons.py",
            "app/utils/bot_sermon_library.py",
            "app/utils/bot_sermon_common.py",
            "app/routes/bot_access.py",
            "app/utils/bot_office.py",
            "app/utils/bot_desks.py",
        )
        blobs = [(root / name).read_text() for name in names]
        routes = blobs[3]
        for blob in blobs:
            self.assertNotIn("delete_sermon", blob)
            self.assertNotIn("delete_illustration", blob)
            self.assertNotIn("save_sermon_sections", blob)
            self.assertNotIn("append_scripture_to_sermon", blob)
            self.assertNotIn("DELETE FROM pastoral_sermons", blob)
            self.assertNotIn("DELETE FROM illustration_library", blob)
            self.assertNotIn("DELETE FROM sermon_sections", blob)
            self.assertNotIn("DELETE FROM pastoral_vault", blob)
        self.assertIn('"/api/bot/sermons"', routes)
        self.assertIn('"/api/bot/verses"', routes)
        self.assertIn('"/api/bot/lineup"', routes)
        self.assertIn("sermons.apply_undo", routes)
        self.assertIn("DELETE FROM service_plans", blobs[1])
        office_src = (root / "app/utils/bot_office.py").read_text()
        worship = (root / "app/models/worship/shared.py").read_text()
        self.assertNotIn("site_staff", worship)
        self.assertIn("DELETE FROM user_groups", office_src)
        self.assertNotIn("DELETE FROM worship_songs", office_src)
        self.assertNotIn("delete_song", office_src)
        sql_lines = "\n".join(
            line for line in office_src.splitlines()
            if "SELECT" in line or "INSERT" in line or "UPDATE" in line
        )
        self.assertNotIn("account_number", sql_lines)
        self.assertNotIn("encrypted_", sql_lines)
        self.assertNotIn("tax_id", sql_lines)
        self.assertIn('"account_number"', office_src)
        self.assertIn('"encrypted_password"', office_src)
        self.assertIn('name="act_as"', (root / "app/templates/settings/bot_access.html").read_text())

    def test_desks_cover_the_church_and_leave_secrets_closed(self):
        from app.utils.bot_desks import CLOSED_TABLES, DESKS, desk_ids, safe_columns, secret_column
        ids = desk_ids()
        self.assertEqual(len(ids), len(set(ids)))
        self.assertGreaterEqual(len(DESKS), 100)
        needed = (
            "users", "groups", "user_groups", "events", "potluck_signups", "event_registrations",
            "announcements", "prayers", "dreams", "prophecies", "sermons",
            "pastoral_sermons", "sermon_sections", "illustration_library", "pastoral_vault",
            "service_plans", "service_plan_assignments", "pastoral_care_requests", "pastoral_care_notes",
            "curriculum_series", "curriculum_lessons", "curriculum_blocks",
            "worship_songs", "worship_setlists", "worship_setlist_songs", "worship_setlist_assignments",
            "worship_weekly_templates", "worship_weekly_template_songs", "worship_member_notes",
            "donations", "donation_recurring", "recurring_bills", "bill_payment_history",
            "acct_accounts", "acct_journal_entries", "acct_journal_lines", "acct_expenses", "acct_budgets",
            "categories", "items", "item_kit_components", "inventory_batches", "inventory_transactions",
            "attendance", "tickets", "ticket_comments",
            "vol_teams", "vol_roles", "vol_events", "vol_assignments",
            "church_pages", "member_spaces", "community_posts", "page_photos",
            "legal_notices", "help_articles", "custom_modules", "settings", "banned_ips",
            "child_classrooms", "child_profiles", "child_guardians", "child_checkins",
            "user_widgets", "bible_notes", "bible_highlights", "moderation_actions",
            "security_area_grants", "access_templates", "worship_user_prefs",
            "pbt_device_bans", "pbt_security_events", "pbt_reputation",
        )
        missing = [name for name in needed if name not in ids]
        self.assertEqual(missing, [])
        by_id = {row["id"]: row for row in DESKS}
        self.assertEqual(by_id["user_groups"]["keys"], ("user_id", "group_id"))
        self.assertTrue(by_id["user_groups"]["link"])
        self.assertTrue(by_id["worship_setlist_songs"]["link"])
        self.assertTrue(by_id["vol_team_members"]["link"])
        self.assertTrue(by_id["sermon_collaborators"]["link"])
        self.assertEqual(by_id["sermon_collaborators"]["keys"], ("sermon_id", "user_id"))
        self.assertEqual(by_id["bible_translations"]["keys"], ("code",))
        self.assertTrue(by_id["bible_translations"]["read_only"])
        self.assertFalse(by_id["worship_songs"]["link"])
        self.assertFalse(by_id["pastoral_sermons"]["link"])
        self.assertFalse(by_id["users"]["link"])
        self.assertFalse(by_id["donations"]["link"])
        self.assertFalse(by_id["acct_expenses"]["link"])
        self.assertTrue(by_id["comm_campaigns"]["read_only"])
        self.assertTrue(by_id["banned_ips"]["keep_ips"])
        self.assertEqual(by_id["banned_ips"]["keys"], ("ip_address",))
        self.assertEqual(by_id["bible_notes"]["own"], "user_id")
        self.assertTrue(by_id["campus_staff"]["link"])
        self.assertEqual(by_id["campus_staff"]["keys"], ("campus_id", "user_id"))
        self.assertEqual(by_id["content_posting"]["keys"], ("content_type", "content_id"))
        self.assertEqual(by_id["church_pages"]["keys"], ("campus_id",))
        self.assertFalse(by_id["church_pages"]["link"])
        self.assertEqual(by_id["member_spaces"]["keys"], ("user_id",))
        self.assertFalse(by_id["member_spaces"]["link"])
        self.assertIn("kiosk_sessions", CLOSED_TABLES)
        for name in ("child_classrooms", "child_profiles", "child_guardians", "child_checkins"):
            self.assertNotIn(name, CLOSED_TABLES)
        for name in CLOSED_TABLES:
            self.assertNotIn(name, ids)
        self.assertTrue(secret_column("password"))
        self.assertTrue(secret_column("email_password"))
        self.assertTrue(secret_column("checkin_pin"))
        self.assertTrue(secret_column("account_number"))
        self.assertTrue(secret_column("ai_api_key"))
        self.assertTrue(secret_column("body_enc"))
        self.assertTrue(secret_column("ip_address"))
        self.assertTrue(secret_column("login_url"))
        self.assertTrue(secret_column("payment_url"))
        self.assertTrue(secret_column("bank_account"))
        self.assertFalse(secret_column("lyrics_raw"))
        self.assertFalse(secret_column("sections_json"))
        self.assertFalse(secret_column("title"))
        self.assertFalse(secret_column("payment_method"))
        self.assertFalse(secret_column("last_login"))
        self.assertFalse(secret_column("pinned_by"))
        self.assertTrue(secret_column("pin_code"))
        self.assertTrue(secret_column("family_pin"))
        self.assertTrue(secret_column("pickup_code"))
        self.assertTrue(secret_column("security_code"))
        self.assertEqual(
            safe_columns(["title", "password", "lyrics_raw", "ip_address", "email"]),
            ["title", "lyrics_raw", "email"],
        )
        self.assertEqual(
            safe_columns(["ip_address", "reason", "encrypted_password"], keep_ips=True),
            ["ip_address", "reason"],
        )

    def test_every_live_table_is_a_desk_or_closed(self):
        import re
        from pathlib import Path
        from app.utils.bot_desks import CLOSED_TABLES, desk_ids
        root = Path(__file__).resolve().parents[1]
        folders = [
            root / "app" / "builddb",
            root / "app" / "models",
            root / "app" / "utils",
            root / "app" / "routes",
            root / "poweredbytop" / "security_build_db",
        ]
        names = set()
        for folder in folders:
            for path in folder.rglob("*.py"):
                if "MyChurch" in path.parts:
                    continue
                names.update(re.findall(r"CREATE TABLE IF NOT EXISTS ([a-z0-9_]+)", path.read_text()))
        known = set(desk_ids()) | set(CLOSED_TABLES)
        self.assertEqual(sorted(names - known), [])
        self.assertEqual(sorted(set(desk_ids()) & set(CLOSED_TABLES)), [])

    def test_named_areas_are_on_the_office_key(self):
        from pathlib import Path
        from app.utils.bot_areas import course_save, covers, moderation_act, modules_save
        from app.utils.bot_desks import _child_checkin_codes, desk_ids
        from app.utils.bot_policy import UNDO_STEPS
        named = covers()
        for key in (
            "my_page", "church_page", "notes", "find_people", "events", "prayers",
            "sermons", "announcements", "dreams", "prophecies", "bible", "study_courses",
            "members", "donations", "bills", "accounting", "inventory", "attendance",
            "child_checkin", "volunteers", "communications", "pastoral", "worship",
            "gathering", "site_moderation", "mod_reviews", "ai_insights", "settings",
            "church_apps_menu", "modules_and_apps", "help",
        ):
            self.assertIn(key, named)
        self.assertEqual(named["study_courses"]["path"], "/api/bot/courses")
        self.assertIn("body_md", named["help"]["about"])
        self.assertIn("PIN", named["child_checkin"]["about"])
        self.assertIn("pickup", named["child_checkin"]["about"].lower())
        self.assertTrue(named["still_closed"])
        ids = set(desk_ids())
        for area in named.values():
            if not isinstance(area, dict):
                continue
            for desk in area.get("desks") or []:
                self.assertIn(desk, ids)
        calls = {row["path"]: row for row in help_payload({})["calls"]}
        for path in (
            "/api/bot/courses",
            "/api/bot/courses/<id>",
            "/api/bot/upload",
            "/api/bot/modules",
            "/api/bot/moderation",
            "/api/bot/insights",
        ):
            self.assertEqual(calls[path]["switch"], "office")
            self.assertFalse(calls[path]["allowed"])
        text = "\n".join(help_payload({"office": True})["lines"])
        self.assertIn("help_articles", text)
        self.assertIn("body_md", text)
        self.assertIn("study course", text.lower())
        self.assertNotIn("course.create", UNDO_STEPS)
        self.assertNotIn("modules.update", UNDO_STEPS)
        self.assertNotIn("insights.run", UNDO_STEPS)
        self.assertFalse(any(action.startswith("moderation.") for action in UNDO_STEPS))
        self.assertFalse(course_save(1, {})["ok"])
        self.assertFalse(course_save(1, {"title": "x", "status": "live"})["ok"])
        self.assertFalse(modules_save({})["ok"])
        self.assertFalse(modules_save({"not_a_module": True})["ok"])
        self.assertFalse(moderation_act(1, "Owner", {"action": "nope"})["ok"])
        self.assertFalse(moderation_act(1, "Admin", {"action": "warn"})["ok"])
        filled = _child_checkin_codes("child_checkins", ["pickup_code", "security_code", "notes"])
        self.assertEqual(set(filled), {"pickup_code", "security_code"})
        self.assertEqual(len(filled["pickup_code"]), 8)
        self.assertEqual(_child_checkin_codes("users", ["pickup_code"]), {})
        root = Path(__file__).resolve().parents[1]
        areas_src = (root / "app/utils/bot_areas.py").read_text()
        desks_src = (root / "app/utils/bot_desks.py").read_text()
        routes = (root / "app/routes/bot_access.py").read_text()
        self.assertNotIn("DELETE FROM", areas_src)
        self.assertNotIn("DELETE FROM pastoral_sermons", desks_src)
        self.assertNotIn("DELETE FROM child_checkins", desks_src)
        self.assertNotIn("DELETE FROM help_articles", desks_src)
        self.assertIn("token_hex", desks_src)
        self.assertNotIn("user_has_permission", areas_src)
        self.assertNotIn("can_edit_church_page", areas_src)
        self.assertNotIn("has_key", areas_src)
        self.assertIn('"/api/bot/courses"', routes)
        self.assertIn('"/api/bot/upload"', routes)
        upload_src = (root / "app/utils/bot_uploads.py").read_text()
        self.assertNotIn("DELETE FROM", upload_src)
        self.assertNotIn("upload.course", UNDO_STEPS)
        self.assertNotIn("upload.page", UNDO_STEPS)
        self.assertIn('"/api/bot/modules"', routes)
        self.assertIn('"/api/bot/moderation"', routes)
        self.assertIn('"/api/bot/insights"', routes)
        self.assertIn("GET /api/bot/helper", text)
        self.assertIn("GET /api/bot/me", text)
        self.assertIn("GET /api/bot/sermons/<id>", text)
        self.assertIn("GET /api/bot/groups/<id>", text)
        self.assertIn("banner_x", text)
        self.assertIn("lesson_id", text)
        self.assertIn("media_url", text)
        for place in ("course", "page", "post", "login", "partner", "giving", "song"):
            self.assertIn(f"place={place}" if place != "page" else "place=page", text)
        payload = help_payload({"office": True})
        area_ids = {row["id"] for row in payload["areas"]}
        for key, area in named.items():
            if key == "still_closed":
                self.assertTrue(area)
                continue
            self.assertIn(key, area_ids)
            self.assertTrue(area.get("about"), key)
            self.assertIn(f"AREA {key} ", text)
        self.assertEqual(set(READ_ABOUT), set(READS))


class BotKeyRuleTests(unittest.TestCase):
    """The rotation rule: only the previous key expires, and an old session is not an attack."""

    def test_known_bearers_are_not_attacks(self):
        from app.utils.bot_policy import (
            PREV_KEY_GRACE_SECONDS,
            RESET_LIMIT_PER_HOUR,
            should_penalize_bot_bearer,
        )
        self.assertEqual(PREV_KEY_GRACE_SECONDS, 15 * 60)
        self.assertEqual(RESET_LIMIT_PER_HOUR, 3)
        for kind in ("live_session", "live_key", "grace_key", "expired_session", "expired_prev", "key_off"):
            self.assertFalse(should_penalize_bot_bearer(kind), kind)
        self.assertTrue(should_penalize_bot_bearer("unknown"))
        self.assertTrue(should_penalize_bot_bearer("missing"))
        self.assertTrue(should_penalize_bot_bearer(""))

    def test_help_says_the_old_key_is_the_only_thing_that_expires(self):
        text = "\n".join(help_payload({})["lines"])
        sign = help_payload({})["sign_in"]
        self.assertIn("POST /api/bot/key/reset", text)
        self.assertIn("POST /api/bot/key/reset-request", text)
        self.assertIn("15 minutes", text)
        self.assertIn("Does not expire", sign["api_key"])
        self.assertIn("A 2FA key is not emailed until POST /api/bot/login", sign["reset"])
        self.assertIn("main inbox", sign["reset"])
        self.assertNotIn("A 2FA key is emailed to the other inbox", sign["reset"])
        self.assertNotIn("this session stop working", text)


class _Clock:
    def __init__(self):
        from datetime import datetime
        self.now = datetime(2026, 10, 25, 12, 0, 0)
        self.keys = {}
        self.sessions = []
        self.logs = []
        self.voices = []
        self.users = {}
        self.grants = set()
        self.session_seq = 1
        self.log_seq = 1
        self.twofa_codes = []
        self.twofa_seq = 1
        self.unhandled = []

    def cursor(self):
        return _Cursor(self)


def _alive(moment, now):
    return moment is not None and moment > now


class _Cursor:
    """Just enough of the bot SQL for these tests. No MariaDB."""

    def __init__(self, db):
        self.db = db
        self.rowcount = 0
        self.lastrowid = 0
        self._rows = []

    def execute(self, sql, params=None):
        self._rows = []
        self.rowcount = 0
        text = " ".join(sql.split())
        params = tuple(params or ())
        handler = self._handler(text)
        if handler is None:
            self.db.unhandled.append(text)
            return
        handler(params)

    def _handler(self, text):
        if text.startswith("SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS"):
            return self._schema
        if text.startswith("CREATE TABLE"):
            return self._noop
        if "bot_twofa_codes" in text:
            found = self._twofa_sql(text)
            if found:
                return found
        if "seconds_left" in text and "FROM bot_sessions" in text:
            return self._session_left
        if "grace_live" in text:
            return self._grace_live
        if "session_expires > NOW()" in text and text.startswith("SELECT id, session_hash, session_expires"):
            return self._legacy_live
        if text.startswith("SELECT session_hash FROM bot_sessions"):
            return self._session_hashes
        if "NOW(), 'legacy'" in text:
            return self._insert_legacy
        if text.startswith("SELECT id, session_hash FROM bot_access_keys"):
            return self._legacy_left
        if "SET session_hash=NULL, session_expires=NULL" in text:
            return self._clear_legacy
        if "prev_key_hash=key_hash" in text:
            return self._replace
        if "SET twofa_hash=%s" in text:
            return self._store_twofa
        if "twofa_hash=NULL" in text:
            return self._clear_twofa
        if "DATE_ADD(NOW(), INTERVAL %s SECOND), NOW(), %s" in text:
            return self._insert_session
        if text.startswith("SELECT id FROM bot_sessions WHERE key_id"):
            return self._session_ids
        if text.startswith("DELETE FROM bot_sessions WHERE id"):
            return self._delete_session
        if text.startswith("UPDATE bot_sessions SET last_used_at"):
            return self._touch
        if "twofa_expires > NOW() AS live" in text:
            return self._twofa
        if "AS live, k.active" in text:
            return self._session_state
        if text.startswith("SELECT (session_expires > NOW()) AS live"):
            return self._legacy_state
        if "AS session_row_id" in text:
            return self._live_session
        if "session_expires > NOW()" in text and "session_hash=%s" in text:
            return self._legacy_session
        if "AS current_match" in text:
            return self._key_state
        if text.startswith("SELECT * FROM bot_access_keys") and "prev_key_hash=%s" in text:
            return self._find_key
        if text.startswith("SELECT * FROM bot_access_keys WHERE id=%s"):
            return self._get_key
        if text.startswith("SELECT COUNT(*)"):
            return self._count_resets
        if text.startswith("INSERT INTO bot_access_log"):
            return self._insert_log
        if text.startswith("SELECT id FROM bot_access_keys WHERE email"):
            return self._inbox
        if "FROM bot_access_voices" in text:
            return self._voices
        if text.startswith("SELECT role FROM users"):
            return self._role
        if text.startswith("SELECT user_id FROM bot_admin_grants"):
            return self._grants
        return None

    def _twofa_sql(self, text):
        if text.startswith("INSERT INTO bot_twofa_codes"):
            return self._insert_twofa
        if text.startswith("SELECT id FROM bot_twofa_codes"):
            return self._twofa_ids
        if text.startswith("SELECT id, code_hash"):
            return self._twofa_match
        if text.startswith("SELECT code_hash"):
            return self._twofa_restore
        if text.startswith("SELECT COUNT(*)"):
            return self._twofa_pending
        if "code_hash=%s" in text:
            return self._twofa_drop_hash
        if text.startswith("UPDATE bot_twofa_codes"):
            return self._twofa_mark
        return None

    def _insert_twofa(self, params):
        from datetime import timedelta
        key_id, digest, seconds = params
        row = {
            "id": self.db.twofa_seq,
            "key_id": int(key_id),
            "code_hash": digest,
            "expires_at": self.db.now + timedelta(seconds=int(seconds)),
            "used_at": None,
        }
        self.db.twofa_seq += 1
        self.db.twofa_codes.append(row)
        self.lastrowid = row["id"]
        self.rowcount = 1

    def _live_codes(self, key_id, include_expired=False):
        rows = [
            row for row in self.db.twofa_codes
            if row["key_id"] == int(key_id) and row["used_at"] is None
            and (include_expired or _alive(row["expires_at"], self.db.now))
        ]
        rows.sort(key=lambda row: row["id"], reverse=True)
        return rows

    def _twofa_ids(self, params):
        self._rows = [{"id": row["id"]} for row in self._live_codes(params[0])]

    def _twofa_mark(self, params):
        for row in self.db.twofa_codes:
            if row["id"] == int(params[0]) and row["used_at"] is None:
                row["used_at"] = self.db.now
                self.rowcount = 1
                return

    def _twofa_drop_hash(self, params):
        key_id, digest = params
        self.rowcount = 0
        for row in self.db.twofa_codes:
            if row["key_id"] == int(key_id) and row["code_hash"] == digest and row["used_at"] is None:
                row["used_at"] = self.db.now
                self.rowcount += 1

    def _twofa_match(self, params):
        rows = self._live_codes(params[0], include_expired=True)[:3]
        self._rows = [{
            "id": row["id"],
            "code_hash": row["code_hash"],
            "live": 1 if _alive(row["expires_at"], self.db.now) else 0,
        } for row in rows]

    def _twofa_restore(self, params):
        rows = self._live_codes(params[0])
        if not rows:
            return
        left = rows[0]
        seconds = int((left["expires_at"] - self.db.now).total_seconds())
        self._rows = [{"code_hash": left["code_hash"], "seconds_left": max(seconds, 0)}]

    def _twofa_pending(self, params):
        self._rows = [{"n": len(self._live_codes(params[0]))}]

    def _session_left(self, params):
        for row in self.db.sessions:
            if row["id"] == params[0]:
                seconds = int((row["expires_at"] - self.db.now).total_seconds())
                self._rows = [{"seconds_left": max(seconds, 0)}]
                return

    def _grace_live(self, params):
        key = self.db.keys.get(params[0]) or {}
        live = _alive(key.get("prev_key_expires"), self.db.now)
        self._rows = [{"grace_live": 1 if live else 0}]

    def _schema(self, _params):
        self._rows = [{"1": 1}]

    def _noop(self, _params):
        return None

    def _legacy_live(self, _params):
        self._rows = [
            {"id": key["id"], "session_hash": key["session_hash"], "session_expires": key["session_expires"]}
            for key in self.db.keys.values()
            if key.get("session_hash") and _alive(key.get("session_expires"), self.db.now)
        ]

    def _session_hashes(self, _params):
        self._rows = [{"session_hash": row["session_hash"]} for row in self.db.sessions]

    def _insert_legacy(self, params):
        self._add_session(int(params[0]), params[1], params[2], "legacy")

    def _legacy_left(self, _params):
        self._rows = [
            {"id": key["id"], "session_hash": key.get("session_hash")}
            for key in self.db.keys.values() if key.get("session_hash")
        ]

    def _clear_legacy(self, params):
        key = self.db.keys.get(params[0])
        if not key:
            return
        key["session_hash"] = None
        key["session_expires"] = None
        self.rowcount = 1

    def _replace(self, params):
        grace, digest, prefix, key_id = params
        key = self.db.keys.get(key_id)
        if not key:
            return
        from datetime import timedelta
        key["prev_key_hash"] = key.get("key_hash")
        key["prev_key_expires"] = self.db.now + timedelta(seconds=int(grace))
        key["key_hash"] = digest
        key["key_prefix"] = prefix
        self.rowcount = 1

    def _store_twofa(self, params):
        from datetime import timedelta
        digest, seconds, key_id = params
        key = self.db.keys.get(key_id)
        if not key:
            return
        key["twofa_hash"] = digest
        key["twofa_expires"] = self.db.now + timedelta(seconds=int(seconds))
        key["twofa_attempts"] = 0
        self.rowcount = 1

    def _clear_twofa(self, params):
        key = self.db.keys.get(params[0])
        if not key:
            return
        key["twofa_hash"] = None
        key["twofa_expires"] = None
        key["twofa_attempts"] = 0
        self.rowcount = 1

    def _insert_session(self, params):
        from datetime import timedelta
        key_id, digest, seconds, label = params
        expires = self.db.now + timedelta(seconds=int(seconds))
        self._add_session(int(key_id), digest, expires, label)

    def _add_session(self, key_id, digest, expires, label):
        sid = self.db.session_seq
        self.db.session_seq += 1
        self.db.sessions.append({
            "id": sid,
            "key_id": key_id,
            "session_hash": digest,
            "expires_at": expires,
            "last_used_at": self.db.now,
            "client_label": label,
        })
        self.lastrowid = sid
        self.rowcount = 1

    def _session_ids(self, params):
        rows = [row for row in self.db.sessions if row["key_id"] == params[0]]
        rows.sort(key=lambda row: row["id"], reverse=True)
        self._rows = [{"id": row["id"]} for row in rows]

    def _delete_session(self, params):
        before = len(self.db.sessions)
        self.db.sessions = [row for row in self.db.sessions if row["id"] != params[0]]
        self.rowcount = before - len(self.db.sessions)

    def _touch(self, params):
        for row in self.db.sessions:
            if row["id"] == params[0]:
                row["last_used_at"] = self.db.now
                self.rowcount = 1

    def _twofa(self, params):
        key = self.db.keys.get(params[0])
        if not key:
            return
        self._rows = [{
            "twofa_hash": key.get("twofa_hash"),
            "live": 1 if _alive(key.get("twofa_expires"), self.db.now) else 0,
        }]

    def _session_state(self, params):
        for row in self.db.sessions:
            if row["session_hash"] != params[0]:
                continue
            key = self.db.keys.get(row["key_id"]) or {}
            self._rows = [{
                "live": 1 if _alive(row["expires_at"], self.db.now) else 0,
                "active": key.get("active", 0),
            }]
            return

    def _legacy_state(self, params):
        for key in self.db.keys.values():
            if key.get("session_hash") != params[0]:
                continue
            self._rows = [{
                "live": 1 if _alive(key.get("session_expires"), self.db.now) else 0,
                "active": key.get("active", 0),
            }]
            return

    def _key_row(self, key, session_id=None):
        row = {
            "id": key["id"],
            "name": key.get("name"),
            "key_hash": key.get("key_hash"),
            "key_prefix": key.get("key_prefix"),
            "active": key.get("active"),
            "controls_json": key.get("controls_json"),
            "created_by": key.get("created_by"),
            "email": key.get("email"),
            "twofa_email": key.get("twofa_email"),
            "created_at": key.get("created_at"),
            "updated_at": key.get("updated_at"),
        }
        if session_id is not None:
            row["session_row_id"] = session_id
        return row

    def _live_session(self, params):
        for row in self.db.sessions:
            if row["session_hash"] == params[0] and _alive(row["expires_at"], self.db.now):
                key = self.db.keys.get(row["key_id"])
                if key:
                    self._rows = [self._key_row(key, row["id"])]
                    return

    def _legacy_session(self, params):
        for key in self.db.keys.values():
            if key.get("session_hash") == params[0] and _alive(key.get("session_expires"), self.db.now):
                self._rows = [self._key_row(key)]
                return

    def _matching_key(self, digest, grace_only_if_live):
        found = []
        for key in self.db.keys.values():
            current = key.get("key_hash") == digest
            prev = key.get("prev_key_hash") == digest
            prev_live = _alive(key.get("prev_key_expires"), self.db.now)
            if current or (prev and (prev_live or not grace_only_if_live)):
                found.append((0 if current else 1, key, current, prev, prev_live))
        found.sort(key=lambda item: item[0])
        return found[0] if found else None

    def _key_state(self, params):
        digest = params[0]
        hit = self._matching_key(digest, grace_only_if_live=False)
        if not hit:
            return
        _order, key, current, prev, prev_live = hit
        self._rows = [{
            "active": key.get("active"),
            "current_match": 1 if current else 0,
            "prev_match": 1 if prev else 0,
            "prev_live": 1 if prev_live else 0,
        }]

    def _find_key(self, params):
        hit = self._matching_key(params[0], grace_only_if_live=True)
        if not hit:
            return
        self._rows = [dict(hit[1])]

    def _get_key(self, params):
        key = self.db.keys.get(params[0])
        if key:
            self._rows = [dict(key)]

    def _count_resets(self, params):
        from datetime import timedelta
        key_id, action, seconds = params
        cutoff = self.db.now - timedelta(seconds=int(seconds))
        count = 0
        for row in self.db.logs:
            if row["key_id"] == key_id and row["action"] == action and row["ok"] in (1, True) and row["created_at"] > cutoff:
                count += 1
        self._rows = [{"n": count}]

    def _insert_log(self, params):
        self.db.logs.append({
            "id": self.db.log_seq,
            "key_id": params[0],
            "action": params[1],
            "ok": params[4],
            "detail": params[5],
            "created_at": self.db.now,
        })
        self.lastrowid = self.db.log_seq
        self.db.log_seq += 1
        self.rowcount = 1

    def _inbox(self, params):
        self._rows = [
            {"id": key["id"]}
            for key in self.db.keys.values()
            if key.get("email") == params[0] and key.get("active") in (1, True)
        ]

    def _voices(self, params):
        key_id = params[0] if params else None
        self._rows = [
            dict(row) for row in self.db.voices
            if key_id is None or row.get("key_id") == key_id
        ]

    def _role(self, params):
        user = self.db.users.get(params[0])
        if user:
            self._rows = [{"role": user["role"]}]

    def _grants(self, _params):
        self._rows = [{"user_id": uid} for uid in self.db.grants]

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class BotKeyStoreTests(unittest.TestCase):
    def setUp(self):
        from app.utils import bot_store as store
        self.store = store
        self.db = _Clock()
        self._patch = unittest.mock.patch.object(store, "_cur", self.db.cursor)
        self._patch.start()
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
            "twofa_hash": "pending",
            "twofa_expires": None,
            "twofa_attempts": 0,
            "session_hash": None,
            "session_expires": None,
            "prev_key_hash": None,
            "prev_key_expires": None,
            "created_at": self.db.now,
            "updated_at": self.db.now,
        }

    def tearDown(self):
        self._patch.stop()
        if self.db.unhandled:
            self.fail("unhandled SQL:\n" + "\n".join(self.db.unhandled))

    def _open(self, label):
        from app.utils.bot_policy import new_session_material
        raw, digest, _prefix = new_session_material()
        self.assertTrue(self.store.open_session(1, digest, label))
        return raw

    def test_two_sessions_stay_open_and_a_twofa_request_keeps_them(self):
        from app.utils.bot_policy import hash_key as digest_of
        first = self._open("vine")
        second = self._open("church")
        self.assertTrue(self.store.store_twofa(1, digest_of("mvos_2fa_pending")))
        self.assertIsNotNone(self.store.find_session(first))
        self.assertIsNotNone(self.store.find_session(second))
        self.assertEqual(len(self.db.sessions), 2)

    def test_a_live_legacy_slot_moves_into_the_session_table(self):
        from datetime import timedelta
        from app.utils.bot_policy import new_session_material
        raw, digest, _prefix = new_session_material()
        self.db.keys[1]["session_hash"] = digest
        self.db.keys[1]["session_expires"] = self.db.now + timedelta(minutes=30)
        self.assertIsNotNone(self.store.find_session(raw))
        self.assertIsNone(self.db.keys[1]["session_hash"])

    def test_the_sixth_session_drops_the_oldest(self):
        opened = [self._open(f"client-{number}") for number in range(6)]
        self.assertIsNone(self.store.find_session(opened[0]))
        for raw in opened[1:]:
            self.assertIsNotNone(self.store.find_session(raw))
        self.assertEqual(len(self.db.sessions), 5)

    def test_rotation_expires_only_the_previous_key(self):
        from datetime import timedelta
        from app.utils.bot_policy import PREV_KEY_GRACE_SECONDS, new_key_material
        session = self._open("vine")
        self.db.keys[1]["twofa_hash"] = "pending-code"
        self.db.keys[1]["twofa_expires"] = self.db.now + timedelta(minutes=10)
        pending = self.db.keys[1]["twofa_hash"]
        second, second_hash, second_prefix = new_key_material()
        third, third_hash, third_prefix = new_key_material()
        self.assertEqual(self.store.replace_api_key(1, second_hash, second_prefix), (True, ""))
        self.assertEqual(self.db.keys[1]["twofa_hash"], pending)
        self.assertIsNotNone(self.store.find_key(self.raw))
        self.assertIsNotNone(self.store.find_key(second))
        self.assertIsNotNone(self.store.find_session(session))
        self.db.now += timedelta(seconds=PREV_KEY_GRACE_SECONDS + 1)
        self.assertIsNone(self.store.find_key(self.raw))
        self.assertIsNotNone(self.store.find_key(second))
        self.assertIsNotNone(self.store.find_session(session))
        self.assertEqual(self.store.replace_api_key(1, third_hash, third_prefix), (True, ""))
        self.assertIsNone(self.store.find_key(self.raw))
        self.assertIsNotNone(self.store.find_key(second))
        self.assertIsNotNone(self.store.find_key(third))
        self.db.now += timedelta(seconds=PREV_KEY_GRACE_SECONDS + 1)
        self.assertIsNone(self.store.find_key(second))
        self.assertIsNotNone(self.store.find_key(third))
        self.assertIsNotNone(self.store.find_session(session))


class BotKeyRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from flask import Flask
        from app.routes.bot_access import bot_access_bp
        cls.app = Flask(__name__)
        cls.app.config["SECRET_KEY"] = "bot-key-tests"
        cls.app.register_blueprint(bot_access_bp)

    def setUp(self):
        from app.utils import bot_login as login_mod
        from app.utils import bot_store as store
        self.store = store
        self.login_mod = login_mod
        self.db = _Clock()
        self.sent = []
        self.mail_error = None
        self.fail_after = None
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
        self._cur = unittest.mock.patch.object(store, "_cur", self.db.cursor)
        self._mail = unittest.mock.patch.object(login_mod, "_send", self._send)
        self._cur.start()
        self._mail.start()
        self.client = self.app.test_client()

    def tearDown(self):
        self._cur.stop()
        self._mail.stop()
        if self.db.unhandled:
            self.fail("unhandled SQL:\n" + "\n".join(self.db.unhandled))

    def _send(self, to_email, subject, body):
        self.sent.append({"to": to_email, "subject": subject, "body": body})
        if self.fail_after and len(self.sent) > self.fail_after:
            return "The email did not send."
        return self.mail_error

    def _line(self, body, prefix):
        for line in body.splitlines():
            if line.startswith(prefix):
                return line.split(":", 1)[1].strip()
        self.fail(prefix)

    def _split_pair(self, batch):
        """The API-key mail is first. The 2FA mail is second. They use different inboxes."""
        self.assertEqual(len(batch), 2, batch)
        api_mail, twofa_mail = batch
        self.assertEqual(api_mail["to"], "keys@example.com")
        self.assertEqual(twofa_mail["to"], "codes@example.com")
        new_key = self._line(api_mail["body"], "api_key:")
        twofa = self._line(twofa_mail["body"], "twofa_key:")
        self.assertIn("expires: never", api_mail["body"])
        self.assertNotIn("twofa_key:", api_mail["body"])
        self.assertNotIn("codes@example.com", api_mail["body"])
        self.assertNotIn(twofa, api_mail["body"])
        self.assertNotIn("api_key:", twofa_mail["body"])
        self.assertNotIn("keys@example.com", twofa_mail["body"])
        self.assertNotIn(new_key, twofa_mail["body"])
        return new_key, twofa

    def _login(self, raw):
        res = self.client.post("/api/bot/login", headers={"Authorization": "Bearer " + raw})
        return res

    def _exchange(self, raw, twofa):
        return self.client.post(
            "/api/bot/login/exchange",
            headers={"Authorization": "Bearer " + raw, "X-Bot-2FA": twofa},
        )

    def test_two_clients_both_stay_signed_in(self):
        first = self._login(self.raw)
        self.assertEqual(first.status_code, 200, first.get_data(as_text=True))
        twofa = self._line(self.sent[-1]["body"], "twofa_key:")
        self.assertEqual(self.sent[-1]["to"], "codes@example.com")
        opened = self._exchange(self.raw, twofa)
        self.assertEqual(opened.status_code, 200, opened.get_data(as_text=True))
        session_a = opened.get_json()["data"]["session"]
        again = self._login(self.raw)
        self.assertEqual(again.status_code, 200)
        still = self.client.get("/api/bot/whoami", headers={"Authorization": "Bearer " + session_a})
        self.assertEqual(still.status_code, 200, still.get_data(as_text=True))
        twofa_b = self._line(self.sent[-1]["body"], "twofa_key:")
        opened_b = self._exchange(self.raw, twofa_b)
        session_b = opened_b.get_json()["data"]["session"]
        for token in (session_a, session_b):
            res = self.client.get("/api/bot/whoami", headers={"Authorization": "Bearer " + token})
            self.assertEqual(res.status_code, 200, res.get_data(as_text=True))

    def test_a_second_sign_in_keeps_the_first_unused_code(self):
        self._login(self.raw)
        first = self._line(self.sent[-1]["body"], "twofa_key:")
        self._login(self.raw)
        second = self._line(self.sent[-1]["body"], "twofa_key:")
        self.assertNotEqual(first, second)
        opened = self._exchange(self.raw, first)
        self.assertEqual(opened.status_code, 200, opened.get_data(as_text=True))
        again = self._exchange(self.raw, second)
        self.assertEqual(again.status_code, 200, again.get_data(as_text=True))

    def test_old_key_works_during_grace_then_returns_key_unknown(self):
        from datetime import timedelta
        from app.utils.bot_policy import PREV_KEY_GRACE_SECONDS, new_session_material
        raw_session, digest, _prefix = new_session_material()
        self.assertTrue(self.store.open_session(1, digest, "vine"))
        res = self.client.post("/api/bot/key/reset", headers={"Authorization": "Bearer " + self.raw})
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        body = res.get_data(as_text=True)
        data = res.get_json()["data"]
        self.assertFalse(data["twofa_sent"])
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0]["to"], "keys@example.com")
        new_key = self._line(self.sent[0]["body"], "api_key:")
        self.assertNotIn(new_key, body)
        self.assertNotIn("twofa_key:", body)
        self.assertNotIn(self.raw, body)
        self.assertNotIn("codes@example.com", body)
        self.assertIn("15 minutes", body)
        signed = self._login(new_key)
        self.assertEqual(signed.status_code, 200, signed.get_data(as_text=True))
        twofa = self._line(self.sent[-1]["body"], "twofa_key:")
        opened = self._exchange(new_key, twofa)
        self.assertEqual(opened.status_code, 200, opened.get_data(as_text=True))
        fresh_session = opened.get_json()["data"]["session"]
        signed_in = self.client.get(
            "/api/bot/whoami", headers={"Authorization": "Bearer " + fresh_session},
        )
        self.assertEqual(signed_in.status_code, 200, signed_in.get_data(as_text=True))
        during = self._login(self.raw)
        self.assertEqual(during.status_code, 200, during.get_data(as_text=True))
        self.assertNotEqual(during.get_json().get("code"), "key_unknown")
        who = self.client.get("/api/bot/whoami", headers={"Authorization": "Bearer " + raw_session})
        self.assertEqual(who.status_code, 200, who.get_data(as_text=True))
        self.db.now += timedelta(seconds=PREV_KEY_GRACE_SECONDS + 1)
        expired = self._login(self.raw)
        self.assertEqual(expired.status_code, 401)
        self.assertEqual(expired.get_json()["code"], "key_unknown")
        fresh = self._login(new_key)
        self.assertEqual(fresh.status_code, 200, fresh.get_data(as_text=True))
        who_later = self.client.get("/api/bot/whoami", headers={"Authorization": "Bearer " + raw_session})
        self.assertEqual(who_later.status_code, 200, who_later.get_data(as_text=True))
        still_fresh = self.client.get(
            "/api/bot/whoami", headers={"Authorization": "Bearer " + fresh_session},
        )
        self.assertEqual(still_fresh.status_code, 200, still_fresh.get_data(as_text=True))

    def test_failed_mail_leaves_the_old_key(self):
        self.mail_error = "The email did not send."
        before = self.db.keys[1]["key_hash"]
        res = self.client.post("/api/bot/password-reset", headers={"Authorization": "Bearer " + self.raw})
        self.assertEqual(res.status_code, 502)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0]["to"], "keys@example.com")
        self.assertEqual(self.db.keys[1]["key_hash"], before)
        self.assertIsNone(self.db.keys[1]["prev_key_hash"])
        self.assertIsNone(self.db.keys[1]["twofa_hash"])
        self.assertFalse(any(row["action"] == "key_reset" and row["ok"] in (1, True) for row in self.db.logs))
        offered = self._line(self.sent[-1]["body"], "api_key:")
        self.assertIsNone(self.store.find_key(offered))
        self.assertIsNotNone(self.store.find_key(self.raw))

    def test_a_failed_twofa_mail_keeps_the_new_api_key(self):
        res = self.client.post("/api/bot/key/reset", headers={"Authorization": "Bearer " + self.raw})
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        data = res.get_json()["data"]
        self.assertFalse(data["twofa_sent"])
        self.assertNotIn("did not send", data["message"])
        self.assertIn("POST /api/bot/login", data["message"])
        self.assertEqual(len(self.sent), 1)
        new_key = self._line(self.sent[0]["body"], "api_key:")
        self.assertEqual(self.sent[0]["to"], "keys@example.com")
        self.assertNotIn(new_key, res.get_data(as_text=True))
        self.assertIsNotNone(self.store.find_key(new_key))
        self.mail_error = "The email did not send."
        failed = self._login(new_key)
        self.assertEqual(failed.status_code, 502, failed.get_data(as_text=True))
        self.assertEqual(self.sent[-1]["to"], "codes@example.com")
        self.assertIsNotNone(self.store.find_key(new_key))
        self.assertIsNone(self.db.keys[1]["twofa_hash"])
        self.mail_error = None
        fresh = self._login(new_key)
        self.assertEqual(fresh.status_code, 200, fresh.get_data(as_text=True))
        self.assertEqual(self.sent[-1]["to"], "codes@example.com")
        code = self._line(self.sent[-1]["body"], "twofa_key:")
        opened = self._exchange(new_key, code)
        self.assertEqual(opened.status_code, 200, opened.get_data(as_text=True))

    def test_fourth_reset_in_an_hour_is_refused(self):
        from app.utils.bot_policy import new_session_material
        raw_session, digest, _prefix = new_session_material()
        self.assertTrue(self.store.open_session(1, digest))
        header = {"Authorization": "Bearer " + raw_session}
        for _number in range(3):
            before = len(self.sent)
            res = self.client.post("/api/bot/key/reset", headers=header)
            self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
            self.assertFalse(res.get_json()["data"]["twofa_sent"])
            self.assertEqual(len(self.sent), before + 1)
            new_key = self._line(self.sent[-1]["body"], "api_key:")
            self.assertEqual(self.sent[-1]["to"], "keys@example.com")
            text = res.get_data(as_text=True)
            self.assertNotIn(new_key, text)
            self.assertNotIn("twofa_key:", text)
        self.assertEqual(len(self.sent), 3)
        blocked = self.client.post("/api/bot/key/reset", headers=header)
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(len(self.sent), 3)

    def test_reset_request_with_the_wrong_email_sends_nothing(self):
        from app.utils.bot_policy import RESET_REQUEST_REPLY
        wrong = self.client.post("/api/bot/key/reset-request", json={"email": "nobody@example.com"})
        self.assertEqual(wrong.status_code, 200)
        self.assertEqual(wrong.get_json()["data"]["message"], RESET_REQUEST_REPLY)
        self.assertEqual(self.sent, [])
        twofa_inbox = self.client.post("/api/bot/key/reset-request", json={"email": "codes@example.com"})
        self.assertEqual(twofa_inbox.status_code, 200)
        self.assertEqual(self.sent, [])
        self.assertEqual(self.db.keys[1]["key_hash"], hash_key(self.raw))
        right = self.client.post("/api/bot/key/reset-request", json={"email": "keys@example.com"})
        self.assertEqual(right.status_code, 200)
        self.assertEqual(right.get_json()["data"]["message"], RESET_REQUEST_REPLY)
        self.assertNotIn("twofa_sent", right.get_json()["data"])
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0]["to"], "keys@example.com")
        new_key = self._line(self.sent[0]["body"], "api_key:")
        text = right.get_data(as_text=True)
        self.assertNotIn(new_key, text)
        self.assertNotIn("twofa_key:", text)
        signed = self._login(new_key)
        self.assertEqual(signed.status_code, 200, signed.get_data(as_text=True))
        twofa = self._line(self.sent[-1]["body"], "twofa_key:")
        opened = self._exchange(new_key, twofa)
        self.assertEqual(opened.status_code, 200, opened.get_data(as_text=True))
        session = opened.get_json()["data"]["session"]
        who = self.client.get("/api/bot/whoami", headers={"Authorization": "Bearer " + session})
        self.assertEqual(who.status_code, 200, who.get_data(as_text=True))
        for _extra in range(2):
            again = self.client.post("/api/bot/key/reset-request", json={"email": "keys@example.com"})
            self.assertEqual(again.status_code, 200)
            self.assertEqual(again.get_json()["data"]["message"], RESET_REQUEST_REPLY)
        self.assertEqual(len(self.sent), 4)
        quiet = self.client.post("/api/bot/key/reset-request", json={"email": "keys@example.com"})
        self.assertEqual(quiet.status_code, 200)
        self.assertEqual(quiet.get_json()["data"]["message"], RESET_REQUEST_REPLY)
        self.assertEqual(len(self.sent), 4)
        still = self.client.get("/api/bot/whoami", headers={"Authorization": "Bearer " + session})
        self.assertEqual(still.status_code, 200, still.get_data(as_text=True))

    def test_a_dead_api_key_mails_a_new_key_and_a_twofa(self):
        from datetime import timedelta
        from app.utils.bot_policy import PREV_KEY_GRACE_SECONDS, RESET_REQUEST_REPLY, new_key_material
        current, current_hash, current_prefix = new_key_material()
        self.assertEqual(self.store.replace_api_key(1, current_hash, current_prefix), (True, ""))
        self.db.now += timedelta(seconds=PREV_KEY_GRACE_SECONDS + 1)
        self.assertIsNone(self.store.find_key(self.raw))
        dead = self._login(self.raw)
        self.assertEqual(dead.status_code, 401)
        self.assertEqual(dead.get_json()["code"], "key_unknown")
        self.assertEqual(self.sent, [])
        res = self.client.post(
            "/api/bot/key/reset-request",
            json={"email": "keys@example.com"},
            headers={"Authorization": "Bearer " + self.raw},
        )
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        payload = res.get_json()["data"]
        self.assertEqual(payload["message"], RESET_REQUEST_REPLY)
        self.assertNotIn("twofa_sent", payload)
        text = res.get_data(as_text=True)
        self.assertNotIn(self.raw, text)
        self.assertEqual(len(self.sent), 1)
        new_key = self._line(self.sent[0]["body"], "api_key:")
        self.assertEqual(self.sent[0]["to"], "keys@example.com")
        self.assertNotIn(new_key, text)
        self.assertNotIn("twofa_key:", text)
        signed = self._login(new_key)
        self.assertEqual(signed.status_code, 200, signed.get_data(as_text=True))
        twofa = self._line(self.sent[-1]["body"], "twofa_key:")
        opened = self._exchange(new_key, twofa)
        self.assertEqual(opened.status_code, 200, opened.get_data(as_text=True))
        session = opened.get_json()["data"]["session"]
        who = self.client.get("/api/bot/whoami", headers={"Authorization": "Bearer " + session})
        self.assertEqual(who.status_code, 200, who.get_data(as_text=True))
        still_dead = self._login(self.raw)
        self.assertEqual(still_dead.status_code, 401)
        self.assertEqual(still_dead.get_json()["code"], "key_unknown")
        during = self._login(current)
        self.assertEqual(during.status_code, 200, during.get_data(as_text=True))
        self.assertEqual(during.get_json().get("code"), None)
        still = self.client.get("/api/bot/whoami", headers={"Authorization": "Bearer " + session})
        self.assertEqual(still.status_code, 200, still.get_data(as_text=True))

    def test_admin_without_a_grant_has_its_own_code(self):
        from app.utils.bot_policy import new_session_material
        raw_session, digest, _prefix = new_session_material()
        self.assertTrue(self.store.open_session(1, digest))
        self.db.users[4] = {"role": "Admin"}
        self.db.voices.append({
            "id": 1,
            "key_id": 1,
            "voice_type": "user",
            "user_id": 4,
            "label": None,
            "username": "ada",
            "first_name": "Ada",
            "last_name": "Admin",
        })
        header = {"Authorization": "Bearer " + raw_session}
        blocked = self.client.get("/api/bot/whoami", headers=header)
        self.assertEqual(blocked.status_code, 200, blocked.get_data(as_text=True))
        body = blocked.get_json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["blocked"])
        self.assertEqual(body["code"], "admin_not_granted")
        self.assertEqual(body["missing"], ["admin_grant:4"])
        self.assertIn("Ada Admin (ada)", body["fix"])
        self.assertEqual(body["data"]["missing"], ["admin_grant:4"])
        self.assertIn("name", body["data"])
        self.assertEqual(body["expired_switches"], [])
        work = self.client.get("/api/bot/security", headers=header)
        self.assertEqual(work.status_code, 403)
        self.assertEqual(work.get_json()["missing"], ["admin_grant:4"])
        helper = self.client.get("/api/bot/help", headers=header)
        self.assertEqual(helper.status_code, 200)
        calls = {row["path"]: row for row in helper.get_json()["data"]["calls"]}
        self.assertFalse(calls["/api/bot/posts"]["allowed"])
        self.assertEqual(calls["/api/bot/posts"]["why"], "admin_grant")
        self.db.grants.add(4)
        allowed = self.client.get("/api/bot/whoami", headers=header)
        self.assertEqual(allowed.status_code, 200, allowed.get_data(as_text=True))
        self.assertTrue(allowed.get_json()["ok"])
        self.assertFalse(allowed.get_json()["blocked"])

    def test_an_expired_session_on_a_work_call_says_so(self):
        from datetime import timedelta
        from app.utils.bot_policy import new_session_material
        raw, digest, _prefix = new_session_material()
        self.db.sessions.append({
            "id": 77,
            "key_id": 1,
            "session_hash": digest,
            "expires_at": self.db.now - timedelta(minutes=1),
            "last_used_at": self.db.now,
            "client_label": None,
        })
        res = self.client.get("/api/bot/whoami", headers={"Authorization": "Bearer " + raw})
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.get_json()["code"], "session_expired")


class BotBearerPenaltyTests(unittest.TestCase):
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

    def tearDown(self):
        self._patch.stop()
        if self.db.unhandled:
            self.fail("unhandled SQL:\n" + "\n".join(self.db.unhandled))

    def _allowed(self, raw, path="/api/bot/whoami", method="GET", score=100, locked_out=False, rate_ok=True):
        from flask import Flask
        import poweredbytop.core.security as sec
        app = Flask(__name__)
        header = {"Authorization": "Bearer " + raw} if raw else {}
        with app.test_request_context(path, method=method, headers=header):
            with unittest.mock.patch.object(sec, "record_bad_behavior") as bad, \
                    unittest.mock.patch.object(sec, "check_rate_limit", return_value=rate_ok) as limited, \
                    unittest.mock.patch.object(sec, "is_locked_out", return_value=locked_out) as locked, \
                    unittest.mock.patch.object(sec, "get_reputation_score", return_value=score):
                allowed = sec._bot_request_allowed("203.0.113.8")
        return allowed, bad, limited, locked

    def test_an_expired_session_does_not_count_as_bad_behavior(self):
        from datetime import timedelta
        from app.utils.bot_policy import new_session_material
        raw, digest, _prefix = new_session_material()
        self.db.sessions.append({
            "id": 50,
            "key_id": 1,
            "session_hash": digest,
            "expires_at": self.db.now - timedelta(minutes=5),
            "last_used_at": self.db.now,
            "client_label": None,
        })
        allowed, bad, _limited, _locked = self._allowed(raw)
        self.assertTrue(allowed)
        bad.assert_not_called()

    def test_an_unknown_bearer_still_counts(self):
        allowed, bad, _limited, _locked = self._allowed("mvos_not_a_key_this_church_issued")
        self.assertTrue(allowed)
        bad.assert_called_once_with("203.0.113.8", "bad_bot_key")

    def test_a_live_session_skips_the_reputation_path(self):
        from app.utils.bot_policy import new_session_material
        raw, digest, _prefix = new_session_material()
        self.assertTrue(self.store.open_session(1, digest))
        allowed, bad, limited, _locked = self._allowed(raw)
        self.assertTrue(allowed)
        bad.assert_not_called()
        limited.assert_not_called()

    def test_a_dead_bearer_on_reset_request_is_not_an_attack(self):
        for raw in ("mvos_not_a_key_this_church_issued", ""):
            allowed, bad, limited, locked = self._allowed(
                raw,
                path="/api/bot/key/reset-request",
                method="POST",
                score=0,
                locked_out=True,
            )
            self.assertTrue(allowed, raw or "missing")
            bad.assert_not_called()
            locked.assert_not_called()
            limited.assert_called()

    def test_reset_request_still_stops_when_the_ip_is_too_fast(self):
        allowed, bad, _limited, _locked = self._allowed(
            "mvos_not_a_key_this_church_issued",
            path="/api/bot/key/reset-request",
            method="POST",
            score=0,
            rate_ok=False,
        )
        self.assertFalse(allowed)
        bad.assert_not_called()
