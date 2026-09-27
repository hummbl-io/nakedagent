"""Migration of v0.2/v0.3 event logs to the strict v0.4 contract.

The migrator replays legacy events through the current reducer and re-seals
under v0.4. It must refuse inconsistent sources rather than launder them into
valid-looking logs.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from nakedagent.eventlog import read_log
from nakedagent.functional import AgentEvent, AgentState, FunctionalMachine
from nakedagent.migrate_log import MigrationError, migrate


def _legacy_log(path: Path, version: str, events: list, *, trailer: dict | None,
                header_extra: dict | None = None) -> None:
    """Write a legacy-format log directly (loose v0.2/v0.3 records)."""
    header = {
        "kind": "header", "version": version, "hash_alg": "sha256-json-v2",
        "system_prompt": "sys",
        "system_prompt_sha256": __import__("hashlib").sha256(b"sys").hexdigest(),
        "model": "m", "workspace": "ws", "max_steps": 5,
    }
    if header_extra is not None:
        header["extra"] = header_extra
    lines = [json.dumps(header)]
    state = AgentState.initial("sys", max_steps=5)
    for i, ev in enumerate(events, start=1):
        state, _ = FunctionalMachine.step(state, ev)
        lines.append(json.dumps({
            "kind": "event", "seq": i, "event_type": ev.event_type,
            "payload": ev.payload,
            "metadata": dict(ev.metadata) if ev.metadata else {},
            "state_hash": "0" * 64,  # legacy hash: opaque to the migrator
        }))
    if trailer is not None:
        lines.append(json.dumps(trailer))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class MigrateLogTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.td = Path(self._td.name)
        self.addCleanup(self._td.cleanup)

    def _events(self):
        return [AgentEvent("USER_INPUT", "hi"),
                AgentEvent("MODEL_REPLY", "done"),
                AgentEvent("TERMINATION", "MODEL_FINISHED")]

    def _final(self, step_count, terminal=True, suspended=False, reason="MODEL_FINISHED"):
        return {"kind": "final", "step_count": step_count,
                "state_hash": "0" * 64, "is_terminal": terminal,
                "terminal_reason": reason, "suspended": suspended}

    def test_v02_terminal_migrates_and_replays(self):
        src = self.td / "old.jsonl"
        _legacy_log(src, "nakedagent.eventlog@v0.2", self._events(),
                    trailer=self._final(3))
        # v0.2 trailer had no `suspended` field
        lines = src.read_text().splitlines()
        t = json.loads(lines[-1]); del t["suspended"]
        src.write_text("\n".join(lines[:-1] + [json.dumps(t)]) + "\n")
        dst = self.td / "new.jsonl"
        summary = migrate(src, dst)
        self.assertEqual(summary["step_count"], 3)
        self.assertTrue(summary["is_terminal"])
        log = read_log(dst)  # strict v0.4 read
        self.assertEqual(log.header["version"], "nakedagent.eventlog@v0.4")
        prov = log.header["extra"]["migrated_from"]
        self.assertEqual(prov["version"], "nakedagent.eventlog@v0.2")
        self.assertEqual(len(prov["source_sha256"]), 64)
        # end-to-end replay verify through the CLI
        r = subprocess.run([sys.executable, "-m", "nakedagent.replay", str(dst)],
                           capture_output=True, text=True, check=False)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_v03_suspended_migrates_with_flag(self):
        src = self.td / "susp.jsonl"
        _legacy_log(src, "nakedagent.eventlog@v0.3",
                    [AgentEvent("USER_INPUT", "hi"),
                     AgentEvent("MODEL_REPLY", "```shell\nls\n```"),
                     AgentEvent("ESCALATE", "shell ls")],
                    trailer=self._final(3, terminal=False, suspended=True, reason=None))
        dst = self.td / "out.jsonl"
        summary = migrate(src, dst)
        self.assertTrue(summary["suspended"])
        self.assertFalse(summary["is_terminal"])
        log = read_log(dst)
        self.assertTrue(log.trailer["suspended"])

    def test_trailer_mismatch_refused_and_dest_removed(self):
        src = self.td / "bad.jsonl"
        _legacy_log(src, "nakedagent.eventlog@v0.3", self._events(),
                    trailer=self._final(3, terminal=False))  # lies: replay is terminal
        dst = self.td / "out.jsonl"
        with self.assertRaises(MigrationError):
            migrate(src, dst)
        self.assertFalse(dst.exists())

    def test_truncated_and_wrong_version_refused(self):
        src = self.td / "t.jsonl"
        _legacy_log(src, "nakedagent.eventlog@v0.3", self._events(), trailer=None)
        with self.assertRaises(MigrationError):
            migrate(src, self.td / "o.jsonl")
        _legacy_log(src, "nakedagent.eventlog@v0.4", [], trailer=self._final(0, reason=None))
        with self.assertRaises(MigrationError):
            migrate(src, self.td / "o2.jsonl")

    def test_suspended_stream_with_nonverdict_event_refused(self):
        src = self.td / "inv.jsonl"
        _legacy_log(src, "nakedagent.eventlog@v0.3",
                    [AgentEvent("USER_INPUT", "hi"),
                     AgentEvent("ESCALATE", "x"),
                     AgentEvent("MODEL_REPLY", "no verdict")],
                    trailer=self._final(3, terminal=False, suspended=True, reason=None))
        with self.assertRaises(MigrationError):
            migrate(src, self.td / "o.jsonl")

    def test_cli_refuses_overwrite(self):
        dst = self.td / "exists.jsonl"
        dst.write_text("x")
        r = subprocess.run(
            [sys.executable, "-m", "nakedagent.migrate_log",
             str(self.td / "nope.jsonl"), str(dst)],
            capture_output=True, text=True, check=False)
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
