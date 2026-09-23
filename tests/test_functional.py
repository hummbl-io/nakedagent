"""Tests for pure functional state machine, Merkle chain, and deterministic replay."""
import unittest

from nakedagent.functional import (
    AgentEvent,
    AgentState,
    agent_reducer,
    compute_step_hash,
    replay_trace,
)


class TestFunctionalStateMachine(unittest.TestCase):
    def setUp(self):
        self.genesis = AgentState.initial("System instructions", max_steps=5)

    def test_genesis_state_invariants(self):
        self.assertEqual(self.genesis.step_count, 0)
        self.assertEqual(len(self.genesis.history), 1)
        self.assertEqual(len(self.genesis.trace), 0)
        self.assertFalse(self.genesis.is_terminal)

    def test_referential_transparency_and_immutability(self):
        event = AgentEvent("USER_INPUT", "Hello world")
        state1, actions1 = agent_reducer(self.genesis, event)
        state2, actions2 = agent_reducer(self.genesis, event)

        self.assertEqual(state1, state2)
        self.assertEqual(actions1, actions2)
        # Genesis remains unmodified
        self.assertEqual(self.genesis.step_count, 0)
        self.assertEqual(len(self.genesis.history), 1)

    def test_tool_action_parsing_in_model_reply(self):
        reply = "Let me read the file\n```read config.json\n```\nDone."
        event = AgentEvent("MODEL_REPLY", reply)
        new_state, actions = agent_reducer(self.genesis, event)

        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].tool_name, "read")
        self.assertEqual(actions[0].args, "config.json")
        self.assertEqual(new_state.step_count, 1)

    def test_bounded_termination_invariant(self):
        state = self.genesis
        for i in range(5):
            state, _ = agent_reducer(state, AgentEvent("USER_INPUT", f"Ping {i}"))
        self.assertEqual(state.step_count, 5)

        # 6th step exceeds max_steps=5
        next_state, actions = agent_reducer(state, AgentEvent("USER_INPUT", "Over limit"))
        self.assertTrue(next_state.is_terminal)
        self.assertEqual(next_state.terminal_reason, "BOUNDED_MAX_STEPS_REACHED")
        self.assertEqual(actions, [])

    def test_merkle_stream_and_deterministic_replay(self):
        events = [
            AgentEvent("USER_INPUT", "Create hello.py"),
            AgentEvent("MODEL_REPLY", "```write hello.py\nprint('hello')\n```"),
            AgentEvent("TOOL_RESULT", "Wrote 15 chars to hello.py."),
            AgentEvent("MODEL_REPLY", "All done!"),
        ]

        final_state, is_valid = replay_trace("System prompt", events)
        self.assertTrue(is_valid)
        self.assertEqual(final_state.step_count, 4)
        self.assertEqual(len(final_state.trace), 4)

        # Verify Merkle link
        t = final_state.trace
        self.assertEqual(t[1].prev_hash, t[0].state_hash)
        self.assertEqual(t[2].prev_hash, t[1].state_hash)
        self.assertEqual(t[3].prev_hash, t[2].state_hash)


if __name__ == "__main__":
    unittest.main()
