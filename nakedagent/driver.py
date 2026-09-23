"""Functional driver: interleave the pure reducer with effect execution.

`functional.agent_reducer` decides *what* to do -- it never touches IO.
This module is the effect boundary: it calls the model and runs tools, then
feeds the outcomes back in as AgentEvents. Every event is optionally mirrored
to a JSONL event log, so the run can be replayed and its Merkle chain
verified without a model call (`python -m nakedagent.replay <log>`).

Separation of concerns:

    reducer        -> (state, event) -> (state, actions)   [pure, provable]
    driver         -> executes actions, produces events     [impure, thin]
    eventlog       -> durable record of what happened       [append-only]

The imperative loop in `loop.py` remains the default path; the driver is the
provable lane for one-shot runs (`--event-log`).
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from . import llm
from .eventlog import EventLogWriter, open_log
from .functional import AgentEvent, AgentState, agent_reducer
from .loop import _build_tools, _system_prompt


def _dispatch(tools: dict, action, workspace: Path) -> str:
    """Execute one ToolAction. Mirrors loop.step's error containment: a tool
    bug or unknown name becomes a result string, not a crash."""
    tool = tools.get(action.tool_name.lower())
    if tool is None:
        return f"Error: unknown tool '{action.tool_name}'."
    try:
        return tool(action.args, action.content, workspace)
    except Exception as e:  # noqa: BLE001 -- tool bugs become results, same as loop.step
        return f"Error: {type(e).__name__}: {e}"


def run_functional(
    prompt: str,
    model: str,
    workspace: Path,
    host: str = llm.DEFAULT_HOST,
    *,
    tools: dict | None = None,
    llm_fn: Callable[..., str] = llm.chat,
    event_log_path: Path | None = None,
    max_steps: int = 25,
    allow_shell: bool = False,
    shell_allowlist: tuple[str, ...] = (),
    shell_timeout: int = 120,
) -> AgentState:
    """Run `prompt` through the reducer-interleaved loop. Returns final state.

    `llm_fn` and `tools` are injectable so tests and replay experiments can
    swap the effect layer without monkeypatching module globals.
    """
    registry = tools if tools is not None else _build_tools(
        workspace,
        allow_shell=allow_shell,
        shell_allowlist=shell_allowlist,
        shell_timeout=shell_timeout,
    )
    system_prompt = _system_prompt(registry)
    state = AgentState.initial(system_prompt, max_steps=max_steps)

    log: EventLogWriter | None = None
    if event_log_path is not None:
        log = open_log(
            event_log_path,
            system_prompt=system_prompt,
            model=model,
            workspace=str(workspace),
            max_steps=max_steps,
        )

    def feed(event: AgentEvent) -> list:
        nonlocal state
        state, actions = agent_reducer(state, event)
        if log is not None:
            log.write_event(event, state.current_hash())
        return actions

    try:
        feed(AgentEvent("USER_INPUT", prompt))
        while not state.is_terminal:
            reply = llm_fn(list(state.history), model, host)
            actions = feed(AgentEvent("MODEL_REPLY", reply))
            if not actions:
                feed(AgentEvent("TERMINATION", "MODEL_FINISHED"))
                break
            for act in actions:
                # Pre-dispatch guard: an effect must never execute when its
                # TOOL_RESULT could not be ledgered -- the reducer ignores
                # events on a terminal/exhausted state, so dispatching first
                # would run the action with no corresponding ledger entry.
                if state.is_terminal or state.step_count >= state.max_steps:
                    break
                result = _dispatch(registry, act, workspace)
                feed(AgentEvent("TOOL_RESULT", result, {"tool": act.tool_name}))
                if state.is_terminal:
                    break
        return state
    finally:
        if log is not None:
            log.close(state.step_count, state.current_hash(), state.is_terminal, state.terminal_reason)

