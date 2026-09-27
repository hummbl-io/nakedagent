"""The v0.4 wire is explicit; older logs are never verified under it."""
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
from nakedagent.replay import verify


class TestEventLog(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "run.jsonl"

    def valid(self):
        writer = open_log(self.path, system_prompt="s", model="m", workspace="w", max_steps=5)
        writer.write_event(AgentEvent("USER_INPUT", "go"), "a" * 64)
        writer.write_event(AgentEvent("ESCALATE", "held", {"tool": "shell"}), "b" * 64)
        writer.close(2, "b" * 64, False, None, suspended=True)
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines()]

    def write(self, rows):
        self.path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    def test_round_trip_suspended_structure(self):
        self.valid()
        log = read_log(self.path)
        self.assertEqual(log.header["version"], SCHEMA_VERSION)
        self.assertEqual(log.header["hash_alg"], HASH_ALG)
        self.assertEqual([e.event_type for e in log.events], ["USER_INPUT", "ESCALATE"])
        self.assertEqual(log.trailer["suspended"], True)
        # Synthetic hashes are structurally valid but not computed.
        self.assertFalse(verify(self.path)[0])

    def test_write_after_close(self):
        self.valid()
        writer = open_log(self.path, system_prompt="s", model="m", workspace="w")
        writer.close(0, "a" * 64, True, "done")
        with self.assertRaises(EventLogError):
            writer.write_event(AgentEvent("USER_INPUT", "x"), "b" * 64)

    def test_legacy_versions_refused_explicitly(self):
        for version in ("nakedagent.eventlog@v0.2", "nakedagent.eventlog@v0.3"):
            with self.subTest(version=version):
                rows = self.valid()
                rows[0]["version"] = version
                self.write(rows)
                with self.assertRaisesRegex(EventLogError, "legacy"):
                    read_log(self.path)

    def test_unknown_versions_and_hash_algorithm_refused(self):
        for key, value, message in (("version", "nakedagent.eventlog@v9", "unsupported"),
                                    ("hash_alg", "other", "hash_alg")):
            with self.subTest(key=key):
                rows = self.valid()
                rows[0][key] = value
                self.write(rows)
                with self.assertRaisesRegex(EventLogError, message):
                    read_log(self.path)

    def test_nonstr_versions_fail_as_log_error(self):
        for version in ([], {}, None, 4):
            with self.subTest(version=version):
                rows = self.valid()
                rows[0]["version"] = version
                self.write(rows)
                with self.assertRaisesRegex(EventLogError, "version must be a string"):
                    read_log(self.path)
                ok, detail = verify(self.path)
                self.assertFalse(ok)
                self.assertIn("version must be a string", detail)

    def test_structural_mutations_refused(self):
        mutations = {
            "missing_header": lambda r: r.pop(0),
            "missing_final": lambda r: r.pop(),
            "duplicate_final": lambda r: r.append(r[-1].copy()),
            "wrong_seq": lambda r: r[1].update(seq=2),
            "missing_max_steps": lambda r: r[0].pop("max_steps"),
            "unknown_event": lambda r: r[1].update(event_type="FUTURE"),
            "unsealed_extra": lambda r: r[0].update(unknown="x"),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                rows = self.valid()
                mutate(rows)
                self.write(rows)
                with self.assertRaises(EventLogError):
                    read_log(self.path)

    def test_duplicate_json_key_and_nonfinite_number_refused(self):
        self.valid()
        raw = self.path.read_text(encoding="utf-8")
        for mutation in (raw.replace('"seq": 1', '"seq": 1, "seq": 1', 1),
                         raw.replace('"seq": 1', '"seq": NaN', 1)):
            with self.subTest(mutation=mutation[:20]):
                self.path.write_text(mutation, encoding="utf-8")
                with self.assertRaises(EventLogError):
                    read_log(self.path)


if __name__ == "__main__":
    unittest.main()
