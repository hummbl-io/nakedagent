import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nakedagent.loop import MAX_STEPS, _run_until_done, step


class TestStep(unittest.TestCase):
    """Highest-value test the GLM-5.2 review flagged as missing: mock the
    model reply and assert on what the loop actually *does*, rather than
    only unit-testing the parser and tools in isolation."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    @patch("sys.stdin.isatty", return_value=False)
    @patch("nakedagent.loop.llm.chat")
    def test_simple_tool_call_runs_and_returns_true(self, mock_chat, _mock_isatty):
        mock_chat.return_value = "```shell\necho hi\n```"
        messages = [{"role": "user", "content": "run echo hi"}]
        ran_again = step(messages, "fake-model", self.workspace)
        self.assertTrue(ran_again)
        self.assertIn("hi", messages[-1]["content"])

    @patch("nakedagent.loop.llm.chat")
    def test_no_tool_calls_returns_false(self, mock_chat):
        mock_chat.return_value = "just a normal reply, no tools"
        messages = [{"role": "user", "content": "hi"}]
        self.assertFalse(step(messages, "fake-model", self.workspace))

    @patch("nakedagent.loop.llm.chat")
    def test_nested_fence_reply_does_not_execute_fabricated_shell_call(
        self, mock_chat
    ):
        # Regression for GLM-5.2 review finding #1 at the loop level, not
        # just the parser level: a `write` reply whose body happens to
        # contain a nested ```shell example must be written as one inert
        # file (the example text is just file content) -- not parsed as a
        # second tool call that actually runs the example command.
        mock_chat.return_value = (
            "```write docs.md\n"
            "intro\n"
            "```python\n"
            "print(1)\n"
            "```\n"
            "```shell\n"
            "echo SHOULD-NOT-RUN\n"
            "```\n"
            "```"
        )
        messages = [{"role": "user", "content": "write some docs"}]
        step(messages, "fake-model", self.workspace)
        # tool outputs are appended as role="user" too (see loop.py), so
        # filter by the "[tool output]" marker rather than by role alone --
        # otherwise the original human prompt (also role="user") is
        # miscounted as a tool result.
        tool_outputs = [
            m["content"]
            for m in messages
            if m["role"] == "user" and m["content"].startswith("[")
        ]
        # exactly one tool ran (the write), never a [shell output] message
        self.assertEqual(len(tool_outputs), 1)
        self.assertTrue(tool_outputs[0].startswith("[write output]"))
        self.assertTrue((self.workspace / "docs.md").exists())
        written = (self.workspace / "docs.md").read_text()
        self.assertIn("echo SHOULD-NOT-RUN", written)  # inert text, not executed

    @patch("nakedagent.loop.llm.chat")
    def test_unknown_tool_reports_error_without_crashing(self, mock_chat):
        mock_chat.return_value = "```nonexistent\nfoo\n```"
        messages = [{"role": "user", "content": "hi"}]
        step(messages, "fake-model", self.workspace)
        self.assertIn("unknown tool", messages[-1]["content"])

    @patch("nakedagent.loop.llm.chat")
    def test_tool_exception_is_caught_not_raised(self, mock_chat):
        # Regression for finding #3: a tool bug must reach the model as an
        # error message, not escape step() as a raw exception.
        mock_chat.return_value = "```patch nope.txt\nnot a valid block\n```"
        messages = [{"role": "user", "content": "patch nope.txt"}]
        step(messages, "fake-model", self.workspace)  # must not raise
        self.assertIn("Error", messages[-1]["content"])

    @patch("sys.stdin.isatty", return_value=False)
    @patch("nakedagent.loop.llm.chat")
    def test_max_steps_is_a_real_bound(self, mock_chat, _mock_isatty):
        # A model stuck always emitting another tool call must not loop
        # forever -- _run_until_done is where the cap actually lives.
        mock_chat.return_value = "```shell\ntrue\n```"  # always another call
        messages = [{"role": "user", "content": "loop forever"}]
        _run_until_done(messages, "fake-model", self.workspace, "http://unused")
        self.assertEqual(mock_chat.call_count, MAX_STEPS)


if __name__ == "__main__":
    unittest.main()
