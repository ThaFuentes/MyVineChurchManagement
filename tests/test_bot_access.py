"""Rules for the church bot. No database."""

import unittest

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
        self.assertIsNone(church)
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
