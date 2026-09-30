"""Offline regressions for redirect credentials and migration ownership."""

import hashlib
import json
import os
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

from nakedagent.llm import chat
from nakedagent.migrate_log import MigrationError, migrate
from nakedagent.replay import verify


class RedirectCredentialTests(unittest.TestCase):
    def make_request(self):
        # urlopen is replaced before chat runs: no sockets or real keys.
        with patch.dict(os.environ, {"NAKEDAGENT_P1_TEST_KEY": "inert-test-value"}), \
                patch("nakedagent.llm.urllib.request.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = (
                b'{"choices": [{"message": {"content": "ok"}}]}'
            )
            self.assertEqual(chat([], "fixture", "https://service.example.invalid/v1",
                                  api="openai", api_key_env="NAKEDAGENT_P1_TEST_KEY"), "ok")
        return urlopen.call_args.args[0]

    def test_initial_request_keeps_authorization(self):
        self.assertEqual(self.make_request().get_header("Authorization"),
                         "Bearer inert-test-value")

    def test_redirects_never_copy_authorization(self):
        request = self.make_request()
        handler = urllib.request.HTTPRedirectHandler()
        targets = (
            "https://other.example.invalid/completions",
            "http://service.example.invalid/completions",
            "https://service.example.invalid:8443/completions",
            # Same-origin redirects also drop credentials deliberately.
            "https://service.example.invalid/another-path",
        )
        for status in (301, 302, 303):
            for target in targets:
                with self.subTest(status=status, target=target):
                    redirected = handler.redirect_request(
                        request, None, status, "fixture redirect", {}, target)
                    self.assertIsNone(redirected.get_header("Authorization"))


class MigrationDestinationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "legacy.jsonl"
        self.dest = self.root / "converted.jsonl"

    def write_source(self, *, invalid_trailer=False):
        rows = [{"kind": "header", "version": "nakedagent.eventlog@v0.3",
                 "system_prompt": "fixture", "model": "fixture",
                 "workspace": "fixture", "max_steps": 5}]
        for number, (kind, payload) in enumerate((
                ("USER_INPUT", "hi"), ("MODEL_REPLY", "done"),
                ("TERMINATION", "MODEL_FINISHED")), start=1):
            rows.append({"kind": "event", "seq": number,
                         "event_type": kind, "payload": payload,
                         "metadata": {}, "state_hash": "0" * 64})
        rows.append({"kind": "final", "step_count": 99 if invalid_trailer else 3,
                     "state_hash": "0" * 64, "is_terminal": True,
                     "terminal_reason": "MODEL_FINISHED", "suspended": False})
        self.source.write_text("\n".join(json.dumps(row) for row in rows) + "\n",
                               encoding="utf-8")
        return self.source.read_bytes()

    def assert_existing_destination_preserved(self, dest):
        source_before = self.source.read_bytes()
        destination_before = dest.read_bytes()
        with self.assertRaises(FileExistsError):
            migrate(self.source, dest)
        self.assertEqual(self.source.read_bytes(), source_before)
        self.assertEqual(dest.read_bytes(), destination_before)

    def test_existing_destination_is_not_overwritten(self):
        self.write_source()
        self.dest.write_bytes(b"unrelated existing artifact\n")
        self.assert_existing_destination_preserved(self.dest)

    def test_failed_replay_does_not_delete_existing_destination(self):
        self.write_source(invalid_trailer=True)
        self.dest.write_bytes(b"unrelated existing artifact\n")
        self.assert_existing_destination_preserved(self.dest)

    def test_source_as_destination_is_untouched(self):
        self.write_source()
        self.assert_existing_destination_preserved(self.source)

    def test_hardlink_to_source_is_untouched(self):
        self.write_source()
        try:
            os.link(self.source, self.dest)
        except OSError as error:
            self.skipTest(f"hardlinks unavailable: {error}")
        self.assert_existing_destination_preserved(self.dest)
        self.assertTrue(self.source.samefile(self.dest))

    def test_symlink_to_source_is_untouched(self):
        self.write_source()
        try:
            self.dest.symlink_to(self.source)
        except OSError as error:
            self.skipTest(f"symlinks unavailable: {error}")
        self.assert_existing_destination_preserved(self.dest)
        self.assertTrue(self.dest.is_symlink())

    def test_new_destination_migrates_and_verifies(self):
        source_before = self.write_source()
        result = migrate(self.source, self.dest)
        self.assertTrue(result["is_terminal"])
        self.assertEqual(self.source.read_bytes(), source_before)
        header = json.loads(self.dest.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(header["extra"]["migrated_from"]["source_sha256"],
                         hashlib.sha256(source_before).hexdigest())
        ok, detail = verify(self.dest)
        self.assertTrue(ok, detail)

    def test_failed_new_destination_is_removed_and_source_preserved(self):
        source_before = self.write_source(invalid_trailer=True)
        with self.assertRaises(MigrationError):
            migrate(self.source, self.dest)
        self.assertFalse(self.dest.exists())
        self.assertEqual(self.source.read_bytes(), source_before)


if __name__ == "__main__":
    unittest.main()
