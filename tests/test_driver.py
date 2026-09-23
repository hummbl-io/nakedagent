"""Tests for the functional driver: reducer-interleaved loop + event log."""
import tempfile
import unittest
from pathlib import Path

from nakedagent.driver import run_functional
from nakedagent.replay import verify


def _scripted_llm(replies):
    """Return an llm_fn that yields scripted replies in order."""
    it = iter(replies)

    def _chat(messages, model, host):
        try:
            return next(it)
        except StopIteration:
            return "scripted llm exhausted"

    return _chat


def _echo_tool(args, content, workspace):
    return f"echo:{args}:{content}"


class TestDriver(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.workspace = Path(self.td.name)
        self.tools = {"echo": _echo_tool}

    def tearDown(self):
        self.td.cleanup()

    def test_no_tool_calls_terminates_with_marker(self):
        state = run_functional(
            "hi", "m", self.workspace, "h",
            tools=self.tools, llm_fn=_scripted_llm(["just text"]),
        )
        self.assertTrue(state.is_terminal)
        self.assertEqual(state.terminal_reason, "MODEL_FINISHED")
        # USER_INPUT + MODEL_REPLY + TERMINATION
        self.assertEqual(state.step_count, 3)

    def test_tool_call_executes_and_feeds_result(self):
        replies = [
            "```echo myargs\nhello world\n```",
            "done",
        ]
        state = run_functional(
            "go", "m", self.workspace, "h",
            tools=self.tools, llm_fn=_scripted_llm(replies),
        )
        tool_results = [
            r for r in state.trace if r.event.event_type == "TOOL_RESULT"
        ]
        self.assertEqual(len(tool_results), 1)
        self.assertEqual(tool_results[0].event.payload, "echo:myargs:hello world")
        self.assertEqual(tool_results[0].event.metadata["tool"], "echo")
        self.assertTrue(state.is_terminal)

    def test_unknown_tool_becomes_result_not_crash(self):
        replies = ["```nosuch x\nbody\n```", "ok"]
        state = run_functional(
            "go", "m", self.workspace, "h",
            tools=self.tools, llm_fn=_scripted_llm(replies),
        )
        results = [r for r in state.trace if r.event.event_type == "TOOL_RESULT"]
        self.assertIn("unknown tool", results[0].event.payload)

    def test_event_log_written_and_replay_verifies(self):
        log_path = self.workspace / "run.jsonl"
        replies = ["```echo a\nb\n```", "done"]
        state = run_functional(
            "go", "m", self.workspace, "h",
            tools=self.tools, llm_fn=_scripted_llm(replies),
            event_log_path=log_path,
        )
        ok, detail = verify(log_path)
        self.assertTrue(ok, detail)
        self.assertIn(str(state.step_count), detail)

    def test_corrupted_log_fails_replay(self):
        log_path = self.workspace / "run.jsonl"
        run_functional(
            "go", "m", self.workspace, "h",
            tools=self.tools, llm_fn=_scripted_llm(["done"]),
            event_log_path=log_path,
        )
        # Tamper: flip a character in an event payload
        lines = log_path.read_text().splitlines()
        lines[1] = lines[1].replace("go", "XX")
        log_path.write_text("\n".join(lines) + "\n")
        ok, _detail = verify(log_path)
        self.assertFalse(ok)

    def test_max_steps_bound_applies(self):
        # Every reply has a tool call; driver must stop at max_steps.
        state = run_functional(
            "go", "m", self.workspace, "h",
            tools=self.tools,
            llm_fn=_scripted_llm(["```echo a\nb\n```"] * 100),
            max_steps=4,
        )
        self.assertTrue(state.is_terminal)
        self.assertEqual(state.terminal_reason, "BOUNDED_MAX_STEPS_REACHED")
        self.assertLessEqual(state.step_count, 4)

    def test_log_trailer_written_on_llm_exception(self):
        def _boom(messages, model, host):
            raise RuntimeError("model down")

        log_path = self.workspace / "run.jsonl"
        with self.assertRaises(RuntimeError):
            run_functional(
                "go", "m", self.workspace, "h",
                tools=self.tools, llm_fn=_boom, event_log_path=log_path,
            )
        from nakedagent.eventlog import read_log

        log = read_log(log_path)
        # Trailer pins the partial state; truncation is distinguishable.
        self.assertIsNotNone(log.trailer)
        self.assertFalse(log.trailer["is_terminal"])


if __name__ == "__main__":
    unittest.main()
