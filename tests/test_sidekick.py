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


if __name__ == "__main__":
    unittest.main()
