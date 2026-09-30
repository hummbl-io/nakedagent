"""Regression coverage for audit-path and protected-directory boundaries."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nakedagent.tools import tool_patch, tool_shell, tool_write


class TestAuditPathBoundary(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.outside = self.root / "outside"
        self.outside.mkdir()

    def link(self, link, target, *, directory=False):
        try:
            link.symlink_to(target, target_is_directory=directory)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlink creation unavailable: {exc}")

    def denied_call(self):
        # No process is started: these calls stop at the --allow-shell gate.
        with patch("nakedagent.tools.sys.stdin.isatty", return_value=False):
            result = tool_shell("", "inert-audit-marker", self.workspace)
        self.assertIn("requires --allow-shell", result)

    def test_log_file_symlink_does_not_append_to_external_file(self):
        external = self.outside / "sentinel.txt"
        external.write_bytes(b"untouched\n")
        audit_dir = self.workspace / ".nakedagent"
        audit_dir.mkdir()
        self.link(audit_dir / "shell_audit.jsonl", external)
        self.denied_call()
        self.assertEqual(external.read_bytes(), b"untouched\n")

    def test_parent_symlink_does_not_append_to_external_log(self):
        external = self.outside / "shell_audit.jsonl"
        external.write_bytes(b"untouched\n")
        self.link(self.workspace / ".nakedagent", self.outside, directory=True)
        self.denied_call()
        self.assertEqual(external.read_bytes(), b"untouched\n")

    def test_parent_symlink_does_not_create_external_log(self):
        self.link(self.workspace / ".nakedagent", self.outside, directory=True)
        self.denied_call()
        self.assertFalse((self.outside / "shell_audit.jsonl").exists())

    @unittest.skipUnless(os.name == "nt", "Windows junction regression")
    def test_parent_junction_does_not_append_to_external_log(self):
        import _winapi

        external = self.outside / "shell_audit.jsonl"
        external.write_bytes(b"untouched\n")
        _winapi.CreateJunction(str(self.outside), str(self.workspace / ".nakedagent"))
        self.denied_call()
        self.assertEqual(external.read_bytes(), b"untouched\n")

    def test_regular_log_still_records_denied_calls(self):
        self.denied_call()
        self.denied_call()
        audit = self.workspace / ".nakedagent" / "shell_audit.jsonl"
        events = [json.loads(line) for line in audit.read_text().splitlines()]
        self.assertEqual(len(events), 2)
        self.assertTrue(all(event["allowed"] is False for event in events))


class TestProtectedDirectoryAliases(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name)

    @unittest.skipUnless(os.name == "nt", "Windows filesystem alias regression")
    def test_write_rejects_absent_uppercase_nakedagent(self):
        result = tool_write(".NAKEDAGENT/plugins/inert.py", "TOOLS = {}\n", self.workspace)
        self.assertIn("protected directory", result)
        self.assertFalse((self.workspace / ".nakedagent").exists())

    @unittest.skipUnless(os.name == "nt", "Windows filesystem alias regression")
    def test_write_rejects_absent_uppercase_git(self):
        result = tool_write(".GIT/config", "inert = true\n", self.workspace)
        self.assertIn("protected directory", result)
        self.assertFalse((self.workspace / ".git").exists())

    @unittest.skipUnless(os.name == "nt", "Windows filesystem alias regression")
    def test_patch_rejects_existing_uppercase_protected_directory(self):
        target = self.workspace / ".NAKEDAGENT" / "config.txt"
        target.parent.mkdir()
        target.write_bytes(b"old\n")
        block = "<<<<<<< SEARCH\nold\n=======\nnew\n>>>>>>> REPLACE"
        result = tool_patch(".nakedagent/config.txt", block, self.workspace)
        self.assertIn("protected directory", result)
        self.assertEqual(target.read_bytes(), b"old\n")

    @unittest.skipIf(os.name == "nt", "POSIX case-sensitive spelling")
    def test_posix_uppercase_directory_remains_writable(self):
        result = tool_write(".NAKEDAGENT/notes.txt", "ordinary data", self.workspace)
        self.assertIn("Wrote", result)
        self.assertEqual(
            (self.workspace / ".NAKEDAGENT" / "notes.txt").read_text(),
            "ordinary data",
        )


if __name__ == "__main__":
    unittest.main()
