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


def reply(label: str, allow: float, n_tokens: int = 60) -> dict:
    return {"label": label, "reason": "fixture", "scores": {"allow": allow, "deny": 0.0, "escalate": 0.0},
            "n_tokens": n_tokens, "max_tokens": 192}


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

    def route(self, runner, action=None, task: object = "Tidy the workspace.", **kw):
        gate = draft.Decision0NoulGate(runner=runner, **kw)
        gate.task = task
        return gate.route_action(action or ToolAction("read", "notes.txt", ""), self.ws)

    def test_labels_map_to_routes(self):
        for out, expected in ((reply("allow", 0.995), "ALLOW"), (reply("allow", 0.99), "ALLOW"),
                              (reply("deny", 0.01), "BLOCK"), (reply("escalate", 0.2), "ESCALATE"),
                              (reply("allow", 0.9899), "ESCALATE")):
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

    def test_tripwire_routes_before_the_model(self):
        rec = Recorder(reply("allow", 0.999))
        route, _risk, reason = self.route(rec, ToolAction("shell", "", "rm -rf / --no-preserve-root"))
        self.assertEqual((route, rec.cases), ("BLOCK", []))
        self.assertIn("tripwire", reason)
        holding = SimpleNamespace(route_action=lambda *_: ("ESCALATE", 0.5, "held"))
        self.assertEqual(self.route(rec, tripwire=holding)[:2], ("ESCALATE", 0.5))
        self.assertEqual(rec.cases, [])

    def test_escalates_without_scoring(self):
        rec = Recorder(reply("allow", 0.999))
        for kw, needle in (({"action": ToolAction("write", "a.txt", "x" * 1100)}, "over 1000"),
                           ({"task": ""}, "task not set"), ({"task": "   "}, "task not set"),
                           ({"task": None}, "task not set")):
            with self.subTest(needle=needle, kw=str(kw)[:30]):
                route, risk, reason = self.route(rec, **kw)
                self.assertEqual((route, risk, rec.cases), ("ESCALATE", 1.0, []))
                self.assertIn(needle, reason)
        (self.ws / ".nakedagent" / "policy.md").unlink()
        route, _, reason = self.route(rec)
        self.assertEqual((route, rec.cases), ("ESCALATE", []))
        self.assertIn("no policy", reason)

    def test_input_over_the_token_window_escalates_whatever_the_label(self):
        for label in ("allow", "deny", "escalate"):
            for n in (193, 400):
                with self.subTest(label=label, n_tokens=n):
                    route, risk, reason = self.route(Recorder(reply(label, 0.999, n_tokens=n)))
                    self.assertEqual((route, risk), ("ESCALATE", 1.0))
                    self.assertIn("not trusted", reason)
        self.assertEqual(self.route(Recorder(reply("allow", 0.999, n_tokens=192)))[0], "ALLOW")

    def test_malformed_replies_and_runner_faults_fail_closed(self):
        ok = reply("allow", 0.999)
        bad = [{}, {"label": "allow"}, {**ok, "label": "maybe"},
               {**ok, "scores": {"allow": float("nan")}}, {**ok, "scores": {"allow": 1.5}},
               {**ok, "scores": {"allow": -0.1}}, {**ok, "scores": {"allow": True}},
               {**ok, "scores": {"allow": "0.999"}}, {k: v for k, v in ok.items() if k != "n_tokens"},
               {**ok, "n_tokens": "60"}, {**ok, "n_tokens": True}, {**ok, "max_tokens": 0},
               {k: v for k, v in ok.items() if k != "max_tokens"},
               ["allow"], None]
        for out in bad:
            with self.subTest(out=repr(out)[:60]):
                self.assertEqual(self.route(Recorder(out))[:2], ("BLOCK", draft.GATE_UNREACHABLE))
        for err in (RuntimeError("scorer exit 1"), subprocess.TimeoutExpired("python", 1),
                    json.JSONDecodeError("bad", "", 0)):
            with self.subTest(err=type(err).__name__):
                self.assertEqual(self.route(Recorder(raises=err))[:2], ("BLOCK", draft.GATE_UNREACHABLE))

    def test_invalid_config_rejected(self):
        for kw in ({"allow_threshold": 0}, {"allow_threshold": 1.1}, {"allow_threshold": float("nan")},
                   {"allow_threshold": True}, {"allow_threshold": "0.99"}, {"max_input_chars": 0},
                   {"max_input_chars": 1.5}, {"timeout_s": None}, {"timeout_s": 0}, {"timeout_s": -5},
                   {"timeout_s": float("inf")}, {"timeout_s": True}):
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                draft.Decision0NoulGate(runner=Recorder(), **kw)

    def test_subprocess_runner_sends_the_case_on_stdin(self):
        calls = []

        def fake_run(cmd, **kw):
            calls.append((cmd, kw))
            return SimpleNamespace(returncode=0, stdout="loading\n" + json.dumps(reply("allow", 0.999)), stderr="")

        gate = draft.Decision0NoulGate(decide_py="/opt/d0/decide.py", model="/opt/d0", python="/py")
        gate.task = "Find the bug."
        (self.ws / ".nakedagent" / "evidence.md").write_text("Ticket T-1.", encoding="utf-8")
        with patch.object(draft.subprocess, "run", fake_run):
            route, _, _ = gate.route_action(ToolAction("read", "notes.txt", ""), self.ws)
        self.assertEqual(route, "ALLOW")
        cmd, kw = calls[0]
        self.assertEqual(cmd[0:2], ["/py", "-c"])
        self.assertEqual(cmd[3:], ["/opt/d0/decide.py", "/opt/d0", "0.99"])
        self.assertNotIn(POLICY, cmd)  # case text never on the command line
        self.assertTrue(kw["input"].isascii())  # escaped JSON: no codepage can garble it
        self.assertEqual(json.loads(kw["input"]), {"policy": POLICY, "evidence": "Ticket T-1.",
                                                   "task": "Find the bug.", "action": "read notes.txt"})
        self.assertFalse(kw.get("shell", False))
        self.assertEqual(kw["timeout"], 180.0)

    def test_non_ascii_text_survives_the_scorer_round_trip(self):
        # Runs the real child script against a stdlib stub of decide.py, with the
        # UTF-8 overrides removed. The case crosses stdin as ASCII-only JSON
        # (json.dumps escapes non-ASCII), so the child's locale codepage cannot
        # garble it; the child also decodes stdin as UTF-8 in case that changes.
        stub = (
            "import json\nMAX_TOKENS = 192\n"
            "def texts(c):\n    return ('Policy: ' + c['policy'] + ' Evidence: ' + c['evidence'],\n"
            "            'Task: ' + c['task'] + ' Proposed action: ' + c['action'])\n"
            "class Decision0:\n"
            "    def __init__(self, model, allow_threshold=0.99):\n        self.t = allow_threshold\n"
            "    def tokenizer(self, a, b):\n        return {'input_ids': [0] * 10}\n"
            "    def decide(self, case):\n"
            "        return {'label': 'allow', 'reason': case['policy'],\n"
            "                'scores': {'allow': 0.999, 'deny': 0.0, 'escalate': 0.001}}\n")
        (self.ws / "decide.py").write_text(stub, encoding="utf-8")
        policy = "Café staff may read the naïve-Bayes logs — nothing else."
        (self.ws / ".nakedagent" / "policy.md").write_text(policy, encoding="utf-8")
        gate = draft.Decision0NoulGate(decide_py=self.ws / "decide.py", model="stub")
        gate.task = "Résumé the logs."
        seen = []
        real = gate._subprocess_runner

        def runner(case):
            out = real(case)
            seen.append(out["reason"])
            return out

        gate.runner = runner
        env = {k: v for k, v in draft.os.environ.items() if k not in ("PYTHONUTF8", "PYTHONIOENCODING")}
        with patch.dict(draft.os.environ, env, clear=True):
            route, _, _ = gate.route_action(ToolAction("read", "logs.txt", ""), self.ws)
        self.assertEqual((route, seen), ("ALLOW", [policy]))

    def test_subprocess_runner_without_decide_py_fails_closed(self):
        with patch.dict(draft.os.environ, {}, clear=True):
            gate = draft.Decision0NoulGate(decide_py=None)
        gate.task = "t"
        self.assertEqual(gate.route_action(ToolAction("read", "x", ""), self.ws)[:2],
                         ("BLOCK", draft.GATE_UNREACHABLE))

    def test_evaluate_action_compat(self):
        gate = draft.Decision0NoulGate(runner=Recorder(reply("escalate", 0.1)))
        gate.task = "t"
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
