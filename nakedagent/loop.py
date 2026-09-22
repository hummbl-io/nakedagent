"""The agent loop: call model -> parse tool calls -> execute -> repeat while
the model keeps invoking tools, then hand control back to the human.

Shape borrowed from reading gptme's chat.py this session (not its code --
reimplemented from scratch, stdlib only): a single `step()` does one model
call plus whatever tool calls it produced; the outer loop keeps calling
`step()`, without new user input, for as long as the last response still
contains a tool call.
"""

from __future__ import annotations

import sys
from functools import partial
from pathlib import Path

from . import llm
from .llm import DEFAULT_HOST
from .plugins import load_plugins
from .toolcall import parse
from .tools import TOOLS, tool_shell

MAX_STEPS = 25  # tool-call rounds per human turn, before handing back control


def _dim(s: str) -> str:
    return f"\033[2m{s}\033[0m" if sys.stdout.isatty() else s


def _warn(s: str) -> str:
    return f"\033[33m{s}\033[0m" if sys.stdout.isatty() else s

_HEADER = (
    "You are nakedagent, a terminal coding agent. You have these tools, "
    "invoked as a fenced code block whose language tag is the tool name:"
)

_RULES = """\
Rules:
- One tool call at a time is safest; you may use more than one per message if
  you're confident, but each runs and its result is shown to you before you
  continue.
- `patch`'s SEARCH text must match the file exactly (including whitespace) \
and uniquely -- if it doesn't, you'll get an error back and should read the \
file again before retrying.
- When you have no more tool calls to make, just respond normally -- that \
hands control back to the user.
"""


def _system_prompt(tools: dict | None = None) -> str:
    """Build the system prompt from the tool registry.

    Each tool with a `.usage` attribute contributes its own fenced-block
    example -- so a plugin that replaces `shell` with different semantics
    replaces the prompt example too (the chef's opinion lives on the tool,
    not in a static string the seam can't reach; DOCTRINE.md). Tools without
    `.usage` are listed by name only, so a plugin author who doesn't set
    `.usage` still gets discoverability without guessing syntax.

    When no plugins are loaded this is byte-identical to the old static
    SYSTEM_PROMPT -- the four foundation tools all carry `.usage`.
    """
    registry = tools if tools is not None else TOOLS
    examples = []
    no_usage = []
    for name, func in registry.items():
        usage = getattr(func, "usage", None)
        if usage:
            examples.append(usage)
        else:
            no_usage.append(name)
    parts = [_HEADER, "\n\n".join(examples)]
    if no_usage:
        parts.append(
            "Additional tools are available (invoked the same way, as a fenced "
            "block whose language tag is the tool name): "
            + ", ".join(f"`{n}`" for n in sorted(no_usage))
            + "."
        )
    parts.append(_RULES)
    return "\n\n".join(parts)


# Preserved as the no-plugins baseline; _system_prompt(TOOLS) is byte-identical.
SYSTEM_PROMPT = _system_prompt(TOOLS)


def _build_tools(
    workspace: Path,
    *,
    allow_shell: bool = False,
    shell_allowlist: tuple[str, ...] = (),
    shell_timeout: int = 120,
) -> dict:
    """Load plugin tools and apply shell-policy hardening.

    Shell is a high-risk tool. Foundation `tool_shell` is policy-wrapped with
    explicit non-interactive allow-switching and allowlist checks to close the
    trust gap in automation.
    """
    tools = load_plugins(workspace)
    if tools.get("shell") is tool_shell:
        tools["shell"] = partial(
            tool_shell,
            allow_shell=allow_shell,
            shell_allowlist=shell_allowlist,
            shell_timeout=shell_timeout,
        )
    return tools


def step(
    messages: list[dict[str, str]], model: str, workspace: Path, host: str = DEFAULT_HOST,
    tools: dict | None = None,
    llm_options: dict | None = None,
) -> bool:
    """One model call + execute any tool calls in its reply.

    Mutates `messages` in place (appends the assistant reply and any tool
    results). Returns True if a tool ran (caller should loop again without
    new user input), False otherwise.

    `tools` is the tool registry to dispatch against; defaulting to the
    foundation TOOLS keeps the existing call sites working. Callers that
    want plugins pass the merged registry from load_plugins().

    `llm_options` is passed to llm.chat as keywords (`api`, `api_key_env`);
    empty means the Ollama default.
    """
    registry = tools if tools is not None else TOOLS
    reply = llm.chat(messages, model, host, **(llm_options or {}))
    messages.append({"role": "assistant", "content": reply})
    print(f"\n{_dim('--- assistant ---')}\n{reply}")

    calls = parse(reply)
    if not calls:
        return False

    for call in calls:
        # bespoke: models often emit uppercase fence tags (```SHELL is valid
        # markdown); normalize at the lookup rather than in the parser so the
        # tool name reported back to the model keeps its original casing in
        # the `[tool output]` header. If a second tool with a case-sensitive
        # name is ever added, this becomes a real collision -- add an alias
        # table then.
        tool = registry.get(call.tool.lower())
        if tool is None:
            result = f"Error: unknown tool '{call.tool}'."
        else:
            try:
                result = tool(call.args, call.content, workspace)
            except Exception as e:  # noqa: BLE001 -- a tool bug shouldn't kill the loop; the
                # model gets to see it and try something else, same as any
                # other tool error.
                result = f"Error: {type(e).__name__}: {e}"
        print(f"{_dim(f'--- {call.tool} {call.args} ---')}\n{result}")
        messages.append({"role": "user", "content": f"[{call.tool} output]\n{result}"})

    return True


def _run_until_done(
    messages: list[dict[str, str]], model: str, workspace: Path, host: str,
    tools: dict | None = None,
    llm_options: dict | None = None,
) -> None:
    """Call step() while it keeps returning True, capped at MAX_STEPS."""
    for _ in range(MAX_STEPS):
        if not step(messages, model, workspace, host, tools=tools, llm_options=llm_options):
            return
    print(_warn(f"\n--- stopped after {MAX_STEPS} tool-call rounds; your turn ---"))


def run(
    prompt: str,
    model: str,
    workspace: Path,
    host: str = DEFAULT_HOST,
    *,
    allow_shell: bool = False,
    shell_allowlist: tuple[str, ...] = (),
    shell_timeout: int = 120,
    llm_options: dict | None = None,
) -> None:
    """One-shot: run `prompt` to completion (no further human input)."""
    tools = _build_tools(
        workspace,
        allow_shell=allow_shell,
        shell_allowlist=shell_allowlist,
        shell_timeout=shell_timeout,
    )
    messages = [
        {"role": "system", "content": _system_prompt(tools)},
        {"role": "user", "content": prompt},
    ]
    _run_until_done(messages, model, workspace, host, tools=tools, llm_options=llm_options)


def run_interactive(
    model: str,
    workspace: Path,
    host: str = DEFAULT_HOST,
    *,
    allow_shell: bool = False,
    shell_allowlist: tuple[str, ...] = (),
    shell_timeout: int = 120,
    llm_options: dict | None = None,
) -> None:
    """REPL: prompt the user for input whenever the agent has no tool calls left."""
    tools = _build_tools(
        workspace,
        allow_shell=allow_shell,
        shell_allowlist=shell_allowlist,
        shell_timeout=shell_timeout,
    )
    messages = [{"role": "system", "content": _system_prompt(tools)}]
    print(f"nakedagent -- workspace: {workspace} -- model: {model}")
    print("Ctrl-D to exit.\n")
    while True:
        try:
            user_input = input("> ")
        except EOFError:
            print()
            return
        if not user_input.strip():
            continue
        messages.append({"role": "user", "content": user_input})
        _run_until_done(messages, model, workspace, host, tools=tools, llm_options=llm_options)
