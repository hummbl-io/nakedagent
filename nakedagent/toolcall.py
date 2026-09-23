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

_OPEN_RE = re.compile(r"^```(?P<tool>[a-zA-Z0-9_]+)(?: (?P<args>[^\n`]*))?$")
_FENCE_MARKER_RE = re.compile(r"^`{3,}")


@dataclass(frozen=True)
class ToolCall:
    tool: str
    args: str
    content: str


def _bare_ticks(line: str) -> int:
    """Length of a column-0 all-backtick line, else 0.

    Column 0 only: an indented run of backticks is body content, not a
    fence marker (matching the opener, which requires ^```). Trailing
    whitespace is tolerated -- a close is still a close.
    """
    s = line.rstrip()
    if s and set(s) == {"`"}:
        return len(s)
    return 0


def _fence_ticks(line: str) -> int:
    """Length of the opening backtick run of a column-0 fence marker, else 0."""
    m = _FENCE_MARKER_RE.match(line)
    return len(m.group(0)) if m else 0


def parse(text: str) -> list[ToolCall]:
    """Return every tool call found in `text`, in the order they appear.

    Unclosed blocks yield a refusal ToolCall (tool ``__refused__``) so the
    refusal is surfaced to the model instead of silently dropping the call
    and every later call the unclosed body would have swallowed.
    """
    # CRLF normalize, then split ONLY on \n: str.splitlines() also splits on
    # \x85, \u2028, \u2029, \v, \f and friends, which would fabricate a
    # column-0 fence out of what markdown treats as mid-line text.
    lines = text.replace("\r\n", "\n").split("\n")
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
        # Stack of fence tick-counts; a real call always opens with exactly
        # 3. A bare close only pops the stack when its length equals the
        # current fence's -- a longer bare run is body content, not a close
        # (a 4-tick line must not prematurely end a 3-tick call).
        stack = [3]
        i += 1
        closed = False

        while i < n:
            line = lines[i]
            bare = _bare_ticks(line)
            if bare:
                if bare == stack[-1]:
                    stack.pop()
                    i += 1
                    if not stack:
                        closed = True
                        break
                    # A nested fence's close is still outer-block body.
                    body.append(line)
                    continue
                body.append(line)
                i += 1
                continue
            ticks = _fence_ticks(line)
            if ticks:
                stack.append(ticks)
            body.append(line)
            i += 1

        if closed:
            calls.append(ToolCall(tool=tool, args=args, content="\n".join(body)))
        else:
            calls.append(ToolCall(
                tool="__refused__",
                args=tool,
                content=f"unclosed fence for '{tool}'; call refused",
            ))

    return calls
