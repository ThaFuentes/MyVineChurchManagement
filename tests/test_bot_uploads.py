"""Picture uploads stay on the same savers as the site. No database."""

import unittest
from unittest.mock import patch

from flask import Flask

from app.utils.bot_uploads import save_upload


class _File:
    def __init__(self, filename):
        self.filename = filename
        self.saved = None

    def save(self, dest):
        self.saved = dest


class UploadPictureTests(unittest.TestCase):
    def test_place_and_missing_picture_are_refused(self):
        self.assertFalse(save_upload(1, "nope", None, {})["ok"])
        self.assertIn("lesson_id", save_upload(1, "course", None, {})["error"])
        self.assertIn("picture", save_upload(1, "course", None, {"lesson_id": "4"})["error"].lower())
        self.assertIn("option_id", save_upload(1, "giving", _File("a.png"), {})["error"])
        self.assertIn("song_id", save_upload(1, "song", None, {})["error"])
        self.assertIn("partner_id", save_upload(1, "partner", _File("a.png"), {})["error"])
        refused = save_upload(1, "login", _File("a.png"), {"surface": "welcome"})
        self.assertFalse(refused["ok"])
        self.assertIn("sign-in", refused["error"])
        other = save_upload(7, "page", _File("a.png"), {"scope": "member", "user_id": "99"})
        self.assertFalse(other["ok"])
        self.assertIn("account the owner chose", other["error"])
        self.assertIn("png", save_upload(1, "page", _File("notes.svg"), {"scope": "member"})["error"])

    def test_course_picture_lands_on_the_lesson(self):
        picture = _File("hope.png")
        app = Flask(__name__)
        with app.app_context(), \
             patch("app.utils.bot_uploads._one", return_value={"id": 4, "series_id": 2}), \
             patch("app.models.pastoral.curriculum.save_curriculum_upload", return_value="abc.png") as saved, \
             patch("app.models.pastoral.curriculum.create_block", return_value=9) as created:
            result = save_upload(1, "course", picture, {"lesson_id": "4"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["block_id"], 9)
        self.assertEqual(result["data"]["series_id"], 2)
        self.assertEqual(result["log"]["action"], "upload.course")
        saved.assert_called_once()
        self.assertEqual(saved.call_args.kwargs["kind"], "image")
        created.assert_called_once()
        self.assertEqual(created.call_args.args[0], 4)
        self.assertEqual(created.call_args.args[1]["media_path"], "abc.png")

    def test_church_page_photo_uses_the_page_saver(self):
        picture = _File("front.jpg")
        with patch("app.models.church_community.single_church_install", return_value=False), \
             patch("app.models.social.add_photo", return_value=(True, "Photo added.")) as added:
            result = save_upload(1, "page", picture, {
                "scope": "church", "slot": "photo", "campus_id": "3", "caption": "Sunday",
            })
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["owner_type"], "campus")
        self.assertEqual(result["data"]["owner_id"], 3)
        self.assertEqual(result["log"]["action"], "upload.page")
        added.assert_called_once()
        self.assertEqual(added.call_args.args[0], "campus")
        self.assertEqual(added.call_args.args[1], 3)

    def test_member_page_photo_stays_on_the_acting_account(self):
        picture = _File("me.png")
        with patch("app.models.social.add_photo", return_value=(True, "Photo added.")) as added:
            result = save_upload(7, "page", picture, {"scope": "member", "slot": "photo"})
        self.assertTrue(result["ok"], result)
        added.assert_called_once()
        self.assertEqual(added.call_args.args[0], "member")
        self.assertEqual(added.call_args.args[1], 7)
        with patch("app.utils.bot_uploads._one", return_value={"user_id": 7}), \
             patch("app.models.social.set_member_identity", return_value=(True, "Saved.")) as ident:
            portrait = save_upload(7, "page", picture, {"scope": "member", "slot": "avatar"})
        self.assertTrue(portrait["ok"], portrait)
        ident.assert_called_once()
        self.assertEqual(ident.call_args.args[0], 7)
        self.assertEqual(ident.call_args.args[1], "avatar")

    def test_wall_picture_is_a_post(self):
        picture = _File("wall.png")
        voice = {"user_id": 7, "posted_as": "member", "as": "user:7", "campus_id": 0}
        with patch("app.models.social.save_identity_file", return_value="p7_wall.png"), \
             patch("app.models.social.create_post", return_value=15) as created, \
             patch("app.models.church_community.record_posting") as stamped:
            result = save_upload(7, "post", picture, {"caption": "Door"}, voice=voice)
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["post_id"], 15)
        self.assertEqual(result["log"]["action"], "post.create")
        self.assertEqual(created.call_args.args[1], "image")
        self.assertEqual(created.call_args.kwargs["image_path"], "p7_wall.png")
        stamped.assert_called_once()


if __name__ == "__main__":
    unittest.main()
