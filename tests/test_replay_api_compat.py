"""Both existing fourth-positional replay APIs remain supported."""
import unittest

from nakedagent.functional import AgentEvent, AgentState, replay_trace


class ReplayApiCompatibilityTests(unittest.TestCase):
    def test_pr18_positional_policy(self) -> None:
        policy = {"model": "m", "workspace": "w", "extra": {}}
        state, valid = replay_trace("system", [], 5, policy)
        self.assertTrue(valid)
        self.assertEqual(state.current_hash(), AgentState.initial("system", 5, policy).current_hash())

    def test_policy_keyword_keeps_its_meaning(self) -> None:
        policy = {"model": "m", "workspace": "w", "extra": {}}
        state, valid = replay_trace("system", [], 5, policy=policy)
        self.assertTrue(valid)
        self.assertEqual(state.current_hash(), AgentState.initial("system", 5, policy).current_hash())

    def test_active_positional_recorded_hashes(self) -> None:
        event = AgentEvent("USER_INPUT", "hi")
        recorded, valid = replay_trace("system", [event], 5)
        self.assertTrue(valid)
        replayed, valid = replay_trace("system", [event], 5, [recorded.current_hash()])
        self.assertTrue(valid)
        self.assertEqual(replayed.current_hash(), recorded.current_hash())
        _, valid = replay_trace("system", [event], 5, ["0" * 64])
        self.assertFalse(valid)

    def test_hash_keyword_keeps_its_meaning(self) -> None:
        event = AgentEvent("USER_INPUT", "hi")
        recorded, _ = replay_trace("system", [event], 5)
        _, valid = replay_trace("system", [event], 5, recorded_hashes=[recorded.current_hash()])
        self.assertTrue(valid)
        _, valid = replay_trace("system", [event], 5, recorded_hashes=["0" * 64])
        self.assertFalse(valid)
        with self.assertRaises(TypeError):
            replay_trace("system", [event], 5, recorded_hashes={"x": 1})

    def test_double_policy_is_rejected(self) -> None:
        with self.assertRaises(TypeError):
            replay_trace("system", [], 5, {"a": 1}, policy={"b": 2})

    def test_double_hashes_are_rejected(self) -> None:
        with self.assertRaises(TypeError):
            replay_trace("system", [], 5, [], recorded_hashes=[])

    def test_extra_positional_argument_is_rejected(self) -> None:
        with self.assertRaises(TypeError):
            replay_trace("system", [], 5, [], {})

    def test_none_is_neutral(self) -> None:
        state, valid = replay_trace("system", [], 5, None)
        self.assertTrue(valid)
        self.assertEqual(state.current_hash(), AgentState.initial("system", 5).current_hash())
        _, valid = replay_trace("system", [], 5, None, policy={"x": 1}, recorded_hashes=[])
        self.assertTrue(valid)

    def test_unknown_fourth_arg_is_rejected(self) -> None:
        with self.assertRaises(TypeError):
            replay_trace("system", [], 5, "unknown")
        with self.assertRaises(TypeError):
            replay_trace("system", [], 5, policy=["x"])
        with self.assertRaises(TypeError):
            replay_trace("system", [], 5, recorded_hashes=("x",))


if __name__ == "__main__":
    unittest.main()
