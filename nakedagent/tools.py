"""Built-in tools. Each is `(args: str, content: str, workspace: Path) -> str`.

`args` is whatever followed the tool name on the fence line (usually a path).
`content` is the fence body. Return value is fed back to the model as the
tool's output message -- including errors, so the model can see and fix its
own mistakes rather than the loop just dying.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

ToolFunc = Callable[[str, str, Path], str]

MAX_OUTPUT = 8000  # chars; keeps one runaway command from blowing the context

# Characters cmd.exe interprets. Windows runs .bat/.cmd files through cmd.exe
# even with shell=False, so these in arguments would reopen injection.
_CMD_METACHARS = set('&|<>^%!"')


def _split_command(cmd: str) -> list[str]:
    """Split a command string into argv, platform-aware.

    POSIX shlex rules treat backslash as an escape, which mangles Windows
    paths (C:\\tools\\git.exe -> C:toolsgit.exe). On Windows, split with
    posix=False and strip one layer of surrounding quotes per token instead.
    Raises ValueError on unbalanced quotes, like shlex.split.
    """
    if os.name != "nt":
        return shlex.split(cmd)
    argv = []
    for tok in shlex.split(cmd, posix=False):
        if len(tok) >= 2 and tok[0] == tok[-1] and tok[0] in "\"'":
            tok = tok[1:-1]
        argv.append(tok)
    return argv


def _is_allowed_shell_command(cmd: str, allowlist: tuple[str, ...]) -> bool:
    """Return True when `cmd` matches any allowlist entry by argv prefix.

    Both the command and each allowlist pattern are parsed with shlex so that
    shell metacharacters (;, &&, $(), |) cannot hijack a prefix match. For
    example, ``git status; rm -rf /`` parses to argv ``["git", "status;",
    "rm", "-rf", "/"]`` — the second token is ``"status;"`` not ``"status"``,
    so it does not match the ``"git status"`` pattern.
    """
    if not allowlist:
        return False
    try:
        cmd_argv = _split_command(cmd.strip())
    except ValueError:
        return False
    if not cmd_argv:
        return False
    for pattern in allowlist:
        item = pattern.strip()
        if not item:
            continue
        try:
            pat_argv = _split_command(item)
        except ValueError:
            continue
        if not pat_argv:
            continue
        if len(cmd_argv) >= len(pat_argv) and cmd_argv[: len(pat_argv)] == pat_argv:
            return True
    return False


def _log_shell_event(
    workspace: Path,
    command: str,
    *,
    allowed: bool,
    tty: bool,
    reason: str | None = None,
) -> None:
    """Append a JSONL audit event for shell invocations.

    Shell is a high-trust tool; this file is meant for local auditability.
    Logging failures never block execution: best-effort audit.
    """
    log_path = workspace / ".nakedagent" / "shell_audit.jsonl"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        event = {
            "event": "shell_tool",
            "allowed": allowed,
            "tty": tty,
            "command": command,
            "reason": reason,
        }
        from datetime import datetime, timezone

        event["ts_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
            "+00:00", "Z"
        )
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False))
            f.write("\n")
    except (OSError, ValueError):
        # Auditability should not prevent the tool call from happening.
        pass


def _truncate(s: str) -> str:
    if len(s) <= MAX_OUTPUT:
        return s
    return s[:MAX_OUTPUT] + f"\n...[truncated, {len(s) - MAX_OUTPUT} more chars]"


def _shell_gate(workspace: Path, cmd: str, is_tty: bool, allow_shell: bool,
                shell_allowlist: tuple[str, ...]) -> str | None:
    """Access checks. Returns an error string on denial, None when execution may proceed."""
    if not is_tty and not allow_shell:
        reason = "non-interactive shell execution requires --allow-shell"
        _log_shell_event(
            workspace, cmd, allowed=False, tty=False, reason=reason
        )
        return f"Error: shell execution blocked ({reason})."
    if (
        not is_tty
        and allow_shell
        and not _is_allowed_shell_command(cmd, shell_allowlist)
    ):
        reason = "non-interactive command is not in --shell-allowlist"
        _log_shell_event(workspace, cmd, allowed=False, tty=False, reason=reason)
        return f"Error: shell execution blocked ({reason})."
    if is_tty:
        return _confirm_tty(workspace, cmd)
    return None


def _confirm_tty(workspace: Path, cmd: str) -> str | None:
    """Interactive confirmation. Returns an error string on denial, None on consent."""
    prefix = (
        "\033[33mnakedagent wants to run:\033[0m"
        if sys.stdout.isatty()
        else "nakedagent wants to run:"
    )
    print(f"{prefix} {cmd}")
    try:
        answer = input("Allow? [y/N] ").strip().lower()
    except EOFError:
        # isatty() said yes but the read still failed -- fail safe:
        # no answer means don't run, not "crash the whole loop."
        _log_shell_event(
            workspace,
            cmd,
            allowed=False,
            tty=True,
            reason="interactive confirmation unreadable",
        )
        return "Error: could not read a confirmation; command not run."
    if answer not in ("y", "yes"):
        _log_shell_event(
            workspace,
            cmd,
            allowed=False,
            tty=True,
            reason="user declined"
        )
        return "Error: user declined to run this command."
    return None


def _check_exe(workspace: Path, cmd: str, argv: list[str], exe: str | None) -> str | None:
    """Executable checks. Returns an error string on failure."""
    if exe is None:
        reason = f"not an executable on PATH: {argv[0] if argv else ''}"
        _log_shell_event(workspace, cmd, allowed=False, tty=False, reason=reason)
        return (
            f"Error: '{argv[0] if argv else ''}' is not an executable on PATH. "
            "Non-interactive mode runs programs directly without a shell, so "
            "shell built-ins (e.g. cmd's echo/dir) and operators (|, &&, ;) "
            "are not available."
        )
    if (
        os.name == "nt"
        and exe.lower().endswith((".bat", ".cmd"))
        and any(ch in _CMD_METACHARS for arg in argv[1:] for ch in arg)
    ):
        reason = "cmd.exe metacharacters in arguments to a batch file"
        _log_shell_event(workspace, cmd, allowed=False, tty=False, reason=reason)
        return (
            f"Error: shell execution blocked ({reason}); Windows runs "
            ".bat/.cmd files through cmd.exe, which would interpret them."
        )
    return None


def _resolve_argv(workspace: Path, cmd: str) -> list[str] | str:
    """Parse and resolve a non-interactive command to argv, or an error string."""
    try:
        argv = _split_command(cmd)
    except ValueError as exc:
        _log_shell_event(
            workspace, cmd, allowed=False, tty=False,
            reason=f"shlex parse failure: {exc}",
        )
        return f"Error: malformed command ({exc})."
    # Resolve the program explicitly: without a shell, built-ins such as
    # cmd.exe's `echo`/`dir` do not exist, and a bare FileNotFoundError
    # tells the model nothing useful.
    exe = shutil.which(argv[0], path=os.environ.get("PATH")) if argv else None
    err = _check_exe(workspace, cmd, argv, exe)
    if err is not None:
        return err
    argv[0] = exe
    return argv


def _run_shell(workspace: Path, cmd: str, is_tty: bool, shell_timeout: int):
    """Run the confirmed command. Returns CompletedProcess or an error string."""
    try:
        if is_tty:
            # Interactive: user confirmed the full command string.
            return subprocess.run(  # nosec B602 -- interactive TTY path: user confirmed the exact command string
                cmd,
                shell=True,
                cwd=workspace,
                capture_output=True,
                text=True,
                timeout=shell_timeout,
                stdin=subprocess.DEVNULL,  # a command that tries to read stdin
                # would otherwise hang instead of failing fast (devin review, P3.8)
                check=False,
            )
        # Non-interactive: parse to argv and run without a shell so that
        # metacharacters (;, &&, $(), |) are literal args, not commands.
        resolved = _resolve_argv(workspace, cmd)
        if isinstance(resolved, str):
            return resolved
        return subprocess.run(  # nosec B603 -- fixed argv list, no shell
            resolved,
            shell=False,
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=shell_timeout,
            stdin=subprocess.DEVNULL,
            check=False,
        )
    except subprocess.TimeoutExpired:
        _log_shell_event(
            workspace,
            cmd,
            allowed=False,
            tty=is_tty,
            reason=f"timeout after {shell_timeout}s",
        )
        return f"Error: command timed out after {shell_timeout}s."
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        _log_shell_event(
            workspace,
            cmd,
            allowed=False,
            tty=is_tty,
            reason=f"execution failure: {type(exc).__name__}: {exc}",
        )
        return f"Error: command execution failed: {type(exc).__name__}: {exc}"


def tool_shell(
    args: str,
    content: str,
    workspace: Path,
    *,
    allow_shell: bool = False,
    shell_allowlist: tuple[str, ...] = (),
    shell_timeout: int = 120,
) -> str:
    """Runs `content` as a shell command in the workspace.

    By default, non-interactive execution is denied unless `allow_shell` is
    explicitly set. Non-interactive execution can still be bounded with
    `--shell-allowlist` to permit safe commands in automation contexts.
    """
    cmd = content.strip() or args.strip()
    if not cmd:
        return "Error: shell tool got no command."

    if shell_timeout <= 0:
        return "Error: --shell-timeout must be a positive integer."

    # An explicit --allow-shell is the operator's consent, so it selects the
    # allowlist policy even with a TTY on stdin. Otherwise a one-shot run
    # started from a terminal (a benchmark, a script run by hand) prompted
    # instead, often could not read an answer, and refused every command.
    is_tty = sys.stdin.isatty() and not allow_shell
    denial = _shell_gate(workspace, cmd, is_tty, allow_shell, shell_allowlist)
    if denial is not None:
        return denial
    proc_or_err = _run_shell(workspace, cmd, is_tty, shell_timeout)
    if isinstance(proc_or_err, str):
        return proc_or_err
    proc = proc_or_err

    _log_shell_event(
        workspace,
        cmd,
        allowed=True,
        tty=is_tty,
        reason=None,
    )
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

# usage: the fenced-block example shown to the model in the system prompt.
# Travels with the function so a plugin that replaces a tool can replace its
# prompt example too -- the chef's opinion lives on the tool, not in a static
# string the seam can't reach (DOCTRINE.md, "the seam is the substitution
# mechanism"). A plugin tool with no `.usage` is listed by name only.
tool_shell.usage = "```shell\n<a shell command to run>\n```"
tool_read.usage = "```read <path>\n```"
tool_write.usage = "```write <path>\n<full file content to write>\n```"
tool_patch.usage = (
    "```patch <path>\n"
    "<<<<<<< SEARCH\n"
    "<exact existing text>\n"
    "=======\n"
    "<replacement text>\n"
    ">>>>>>> REPLACE\n"
    "```"
)
