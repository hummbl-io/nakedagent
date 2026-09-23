"""Tests for JSONL event-log persistence."""
import json
import tempfile
import unittest
from pathlib import Path

from nakedagent.eventlog import (
    SCHEMA_VERSION,
    EventLogError,
    open_log,
    read_log,
)
from nakedagent.functional import AgentEvent


class TestEventLog(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "run.jsonl"
            w = open_log(path, system_prompt="SYS", model="m:1", workspace="/w")
            w.write_event(AgentEvent("USER_INPUT", "hi"), "h1")
            w.write_event(
                AgentEvent("MODEL_REPLY", "ok", {"k": "v"}), "h2"
            )
            w.close(2, "h2", True, "MODEL_FINISHED")

            log = read_log(path)
            self.assertEqual(log.header["version"], SCHEMA_VERSION)
            self.assertEqual(log.header["system_prompt"], "SYS")
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
            w = open_log(path, system_prompt="s", model="m", workspace="w")
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
            w = open_log(path, system_prompt="s", model="m", workspace="w")
            w.close(0, "h", False, None)
            with self.assertRaises(EventLogError):
                w.write_event(AgentEvent("USER_INPUT", "x"), "h")

    def test_malformed_line_reports_lineno(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "bad.jsonl"
            path.write_text(
                '{"kind": "header", "version": "x", "system_prompt": "s"}\n'
                "not-json\n"
            )
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
                '{"kind": "header", "version": "x", "system_prompt": "s"}\n'
                '{"kind": "event", "seq": 1, "event_type": "USER_INPUT", '
                '"payload": "x"}\n'
            )
            with self.assertRaises(EventLogError) as cm:
                read_log(path)
            self.assertIn("state_hash", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
