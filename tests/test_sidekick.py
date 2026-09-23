"""Tests for NakedAgent Sidekick harness."""
import json
import tempfile
import unittest
from pathlib import Path

from nakedagent.functional import ToolAction
from nakedagent.mcp import StdlibMcpClient
from nakedagent.sidekick import (
    CallableProvider,
    DefaultSafeNoulGate,
    SidekickHarness,
)


class TestSidekickHarness(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_sidekick_single_turn_no_tools(self):
        def mock_model(messages):
            return "I am ready to help you write code."

        harness = SidekickHarness(
            workspace=self.workspace,
            provider=CallableProvider(mock_model),
            max_steps=5,
        )

        state = harness.run_turn("Hello, sidekick!")
        self.assertFalse(state.is_terminal)
        self.assertEqual(len(state.history), 3)  # system, user, assistant
        self.assertEqual(state.history[-1]["content"], "I am ready to help you write code.")

        trace = harness.export_merkle_trace()
        self.assertEqual(len(trace), 2)  # USER_INPUT and MODEL_REPLY
        self.assertEqual(trace[0]["event_type"], "USER_INPUT")
        self.assertEqual(trace[1]["event_type"], "MODEL_REPLY")

    def test_sidekick_tool_execution_flow(self):
        call_count = 0

        def mock_model(messages):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "```write test.txt\nHello from Sidekick!\n```"
            return "File has been created."

        harness = SidekickHarness(
            workspace=self.workspace,
            provider=CallableProvider(mock_model),
            max_steps=5,
        )

        state = harness.run_turn("Write hello world to test.txt")
        target_file = self.workspace / "test.txt"
        self.assertTrue(target_file.exists())
        self.assertEqual(target_file.read_text(encoding="utf-8").strip(), "Hello from Sidekick!")

        trace = harness.export_merkle_trace()
        # Events: USER_INPUT -> MODEL_REPLY (with write action) -> TOOL_RESULT -> MODEL_REPLY
        self.assertEqual(len(trace), 4)
        self.assertEqual(trace[2]["event_type"], "TOOL_RESULT")

    def test_sidekick_noul_gate_tripwire(self):
        def malicious_model(messages):
            return "```shell\nrm -rf /\n```"

        harness = SidekickHarness(
            workspace=self.workspace,
            provider=CallableProvider(malicious_model),
            max_steps=5,
            noul_gate=DefaultSafeNoulGate(),
        )

        state = harness.run_turn("Clean up files")
        trace = harness.export_merkle_trace()
        event_types = [t["event_type"] for t in trace]
        self.assertIn("ALARM", event_types)


class _EscalatingGate:
    """Gate that ESCALATEs shell actions, allows the rest."""

    def route_action(self, action, workspace):
        if action.tool_name == "shell":
            return "ESCALATE", 0.65, "shell needs human review"
        return "ALLOW", 0.05, "ok"


class _LegacyBoolGate:
    """Pre-tri-state gate: only evaluate_action, no route_action."""

    def __init__(self, alarm):
        self._alarm = alarm

    def evaluate_action(self, action, workspace):
        return self._alarm, 0.9 if self._alarm else 0.1, "legacy"


class TestEscalateGate(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_escalate_suspends_without_dispatch(self):
        def model(messages):
            return "```shell\nrm -rf /tmp/x\n```"

        harness = SidekickHarness(
            workspace=self.workspace,
            provider=CallableProvider(model),
            max_steps=10,
            noul_gate=_EscalatingGate(),
        )
        state = harness.run_turn("clean")
        self.assertTrue(state.suspended)
        self.assertFalse(state.is_terminal)
        esc = [r for r in state.trace if r.event.event_type == "ESCALATE"]
        self.assertEqual(len(esc), 1)
        # The held action is sealed into the ledger — fully reconstructible.
        self.assertEqual(esc[0].event.metadata["tool"], "shell")
        self.assertIn("rm -rf /tmp/x", esc[0].event.metadata["content"])
        self.assertEqual(esc[0].event.metadata["p_risk"], 0.65)
        # No TOOL_RESULT was fabricated for the held action.
        self.assertFalse(
            any(r.event.event_type == "TOOL_RESULT" for r in state.trace)
        )

    def test_resume_via_verdict_reenters_model(self):
        calls = []

        def model(messages):
            calls.append(len(messages))
            if len(calls) == 1:
                return "```shell\nrm -rf /tmp/x\n```"
            return "Understood, not running that."

        harness = SidekickHarness(
            workspace=self.workspace,
            provider=CallableProvider(model),
            max_steps=10,
            noul_gate=_EscalatingGate(),
        )
        state = harness.run_turn("clean")
        self.assertTrue(state.suspended)
        # Human verdict re-enters as a USER_INPUT; suspension lifts.
        state = harness.run_turn("denied: do not run shell commands")
        self.assertFalse(state.suspended)
        self.assertEqual(len(calls), 2)  # model re-called with verdict in context

    def test_legacy_evaluate_only_gate_still_works(self):
        def model(messages):
            return "```shell\nrm -rf /\n```"

        harness = SidekickHarness(
            workspace=self.workspace,
            provider=CallableProvider(model),
            max_steps=5,
            noul_gate=_LegacyBoolGate(alarm=True),
        )
        state = harness.run_turn("clean")
        self.assertTrue(state.is_terminal)
        self.assertFalse(state.suspended)
        self.assertIn(
            "ALARM", [r.event.event_type for r in state.trace]
        )

    def test_default_gate_route_action_shim(self):
        # DefaultSafeNoulGate derives ALLOW/BLOCK through route_action.
        gate = DefaultSafeNoulGate()
        action = ToolAction("read", "x.txt", "")
        route, p, _ = gate.route_action(action, self.workspace)
        self.assertEqual(route, "ALLOW")
        danger = ToolAction("shell", "", "rm -rf /")
        route, p, _ = gate.route_action(danger, self.workspace)
        self.assertEqual(route, "BLOCK")


if __name__ == "__main__":
    unittest.main()
