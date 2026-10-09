"""Streaming transport and the system preamble.

Both are foundation changes, so these tests pin the two promises the
foundation makes: an existing caller sees no difference, and a streamed
reply returns the same text a non-streamed one would.
"""

import json
import unittest
from unittest.mock import patch

from nakedagent.llm import chat
from nakedagent.loop import SYSTEM_PROMPT, TOOLS, _system_prompt

OLLAMA_LINES = [
    b'{"message": {"content": "Hello"}, "done": false}\n',
    b'{"message": {"content": ", "}, "done": false}\n',
    b'{"message": {"content": "world"}, "done": false}\n',
    b'{"message": {"content": ""}, "done": true}\n',
]

OPENAI_LINES = [
    b"\n",
    b'data: {"choices": [{"delta": {"content": "Hello"}}]}\n',
    b'data: {"choices": [{"delta": {"content": ", world"}}]}\n',
    b"data: [DONE]\n",
]


def _streamed(lines):
    """A urlopen context manager whose response iterates `lines`."""
    mock = patch("urllib.request.urlopen")
    handle = mock.start()
    handle.return_value.__enter__.return_value = iter(lines)
    return mock, handle


class OllamaStreamTests(unittest.TestCase):
    def test_joins_deltas_in_order(self):
        mock, _ = _streamed(OLLAMA_LINES)
        try:
            out = chat([], "m", host="http://localhost:11434", stream=True)
        finally:
            mock.stop()
        self.assertEqual(out, "Hello, world")

    def test_on_chunk_receives_each_delta(self):
        seen = []
        mock, _ = _streamed(OLLAMA_LINES)
        try:
            out = chat(
                [], "m", host="http://localhost:11434",
                stream=True, on_chunk=seen.append,
            )
        finally:
            mock.stop()
        self.assertEqual(seen, ["Hello", ", ", "world"])
        self.assertEqual("".join(seen), out)

    def test_stream_flag_reaches_the_payload(self):
        mock, handle = _streamed(OLLAMA_LINES)
        try:
            chat([], "m", host="http://localhost:11434", stream=True)
        finally:
            mock.stop()
        sent = json.loads(handle.call_args[0][0].data.decode("utf-8"))
        self.assertIs(sent["stream"], True)
        # think:false must survive: a thinking model otherwise streams its
        # reasoning and leaves content empty, which is the bug the
        # non-streaming path already guards against.
        self.assertIs(sent["think"], False)

    def test_malformed_line_is_skipped_not_fatal(self):
        """A stream is a partial result; a bad line must not discard the rest."""
        lines = [
            b'{"message": {"content": "keep"}, "done": false}\n',
            b"{ this is not json\n",
            b'{"message": {"content": "this"}, "done": true}\n',
        ]
        mock, _ = _streamed(lines)
        try:
            out = chat([], "m", host="http://localhost:11434", stream=True)
        finally:
            mock.stop()
        self.assertEqual(out, "keepthis")

    def test_done_stops_reading(self):
        lines = [
            b'{"message": {"content": "first"}, "done": true}\n',
            b'{"message": {"content": "AFTER-DONE"}, "done": false}\n',
        ]
        mock, _ = _streamed(lines)
        try:
            out = chat([], "m", host="http://localhost:11434", stream=True)
        finally:
            mock.stop()
        self.assertEqual(out, "first")


class OpenAIStreamTests(unittest.TestCase):
    def test_sse_deltas_are_joined(self):
        mock, _ = _streamed(OPENAI_LINES)
        try:
            out = chat(
                [], "m", host="https://api.example.invalid/v1",
                api="openai", stream=True,
            )
        finally:
            mock.stop()
        self.assertEqual(out, "Hello, world")

    def test_non_data_lines_are_ignored(self):
        lines = [
            b": keep-alive comment\n",
            b"event: ping\n",
            b'data: {"choices": [{"delta": {"content": "ok"}}]}\n',
            b"data: [DONE]\n",
        ]
        mock, _ = _streamed(lines)
        try:
            out = chat(
                [], "m", host="https://api.example.invalid/v1",
                api="openai", stream=True,
            )
        finally:
            mock.stop()
        self.assertEqual(out, "ok")


class NonStreamingUnchangedTests(unittest.TestCase):
    """The default path must behave exactly as before."""

    @patch("urllib.request.urlopen")
    def test_default_sends_stream_false(self, mock_urlopen):
        body = json.dumps({"message": {"content": "whole reply"}}).encode()
        mock_urlopen.return_value.__enter__.return_value.read.return_value = body
        out = chat([], "m", host="http://localhost:11434")
        self.assertEqual(out, "whole reply")
        sent = json.loads(mock_urlopen.call_args[0][0].data.decode("utf-8"))
        self.assertIs(sent["stream"], False)


class SystemPreambleTests(unittest.TestCase):
    def test_no_preamble_is_byte_identical_to_the_baseline(self):
        """The docstring promises this; pin it so a future edit cannot break it."""
        self.assertEqual(_system_prompt(TOOLS), SYSTEM_PROMPT)
        self.assertEqual(_system_prompt(TOOLS, None), SYSTEM_PROMPT)
        self.assertEqual(_system_prompt(TOOLS, "   "), SYSTEM_PROMPT)

    def test_preamble_precedes_the_tool_contract(self):
        """Role first, tool mechanics after, so a persona cannot redefine them."""
        prompt = _system_prompt(TOOLS, "You are a specialist.")
        self.assertTrue(prompt.startswith("You are a specialist."))
        self.assertIn(SYSTEM_PROMPT, prompt)
        self.assertGreater(prompt.index(SYSTEM_PROMPT), 0)

    def test_preamble_is_stripped(self):
        prompt = _system_prompt(TOOLS, "\n\n  You are a specialist.  \n\n")
        self.assertTrue(prompt.startswith("You are a specialist."))


if __name__ == "__main__":
    unittest.main(verbosity=2)
