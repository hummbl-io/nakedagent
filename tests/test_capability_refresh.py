"""Offline capability propagation checks with recorded provider inputs."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from nakedagent.functional import AgentEvent, agent_reducer, replay_trace
from nakedagent.sidekick import CallableProvider, SidekickHarness


class CapabilityRefreshTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name)
        self.provider_inputs = []

    def harness(self, **kwargs):
        def provider(messages):
            self.provider_inputs.append(messages)
            return "done"
        with patch("nakedagent.sidekick.TOOLS", {}):
            harness = SidekickHarness(self.workspace, CallableProvider(provider), **kwargs)
        self.addCleanup(harness.close)
        return harness

    def client(self, *names):
        client = Mock()
        client.list_tools.return_value = [{"name": name} for name in names]
        client.invoke_tool.return_value = "inert result"
        return client

    def test_attachment_reaches_first_provider_request_and_replays(self):
        harness = self.harness(policy={"model": "fixture", "nested": {"ids": [1, 2]}})
        original_hash = harness.state.current_hash()
        self.assertEqual(harness.attach_mcp_client(self.client("pilot_extra")), ["pilot_extra"])
        self.assertIn("```pilot_extra", harness.state.history[0]["content"])
        self.assertEqual(harness.state.history[0]["content"], harness.system_prompt)
        self.assertNotEqual(harness.state.current_hash(), original_hash)
        self.assertEqual(harness.state.policy["nested"]["ids"], (1, 2))
        genesis = harness.state.current_hash()
        state = harness.run_turn("fixture task")
        self.assertIn("```pilot_extra", self.provider_inputs[0][0]["content"])
        self.assertEqual(state.trace[0].prev_hash, genesis)
        replayed, valid = replay_trace(
            harness.system_prompt, [receipt.event for receipt in state.trace],
            max_steps=state.max_steps,
            policy={"model": "fixture", "nested": {"ids": [1, 2]}},
            recorded_hashes=[receipt.state_hash for receipt in state.trace])
        self.assertTrue(valid)
        self.assertEqual(replayed.history, state.history)

    def test_empty_attachment_preserves_custom_prompt_and_genesis(self):
        harness = self.harness(system_prompt="Custom task policy.")
        initial = harness.state
        self.assertEqual(harness.attach_mcp_client(self.client()), [])
        self.assertIs(harness.state, initial)
        self.assertEqual(harness.system_prompt, "Custom task policy.")

    def test_custom_prompt_survives_multiple_startup_attachments(self):
        harness = self.harness(system_prompt="Custom task policy.")
        harness.attach_mcp_client(self.client("first_tool"))
        harness.attach_mcp_client(self.client("second_tool"))
        harness.run_turn("fixture task")
        prompt = self.provider_inputs[0][0]["content"]
        self.assertEqual(prompt.count("Custom task policy."), 1)
        self.assertIn("```first_tool", prompt)
        self.assertIn("```second_tool", prompt)
        self.assertEqual(prompt, harness.system_prompt)

    def assert_late_attachment_refused(self, harness):
        before_state = harness.state
        before_tools = dict(harness.tools)
        before_prompt = harness.system_prompt
        client = self.client("late_tool")
        with self.assertRaisesRegex(RuntimeError, "before.*first|started"):
            harness.attach_mcp_client(client)
        client.start.assert_not_called()
        client.list_tools.assert_not_called()
        self.assertIs(harness.state, before_state)
        self.assertEqual(harness.tools, before_tools)
        self.assertEqual(harness.system_prompt, before_prompt)

    def test_attachment_after_completed_turn_refused_before_effects(self):
        harness = self.harness()
        harness.run_turn("fixture task")
        self.assert_late_attachment_refused(harness)

    def test_attachment_while_suspended_refused_before_effects(self):
        harness = self.harness()
        harness.state, _ = agent_reducer(harness.state, AgentEvent("ESCALATE", "review"))
        self.assert_late_attachment_refused(harness)

    def test_new_tool_still_dispatches_and_result_reaches_provider(self):
        harness = self.harness()
        client = self.client("pilot_extra")
        harness.attach_mcp_client(client)
        replies = iter(['```pilot_extra\n{"value": "fixture"}\n```', "done"])

        def provider(messages):
            self.provider_inputs.append(messages)
            return next(replies)
        harness.provider = CallableProvider(provider)
        state = harness.run_turn("fixture task")
        client.invoke_tool.assert_called_once_with("pilot_extra", {"value": "fixture"})
        self.assertTrue(any("inert result" in message["content"]
                            for message in self.provider_inputs[-1]))
        self.assertEqual(sum(receipt.event.event_type == "TOOL_RESULT"
                             for receipt in state.trace), 1)


if __name__ == "__main__":
    unittest.main()
