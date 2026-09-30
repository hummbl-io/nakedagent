"""Inert regressions for resume trailers and exact-byte legacy migration."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from nakedagent.driver import run_functional
from nakedagent.eventlog import open_log, read_log
from nakedagent.functional import AgentEvent, AgentState, agent_reducer
from nakedagent.loop import _system_prompt
from nakedagent.migrate_log import MigrationError, migrate
from nakedagent.replay import verify


class ResumeFinalIntegrityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.workspace = Path(temporary.name).resolve()
        self.log = self.workspace / "suspended.jsonl"
        self.tool = Mock(return_value="inert result")
        self.tools = {"probe": self.tool}
        # Mock's arbitrary attribute fabrication is not tool usage metadata.
        self.tool.usage = "```probe\nfixture\n```"
        prompt = _system_prompt(self.tools)
        state = AgentState.initial(prompt, policy={
            "model": "fixture", "workspace": str(self.workspace), "extra": {},
        })
        writer = open_log(self.log, system_prompt=prompt, model="fixture",
                          workspace=str(self.workspace))
        for event in (AgentEvent("USER_INPUT", "original task"),
                      AgentEvent("MODEL_REPLY", "```probe\nfixture\n```"),
                      AgentEvent("ESCALATE", "awaiting review")):
            state, _ = agent_reducer(state, event)
            writer.write_event(event, state.current_hash())
        writer.close(state.step_count, state.current_hash(), state.is_terminal,
                     state.terminal_reason, state.suspended)

    def mutate_final(self, **changes):
        rows = [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]
        rows[-1].update(changes)
        self.log.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    def assert_resume_refused(self):
        before = self.log.read_bytes()
        self.assertFalse(verify(self.log)[0], "fixture must fail standalone verification")
        provider = Mock(return_value="done")
        with patch("nakedagent.driver._build_tools", return_value=self.tools) as build:
            with self.assertRaises(RuntimeError):
                run_functional("approve", "fixture", self.workspace,
                               llm_fn=provider, event_log_path=self.log,
                               resume_from=self.log)
            build.assert_not_called()
        provider.assert_not_called()
        self.tool.assert_not_called()
        self.assertEqual(self.log.read_bytes(), before)

    def test_mismatched_final_count_is_refused_before_plugins(self):
        self.mutate_final(step_count=4)
        self.assert_resume_refused()

    def test_mismatched_final_hash_is_refused_before_plugins(self):
        self.mutate_final(state_hash="0" * 64)
        self.assert_resume_refused()

    def test_mismatched_final_reason_is_refused_before_plugins(self):
        self.mutate_final(terminal_reason="unexpected reason")
        self.assert_resume_refused()

    def test_inconsistent_final_status_remains_refused(self):
        self.mutate_final(is_terminal=True)
        self.assert_resume_refused()

    def test_valid_suspended_log_still_resumes(self):
        provider = Mock(return_value="done")
        with patch("nakedagent.driver._build_tools", return_value=self.tools) as build:
            state = run_functional("approve", "fixture", self.workspace,
                                   llm_fn=provider, event_log_path=self.log,
                                   resume_from=self.log)
            build.assert_called_once()
        provider.assert_called_once()
        self.assertTrue(state.is_terminal)
        self.assertEqual(state.step_count, 6)
        self.assertTrue(verify(self.log)[0])


class MigrationIntegrityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "legacy.jsonl"
        self.dest = self.root / "migrated.jsonl"

    def rows(self, payload="version A", version="nakedagent.eventlog@v0.3", suspended=False):
        rows = [{"kind": "header", "version": version,
                 "system_prompt": "fixture", "model": "fixture",
                 "workspace": "fixture", "max_steps": 8}]
        events = [("USER_INPUT", payload), ("MODEL_REPLY", "done"),
                  ("ESCALATE", "held") if suspended else ("TERMINATION", "MODEL_FINISHED")]
        for number, (kind, content) in enumerate(events, start=1):
            rows.append({"kind": "event", "seq": number, "event_type": kind,
                         "payload": content, "metadata": {}, "state_hash": "0" * 64})
        final = {"kind": "final", "step_count": 3, "state_hash": "0" * 64,
                 "is_terminal": not suspended,
                 "terminal_reason": None if suspended else "MODEL_FINISHED"}
        if version != "nakedagent.eventlog@v0.2":
            final["suspended"] = suspended
        rows.append(final)
        return rows

    def encoded(self, rows, newline="\n"):
        return (newline.join(json.dumps(row, ensure_ascii=False) for row in rows) + newline).encode("utf-8")

    def assert_order_refused(self, rows):
        before = self.encoded(rows)
        self.source.write_bytes(before)
        with patch("nakedagent.migrate_log.open_log", wraps=open_log) as create:
            with self.assertRaises(MigrationError):
                migrate(self.source, self.dest)
            create.assert_not_called()
        self.assertEqual(self.source.read_bytes(), before)
        self.assertFalse(self.dest.exists())

    def test_final_before_header_is_refused(self):
        rows = self.rows()
        self.assert_order_refused([rows[-1], *rows[:-1]])

    def test_final_before_first_event_is_refused(self):
        rows = self.rows()
        self.assert_order_refused([rows[0], rows[-1], *rows[1:-1]])

    def test_final_before_last_event_is_refused(self):
        rows = self.rows()
        self.assert_order_refused([*rows[:-2], rows[-1], rows[-2]])

    def test_duplicate_final_remains_refused(self):
        rows = self.rows()
        self.assert_order_refused([*rows, rows[-1]])

    def test_header_after_final_remains_refused(self):
        rows = self.rows()
        self.assert_order_refused([*rows, rows[0]])

    def test_digest_identifies_the_same_bytes_that_are_parsed(self):
        captured = self.encoded(self.rows("version A"))
        replacement = self.encoded(self.rows("version B"))
        self.source.write_bytes(captured)
        original_read = Path.read_bytes
        source_reads = []

        def capture_then_replace(path):
            data = original_read(path)
            if path == self.source:
                source_reads.append(data)
                path.write_bytes(replacement)
            return data

        with patch.object(Path, "read_bytes", capture_then_replace):
            migrate(self.source, self.dest)
        migrated = read_log(self.dest)
        self.assertEqual(migrated.events[0].payload, "version A")
        self.assertEqual(migrated.header["extra"]["migrated_from"]["source_sha256"],
                         hashlib.sha256(captured).hexdigest())
        self.assertEqual(source_reads, [captured])
        self.assertEqual(self.source.read_bytes(), replacement)
        self.assertTrue(verify(self.dest)[0])

    def test_legacy_newlines_and_literal_unicode_are_preserved(self):
        payload = "caf\u00e9\u2028separator\u0085still one JSON string"
        for number, newline in enumerate(("\n", "\r\n", "\r")):
            with self.subTest(newline=repr(newline)):
                source = self.encoded(self.rows(payload), newline)
                self.source.write_bytes(source)
                dest = self.root / f"newline-{number}.jsonl"
                migrate(self.source, dest)
                parsed = read_log(dest)
                self.assertEqual(parsed.events[0].payload, payload)
                self.assertEqual(parsed.header["extra"]["migrated_from"]["source_sha256"],
                                 hashlib.sha256(source).hexdigest())
                self.assertTrue(verify(dest)[0])

    def test_v02_terminal_and_v03_suspended_controls(self):
        cases = (("nakedagent.eventlog@v0.2", False),
                 ("nakedagent.eventlog@v0.3", True))
        for number, (version, suspended) in enumerate(cases):
            with self.subTest(version=version):
                source = self.encoded(self.rows(version=version, suspended=suspended))
                self.source.write_bytes(source)
                dest = self.root / f"control-{number}.jsonl"
                result = migrate(self.source, dest)
                self.assertEqual(result["suspended"], suspended)
                self.assertEqual(self.source.read_bytes(), source)
                self.assertTrue(verify(dest)[0])

    def test_legacy_blank_lines_remain_supported(self):
        source = b"\n" + self.encoded(self.rows()).replace(b"\n", b"\n \n")
        self.source.write_bytes(source)
        migrate(self.source, self.dest)
        self.assertTrue(verify(self.dest)[0])
