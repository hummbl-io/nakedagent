import tempfile
import unittest
from functools import partial
from pathlib import Path
from unittest.mock import patch

from nakedagent.loop import (
    MAX_STEPS,
    SYSTEM_PROMPT,
    _run_until_done,
    _system_prompt,
    step,
)
from nakedagent.tools import TOOLS, tool_shell


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
        # python, not echo: non-interactive shell runs programs directly, and on
        # Windows echo is a cmd.exe built-in rather than an executable.
        mock_chat.return_value = "```shell\npython -c \"print('hi')\"\n```"
        messages = [{"role": "user", "content": "run a command"}]
        tools = dict(TOOLS)
        tools["shell"] = partial(
            tool_shell, allow_shell=True, shell_allowlist=("python",)
        )
        ran_again = step(messages, "fake-model", self.workspace, tools=tools)
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

    @patch("sys.stdin.isatty", return_value=False)
    @patch("nakedagent.loop.llm.chat")
    def test_uppercase_fence_tag_runs_the_tool(self, mock_chat, _mock_isatty):
        # bespoke: models often emit ```SHELL (valid markdown, capitalized
        # language tag). Without case-normalization at the lookup this became
        # "unknown tool 'SHELL'" and the command never ran -- a silent
        # capability gap, not a crash.
        mock_chat.return_value = "```SHELL\npython -c \"print('upper-works')\"\n```"
        messages = [{"role": "user", "content": "run it"}]
        tools = dict(TOOLS)
        tools["shell"] = partial(
            tool_shell, allow_shell=True, shell_allowlist=("python",)
        )
        ran_again = step(messages, "fake-model", self.workspace, tools=tools)
        self.assertTrue(ran_again)
        self.assertIn("upper-works", messages[-1]["content"])

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
        mock_chat.return_value = (
            "```shell\npython -c \"import sys; sys.exit(0)\"\n```"  # always another call
        )
        messages = [{"role": "user", "content": "loop forever"}]
        tools = dict(TOOLS)
        tools["shell"] = partial(
            tool_shell, allow_shell=True, shell_allowlist=("python",)
        )
        _run_until_done(messages, "fake-model", self.workspace, "http://unused", tools=tools)
        self.assertEqual(mock_chat.call_count, MAX_STEPS)


class TestSystemPrompt(unittest.TestCase):
    """The system prompt is built from the tool registry, not a static string.
    Each tool's `.usage` attribute contributes its own fenced-block example, so
    a plugin that replaces a tool replaces its prompt example too (DOCTRINE.md:
    the chef's opinion lives on the tool, not in a static string the seam
    can't reach). Tools without `.usage` fall back to a name-only listing."""

    def test_no_plugins_byte_identical_to_static(self):
        # the four foundation tools all carry .usage, so building from the
        # registry must produce the exact same string as the old static prompt.
        self.assertEqual(_system_prompt(TOOLS), SYSTEM_PROMPT)

    def test_plugin_usage_replaces_foundation_example(self):
        # a plugin that replaces `shell` with different semantics must also
        # replace the prompt example -- otherwise the model gets the
        # foundation's syntax while the actual function expects something else.
        def my_shell(args, content, workspace):
            return "blocked"
        my_shell.usage = "```shell\n<command> [dry-run only]\n```"
        tools = dict(TOOLS)
        tools["shell"] = my_shell
        prompt = _system_prompt(tools)
        self.assertIn("[dry-run only]", prompt)
        self.assertNotIn("<a shell command to run>", prompt)

    def test_plugin_tool_without_usage_listed_by_name(self):
        # a plugin tool with no .usage is still discoverable -- listed by name
        # in the "additional tools" line, same as before the per-tool usage
        # refactor. The plugin author doesn't have to set .usage to get
        # discoverability.
        def my_tool(args, content, workspace):
            return "ok"
        tools = dict(TOOLS)
        tools["mytool"] = my_tool
        prompt = _system_prompt(tools)
        self.assertIn("`mytool`", prompt)
        self.assertNotIn("```mytool", prompt)  # no fenced example

    def test_disabled_tool_absent_from_prompt(self):
        # DISABLE removes a tool from the registry, so it must also be absent
        # from the prompt -- the model never sees it, never tries to call it.
        tools = {k: v for k, v in TOOLS.items() if k != "shell"}
        prompt = _system_prompt(tools)
        self.assertNotIn("```shell", prompt)
        self.assertIn("```read", prompt)  # others still present


if __name__ == "__main__":
    unittest.main()
