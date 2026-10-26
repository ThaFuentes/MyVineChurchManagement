"""Illustration field rules. No database."""

import unittest
from datetime import date

from app.utils.bot_illustration_fields import (
    blank_date,
    link_without_section,
    normalize_fact,
    normalize_kind,
    parse_scripture,
    passage_from,
    rewrite_tags,
)
from app.utils.bot_sermon_common import _parse_date


class IllustrationFieldTests(unittest.TestCase):
    def test_scripture_book_and_chapter(self):
        john = parse_scripture("John 3:16")
        self.assertEqual(john["book"], "John")
        self.assertEqual(john["chapter"], 3)
        self.assertIsNone(john["translation"])

        first = parse_scripture("1 John 1")
        self.assertEqual(first["book"], "1 John")
        self.assertEqual(first["chapter"], 1)

        psalm = parse_scripture("Psalm 23 (KJV)")
        self.assertEqual(psalm["book"], "Psalms")
        self.assertEqual(psalm["chapter"], 23)
        self.assertEqual(psalm["translation"], "KJV")

        alias = parse_scripture("Jn 3:16")
        self.assertEqual(alias["book"], "John")
        self.assertEqual(alias["chapter"], 3)

    def test_fact_and_kind(self):
        self.assertEqual(normalize_fact("needs review"), "needs_review")
        self.assertEqual(normalize_fact("verified"), "verified")
        self.assertEqual(normalize_kind("Bible"), "bible")
        self.assertEqual(normalize_kind("historical"), "historical")
        self.assertIsNone(normalize_fact("maybe"))
        self.assertIsNone(normalize_kind("poem"))

    def test_blank_dates_and_passage_alias(self):
        self.assertIsNone(blank_date(""))
        self.assertIsNone(blank_date("0000-00-00"))
        self.assertIsNone(blank_date("0000-00-00 00:00:00"))
        self.assertEqual(blank_date(date(2026, 10, 26)), "2026-10-26")
        self.assertEqual(_parse_date("0000-00-00"), (None, None))
        self.assertEqual(_parse_date(""), (None, None))

        self.assertEqual(passage_from({"primary_passage": "John 3", "passage": "Romans 8"}), ("John 3", True))
        self.assertEqual(passage_from({"primary_passage": "  ", "passage": "Romans 8"}), ("Romans 8", True))
        self.assertEqual(passage_from({"passage": "Romans 8"}), ("Romans 8", True))
        self.assertEqual(passage_from({}), (None, False))

    def test_link_needs_its_own_action(self):
        bare = link_without_section({"illustration_id": 4})
        self.assertIn("does not add a section", bare)
        self.assertIsNone(link_without_section({"section_id": 9, "illustration_id": 4}))
        self.assertIsNone(link_without_section({"illustration_id": 4, "insert": True}))
        self.assertIsNone(link_without_section({"title": "Point"}))

    def test_tag_rename_replaces_and_merges(self):
        renamed, changed = rewrite_tags(["Grace", "Faith"], ["grace"], "Mercy")
        self.assertTrue(changed)
        self.assertEqual(renamed, ["Mercy", "Faith"])
        merged, changed = rewrite_tags(["Grace", "Mercy", "Faith"], ["grace", "mercy"], "Hope")
        self.assertTrue(changed)
        self.assertEqual(merged, ["Hope", "Faith"])


if __name__ == "__main__":
    unittest.main()
