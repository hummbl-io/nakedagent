"""Built-in tools. Each is `(args: str, content: str, workspace: Path) -> str`.

`args` is whatever followed the tool name on the fence line (usually a path).
`content` is the fence body. Return value is fed back to the model as the
tool's output message -- including errors, so the model can see and fix its
own mistakes rather than the loop just dying.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Callable

ToolFunc = Callable[[str, str, Path], str]

MAX_OUTPUT = 8000  # chars; keeps one runaway command from blowing the context


def _truncate(s: str) -> str:
    if len(s) <= MAX_OUTPUT:
        return s
    return s[:MAX_OUTPUT] + f"\n...[truncated, {len(s) - MAX_OUTPUT} more chars]"


def tool_shell(args: str, content: str, workspace: Path) -> str:
    """Runs `content` as a shell command in the workspace.

    No allowlist, no resource limits beyond the timeout below -- this is an
    unrestricted `subprocess.run(shell=True)`. The only gate is an
    interactive y/N confirmation, and that only fires when stdin is a real
    TTY: a one-shot/piped/non-interactive run has no one to answer a
    prompt, so it proceeds unconfirmed. That's a real trust boundary, not
    an oversight -- documented in README.md.
    """
    cmd = content.strip() or args.strip()
    if not cmd:
        return "Error: shell tool got no command."
    if sys.stdin.isatty():
        print(f"\033[33mnakedagent wants to run:\033[0m {cmd}")
        try:
            answer = input("Allow? [y/N] ").strip().lower()
        except EOFError:
            # isatty() said yes but the read still failed -- fail safe:
            # no answer means don't run, not "crash the whole loop."
            return "Error: could not read a confirmation; command not run."
        if answer not in ("y", "yes"):
            return "Error: user declined to run this command."
    try:
        proc = subprocess.run(
            cmd,
            shell=True,
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=120,
            stdin=subprocess.DEVNULL,  # a command that tries to read stdin
            # would otherwise hang instead of failing fast (devin review, P3.8)
        )
    except subprocess.TimeoutExpired:
        return "Error: command timed out after 120s."
    parts = [f"(exit {proc.returncode})"]
    if proc.stdout:
        parts.append(proc.stdout)
    if proc.stderr:
        parts.append(f"--- stderr ---\n{proc.stderr}")
    return _truncate("\n".join(parts))


def tool_read(args: str, content: str, workspace: Path) -> str:
    path = args.strip()
    if not path:
        return "Error: read tool needs a path, e.g. ```read path/to/file.py```"
    target = (workspace / path).resolve()
    if not target.is_relative_to(workspace.resolve()):
        return f"Error: {path} is outside the workspace."
    if not target.exists():
        return f"Error: {path} does not exist."
    if target.is_dir():
        names = sorted(p.name for p in target.iterdir())
        return f"{path} is a directory:\n" + "\n".join(names)
    # No line numbers: `patch`'s SEARCH text has to match file content
    # exactly, and a model that copies from a numbered `read` output would
    # copy the numbers too (devin review, P2.4).
    return _truncate(target.read_text(encoding="utf-8", errors="replace"))


def tool_write(args: str, content: str, workspace: Path) -> str:
    path = args.strip()
    if not path:
        return "Error: write tool needs a path, e.g. ```write path/to/file.py```"
    target = (workspace / path).resolve()
    if not target.is_relative_to(workspace.resolve()):
        return f"Error: {path} is outside the workspace."
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"Wrote {len(content)} chars to {path}."


def tool_patch(args: str, content: str, workspace: Path) -> str:
    """Search-and-replace edit, aider-style SEARCH/REPLACE block:

        <<<<<<< SEARCH
        old text
        =======
        new text
        >>>>>>> REPLACE
    """
    path = args.strip()
    if not path:
        return "Error: patch tool needs a path, e.g. ```patch path/to/file.py```"
    target = (workspace / path).resolve()
    if not target.is_relative_to(workspace.resolve()):
        return f"Error: {path} is outside the workspace."
    if not target.exists():
        return f"Error: {path} does not exist. Use write to create it."

    try:
        search, replace = _split_search_replace(content)
    except ValueError as e:
        return f"Error: malformed patch block ({e})."

    original = target.read_text(encoding="utf-8", errors="replace")
    count = original.count(search)
    if count == 0:
        return f"Error: SEARCH text not found in {path}. It must match exactly, including whitespace."
    if count > 1:
        return f"Error: SEARCH text matches {count} locations in {path}; make it more specific."

    target.write_text(original.replace(search, replace, 1), encoding="utf-8")
    return f"Patched {path}."


def _split_search_replace(block: str) -> tuple[str, str]:
    """Split a <<<<<<< SEARCH / ======= / >>>>>>> REPLACE block.

    Markers are found in order (start, then sep after start, then end after
    sep) rather than each independently from index 0 -- the latter let a
    marker-shaped line *inside* the SEARCH or REPLACE body hijack the split
    and silently produce the wrong edit while still reporting success (e.g.
    patching a file that itself contains git conflict markers). A second
    <<<<<<< before the matching >>>>>>> is rejected outright rather than
    guessed at, for the same reason.
    """
    lines = block.splitlines()
    try:
        start = next(i for i, ln in enumerate(lines) if ln.strip().startswith("<<<<<<<"))
        sep = next(
            i for i in range(start + 1, len(lines)) if lines[i].strip() == "======="
        )
        end = next(
            i
            for i in range(sep + 1, len(lines))
            if lines[i].strip().startswith(">>>>>>>")
        )
    except StopIteration:
        raise ValueError(
            "expected <<<<<<< SEARCH / ======= / >>>>>>> REPLACE markers, in that order"
        )
    if any(lines[i].strip().startswith("<<<<<<<") for i in range(start + 1, end)):
        raise ValueError("a second <<<<<<< marker appears before the matching >>>>>>>")
    search = "\n".join(lines[start + 1 : sep])
    replace = "\n".join(lines[sep + 1 : end])
    return search, replace


TOOLS: dict[str, ToolFunc] = {
    "shell": tool_shell,
    "read": tool_read,
    "write": tool_write,
    "patch": tool_patch,
}
