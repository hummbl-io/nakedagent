import unittest

from nakedagent.toolcall import parse


class TestParse(unittest.TestCase):
    def test_single_shell_call(self):
        calls = parse("Let me check.\n```shell\nls -la\n```\nDone.")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].tool, "shell")
        self.assertEqual(calls[0].args, "")
        self.assertEqual(calls[0].content, "ls -la")

    def test_call_with_args(self):
        calls = parse("```write foo/bar.py\nprint(1)\n```")
        self.assertEqual(calls[0].tool, "write")
        self.assertEqual(calls[0].args, "foo/bar.py")
        self.assertEqual(calls[0].content, "print(1)")

    def test_no_calls(self):
        self.assertEqual(parse("just talking, no fences here"), [])

    def test_multiple_calls_in_order(self):
        text = "```read a.py\n```\nsome text\n```read b.py\n```"
        calls = parse(text)
        self.assertEqual([c.args for c in calls], ["a.py", "b.py"])

    def test_empty_body_fence(self):
        # matches the `read <path>` shape from SYSTEM_PROMPT: no body line at all
        calls = parse("```read a.py\n```")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].args, "a.py")
        self.assertEqual(calls[0].content, "")

    def test_nested_fence_is_captured_whole_not_truncated(self):
        # GLM-5.2 review finding #1: a `write` body containing its own
        # ```python example used to silently truncate to content before
        # the inner fence (the lazy regex closed on the first ``` it saw,
        # regardless of nesting). The depth-tracking scanner captures the
        # nested fence as part of the body instead.
        text = (
            "```write docs.md\n"
            "# Title\n"
            "```python\n"
            "print(1)\n"
            "```\n"
            "more text\n"
            "```"
        )
        calls = parse(text)
        self.assertEqual(len(calls), 1)
        self.assertEqual(
            calls[0].content, "# Title\n```python\nprint(1)\n```\nmore text"
        )

    def test_nested_fence_does_not_fabricate_a_shell_call(self):
        # Same finding, worse variant: a second inner fence tagged `shell`
        # used to get mis-parsed as a *second*, real, executable tool call
        # (the loop would then actually run `rm -rf /`). It's correctly one
        # `write` call now, not two calls with a fabricated `shell` among
        # them.
        text = (
            "```write docs.md\n"
            "intro\n"
            "```python\n"
            "print(1)\n"
            "```\n"
            "```shell\n"
            "rm -rf /\n"
            "```\n"
            "```"
        )
        calls = parse(text)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].tool, "write")
        self.assertNotIn("shell", [c.tool for c in calls])

    def test_multiline_content_preserved(self):
        text = "```write x.py\nline1\nline2\n```"
        self.assertEqual(parse(text)[0].content, "line1\nline2")


if __name__ == "__main__":
    unittest.main()
