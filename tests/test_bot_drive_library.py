"""Google Drive message library bot calls. No database and no network."""

import os
import unittest
from unittest.mock import patch

from app.utils import bot_drive_library as lib
from app.utils import drive_write
from app.utils.bot_policy import (
    CLOSED,
    call_map,
    default_controls,
    help_payload,
    switch_by_id,
    undo_plan,
)
from app.utils.sermon_drive import extract_file_id, media_extension, media_kind

FILE = "1IBlvrocxD0lpGDl39t_n33bq93KgbFTr"
FOLDER = "1Q4lfrixsNDrWpvnT3SmXiDb2IjZedAU1"


class _Upload:
    def __init__(self, filename, payload=b"audio"):
        self.filename = filename
        self._payload = payload

    def read(self):
        return self._payload


class FileIdTests(unittest.TestCase):
    def test_file_links_and_bare_ids(self):
        self.assertEqual(extract_file_id(f"https://drive.google.com/file/d/{FILE}/view?usp=sharing"), FILE)
        self.assertEqual(extract_file_id(f"https://drive.google.com/file/d/{FILE}"), FILE)
        self.assertEqual(extract_file_id(f"https://drive.google.com/open?id={FILE}"), FILE)
        self.assertEqual(extract_file_id(f"https://drive.google.com/uc?id={FILE}&export=download"), FILE)
        self.assertEqual(extract_file_id(FILE), FILE)
        self.assertEqual(extract_file_id(f'"{FILE}"'), FILE)

    def test_rejected_shapes(self):
        self.assertIsNone(extract_file_id(None))
        self.assertIsNone(extract_file_id(""))
        self.assertIsNone(extract_file_id("not a link"))
        self.assertIsNone(extract_file_id(f"https://drive.google.com/drive/folders/{FOLDER}"))
        self.assertIsNone(extract_file_id(f"https://drive.google.com/file/d/{FILE}\r\n/view"))
        self.assertIsNone(extract_file_id(f"{FILE}\n{FILE}"))
        self.assertIsNone(extract_file_id("https://example.com/file/d/" + FILE))

    def test_media_kind(self):
        self.assertEqual(media_extension("VFC 11-8-26.m4a"), "m4a")
        self.assertEqual(media_extension("Sunday.MP4"), "mp4")
        self.assertIsNone(media_extension("notes.txt"))
        self.assertEqual(media_kind("a.m4a"), "audio")
        self.assertEqual(media_kind("a.mov"), "video")
        self.assertEqual(media_kind("a.txt"), "other")


class NameTests(unittest.TestCase):
    def test_pattern_matches_the_folder_mirror(self):
        name = lib.drive_filename(
            {"preached_on": "2026-11-08", "speaker": "Josh Villasenor", "title": "Hope That Holds"},
            "m4a",
        )
        self.assertEqual(name, "2026-11-08 - Josh Villasenor - Hope That Holds.m4a")

    def test_scripture_colon_survives_and_a_slash_does_not(self):
        name = lib.drive_filename(
            {"preached_on": "2026-11-08", "speaker": "Josh V", "title": "Hope / Holds",
             "summary": "Romans 5:1-5"},
            "m4a",
        )
        self.assertEqual(name, "2026-11-08 - Josh V - Hope Holds (Romans 5:1-5).m4a")

    def test_a_long_note_is_left_out(self):
        name = lib.drive_filename({"title": "Hope", "summary": "x" * 80}, "mp3")
        self.assertEqual(name, "Hope.mp3")


class FieldTests(unittest.TestCase):
    def test_unknown_field_is_refused(self):
        fields, problem = lib.clean_fields({"title": "Hope", "colour": "red"}, creating=True)
        self.assertIsNone(fields)
        self.assertEqual(problem["code"], "unknown_field")

    def test_title_is_required_on_create(self):
        fields, problem = lib.clean_fields({"speaker": "Josh"}, creating=True)
        self.assertIsNone(fields)
        self.assertIn("title", problem["error"].lower())

    def test_patch_does_not_require_a_title(self):
        fields, problem = lib.clean_fields({"series": "Hope"}, creating=False)
        self.assertIsNone(problem)
        self.assertEqual(fields, {"series": "Hope"})

    def test_date_aliases_must_agree(self):
        fields, problem = lib.clean_fields(
            {"title": "Hope", "date": "2026-11-08", "preached_on": "2026-11-09"}, creating=True,
        )
        self.assertIsNone(fields)
        self.assertEqual(problem["code"], "invalid_field")

    def test_summary_alias_and_published_flag(self):
        fields, problem = lib.clean_fields(
            {"title": "Hope", "description": "Romans 5:1-5", "published": "false"}, creating=True,
        )
        self.assertIsNone(problem)
        self.assertEqual(fields["summary"], "Romans 5:1-5")
        self.assertEqual(fields["hidden"], 1)

    def test_visibility_must_be_one_of_the_three(self):
        fields, problem = lib.clean_fields({"title": "Hope", "visibility": "everyone"}, creating=True)
        self.assertIsNone(fields)
        self.assertEqual(problem["status"], 400)

    def test_unknown_query_is_refused(self):
        result = lib.items({"colour": "red"})
        self.assertEqual(result["code"], "unknown_field")

    def test_hidden_filter_is_validated_before_any_read(self):
        result = lib.items({"hidden": "yes"})
        self.assertEqual(result["status"], 400)
        self.assertIn("hidden", result["error"])


class CreateTests(unittest.TestCase):
    def test_title_required_before_any_database(self):
        result = lib.create_item({"drive_url": f"https://drive.google.com/file/d/{FILE}/view"}, 7)
        self.assertEqual(result["status"], 400)
        self.assertIn("title", result["error"].lower())

    def test_folder_link_is_not_a_file(self):
        result = lib.create_item(
            {"title": "Hope", "drive_url": f"https://drive.google.com/drive/folders/{FOLDER}"}, 7,
        )
        self.assertEqual(result["code"], "invalid_file")

    def test_empty_drive_link_is_refused(self):
        result = lib.create_item({"title": "Hope"}, 7)
        self.assertEqual(result["code"], "invalid_file")

    def test_campus_is_not_silently_dropped(self):
        result = lib.create_item({"title": "Hope", "drive_url": FILE, "campus": "Odessa"}, 7)
        self.assertEqual(result["code"], "invalid_field")
        self.assertIn("campus", result["error"])

    def test_unknown_field_is_refused(self):
        result = lib.create_item({"title": "Hope", "drive_url": FILE, "colour": "red"}, 7)
        self.assertEqual(result["code"], "unknown_field")


class SourceAndSpeakerTests(unittest.TestCase):
    def test_a_file_link_is_not_a_folder(self):
        result = lib.add_source({"folder": f"https://drive.google.com/file/d/{FILE}/view"}, None)
        self.assertEqual(result["status"], 400)
        self.assertIn("folder", result["error"].lower())

    def test_unknown_source_field(self):
        result = lib.add_source({"folder": FOLDER, "name": "Sunday"}, None)
        self.assertEqual(result["code"], "unknown_field")

    def test_unknown_source_patch_field(self):
        result = lib.update_source(1, {"folder": FOLDER}, None)
        self.assertEqual(result["code"], "unknown_field")

    def test_speaker_needs_a_name(self):
        result = lib.add_speaker({}, None)
        self.assertEqual(result["status"], 400)
        self.assertIn("name", result["error"].lower())

    def test_unknown_speaker_field(self):
        result = lib.add_speaker({"voice": "Tim Lien"}, None)
        self.assertEqual(result["code"], "unknown_field")


class ViewTests(unittest.TestCase):
    def test_row_keeps_the_public_url_and_no_local_path(self):
        row = {
            "id": 114,
            "title": "Hope That Holds",
            "speaker_label": "Josh Villasenor",
            "speaker_id": 3,
            "scripture": "",
            "summary": "Romans 5:1-5",
            "series": "Hope",
            "preached_on": "2026-11-08",
            "visibility": "public",
            "hidden": 0,
            "kind": "audio",
            "source_id": 1,
            "source_label": "Church messages",
            "drive_file_id": FILE,
            "drive_name": "VFC 11-8-26.m4a",
            "missing_on_drive": 0,
            "site_edited": 1,
            "local_name": None,
        }
        payload = lib.view(row)
        self.assertEqual(payload["id"], 114)
        self.assertIn("/sermons/library/114", payload["url"])
        self.assertEqual(payload["speaker"], "Josh Villasenor")
        self.assertFalse(payload["hidden"])
        self.assertFalse(payload["has_copy"])
        self.assertNotIn("local_name", payload)
        self.assertNotIn("copy_path", payload)


class OffByDefaultTests(unittest.TestCase):
    def test_mode_defaults_to_off(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DRIVE_WRITE_MODE", None)
            self.assertEqual(drive_write.mode(), "off")
        with patch.dict(os.environ, {"DRIVE_WRITE_MODE": "service_account"}):
            self.assertEqual(drive_write.mode(), "service_account")
        with patch.dict(os.environ, {"DRIVE_WRITE_MODE": "nonsense"}):
            self.assertEqual(drive_write.mode(), "off")

    def test_off_is_a_clear_503(self):
        with patch.dict(os.environ, {"DRIVE_WRITE_MODE": "off"}):
            result = lib.upload({"title": "Hope"}, None, 7)
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], 503)
        self.assertEqual(result["code"], "drive_writes_off")
        self.assertIn("not turned on", result["error"])
        with patch.dict(os.environ, {"DRIVE_WRITE_MODE": "off"}):
            with self.assertRaises(drive_write.DriveWriteOff):
                drive_write.upload_media(FOLDER, "x.m4a", b"bytes", "audio/mp4")

    def test_missing_file_and_bad_type_are_refused(self):
        with patch.dict(os.environ, {"DRIVE_WRITE_MODE": "service_account"}):
            self.assertEqual(lib.upload({"title": "Hope"}, None, 7)["code"], "missing_file")
            self.assertEqual(
                lib.upload({"title": "Hope"}, {"file": _Upload("notes.txt")}, 7)["code"],
                "bad_file",
            )

    def test_oversize_file_is_413(self):
        with patch.dict(os.environ, {"DRIVE_WRITE_MODE": "service_account"}), \
                patch.object(lib.drive, "MAX_COPY_BYTES", 4):
            result = lib.upload({"title": "Hope"}, {"file": _Upload("x.m4a", b"123456")}, 7)
        self.assertEqual(result["status"], 413)


class PolicyTests(unittest.TestCase):
    def test_undo_plans(self):
        self.assertEqual(undo_plan("bot_drive_item_create", False), "hide")
        self.assertEqual(undo_plan("bot_drive_item_create", True), "show")
        self.assertEqual(undo_plan("bot_drive_upload", False), "hide")
        self.assertEqual(undo_plan("bot_drive_source_create", False), "hide")
        self.assertEqual(undo_plan("bot_drive_source_update", False), "restore")
        self.assertEqual(undo_plan("bot_drive_item_hide", False), "show")
        self.assertIsNone(undo_plan("bot_drive_refresh", False))

    def test_call_map_lists_the_library_calls_on_the_sermons_switch(self):
        calls = call_map(default_controls())
        paths = {call["path"] for call in calls}
        for path in (
            "/api/bot/sermons/library",
            "/api/bot/sermons/library/<id>",
            "/api/bot/sermons/library/sources",
            "/api/bot/sermons/library/sources/<id>",
            "/api/bot/sermons/library/refresh",
            "/api/bot/sermons/library/speakers",
            "/api/bot/sermons/library/upload",
        ):
            self.assertIn(path, paths)
        library = [call for call in calls if call["path"].startswith("/api/bot/sermons/library")]
        self.assertTrue(library)
        self.assertTrue(all(call["switch"] == "sermons" for call in library))

    def test_switch_and_help_are_honest(self):
        self.assertEqual(switch_by_id("sermons")["label"], "Public sermon library")
        self.assertIn("Drive", switch_by_id("sermons")["detail"])
        payload = help_payload(default_controls())
        self.assertIn("Drive file is never deleted", payload["undo"])
        self.assertTrue(any("message library" in line for line in CLOSED))


class RouteTests(unittest.TestCase):
    def test_the_new_routes_are_registered(self):
        from flask import Flask

        from app.routes.bot_access import bot_access_bp

        app = Flask(__name__)
        app.register_blueprint(bot_access_bp)
        rules = {(rule.rule, method) for rule in app.url_map.iter_rules()
                 for method in rule.methods if method in ("GET", "POST", "PATCH")}
        for rule, method in (
            ("/api/bot/sermons/library/sources", "GET"),
            ("/api/bot/sermons/library/sources", "POST"),
            ("/api/bot/sermons/library/sources/<int:source_id>", "POST"),
            ("/api/bot/sermons/library/refresh", "POST"),
            ("/api/bot/sermons/library", "GET"),
            ("/api/bot/sermons/library", "POST"),
            ("/api/bot/sermons/library/<int:item_id>", "GET"),
            ("/api/bot/sermons/library/<int:item_id>", "PATCH"),
            ("/api/bot/sermons/library/speakers", "GET"),
            ("/api/bot/sermons/library/speakers", "POST"),
            ("/api/bot/sermons/library/upload", "POST"),
        ):
            self.assertIn((rule, method), rules)

    def test_the_old_desk_routes_still_exist(self):
        from flask import Flask

        from app.routes.bot_access import bot_access_bp

        app = Flask(__name__)
        app.register_blueprint(bot_access_bp)
        rules = {rule.rule for rule in app.url_map.iter_rules()}
        self.assertIn("/api/bot/sermons/<int:sermon_id>", rules)
        self.assertIn("/api/bot/desk/<area>", rules)


if __name__ == "__main__":
    unittest.main()
