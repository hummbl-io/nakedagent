"""Patch integrity regressions using temporary files only."""

import tempfile
import unittest
from pathlib import Path

from nakedagent.tools import tool_patch


class TestPatchIntegrity(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.workspace = Path(temporary.name)
        self.target = self.workspace / "fixture.txt"
        self.original = b"old\n"
        self.target.write_bytes(self.original)

    def assert_refused_unchanged(self, block):
        original = self.target.read_bytes()
        result = tool_patch("fixture.txt", block, self.workspace)
        self.assertEqual(self.target.read_bytes(), original)
        self.assertIn("Error:", result)

    def test_invalid_utf8_is_refused_without_changing_unmatched_bytes(self):
        self.target.write_bytes(b"old\n# unrelated byte: \xff\n")
        self.assert_refused_unchanged(
            "<<<<<<< SEARCH\nold\n=======\nnew\n>>>>>>> REPLACE"
        )

    def test_valid_utf8_content_survives_patch(self):
        self.target.write_text("old\n# caf\u00e9 \u03c0\n", encoding="utf-8")
        result = tool_patch(
            "fixture.txt", "<<<<<<< SEARCH\nold\n=======\nnew\n>>>>>>> REPLACE",
            self.workspace,
        )
        self.assertIn("Patched", result)
        self.assertEqual(self.target.read_text(encoding="utf-8"), "new\n# caf\u00e9 \u03c0\n")

    def test_marker_shaped_replacement_line_is_preserved(self):
        result = tool_patch(
            "fixture.txt",
            "<<<<<<< SEARCH\nold\n=======\nbefore\n>>>>>>> example\nafter\n>>>>>>> REPLACE",
            self.workspace,
        )
        self.assertIn("Patched", result)
        self.assertEqual(
            self.target.read_text(encoding="utf-8"),
            "before\n>>>>>>> example\nafter\n",
        )

    def test_missing_exact_closing_marker_is_refused(self):
        self.assert_refused_unchanged(
            "<<<<<<< SEARCH\nold\n=======\nnew\n>>>>>>> example"
        )

    def test_missing_exact_opening_marker_is_refused(self):
        self.assert_refused_unchanged(
            "<<<<<<< example\nold\n=======\nnew\n>>>>>>> REPLACE"
        )

    def test_trailing_nonwhitespace_content_is_refused(self):
        self.assert_refused_unchanged(
            "<<<<<<< SEARCH\nold\n=======\nnew\n>>>>>>> REPLACE\nnot part of the patch"
        )

    def test_second_patch_block_is_refused_without_partial_edit(self):
        self.assert_refused_unchanged(
            "<<<<<<< SEARCH\nold\n=======\nnew\n>>>>>>> REPLACE\n"
            "<<<<<<< SEARCH\nnew\n=======\nlast\n>>>>>>> REPLACE"
        )

    def test_trailing_blank_lines_are_accepted(self):
        result = tool_patch(
            "fixture.txt",
            "<<<<<<< SEARCH\nold\n=======\nnew\n>>>>>>> REPLACE\n\n  \n",
            self.workspace,
        )
        self.assertIn("Patched", result)
        self.assertEqual(self.target.read_text(encoding="utf-8"), "new\n")


if __name__ == "__main__":
    unittest.main()
