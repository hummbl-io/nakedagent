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
from pathlib import Path

from . import llm
from .llm import DEFAULT_HOST
from .toolcall import parse
from .tools import TOOLS

MAX_STEPS = 25  # tool-call rounds per human turn, before handing back control


def _dim(s: str) -> str:
    return f"\033[2m{s}\033[0m" if sys.stdout.isatty() else s


def _warn(s: str) -> str:
    return f"\033[33m{s}\033[0m" if sys.stdout.isatty() else s

SYSTEM_PROMPT = """\
You are nakedagent, a terminal coding agent. You have these tools, invoked \
as a fenced code block whose language tag is the tool name:

```shell
<a shell command to run>
```

```read <path>
```

```write <path>
<full file content to write>
```

```patch <path>
<<<<<<< SEARCH
<exact existing text>
=======
<replacement text>
>>>>>>> REPLACE
```

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


def step(
    messages: list[dict[str, str]], model: str, workspace: Path, host: str = DEFAULT_HOST
) -> bool:
    """One model call + execute any tool calls in its reply.

    Mutates `messages` in place (appends the assistant reply and any tool
    results). Returns True if a tool ran (caller should loop again without
    new user input), False otherwise.
    """
    reply = llm.chat(messages, model, host)
    messages.append({"role": "assistant", "content": reply})
    print(f"\n{_dim('--- assistant ---')}\n{reply}")

    calls = parse(reply)
    if not calls:
        return False

    for call in calls:
        tool = TOOLS.get(call.tool)
        if tool is None:
            result = f"Error: unknown tool '{call.tool}'."
        else:
            try:
                result = tool(call.args, call.content, workspace)
            except Exception as e:  # a tool bug shouldn't kill the loop; the
                # model gets to see it and try something else, same as any
                # other tool error.
                result = f"Error: {type(e).__name__}: {e}"
        print(f"{_dim(f'--- {call.tool} {call.args} ---')}\n{result}")
        messages.append({"role": "user", "content": f"[{call.tool} output]\n{result}"})

    return True


def _run_until_done(
    messages: list[dict[str, str]], model: str, workspace: Path, host: str
) -> None:
    """Call step() while it keeps returning True, capped at MAX_STEPS."""
    for _ in range(MAX_STEPS):
        if not step(messages, model, workspace, host):
            return
    print(_warn(f"\n--- stopped after {MAX_STEPS} tool-call rounds; your turn ---"))


def run(prompt: str, model: str, workspace: Path, host: str = DEFAULT_HOST) -> None:
    """One-shot: run `prompt` to completion (no further human input)."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    _run_until_done(messages, model, workspace, host)


def run_interactive(model: str, workspace: Path, host: str = DEFAULT_HOST) -> None:
    """REPL: prompt the user for input whenever the agent has no tool calls left."""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
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
        _run_until_done(messages, model, workspace, host)
