"""Course Creator calls: one tree edit, publish, enroll, copy, export, answers.

Pure checks do not touch the database. Database checks use the local church
app, write rows marked BOTCOURSE-20261026, and delete those rows at the end.
"""

import unittest

from app.utils.bot_areas import course_save
from app.utils.bot_policy import UNDO_STEPS, call_map

MARK = "BOTCOURSE-20261026"


class CourseRuleTests(unittest.TestCase):
    def test_dry_run_keeps_answer_keys_without_a_database(self):
        result = course_save(1, {
            "title": "T",
            "cover_image": "covers/hope.jpg",
            "dry_run": True,
            "lessons": [{
                "title": "Lesson",
                "blocks": [
                    {
                        "block_type": "fill",
                        "correct_answers": "Jesus|Christ",
                        "settings": {"reference": "John 3:16", "password": "nope"},
                    },
                    {
                        "block_type": "scripture",
                        "correct_answers_json": ["In the beginning"],
                        "scripture_reference": "Genesis 1:1",
                    },
                    {"block_type": "choice", "choices": [{"label": "Yes", "is_correct": True}]},
                    {"block_type": "truefalse"},
                ],
            }],
        })
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["wrote"], 0)
        self.assertFalse(result.get("log"))
        self.assertEqual(result["data"]["course"]["cover_image"], "covers/hope.jpg")
        blocks = result["data"]["lessons"][0]["blocks"]
        self.assertEqual(blocks[0]["block_type"], "fill_blank")
        self.assertIn("Jesus", blocks[0]["correct_answers"])
        self.assertEqual(blocks[0]["settings"]["reference"], "John 3:16")
        self.assertNotIn("password", blocks[0]["settings"])
        self.assertEqual(blocks[1]["block_type"], "scripture")
        self.assertIn("In the beginning", blocks[1]["correct_answers"])
        self.assertEqual(blocks[1]["settings"]["reference"], "Genesis 1:1")
        self.assertEqual(blocks[2]["block_type"], "multiple_choice")
        self.assertEqual(blocks[3]["block_type"], "true_false")
        self.assertEqual(blocks[3]["choices"][0]["label"], "True")

    def test_empty_title_and_bad_status_fail_before_a_write(self):
        self.assertFalse(course_save(1, {})["ok"])
        self.assertFalse(course_save(1, {"title": "x", "status": "live"})["ok"])
        self.assertFalse(course_save(1, {"dry_run": True})["ok"])

    def test_help_lists_course_management_on_the_office_switch(self):
        calls = {(row["method"], row["path"]): row for row in call_map({})}
        for key in (
            ("POST", "/api/bot/courses"),
            ("POST", "/api/bot/courses/<id>"),
            ("POST", "/api/bot/courses/from-sermons"),
            ("POST", "/api/bot/courses/<id>/publish"),
            ("POST", "/api/bot/courses/<id>/duplicate"),
            ("POST", "/api/bot/courses/<id>/delete"),
            ("GET", "/api/bot/courses/<id>/export"),
            ("GET", "/api/bot/courses/<id>/progress"),
            ("POST", "/api/bot/courses/<id>/enroll"),
            ("POST", "/api/bot/courses/<id>/unenroll"),
            ("POST", "/api/bot/courses/<id>/lessons/reorder"),
            ("POST", "/api/bot/courses/<id>/lessons/<lesson_id>/delete"),
            ("GET", "/api/bot/courses/<id>/lessons/<lesson_id>/export"),
            ("POST", "/api/bot/courses/<id>/lessons/<lesson_id>/blocks/reorder"),
            ("POST", "/api/bot/courses/<id>/blocks/<block_id>/delete"),
        ):
            self.assertEqual(calls[key]["switch"], "office", key)
            self.assertFalse(calls[key]["allowed"], key)
        about = calls[("POST", "/api/bot/courses")]["about"]
        self.assertIn("study course", about.lower())
        self.assertIn("cover_image", about)
        self.assertIn("correct_answers", about)
        self.assertIn("fill_blank", about)
        self.assertIn("multiple_choice", about)
        self.assertIn("dry_run", about)
        for action in ("course.create", "course.update", "course.delete", "course.enroll"):
            self.assertNotIn(action, UNDO_STEPS)


class CourseDatabaseTests(unittest.TestCase):
    """Writes are limited to rows this class creates, then removed."""

    app = None
    ctx = None

    @classmethod
    def setUpClass(cls):
        from app import create_app
        cls.app = create_app()
        cls.ctx = cls.app.app_context()
        cls.ctx.push()
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
        cur.execute("SELECT id FROM curriculum_series WHERE title LIKE %s", (f"%{MARK}%",))
        series_ids = [int(row["id"]) for row in cur.fetchall() or []]
        for series_id in series_ids:
            cur.execute(
                """
                DELETE c FROM curriculum_choices c
                JOIN curriculum_blocks b ON b.id = c.block_id
                JOIN curriculum_lessons l ON l.id = b.lesson_id
                WHERE l.series_id=%s
                """,
                (series_id,),
            )
            cur.execute(
                """
                DELETE b FROM curriculum_blocks b
                JOIN curriculum_lessons l ON l.id = b.lesson_id
                WHERE l.series_id=%s
                """,
                (series_id,),
            )
            cur.execute("DELETE FROM curriculum_lessons WHERE series_id=%s", (series_id,))
            cur.execute("DELETE FROM curriculum_progress WHERE series_id=%s", (series_id,))
            cur.execute("DELETE FROM curriculum_enrollments WHERE series_id=%s", (series_id,))
            cur.execute("DELETE FROM sermon_series_links WHERE series_id=%s", (series_id,))
            cur.execute("DELETE FROM curriculum_series WHERE id=%s", (series_id,))
        cur.execute("SELECT id FROM pastoral_sermons WHERE title LIKE %s", (f"%{MARK}%",))
        for row in cur.fetchall() or []:
            sermon_id = int(row["id"])
            cur.execute("DELETE FROM sermon_sections WHERE sermon_id=%s", (sermon_id,))
            cur.execute("DELETE FROM sermon_series_links WHERE sermon_id=%s", (sermon_id,))
            cur.execute("DELETE FROM pastoral_sermons WHERE id=%s", (sermon_id,))

    def test_manage_a_course_then_remove_it(self):
        from app.utils.bot_areas import course_open
        from app.utils.bot_courses import (
            block_delete,
            course_delete,
            course_duplicate,
            course_enroll,
            course_export,
            course_progress,
            course_publish,
            course_unenroll,
            course_update,
            lesson_delete,
            lesson_export,
            lessons_reorder,
            blocks_reorder,
        )
        saved = course_save(1, {
            "title": MARK,
            "cover_image": "covers/hope.jpg",
            "lessons": [{
                "title": "Lesson A",
                "blocks": [
                    {
                        "block_type": "fill",
                        "title": "Who",
                        "correct_answers": "Jesus|Christ",
                        "settings": {"reference": "John 3:16"},
                    },
                    {
                        "block_type": "scripture",
                        "body": "In the beginning",
                        "correct_answers_json": ["God"],
                        "scripture_reference": "Genesis 1:1",
                    },
                ],
            }],
        })
        self.assertTrue(saved["ok"], saved.get("error"))
        series_id = int(saved["data"]["course"]["id"])
        self.assertEqual(saved["data"]["course"]["cover_image"], "covers/hope.jpg")
        opened = course_open(series_id)
        blocks = opened["data"]["lessons"][0]["blocks"]
        self.assertEqual(blocks[0]["block_type"], "fill_blank")
        self.assertIn("Jesus", blocks[0]["correct_answers"])
        self.assertEqual(blocks[0]["settings"]["reference"], "John 3:16")
        self.assertEqual(blocks[1]["block_type"], "scripture")
        self.assertIn("God", blocks[1]["correct_answers"])
        self.assertEqual(blocks[1]["settings"]["reference"], "Genesis 1:1")
        lesson_a = int(opened["data"]["lessons"][0]["id"])
        block_ids = [int(block["id"]) for block in blocks]

        preview = course_update(1, series_id, {
            "dry_run": True,
            "lessons": [{"title": "Lesson B"}],
        })
        self.assertTrue(preview["ok"], preview.get("error"))
        self.assertEqual(preview["data"]["wrote"], 0)
        self.assertFalse(preview.get("log"))
        self.assertEqual(len(course_open(series_id)["data"]["lessons"]), 1)

        added = course_update(1, series_id, {"lessons": [{"title": "Lesson B", "blocks": [{"block_type": "text", "body": "Second"}]}]})
        self.assertTrue(added["ok"], added.get("error"))
        self.assertEqual(added["log"]["action"], "course.update")
        self.assertNotIn("hard", added["log"]["snapshot"])
        lessons = course_open(series_id)["data"]["lessons"]
        self.assertEqual(sorted(lesson["title"] for lesson in lessons), ["Lesson A", "Lesson B"])
        lesson_b = int(next(lesson["id"] for lesson in lessons if lesson["title"] == "Lesson B"))

        refused = course_update(1, series_id, {
            "replace": True,
            "lessons": [{"id": lesson_b, "title": "Lesson B"}],
        }, hard_on=False)
        self.assertEqual(refused.get("status"), 403)
        self.assertEqual(refused.get("code"), "hard_delete")
        self.assertEqual(len(course_open(series_id)["data"]["lessons"]), 2)

        ordered = lessons_reorder(1, series_id, {"ids": [lesson_b, lesson_a]})
        self.assertTrue(ordered["ok"], ordered.get("error"))
        self.assertEqual(
            [int(lesson["id"]) for lesson in course_open(series_id)["data"]["lessons"]],
            [lesson_b, lesson_a],
        )
        flipped = blocks_reorder(1, series_id, lesson_a, {"ids": list(reversed(block_ids))})
        self.assertTrue(flipped["ok"], flipped.get("error"))
        seen = [int(block["id"]) for block in course_open(series_id)["data"]["lessons"][1]["blocks"]]
        self.assertEqual(seen, list(reversed(block_ids)))

        published = course_publish(1, series_id, {})
        self.assertTrue(published["ok"], published.get("error"))
        self.assertEqual(published["data"]["course"]["status"], "published")
        self.assertTrue(all(lesson["status"] == "published" for lesson in published["data"]["lessons"]))

        copied = course_duplicate(1, series_id, {})
        self.assertTrue(copied["ok"], copied.get("error"))
        self.assertEqual(copied["data"]["course"]["status"], "draft")
        self.assertIn("(Copy)", copied["data"]["course"]["title"])
        self.assertEqual(copied["data"]["course"]["cover_image"], "covers/hope.jpg")
        copy_blocks = []
        for lesson in copied["data"]["lessons"]:
            copy_blocks.extend(lesson["blocks"])
        fill = next(block for block in copy_blocks if block["block_type"] == "fill_blank")
        self.assertIn("Jesus", fill["correct_answers"])

        missing_person = course_enroll(1, series_id, {"user_id": 999999999})
        self.assertEqual(missing_person.get("status"), 404)
        missing_group = course_enroll(1, series_id, {"group_id": 999999999})
        self.assertEqual(missing_group.get("status"), 404)
        enrolled = course_enroll(1, series_id, {"user_id": 1})
        self.assertTrue(enrolled["ok"], enrolled.get("error"))
        self.assertEqual(enrolled["data"]["enrolled"], 1)
        report = course_progress(series_id)
        self.assertTrue(report["ok"], report.get("error"))
        person = report["data"]["people"][0]
        self.assertEqual(person["user_id"], 1)
        self.assertTrue(person["name"])
        self.assertEqual(person["answered"], 0)
        self.assertNotIn("answer_json", person)
        self.assertNotIn("email", person)
        self.assertGreaterEqual(report["data"]["series_stats"]["enrolled"], 1)
        removed = course_unenroll(1, series_id, {"user_id": 1})
        self.assertTrue(removed["ok"], removed.get("error"))
        self.assertEqual(course_progress(series_id)["data"]["count"], 0)

        exported = course_export(series_id)
        self.assertTrue(exported["download"]["bytes"].startswith(b"#"))
        self.assertIn("Jesus", exported["download"]["bytes"].decode("utf-8"))
        self.assertEqual(exported["download"]["mimetype"], "text/markdown; charset=utf-8")
        self.assertEqual(exported["log"]["action"], "course.export")
        lesson_file = lesson_export(series_id, lesson_a)
        self.assertTrue(lesson_file["download"]["bytes"].startswith(b"#"))

        kept = course_update(1, series_id, {
            "lessons": [{"id": lesson_a, "blocks": [{"id": block_ids[0], "delete": True}]}],
        }, hard_on=False)
        self.assertEqual(kept.get("status"), 403)
        still = [int(block["id"]) for block in course_open(series_id)["data"]["lessons"][1]["blocks"]]
        self.assertIn(block_ids[0], still)

        gone = block_delete(1, series_id, block_ids[0], {"confirm": f"DELETE {block_ids[0]}"}, hard_on=True)
        self.assertTrue(gone["ok"], gone.get("error"))
        self.assertTrue(gone["log"]["snapshot"]["hard"])
        after = [int(block["id"]) for block in course_open(series_id)["data"]["lessons"][1]["blocks"]]
        self.assertNotIn(block_ids[0], after)

        blocked = lesson_delete(1, series_id, lesson_b, {}, hard_on=False)
        self.assertEqual(blocked.get("status"), 403)
        self.assertEqual(len(course_open(series_id)["data"]["lessons"]), 2)
        deleted_lesson = lesson_delete(
            1, series_id, lesson_b, {"confirm": f"DELETE {lesson_b}"}, hard_on=True,
        )
        self.assertTrue(deleted_lesson["ok"], deleted_lesson.get("error"))
        self.assertEqual(len(course_open(series_id)["data"]["lessons"]), 1)

        blocked_course = course_delete(1, series_id, {}, hard_on=False)
        self.assertEqual(blocked_course.get("status"), 403)
        self.assertTrue(course_open(series_id)["ok"])
        removed_course = course_delete(1, series_id, {"confirm": f"DELETE {series_id}"}, hard_on=True)
        self.assertTrue(removed_course["ok"], removed_course.get("error"))
        self.assertTrue(removed_course["log"]["snapshot"]["hard"])
        self.assertEqual(course_open(series_id).get("status"), 404)
        copy_id = int(copied["data"]["course"]["id"])
        self.assertTrue(course_delete(1, copy_id, {"confirm": f"DELETE {copy_id}"}, hard_on=True)["ok"])

    def test_sermons_become_lessons(self):
        from app.utils.bot_areas import course_open
        from app.utils.bot_courses import course_delete, course_from_sermons
        from app.utils.bot_sermon_common import _db
        cur = _db().cursor()
        cur.execute(
            """
            INSERT INTO pastoral_sermons
                (title, primary_passage, notes, visibility, created_by)
            VALUES (%s, %s, %s, 'private', 1)
            """,
            (f"{MARK} sermon", "John 3:16", "A short note"),
        )
        sermon_id = int(cur.lastrowid)
        cur.execute(
            """
            INSERT INTO sermon_sections
                (sermon_id, sort_order, section_type, title, content, scripture_reference)
            VALUES (%s, 0, 'point', 'Point', 'God so loved the world', 'John 3:16')
            """,
            (sermon_id,),
        )
        preview = course_from_sermons(1, {
            "sermon_ids": [sermon_id],
            "title": f"{MARK} course",
            "dry_run": True,
        })
        self.assertTrue(preview["ok"], preview.get("error"))
        self.assertEqual(preview["data"]["wrote"], 0)
        self.assertFalse(preview.get("log"))
        cur.execute("SELECT COUNT(*) AS n FROM curriculum_series WHERE title=%s", (f"{MARK} course",))
        self.assertEqual(int(cur.fetchone()["n"]), 0)
        made = course_from_sermons(1, {"sermon_ids": [sermon_id], "title": f"{MARK} course"})
        self.assertTrue(made["ok"], made.get("error"))
        self.assertEqual(made["data"]["course"]["status"], "draft")
        self.assertEqual(made["log"]["action"], "course.from_sermons")
        lesson = made["data"]["lessons"][0]
        self.assertEqual(lesson["title"], f"{MARK} sermon")
        self.assertEqual(lesson["summary"], "John 3:16")
        self.assertEqual(lesson["blocks"][0]["block_type"], "scripture")
        self.assertEqual(lesson["blocks"][0]["settings"]["reference"], "John 3:16")
        self.assertIn("loved", lesson["blocks"][0]["body"])
        series_id = int(made["data"]["course"]["id"])
        self.assertTrue(course_open(series_id)["ok"])
        self.assertTrue(course_delete(1, series_id, {"confirm": f"DELETE {series_id}"}, hard_on=True)["ok"])
