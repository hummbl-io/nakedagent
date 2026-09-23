"""Offline effect admission and complete-log counterexamples for v0.4."""
import json
import tempfile
import unittest
from pathlib import Path

from nakedagent.driver import run_functional
from nakedagent.eventlog import open_log
from nakedagent.functional import AgentEvent, AgentState, agent_reducer, replay_trace
from nakedagent.replay import verify
from nakedagent.sidekick import CallableProvider, SidekickHarness


class TestV04Contract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.log = self.root / "run.jsonl"

    def test_driver_no_model_without_reply_slot(self):
        calls = []
        state = run_functional("go", "m", self.root, "offline", tools={},
                               llm_fn=lambda *_: calls.append("model") or "done",
                               max_steps=1, event_log_path=self.log)
        self.assertEqual(calls, [])
        self.assertEqual(state.step_count, 1)
        self.assertEqual(state.terminal_reason, "BOUNDED_MAX_STEPS_REACHED")
        self.assertTrue(verify(self.log)[0])

    def test_driver_no_tool_without_result_slot(self):
        effects = []
        state = run_functional("go", "m", self.root, "offline",
                               tools={"read": lambda *_: effects.append("tool") or "ok"},
                               llm_fn=lambda *_: "```read x\n```", max_steps=2,
                               event_log_path=self.log)
        self.assertEqual(effects, [])
        self.assertEqual(state.step_count, 2)
        self.assertTrue(verify(self.log)[0])

    def test_sidekick_no_model_and_no_tool_at_bound(self):
        for budget, expected_models in ((1, 0), (2, 1)):
            with self.subTest(budget=budget):
                models, effects = [], []
                harness = SidekickHarness(self.root, CallableProvider(
                    lambda _, calls=models: calls.append(1) or "```read x\n```"), max_steps=budget)
                harness.tools["read"] = lambda *_, calls=effects: calls.append(1) or "ok"
                state = harness.run_turn("go")
                self.assertEqual((len(models), effects), (expected_models, []))
                self.assertTrue(state.is_terminal)

    def test_suspended_resume_carries_policy_and_complete_status(self):
        policy = {"model": "m", "workspace": "w", "extra": {"rule": [1]}}
        events = [AgentEvent("USER_INPUT", "go"), AgentEvent("MODEL_REPLY", "```read x\n```"),
                  AgentEvent("ESCALATE", "held", {"tool": "read"})]
        state = AgentState.initial("sys", max_steps=9, policy=policy)
        for event in events:
            state, _ = agent_reducer(state, event)
        self.assertTrue(state.suspended)
        self.assertFalse(state.is_terminal)
        held_hash = state.current_hash()
        writer = open_log(self.log, system_prompt="sys", model="m", workspace="w",
                          max_steps=9, extra={"rule": [1]})
        for rec in state.trace:
            writer.write_event(rec.event, rec.state_hash)
        writer.close(state.step_count, state.current_hash(), False, None, suspended=True)
        self.assertTrue(verify(self.log)[0])
        resumed, _ = agent_reducer(state, AgentEvent("USER_INPUT", "denied"))
        self.assertFalse(resumed.suspended)
        self.assertFalse(resumed.is_terminal)
        self.assertEqual(resumed.trace[-1].prev_hash, held_hash)
        replayed, ok = replay_trace("sys", events + [AgentEvent("USER_INPUT", "denied")],
                                    max_steps=9, policy=policy)
        self.assertTrue(ok)
        self.assertEqual(replayed.current_hash(), resumed.current_hash())
        _, wrong_policy = replay_trace("sys", events + [AgentEvent("USER_INPUT", "denied")],
                                       max_steps=9,
                                       policy={"model": "changed", "workspace": "w", "extra": {"rule": [1]}},
                                       recorded_hashes=[r.state_hash for r in resumed.trace])
        self.assertFalse(wrong_policy)

    def test_escalation_at_last_slot_terminates_without_resume(self):
        state = AgentState.initial("sys", max_steps=2)
        state, _ = agent_reducer(state, AgentEvent("USER_INPUT", "go"))
        state, _ = agent_reducer(state, AgentEvent("ESCALATE", "held"))
        self.assertTrue(state.is_terminal)
        self.assertFalse(state.suspended)
        self.assertEqual(state.terminal_reason, "BOUNDED_MAX_STEPS_REACHED")
        resumed, _ = agent_reducer(state, AgentEvent("USER_INPUT", "approved"))
        self.assertIs(resumed, state)

    def test_valid_log_mutations_rejected(self):
        self.test_driver_no_model_without_reply_slot()
        original = [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]
        mutations = {
            "model": lambda r: r[0].update(model="different"),
            "workspace": lambda r: r[0].update(workspace="different"),
            "event": lambda r: r[1].update(payload="changed"),
            "final_hash": lambda r: r[-1].update(state_hash="f" * 64),
            "final_status": lambda r: r[-1].update(is_terminal=False, suspended=True, terminal_reason=None),
            "missing_final": lambda r: r.pop(),
            "duplicate_final": lambda r: r.append(r[-1].copy()),
            "future_version": lambda r: r[0].update(version="nakedagent.eventlog@v9"),
            "bad_seq": lambda r: r[1].update(seq=2),
        }
        for name, mutation in mutations.items():
            with self.subTest(name=name):
                rows = json.loads(json.dumps(original))
                mutation(rows)
                self.log.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
                self.assertFalse(verify(self.log)[0])


if __name__ == "__main__":
    unittest.main()
