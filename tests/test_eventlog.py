"""Tests for JSONL event-log persistence."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from nakedagent.eventlog import (
    HASH_ALG,
    SCHEMA_VERSION,
    EventLogError,
    open_log,
    read_log,
)
from nakedagent.functional import AgentEvent


def _header(**over):
    """A minimal valid v0.2 header line."""
    h = {
        "kind": "header",
        "version": SCHEMA_VERSION,
        "hash_alg": HASH_ALG,
        "system_prompt": "s",
        "system_prompt_sha256": hashlib.sha256(b"s").hexdigest(),
        "max_steps": 25,
        "model": "m",
        "workspace": "w",
    }
    h.update(over)
    return json.dumps(h)


class TestEventLog(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "run.jsonl"
            w = open_log(
                path, system_prompt="SYS", model="m:1",
                workspace="/w", max_steps=9,
            )
            w.write_event(AgentEvent("USER_INPUT", "hi"), "h1")
            w.write_event(
                AgentEvent("MODEL_REPLY", "ok", {"k": "v"}), "h2"
            )
            w.close(2, "h2", True, "MODEL_FINISHED")

            log = read_log(path)
            self.assertEqual(log.header["version"], SCHEMA_VERSION)
            self.assertEqual(log.header["hash_alg"], HASH_ALG)
            self.assertEqual(log.header["system_prompt"], "SYS")
            self.assertEqual(log.header["max_steps"], 9)
            self.assertEqual(
                log.header["system_prompt_sha256"],
                hashlib.sha256(b"SYS").hexdigest(),
            )
            self.assertEqual(log.header["model"], "m:1")
            self.assertEqual(len(log.events), 2)
            self.assertEqual(log.events[0].event_type, "USER_INPUT")
            self.assertEqual(log.events[1].metadata, {"k": "v"})
            self.assertEqual(log.event_hashes, ["h1", "h2"])
            self.assertEqual(log.trailer["step_count"], 2)
            self.assertTrue(log.trailer["is_terminal"])

    def test_seq_numbers_increment(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "run.jsonl"
            w = open_log(path, system_prompt="s", model="m", workspace="w", max_steps=5)
            w.write_event(AgentEvent("USER_INPUT", "a"), "x")
            w.write_event(AgentEvent("USER_INPUT", "b"), "y")
            w.close(2, "y", False, None)
            seqs = [
                json.loads(l)["seq"]
                for l in path.read_text().splitlines()
                if json.loads(l)["kind"] == "event"
            ]
            self.assertEqual(seqs, [1, 2])

    def test_write_after_close_raises(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "run.jsonl"
            w = open_log(path, system_prompt="s", model="m", workspace="w", max_steps=5)
            w.close(0, "h", False, None)
            with self.assertRaises(EventLogError):
                w.write_event(AgentEvent("USER_INPUT", "x"), "h")

    def test_malformed_line_reports_lineno(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "bad.jsonl"
            path.write_text(_header() + "\n" + "not-json\n")
            with self.assertRaises(EventLogError) as cm:
                read_log(path)
            self.assertIn(":2:", str(cm.exception))

    def test_missing_header_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "nohead.jsonl"
            path.write_text(
                '{"kind": "event", "seq": 1, "event_type": "USER_INPUT", '
                '"payload": "x", "state_hash": "h"}\n'
            )
            with self.assertRaises(EventLogError):
                read_log(path)

    def test_event_missing_field_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "miss.jsonl"
            path.write_text(
                _header() + "\n"
                '{"kind": "event", "seq": 1, "event_type": "USER_INPUT", '
                '"payload": "x"}\n'
            )
            with self.assertRaises(EventLogError) as cm:
                read_log(path)
            self.assertIn("state_hash", str(cm.exception))


class TestV02HeaderValidation(unittest.TestCase):
    """v0.2 strictness: version, hash_alg, max_steps, prompt sha."""

    def _write(self, td, header_line, *body_lines):
        path = Path(td) / "run.jsonl"
        path.write_text(header_line + "\n" + "\n".join(body_lines) + "\n")
        return path

    def test_v01_log_refused(self):
        with tempfile.TemporaryDirectory() as td:
            # A syntactically fine v0.1 log must still be refused: its seals
            # were computed under a different algorithm.
            path = self._write(
                td,
                json.dumps({
                    "kind": "header", "version": "nakedagent.eventlog@v0.1",
                    "system_prompt": "s", "model": "m", "workspace": "w",
                }),
                '{"kind": "event", "seq": 1, "event_type": "USER_INPUT", '
                '"payload": "x", "state_hash": "h"}',
            )
            with self.assertRaises(EventLogError) as cm:
                read_log(path)
            self.assertIn("v0.1", str(cm.exception))

    def test_unknown_version_refused(self):
        with tempfile.TemporaryDirectory() as td:
            path = self._write(td, _header(version="nakedagent.eventlog@v9.9"))
            with self.assertRaises(EventLogError) as cm:
                read_log(path)
            self.assertIn("unsupported", str(cm.exception))

    def test_wrong_hash_alg_refused(self):
        with tempfile.TemporaryDirectory() as td:
            path = self._write(td, _header(hash_alg="md5-concat"))
            with self.assertRaises(EventLogError) as cm:
                read_log(path)
            self.assertIn("hash_alg", str(cm.exception))

    def test_missing_max_steps_refused(self):
        with tempfile.TemporaryDirectory() as td:
            bad = _header()
            rec = json.loads(bad)
            del rec["max_steps"]
            path = self._write(td, json.dumps(rec))
            with self.assertRaises(EventLogError) as cm:
                read_log(path)
            self.assertIn("max_steps", str(cm.exception))

    def test_nonpositive_max_steps_refused(self):
        with tempfile.TemporaryDirectory() as td:
            path = self._write(td, _header(max_steps=0))
            with self.assertRaises(EventLogError):
                read_log(path)

    def test_missing_prompt_sha_refused(self):
        with tempfile.TemporaryDirectory() as td:
            rec = json.loads(_header())
            del rec["system_prompt_sha256"]
            path = self._write(td, json.dumps(rec))
            with self.assertRaises(EventLogError):
                read_log(path)

    def test_unknown_event_type_refused(self):
        with tempfile.TemporaryDirectory() as td:
            # Forward-compat: a v0.3+ log with a type we cannot replay must
            # be refused, not silently skipped.
            path = self._write(
                td, _header(),
                '{"kind": "event", "seq": 1, "event_type": "ESCALATE", '
                '"payload": "x", "state_hash": "h"}',
            )
            with self.assertRaises(EventLogError) as cm:
                read_log(path)
            self.assertIn("ESCALATE", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
