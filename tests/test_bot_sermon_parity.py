"""Sermon Builder calls the church bot was missing.

Pure checks do not touch the database. The database checks use the local
church app, write rows marked BOTPARITY, and delete those rows at the end.
"""

import unittest

from app.utils.bot_illustration_fields import infer_fact, infer_kind
from app.utils.bot_policy import (
    READS,
    SWITCHES,
    call_map,
    default_controls,
    help_payload,
    undo_plan,
)
from app.utils.bot_sermon_common import (
    SECTION_BODY_CAP,
    TEXT_CAP,
    as_html,
    normalize_section_list,
    section_html,
)

MARK = "BOTPARITY-20261026"


class SermonParityRulesTests(unittest.TestCase):
    def test_section_body_is_longer_than_the_old_cap(self):
        self.assertEqual(TEXT_CAP, 20000)
        self.assertGreaterEqual(SECTION_BODY_CAP, 1_000_000)
        self.assertEqual(as_html("John 3:16"), "<p>John 3:16</p>")
        long = "A" * 25000
        self.assertEqual(len(as_html(long)), len("<p></p>") + TEXT_CAP)
        stored = section_html(long)
        self.assertIn(long, stored)
        self.assertGreater(len(stored), TEXT_CAP)

    def test_bad_section_type_is_refused_before_a_write(self):
        rows, err = normalize_section_list([{"section_type": "poem", "content": "x"}])
        self.assertIsNone(rows)
        self.assertIn("section_type", err)
        good, err = normalize_section_list([
            {"section_type": "point", "title": "One", "content": "A" * 25000, "tags": ["hope", "grace"]},
        ])
        self.assertIsNone(err)
        self.assertEqual(len(good[0]["content"]), 25000)
        self.assertEqual(good[0]["tags"], "hope, grace")

    def test_help_documents_tags_and_the_longer_body(self):
        about = {
            row["path"]: row["about"]
            for row in call_map({})
            if row["method"] == "POST"
        }
        section = about["/api/bot/sermons/<id>/sections"]
        create = about["/api/bot/sermons"]
        self.assertIn("tags", section)
        self.assertIn("million", section)
        self.assertIn("dry_run", create)
        self.assertIn("sections", create)
        self.assertIn("template_id", create)
        text = "\n".join(help_payload({})["lines"])
        self.assertIn("tags", text)
        self.assertIn("/api/bot/sermons/<id>/collaborators", text)
        self.assertIn("/api/bot/capabilities", text)

    def test_new_switches_stay_off_and_are_not_read_areas(self):
        controls = default_controls()
        self.assertFalse(controls["sermon_ai"])
        self.assertFalse(controls["notifications"])
        kinds = {row["id"]: row["kind"] for row in SWITCHES}
        self.assertEqual(kinds["sermon_ai"], "sermon")
        self.assertEqual(kinds["notifications"], "sermon")
        self.assertNotIn("sermon_ai", READS)
        self.assertNotIn("notifications", READS)
        calls = {(row["method"], row["path"]): row for row in call_map({})}
        self.assertTrue(calls[("GET", "/api/bot/capabilities")]["allowed"])
        self.assertFalse(calls[("GET", "/api/bot/illustrations/<id>")]["allowed"])
        self.assertFalse(calls[("POST", "/api/bot/sermons/<id>/ai/<tool>")]["allowed"])
        self.assertIn("allowed", calls[("GET", "/api/bot/media")])

    def test_undo_hides_the_new_sermon_writes(self):
        self.assertEqual(undo_plan("bot_sermon_import", False), "hide")
        self.assertEqual(undo_plan("bot_sermon_note_illustration", False), "hide")
        self.assertEqual(undo_plan("bot_sermon_section_unhide", False), "hide")
        self.assertEqual(undo_plan("sermon.create", False), "hide")

    def test_kind_and_fact_check_come_from_tags_not_the_story(self):
        story = "A science story about a disputed historical testimony."
        self.assertEqual(infer_kind('["historical"]', story), "historical")
        self.assertEqual(infer_kind("science, hope", ""), "science")
        self.assertIsNone(infer_kind("", story))
        self.assertEqual(infer_fact("", "fact_check: verified"), "verified")
        self.assertEqual(infer_fact(["testimony"], story), "testimony")
        self.assertIsNone(infer_fact("", story))
        self.assertIsNone(infer_fact("disputed", ""))


class SermonParityDatabaseTests(unittest.TestCase):
    """Writes are limited to rows this class creates, then removed."""

    app = None
    ctx = None

    @classmethod
    def setUpClass(cls):
        from app import create_app
        cls.app = create_app()
        cls.ctx = cls.app.app_context()
        cls.ctx.push()
        cls.client = cls.app.test_client()
        cls.actor = 1
        cls.sermon_ids = []
        cls.template_ids = []
        cls.note_ids = []
        cls.illustration_ids = []
        cls.series_ids = []
        cls.public_sermon_ids = []
        cls.comment_ids = []
        cls.default_rows = []
        from app.utils.bot_sermon_common import ensure_soft_columns
        problem = ensure_soft_columns()
        if problem:
            raise RuntimeError(problem)

    @classmethod
    def tearDownClass(cls):
        try:
            cls._cleanup()
        finally:
            if cls.ctx is not None:
                cls.ctx.pop()

    @classmethod
    def _cleanup(cls):
        from app.utils.bot_sermon_common import _db
        cur = _db().cursor()
        for row_id, content in cls.default_rows:
            cur.execute(
                "UPDATE illustration_library SET content=%s WHERE id=%s",
                (content, row_id),
            )
        for sermon_id in cls.sermon_ids:
            cur.execute("DELETE FROM sermon_sections WHERE sermon_id=%s", (sermon_id,))
            cur.execute("DELETE FROM sermon_collaborators WHERE sermon_id=%s", (sermon_id,))
            cur.execute("DELETE FROM sermon_series_links WHERE sermon_id=%s", (sermon_id,))
            cur.execute("DELETE FROM pastoral_sermons WHERE id=%s AND title LIKE %s", (sermon_id, MARK + "%"))
        for template_id in cls.template_ids:
            cur.execute("DELETE FROM sermon_templates WHERE id=%s", (template_id,))
        for note_id in cls.note_ids:
            cur.execute("DELETE FROM sermon_prep_notes WHERE id=%s", (note_id,))
        for illus_id in cls.illustration_ids:
            cur.execute("DELETE FROM illustration_tag_links WHERE illustration_id=%s", (illus_id,))
            cur.execute("DELETE FROM illustration_library WHERE id=%s", (illus_id,))
        for series_id in cls.series_ids:
            cur.execute("DELETE FROM sermon_series_links WHERE series_id=%s", (series_id,))
            cur.execute("DELETE FROM curriculum_series WHERE id=%s AND title LIKE %s", (series_id, MARK + "%"))
        for comment_id in cls.comment_ids:
            cur.execute("DELETE FROM sermon_comments WHERE id=%s", (comment_id,))
        for sermon_id in cls.public_sermon_ids:
            cur.execute("DELETE FROM sermons WHERE id=%s AND title LIKE %s", (sermon_id, MARK + "%"))

    def _count_sermons(self):
        from app.utils.bot_sermon_common import _db
        cur = _db().cursor()
        cur.execute("SELECT COUNT(*) AS n FROM pastoral_sermons")
        return int(cur.fetchone()["n"])

    def _staff_id(self):
        from app.utils.bot_sermon_common import _db
        cur = _db().cursor()
        cur.execute(
            """
            SELECT id FROM users
            WHERE role IN ('Owner', 'Admin') AND id<>%s
            ORDER BY id
            LIMIT 1
            """,
            (self.actor,),
        )
        row = cur.fetchone()
        return int(row["id"]) if row else None

    def test_missing_session_is_json(self):
        caps = self.client.get("/api/bot/capabilities")
        one = self.client.get("/api/bot/illustrations/1")
        for resp in (caps, one):
            self.assertEqual(resp.status_code, 401)
            self.assertEqual(resp.mimetype, "application/json")
            body = resp.get_json()
            self.assertFalse(body["ok"])
            self.assertTrue(body["error"])
        self.assertEqual(caps.get_json()["code"], "session_unknown")

    def test_dry_run_and_a_bad_section_write_nothing(self):
        from app.utils.bot_sermons import create_builder_sermon
        before = self._count_sermons()
        dry = create_builder_sermon(self.actor, {
            "title": MARK + " dry",
            "sections": [{"section_type": "point", "title": "One", "content": "Hello", "tags": "hope"}],
            "dry_run": True,
        })
        self.assertTrue(dry["ok"], dry)
        self.assertTrue(dry["data"]["dry_run"])
        self.assertEqual(dry["data"]["wrote"], 0)
        self.assertFalse(dry.get("log"))
        self.assertEqual(dry["data"]["sections"][0]["tags"], "hope")
        bad = create_builder_sermon(self.actor, {
            "title": MARK + " bad",
            "sections": [{"section_type": "poem", "content": "no"}],
        })
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["status"], 400)
        self.assertEqual(self._count_sermons(), before)

    def test_create_sections_defaults_template_tags_and_a_long_body(self):
        from app.utils.bot_sermon_common import _db
        from app.utils.bot_sermon_parity import delete_template, save_template, sermon_defaults
        from app.utils.bot_sermons import _DEFAULT_HEADER, create_builder_sermon, save_section, sermon_detail
        cur = _db().cursor()
        cur.execute(
            """
            SELECT id, content FROM illustration_library
            WHERE title=%s AND user_id=%s AND removed_at IS NULL
            """,
            (_DEFAULT_HEADER, self.actor),
        )
        before = {int(row["id"]): row.get("content") for row in cur.fetchall() or []}
        header = MARK + " header line"
        saved = sermon_defaults(self.actor, {"header": header}, True)
        self.assertTrue(saved["ok"], saved)
        self.assertTrue(saved["log"]["action"].startswith("bot_sermon_"))
        header_id = int(saved["data"]["header"]["illustration_id"])
        if header_id in before:
            self.default_rows.append((header_id, before[header_id]))
        else:
            self.illustration_ids.append(header_id)
        template = save_template(self.actor, {
            "name": MARK + " template",
            "sections": [{"section_type": "introduction", "title": "Open"}],
        })
        self.assertTrue(template["ok"], template)
        self.assertTrue(template["log"]["action"].startswith("bot_sermon_"))
        template_id = template["data"]["template_id"]
        self.template_ids.append(template_id)
        long = "B" * 25000
        created = create_builder_sermon(self.actor, {
            "title": MARK + " built",
            "visibility": "private",
            "use_default_header": True,
            "template_id": template_id,
            "sections": [{
                "section_type": "point",
                "title": "Long point",
                "content": long,
                "tags": ["hope", "grace"],
            }],
        })
        self.assertTrue(created["ok"], created)
        self.assertEqual(created["log"]["action"], "sermon.create")
        sermon_id = created["data"]["sermon_id"]
        self.sermon_ids.append(sermon_id)
        detail = sermon_detail(sermon_id, self.actor)
        self.assertTrue(detail["ok"], detail)
        self.assertIn(header, detail["data"].get("header_text") or "")
        sections = detail["data"]["sections"]
        self.assertEqual(len(sections), 1)
        self.assertIn(long, sections[0]["content"])
        self.assertEqual(sections[0].get("tags"), "hope, grace")
        changed = save_section(sermon_id, {
            "section_id": sections[0]["id"],
            "tags": "mercy",
            "content": "C" * 21000,
        }, self.actor)
        self.assertTrue(changed["ok"], changed)
        self.assertEqual(changed["log"]["action"], "section.update")
        self.assertNotIn("content", changed["data"])
        self.assertTrue(changed["data"]["content_stored"])
        self.assertGreater(changed["data"]["content_length"], TEXT_CAP)
        again = sermon_detail(sermon_id, self.actor)
        self.assertEqual(again["data"]["sections"][0]["tags"], "mercy")
        self.assertGreater(len(again["data"]["sections"][0]["content"]), TEXT_CAP)
        removed = delete_template(self.actor, template_id, {"confirm": f"DELETE {template_id}"})
        self.assertTrue(removed["ok"], removed)
        self.assertTrue(removed["log"]["action"].startswith("bot_sermon_"))

    def test_collaborator_note_export_bulk_and_comment(self):
        from app.utils.bot_sermon_parity import (
            add_collaborator,
            add_sermon_comment,
            bulk_sermons,
            export_sermon,
            list_collaborators,
            note_to_illustration,
            remove_collaborator,
            save_note,
        )
        from app.utils.bot_sermons import create_builder_sermon
        from app.utils.bot_sermon_common import _db
        created = create_builder_sermon(self.actor, {
            "title": MARK + " desk",
            "visibility": "private",
            "sections": [{"section_type": "point", "title": "Desk", "content": "Short"}],
        })
        self.assertTrue(created["ok"], created)
        sermon_id = created["data"]["sermon_id"]
        self.sermon_ids.append(sermon_id)
        staff = self._staff_id()
        self.assertIsNotNone(staff)
        added = add_collaborator(sermon_id, {"user_id": staff}, self.actor)
        self.assertTrue(added["ok"], added)
        self.assertEqual(added["log"]["action"], "bot_sermon_collab_add")
        listed = list_collaborators(sermon_id, self.actor)
        self.assertIn(staff, [row["user_id"] for row in listed["data"]["collaborators"]])
        gone = remove_collaborator(sermon_id, staff, self.actor)
        self.assertTrue(gone["ok"], gone)
        self.assertEqual(gone["log"]["action"], "bot_sermon_collab_remove")
        note = save_note(self.actor, {"body": MARK + " a note to keep", "sermon_id": sermon_id}, None)
        self.assertTrue(note["ok"], note)
        self.assertTrue(note["log"]["action"].startswith("bot_sermon_"))
        note_id = note["data"]["note_id"]
        self.note_ids.append(note_id)
        copied = note_to_illustration(self.actor, note_id, {
            "title": MARK + " from note",
            "visibility": "private",
            "confirm_duplicate": True,
        })
        self.assertTrue(copied["ok"], copied)
        self.assertEqual(copied["log"]["action"], "bot_sermon_note_illustration")
        self.illustration_ids.append(copied["data"]["illustration_id"])
        exported = export_sermon(sermon_id, self.actor, "txt")
        self.assertTrue(exported["ok"], exported)
        self.assertEqual(exported["log"]["action"], "bot_sermon_export")
        self.assertIn(MARK.encode(), exported["download"]["bytes"])
        pdf = export_sermon(sermon_id, self.actor, "pdf")
        self.assertTrue(pdf["download"]["bytes"].startswith(b"%PDF"))
        hidden = bulk_sermons(self.actor, {"ids": [sermon_id], "action": "hide"}, hard_on=False)
        self.assertTrue(hidden["ok"], hidden)
        self.assertEqual(hidden["log"]["action"], "bot_sermon_bulk_hide")
        cur = _db().cursor()
        cur.execute("SELECT removed_at FROM pastoral_sermons WHERE id=%s", (sermon_id,))
        self.assertIsNotNone(cur.fetchone()["removed_at"])
        shown = bulk_sermons(self.actor, {"ids": [sermon_id], "action": "unhide"}, hard_on=False)
        self.assertTrue(shown["ok"], shown)
        blocked = bulk_sermons(
            self.actor,
            {"ids": [sermon_id], "action": "delete", "confirm": f"DELETE {sermon_id}"},
            hard_on=False,
        )
        self.assertFalse(blocked["ok"])
        self.assertEqual(blocked["status"], 403)
        self.assertEqual(blocked["code"], "hard_delete")
        cur.execute("SELECT id FROM pastoral_sermons WHERE id=%s", (sermon_id,))
        self.assertIsNotNone(cur.fetchone())
        cur.execute(
            """
            INSERT INTO sermons (title, notes, details, sermon_file, external_link, visibility, uploaded_by)
            VALUES (%s, '', '', '', NULL, 'public', %s)
            """,
            (MARK + " public", self.actor),
        )
        public_id = int(cur.lastrowid)
        self.public_sermon_ids.append(public_id)
        comment = add_sermon_comment(public_id, {"body": MARK + " amen"}, self.actor, "Owner")
        self.assertTrue(comment["ok"], comment)
        self.assertEqual(comment["log"]["action"], "bot_comment_reply")
        self.comment_ids.append(comment["data"]["comment_id"])
        missing = add_sermon_comment(99999999, {"body": "no"}, self.actor, "Owner")
        self.assertEqual(missing["status"], 404)

    def test_backfill_reads_a_tag_and_a_verse_line(self):
        from app.utils.bot_sermon_common import _db, backfill_illustration_fields
        cur = _db().cursor()
        cur.execute(
            """
            INSERT INTO illustration_library
                (user_id, title, content, source, tags, notes, scripture_reference)
            VALUES (%s, %s, %s, '', %s, '', %s)
            """,
            (self.actor, MARK + " illus", "A short story.", '["historical"]', "John 3:16"),
        )
        illus_id = int(cur.lastrowid)
        self.illustration_ids.append(illus_id)
        updated = backfill_illustration_fields()
        self.assertGreaterEqual(updated, 1)
        cur.execute(
            "SELECT scripture_book, scripture_chapter, kind, fact_check FROM illustration_library WHERE id=%s",
            (illus_id,),
        )
        row = cur.fetchone()
        self.assertEqual(row["scripture_book"], "John")
        self.assertEqual(int(row["scripture_chapter"]), 3)
        self.assertEqual(row["kind"], "historical")
        self.assertFalse(row["fact_check"])

    def test_series_link_stays_a_draft(self):
        from app.utils.bot_sermon_parity import list_series, save_series
        from app.utils.bot_sermons import create_builder_sermon
        created = create_builder_sermon(self.actor, {
            "title": MARK + " series sermon",
            "visibility": "private",
        })
        self.assertTrue(created["ok"], created)
        sermon_id = created["data"]["sermon_id"]
        self.sermon_ids.append(sermon_id)
        series = save_series(self.actor, {"title": MARK + " series", "sermon_id": sermon_id}, None)
        self.assertTrue(series["ok"], series)
        self.assertTrue(series["log"]["action"].startswith("bot_sermon_"))
        series_id = series["data"]["series_id"]
        self.series_ids.append(series_id)
        opened = list_series(self.actor, series_id)
        self.assertEqual(opened["data"]["status"], "draft")
        self.assertIn(sermon_id, opened["data"]["sermon_ids"])
