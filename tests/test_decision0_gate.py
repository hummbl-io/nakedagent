"""Decision0NoulGate: routing, fail-closed handling and harness wiring, with the model stubbed."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import nakedagent.providers_draft as draft
from nakedagent.functional import ToolAction
from nakedagent.sidekick import CallableProvider, SidekickHarness

POLICY = "Agents may read files in the workspace. Deleting files needs a ticket."


def reply(label: str, allow: float) -> dict:
    return {"label": label, "reason": "fixture", "scores": {"allow": allow, "deny": 0.0, "escalate": 0.0}}


class Recorder:
    def __init__(self, out=None, raises=None):
        self.out, self.raises, self.cases = out, raises, []

    def __call__(self, case):
        self.cases.append(case)
        if self.raises:
            raise self.raises
        return self.out


class Decision0GateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self._tmp.name)
        (self.ws / ".nakedagent").mkdir()
        (self.ws / ".nakedagent" / "policy.md").write_text(POLICY, encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def route(self, runner, action=None, **kw):
        gate = draft.Decision0NoulGate(runner=runner, **kw)
        gate.task = "Tidy the workspace."
        return gate.route_action(action or ToolAction("read", "notes.txt", ""), self.ws)

    def test_labels_map_to_routes(self):
        for out, expected in ((reply("allow", 0.995), "ALLOW"), (reply("deny", 0.01), "BLOCK"),
                              (reply("escalate", 0.2), "ESCALATE"), (reply("allow", 0.95), "ESCALATE")):
            with self.subTest(out=out["label"], allow=out["scores"]["allow"]):
                route, risk, _ = self.route(Recorder(out))
                self.assertEqual(route, expected)
                self.assertAlmostEqual(risk, 1 - out["scores"]["allow"])

    def test_case_sent_to_the_model(self):
        rec = Recorder(reply("allow", 0.999))
        (self.ws / ".nakedagent" / "evidence.md").write_text("Ticket T-1 approved.", encoding="utf-8")
        self.route(rec, ToolAction("shell", "", "ls -la"))
        self.assertEqual(rec.cases, [{"policy": POLICY, "evidence": "Ticket T-1 approved.",
                                      "task": "Tidy the workspace.", "action": "shell\nls -la"}])

    def test_tripwire_blocks_before_the_model(self):
        rec = Recorder(reply("allow", 0.999))
        route, _risk, reason = self.route(rec, ToolAction("shell", "", "rm -rf / --no-preserve-root"))
        self.assertEqual((route, rec.cases), ("BLOCK", []))
        self.assertIn("tripwire", reason)

    def test_missing_policy_and_long_action_escalate_without_scoring(self):
        rec = Recorder(reply("allow", 0.999))
        route, _, reason = self.route(rec, ToolAction("write", "a.txt", "x" * 700))
        self.assertEqual((route, rec.cases), ("ESCALATE", []))
        self.assertIn("over 600", reason)
        (self.ws / ".nakedagent" / "policy.md").unlink()
        route, _, reason = self.route(rec)
        self.assertEqual((route, rec.cases), ("ESCALATE", []))
        self.assertIn("no policy", reason)

    def test_malformed_replies_and_runner_faults_fail_closed(self):
        bad = [{}, {"label": "allow"}, {"label": "maybe", "scores": {"allow": 0.999}},
               reply("allow", float("nan")), reply("allow", 1.5), reply("allow", -0.1),
               {"label": "allow", "scores": {"allow": True}}, {"label": "allow", "scores": {"allow": "0.999"}},
               ["allow"], None]
        for out in bad:
            with self.subTest(out=repr(out)[:40]):
                self.assertEqual(self.route(Recorder(out))[:2], ("BLOCK", draft.GATE_UNREACHABLE))
        for err in (RuntimeError("decide.py exit 1"), subprocess.TimeoutExpired("decide.py", 1),
                    json.JSONDecodeError("bad", "", 0)):
            with self.subTest(err=type(err).__name__):
                self.assertEqual(self.route(Recorder(raises=err))[:2], ("BLOCK", draft.GATE_UNREACHABLE))

    def test_invalid_config_rejected(self):
        for kw in ({"allow_threshold": 0}, {"allow_threshold": 1.1}, {"allow_threshold": float("nan")},
                   {"allow_threshold": True}, {"allow_threshold": "0.99"}, {"max_action_chars": 0},
                   {"max_action_chars": 1.5}):
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                draft.Decision0NoulGate(runner=Recorder(), **kw)

    def test_subprocess_runner_command(self):
        calls = []

        def fake_run(cmd, **kw):
            calls.append((cmd, kw))
            return SimpleNamespace(returncode=0, stdout=json.dumps(reply("allow", 0.999)), stderr="")

        gate = draft.Decision0NoulGate(decide_py="/opt/d0/decide.py", model="/opt/d0", python="/py")
        gate.task = "t"
        with patch.object(draft.subprocess, "run", fake_run):
            route, _, _ = gate.route_action(ToolAction("read", "notes.txt", ""), self.ws)
        self.assertEqual(route, "ALLOW")
        cmd, kw = calls[0]
        self.assertEqual(cmd[:6], ["/py", "/opt/d0/decide.py", "--model", "/opt/d0", "--allow-threshold", "0.99"])
        self.assertEqual(cmd[cmd.index("--policy") + 1], POLICY)
        self.assertEqual(cmd[cmd.index("--action") + 1], "read notes.txt")
        self.assertFalse(kw.get("shell", False))
        self.assertEqual(kw["timeout"], 180)

    def test_subprocess_runner_without_decide_py_fails_closed(self):
        with patch.dict(draft.os.environ, {}, clear=True):
            gate = draft.Decision0NoulGate(decide_py=None)
        self.assertEqual(gate.route_action(ToolAction("read", "x", ""), self.ws)[:2],
                         ("BLOCK", draft.GATE_UNREACHABLE))

    def test_evaluate_action_compat(self):
        gate = draft.Decision0NoulGate(runner=Recorder(reply("escalate", 0.1)))
        self.assertTrue(gate.evaluate_action(ToolAction("read", "x", ""), self.ws)[0])

    def test_harness_dispatches_only_on_allow(self):
        for out, effects_expected, suspended in ((reply("allow", 0.999), 1, False),
                                                 (reply("escalate", 0.1), 0, True),
                                                 (reply("deny", 0.0), 0, False)):
            with self.subTest(label=out["label"]):
                effects = []
                gate = draft.Decision0NoulGate(runner=Recorder(out))
                harness = SidekickHarness(self.ws, CallableProvider(lambda _m: "```probe x\nfixture\n```"),
                                          max_steps=4, noul_gate=gate)
                harness.tools["probe"] = lambda *_a, effects=effects: (effects.append(1) or "ok")
                gate.task = "fixture"
                state = harness.run_turn("fixture")
                self.assertEqual(len(effects), effects_expected)
                self.assertEqual(state.suspended, suspended)


if __name__ == "__main__":
    unittest.main()
