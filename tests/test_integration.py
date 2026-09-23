"""Stub-only integration checks for the active Sidekick and PR18 replay seam."""
import json
import tempfile
import unittest
from pathlib import Path

from nakedagent.functional import AgentEvent, replay_trace
from nakedagent.sidekick import CallableProvider, SidekickHarness


class TestIntegratedSeams(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name)

    def test_provider_receives_plain_json_messages_from_frozen_history(self):
        observed = []

        def provider(messages):
            observed.append(json.dumps(messages))
            return "done"

        harness = SidekickHarness(self.workspace, CallableProvider(provider), max_steps=5)
        state = harness.run_turn("hello")
        self.assertEqual(len(observed), 1)
        self.assertIn('"content": "hello"', observed[0])
        with self.assertRaises(TypeError):
            state.history[0]["content"] = "changed"

    def test_mounted_mcp_tool_uses_existing_invoke_tool_seam(self):
        calls = []

        class FakeMcp:
            def start(self):
                calls.append("start")

            def list_tools(self):
                return [{"name": "mcp_echo"}]

            def invoke_tool(self, name, params):
                calls.append((name, params))
                return {"echo": params}

            def close(self):
                calls.append("close")

        replies = iter(['```mcp_echo\n{"x": 1}\n```', "done"])
        harness = SidekickHarness(self.workspace, CallableProvider(lambda _msgs: next(replies)), max_steps=5)
        self.assertEqual(harness.attach_mcp_client(FakeMcp()), ["mcp_echo"])
        state = harness.run_turn("go")
        harness.close()
        self.assertEqual(calls, ["start", ("mcp_echo", {"x": 1}), "close"])
        results = [r for r in state.trace if r.event.event_type == "TOOL_RESULT"]
        self.assertEqual(len(results), 1)
        self.assertIn('"echo"', results[0].event.payload)

    def test_sidekick_reserves_result_slot_before_stub_tool(self):
        calls = []
        harness = SidekickHarness(
            self.workspace,
            CallableProvider(lambda _msgs: "```read a\n```\n```read b\n```"),
            max_steps=3,
        )
        harness.tools["read"] = lambda args, _content, _workspace: calls.append(args) or "stub"
        state = harness.run_turn("go")
        self.assertEqual(calls, ["a"])
        self.assertEqual(state.step_count, 3)
        self.assertEqual(state.terminal_reason, "BOUNDED_MAX_STEPS_REACHED")
        self.assertEqual([r.event.event_type for r in state.trace],
                         ["USER_INPUT", "MODEL_REPLY", "TOOL_RESULT"])

    def test_sidekick_does_not_call_provider_without_reply_capacity(self):
        calls = []
        harness = SidekickHarness(self.workspace, CallableProvider(lambda _msgs: calls.append(1) or "done"), max_steps=1)
        state = harness.run_turn("go")
        self.assertEqual(calls, [])
        self.assertEqual(state.step_count, 1)
        self.assertEqual(state.terminal_reason, "BOUNDED_MAX_STEPS_REACHED")

    def test_recorded_hash_api_still_detects_changed_event(self):
        events = [AgentEvent("USER_INPUT", "go"), AgentEvent("MODEL_REPLY", "done")]
        state, ok = replay_trace("sys", events, max_steps=5)
        self.assertTrue(ok)
        recorded = [r.state_hash for r in state.trace]
        _, same = replay_trace("sys", events, max_steps=5, recorded_hashes=recorded)
        _, changed = replay_trace("sys", [events[0], AgentEvent("MODEL_REPLY", "changed")],
                                  max_steps=5, recorded_hashes=recorded)
        self.assertTrue(same)
        self.assertFalse(changed)


if __name__ == "__main__":
    unittest.main()
