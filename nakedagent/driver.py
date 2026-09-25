"""Functional driver: interleave the pure reducer with effect execution.

`functional.agent_reducer` decides *what* to do -- it never touches IO.
This module is the effect boundary: it calls the model and runs tools, then
feeds the outcomes back in as AgentEvents. Every event is optionally mirrored
to a JSONL event log, so the run can be replayed and its Merkle chain
verified without a model call (`python -m nakedagent.replay <log>`).

Separation of concerns:

    reducer        -> (state, event) -> (state, actions)   [pure, provable]
    driver         -> executes actions, produces events     [impure, thin]
    eventlog       -> local record of admitted events       [append-only]

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
    trust_plugins: bool = False,
    llm_options: dict | None = None,
    resume_from: Path | None = None,
) -> AgentState:
    """Run `prompt` through the reducer-interleaved loop. Returns final state.

    `llm_fn` and `tools` are injectable so tests and replay experiments can
    swap the effect layer without monkeypatching module globals.

    `resume_from` re-opens a suspended event log instead of starting a
    fresh run: the recorded events are replayed through the reducer with
    recorded-hash and policy binding (refusing a corrupted or non-suspended
    source), the trailer is replaced, and `prompt` enters as the human
    verdict that lifts the suspension. `event_log_path` must equal
    `resume_from` — resuming writes back to the same file.
    """
    registry = tools if tools is not None else _build_tools(
        workspace,
        allow_shell=allow_shell,
        shell_allowlist=shell_allowlist,
        shell_timeout=shell_timeout,
        trust_plugins=trust_plugins,
    )
    system_prompt = _system_prompt(registry)

    log: EventLogWriter | None = None
    if resume_from is not None:
        if event_log_path != resume_from:
            raise ValueError("resume_from requires event_log_path to name the same file")
        from .eventlog import open_resumed_log, read_log, require_resumable
        from .functional import replay_trace
        parsed = read_log(resume_from)
        require_resumable(parsed, resume_from)
        header = parsed.header
        state, chain_ok = replay_trace(
            header["system_prompt"], parsed.events,
            max_steps=header["max_steps"],
            recorded_hashes=parsed.event_hashes,
            policy={"model": header["model"], "workspace": header["workspace"],
                    "extra": header.get("extra", {})},
        )
        if not chain_ok:
            raise RuntimeError("cannot resume: recorded chain does not recompute")
        if not state.suspended or state.is_terminal:
            raise RuntimeError("cannot resume: replayed state is not suspended")
        if system_prompt != header["system_prompt"]:
            raise RuntimeError(
                "cannot resume: current registry prompt differs from the "
                "recorded genesis prompt — the continued run must bind the "
                "same policy surface")
        max_steps = state.max_steps
        log = open_resumed_log(resume_from, parsed)
    else:
        state = AgentState.initial(
            system_prompt, max_steps=max_steps,
            policy={"model": model, "workspace": str(workspace), "extra": {}},
        )
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
        if state.is_terminal or state.step_count >= state.max_steps or (state.suspended and event.event_type != "USER_INPUT"):
            raise RuntimeError("cannot admit an event after terminal state or max_steps")
        state, actions = agent_reducer(state, event)
        if log is not None:
            log.write_event(event, state.current_hash())
        return actions

    try:
        feed(AgentEvent("USER_INPUT", prompt))
        while not state.is_terminal and not state.suspended:
            # A reply needs one admission slot before the model effect.
            if state.step_count >= state.max_steps:
                break
            reply = llm_fn([dict(message) for message in state.history], model, host, **(llm_options or {}))
            actions = feed(AgentEvent("MODEL_REPLY", reply))
            if state.is_terminal:
                break
            if not actions:
                feed(AgentEvent("TERMINATION", "MODEL_FINISHED"))
                break
            for act in actions:
                # Reserve the TOOL_RESULT admission slot before execution.
                if state.is_terminal or state.step_count >= state.max_steps:
                    break
                result = _dispatch(registry, act, workspace)
                feed(AgentEvent("TOOL_RESULT", result, {"tool": act.tool_name}))
                if state.is_terminal:
                    break
        return state
    finally:
        if log is not None:
            log.close(state.step_count, state.current_hash(), state.is_terminal,
                      state.terminal_reason, state.suspended)
