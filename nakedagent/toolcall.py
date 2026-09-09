"""Parse tool invocations out of a model's markdown response.

Format (same shape gptme uses, reimplemented from scratch here): a fenced
code block whose language tag is the tool name, e.g.

    ```shell
    ls -la
    ```

    ```write path/to/file.py
    print("hi")
    ```

This works with any model that can write a code fence -- no dependency on
a provider's native tool-calling API.

The parser is a depth-tracking line scanner, not a single regex: a body
line that itself opens a nested fence (any ``` line followed by more text,
e.g. an inner ```python example) increments depth instead of ending the
block, and only a bare ``` line (nothing else on it) at depth 1 closes the
outer call. A block that never returns to depth 0 is refused rather than
guessed at -- an earlier lazy-regex version stopped at the *first* ``` it
saw regardless of nesting, which silently truncated `write` bodies and, in
the worst case, let a nested ```shell example get mis-parsed as a second,
real, executable tool call.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_OPEN_RE = re.compile(r"^```(?P<tool>[a-zA-Z0-9_]+)(?: (?P<args>[^\n]*))?$")
_FENCE_MARKER_RE = re.compile(r"^`{3,}")


@dataclass(frozen=True)
class ToolCall:
    tool: str
    args: str
    content: str


def _is_bare_close(line: str) -> bool:
    """A line that is *only* backticks (3+), nothing else -- always a close."""
    s = line.strip()
    return len(s) >= 3 and set(s) == {"`"}


def _is_fence_marker(line: str) -> bool:
    """Any line starting a run of 3+ backticks, open or close."""
    return _FENCE_MARKER_RE.match(line.strip()) is not None


def parse(text: str) -> list[ToolCall]:
    """Return every tool call found in `text`, in the order they appear."""
    lines = text.split("\n")
    calls: list[ToolCall] = []
    i, n = 0, len(lines)
    while i < n:
        m = _OPEN_RE.match(lines[i])
        if not m:
            i += 1
            continue

        tool = m["tool"]
        args = (m["args"] or "").strip()
        body: list[str] = []
        depth = 1
        i += 1
        closed = False

        while i < n:
            line = lines[i]
            if _is_bare_close(line):
                depth -= 1
                i += 1
                if depth == 0:
                    closed = True
                    break
                body.append(line)
                continue
            if _is_fence_marker(line):
                depth += 1
            body.append(line)
            i += 1

        if closed:
            calls.append(ToolCall(tool=tool, args=args, content="\n".join(body)))
        # else: unterminated (depth never returned to 0) -- refuse rather
        # than guess at where it was meant to close.

    return calls
