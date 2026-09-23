"""Exact-source PR20 gate hardening, all transport/model/tool effects stubbed."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import nakedagent.providers_draft as draft
from nakedagent.functional import ToolAction
from nakedagent.sidekick import CallableProvider, SidekickHarness


class FakeResponse:
    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.body


class JevShapeTests(unittest.TestCase):
    def _route(self, score_json: str):
        body = ('{"answers":{"p_risk":{"score":' + score_json + '}}}').encode()
        requests = []
        fake_urllib = SimpleNamespace(
            request=SimpleNamespace(
                Request=lambda *_a, **_k: object(),
                urlopen=lambda *_a, **_k: (requests.append(1) or FakeResponse(body)),
            ),
            error=SimpleNamespace(HTTPError=type("NeverRaisedHTTPError", (Exception,), {})),
        )
        with patch.object(draft, "os", SimpleNamespace(environ={"REC064_FAKE": "fixture"})), \
             patch.object(draft, "urllib", fake_urllib):
            route, score, _reason = draft.JevNoulGate(api_key_env="REC064_FAKE").route_action(
                ToolAction("shell", "echo fixture", ""), Path("."),
            )
        return route, score, len(requests)

    def test_invalid_scores_fail_closed_without_retry(self):
        # Score is on the criteria-index scale: 5 legend points -> raw in
        # [0,4] (verified against the live Decisions API 2026-09-23).
        invalid = ('"NaN"', 'NaN', '"Infinity"', '"-Infinity"', '1e9999',
                   'true', 'false', 'null', '[]', '{}', '-0.1', '4.1', '5',
                   '"bad"')
        for raw in invalid:
            with self.subTest(raw=raw):
                self.assertEqual(self._route(raw), ("BLOCK", draft.GATE_UNREACHABLE, 1))

    def test_finite_unit_interval_boundaries_and_numeric_string(self):
        # Raw index-scale boundaries: normalized = raw / 4, so the abstain
        # band [0.30, 0.55) maps to raw [1.2, 2.2).
        for raw, expected in (("0", "ALLOW"), ("1.196", "ALLOW"),
                              ("1.2", "ESCALATE"), ("2.196", "ESCALATE"),
                              ("2.2", "BLOCK"), ("4", "BLOCK"),
                              ('"1.6"', "ESCALATE"), ("1.1", "ALLOW")):
            with self.subTest(raw=raw):
                route, score, count = self._route(raw)
                self.assertEqual(route, expected)
                self.assertGreaterEqual(score, 0)
                self.assertLessEqual(score, 1)
                self.assertEqual(count, 1)

    def test_invalid_abstention_config_rejected_before_transport(self):
        invalid = ((float("nan"), float("nan")), (0.8, 0.2),
                   (0.3, 0.3), (-0.1, 0.5), (0.2, 1.1),
                   (False, 0.5), (0.2, True), ("0.2", 0.5),
                   (0.2, 10**1000))
        for lo, hi in invalid:
            with self.subTest(lo=lo, hi=hi), self.assertRaises(ValueError):
                draft.JevNoulGate(abstain_lo=lo, abstain_hi=hi)
        gate = draft.JevNoulGate(abstain_lo=0, abstain_hi=1)
        self.assertEqual((gate.abstain_lo, gate.abstain_hi), (0.0, 1.0))


class Gate:
    def __init__(self, route, risk, raises=False):
        self.route = route
        self.risk = risk
        self.raises = raises

    def route_action(self, _action, _workspace):
        if self.raises:
            raise RuntimeError("synthetic gate outage")
        return self.route, self.risk, "fixture"


class SidekickGateTests(unittest.TestCase):
    def _run(self, gate):
        with tempfile.TemporaryDirectory() as folder:
            effects = []
            harness = SidekickHarness(
                Path(folder), CallableProvider(lambda _messages: "```probe x\nfixture\n```"),
                max_steps=4, noul_gate=gate,
            )
            harness.tools["probe"] = lambda *_args: (effects.append(1) or "ok")
            state = harness.run_turn("fixture")
            return len(effects), [x.event.event_type for x in state.trace], state.suspended

    def test_unknown_route_nonfinite_risk_and_gate_exception_do_not_dispatch(self):
        for gate in (Gate("UNKNOWN", 0.1), Gate("ALLOW", float("nan")),
                     Gate("ALLOW", -0.1), Gate("ESCALATE", float("nan")),
                     Gate("ALLOW", 0.1, raises=True)):
            with self.subTest(gate=(gate.route, str(gate.risk), gate.raises)):
                effects, events, suspended = self._run(gate)
                self.assertEqual(effects, 0)
                self.assertIn("ALARM", events)
                self.assertFalse(suspended)

    def test_valid_route_and_outage_sentinel(self):
        effects, events, suspended = self._run(Gate("ALLOW", 0.1))
        self.assertEqual(effects, 1)
        self.assertIn("TOOL_RESULT", events)
        self.assertFalse(suspended)
        effects, events, suspended = self._run(Gate("BLOCK", -1.0))
        self.assertEqual(effects, 0)
        self.assertIn("ALARM", events)
        self.assertFalse(suspended)
        effects, events, suspended = self._run(Gate("ESCALATE", 0.4))
        self.assertEqual(effects, 0)
        self.assertIn("ESCALATE", events)
        self.assertTrue(suspended)

    def test_huge_integer_and_malformed_legacy_alarm_do_not_dispatch(self):
        invalid = (Gate("ALLOW", 10**1000),
                   SimpleNamespace(evaluate_action=lambda *_: (None, 0.1, "fixture")),
                   SimpleNamespace(evaluate_action=lambda *_: (0, 0.1, "fixture")))
        for gate in invalid:
            with self.subTest(gate=type(gate).__name__):
                effects, events, suspended = self._run(gate)
                self.assertEqual(effects, 0)
                self.assertIn("ALARM", events)
                self.assertFalse(suspended)

    def test_exact_legacy_bool_results_keep_existing_meanings(self):
        for alarm, expected_effects in ((False, 1), (True, 0)):
            gate = SimpleNamespace(evaluate_action=lambda *_, alarm=alarm: (alarm, 0.1, "fixture"))
            with self.subTest(alarm=alarm):
                effects, events, suspended = self._run(gate)
                self.assertEqual(effects, expected_effects)
                self.assertIn("TOOL_RESULT" if expected_effects else "ALARM", events)
                self.assertFalse(suspended)


if __name__ == "__main__":
    unittest.main()
