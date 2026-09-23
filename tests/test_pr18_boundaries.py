"""Offline counterexamples for PR18 complete replay and pre-effect bounds."""
import json
import tempfile
import unittest
from pathlib import Path

from nakedagent.driver import run_functional
from nakedagent.functional import AgentEvent, AgentState, ToolAction, compute_step_hash
from nakedagent.replay import verify


class PR18Boundaries(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "run.jsonl"
        self.model_calls = 0
        self.tool_calls = 0

    def run_agent(self, max_steps=5, reply="done"):
        def llm(_messages, _model, _host):
            self.model_calls += 1
            return reply

        def tool(_args, _content, _workspace):
            self.tool_calls += 1
            return "observed-result"

        return run_functional("go", "model", Path(self.temp.name), "offline",
                              tools={"echo": tool}, llm_fn=llm,
                              event_log_path=self.path, max_steps=max_steps)

    def records(self):
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines()]

    def put(self, records):
        self.path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")

    def test_complete_log_rejects_structural_and_policy_tamper(self):
        self.run_agent()
        baseline = self.records()
        self.assertTrue(verify(self.path)[0])
        variants = {
            "missing final": baseline[:-1],
            "prefix only": baseline[:2],
            "duplicate final": baseline + [baseline[-1]],
            "final before event": [baseline[0], baseline[-1], *baseline[1:-1]],
        }
        for name, records in variants.items():
            with self.subTest(name=name):
                self.put(records)
                self.assertFalse(verify(self.path)[0])
        for name, index, key, value in (
            ("policy", 0, "system_prompt", "different"),
            ("model", 0, "model", "different"),
            ("workspace", 0, "workspace", "different"),
            ("budget", 0, "max_steps", 25),
            ("metadata", 1, "metadata", {"x": 1}),
            ("sequence", 1, "seq", 17),
            ("version", 0, "version", "unknown"),
            ("terminal flag", -1, "is_terminal", False),
            ("terminal reason", -1, "terminal_reason", "fabricated"),
        ):
            with self.subTest(name=name):
                records = json.loads(json.dumps(baseline))
                records[index][key] = value
                self.put(records)
                self.assertFalse(verify(self.path)[0])

    def test_duplicate_json_keys_and_nonfinite_rejected(self):
        self.run_agent()
        raw = self.path.read_text(encoding="utf-8")
        self.path.write_text(raw.replace('"seq": 1', '"seq": 1, "seq": 1', 1), encoding="utf-8")
        self.assertFalse(verify(self.path)[0])
        self.run_agent()
        for invalid in ("NaN", "1e999"):
            with self.subTest(invalid=invalid):
                self.run_agent()
                self.path.write_text(self.path.read_text(encoding="utf-8").replace('"seq": 1', f'"seq": {invalid}', 1), encoding="utf-8")
                self.assertFalse(verify(self.path)[0])

    def test_invalid_utf8_rejected_without_crash(self):
        self.path.write_bytes(b"\xff\n")
        ok, detail = verify(self.path)
        self.assertFalse(ok)
        self.assertIn("cannot read log", detail)

    def test_pre_effect_capacity_and_replay(self):
        reply = "```echo a\nb\n```\n```echo c\nd\n```"
        for bound, expected_models, expected_tools in ((1, 0, 0), (2, 1, 0),
                                                        (3, 1, 1), (4, 1, 2)):
            with self.subTest(bound=bound):
                self.model_calls = self.tool_calls = 0
                state = self.run_agent(bound, reply)
                self.assertEqual(state.step_count, bound)
                self.assertEqual(state.terminal_reason, "BOUNDED_MAX_STEPS_REACHED")
                self.assertEqual(self.model_calls, expected_models)
                self.assertEqual(self.tool_calls, expected_tools)
                self.assertEqual(sum(r.event.event_type == "TOOL_RESULT" for r in state.trace), expected_tools)
                self.assertTrue(verify(self.path)[0], verify(self.path)[1])

    def test_default_bound_has_no_unadmitted_effect(self):
        state = self.run_agent(25, "```echo a\nb\n```")
        self.assertEqual(state.step_count, 25)
        self.assertEqual(self.tool_calls, 12)
        self.assertEqual(sum(r.event.event_type == "TOOL_RESULT" for r in state.trace), 12)
        self.assertTrue(verify(self.path)[0])

    def test_exception_trailer_is_inspectable_but_not_complete(self):
        def fail(_messages, _model, _host):
            raise RuntimeError("synthetic model failure")

        with self.assertRaisesRegex(RuntimeError, "synthetic"):
            run_functional("go", "model", Path(self.temp.name), "offline", tools={},
                           llm_fn=fail, event_log_path=self.path)
        self.assertEqual(self.records()[-1]["is_terminal"], False)
        self.assertFalse(verify(self.path)[0])

    def test_policy_encoding_and_snapshots(self):
        a = AgentState.initial("A", 5)
        b = AgentState.initial("B", 5)
        c = AgentState.initial("A", 6)
        self.assertEqual(len({a.current_hash(), b.current_hash(), c.current_hash()}), 3)
        with self.assertRaises(TypeError):
            a.history[0]["content"] = "changed"
        source = {"nested": {"x": [1]}}
        event = AgentEvent("MODEL_REPLY", "done", source)
        source["nested"]["x"].append(2)
        with self.assertRaises(TypeError):
            event.metadata["nested"]["x"] = (3,)
        self.assertEqual(event.metadata["nested"]["x"], (1,))
        first = compute_step_hash(a.current_hash(), 1, event, (ToolAction("ab", "c", ""),))
        other = compute_step_hash(a.current_hash(), 1, event, (ToolAction("a", "bc", ""),))
        self.assertNotEqual(first, other)

    def test_invalid_bound_rejected_before_model_and_tool(self):
        for bound in (True, 0, -1, 1.5):
            with self.subTest(bound=bound), self.assertRaises(ValueError):
                self.run_agent(bound, "```echo a\nb\n```")
        self.assertEqual(self.model_calls, 0)
        self.assertEqual(self.tool_calls, 0)


if __name__ == "__main__":
    unittest.main()
