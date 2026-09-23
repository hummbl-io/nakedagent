"""Pure functional state machine & Merkle execution stream for NakedAgent.

Formulates agent execution as an algebraic Mealy state machine:
    step : (AgentState, AgentEvent) -> (AgentState, list[Action])

Models locally replayable transitions:
1. Referential transparency: pure reducer with zero side effects.
2. Monotonicity: state history is strictly append-only.
3. Hash-linked declared policy and event content (SHA-256) per transition.
4. Deterministic replay: reconstruct exact execution history without model calls.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Literal


@dataclass(frozen=True)
class ToolAction:
    """Action emitted by the pure state transition."""
    tool_name: str
    args: str
    content: str


@dataclass(frozen=True)
class AgentEvent:
    """Incoming event stimulating a state transition."""
    event_type: Literal["USER_INPUT", "MODEL_REPLY", "TOOL_RESULT", "TERMINATION", "ALARM", "ESCALATE"]
    payload: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Snapshot nested JSON before a caller can mutate a recorded event.
        object.__setattr__(self, "metadata", _freeze(_json_copy(self.metadata)))


@dataclass(frozen=True)
class TransitionReceipt:
    """Hash-linked reported transition, not authenticated effect evidence."""
    step_index: int
    prev_hash: str
    event: AgentEvent
    actions: tuple[ToolAction, ...]
    state_hash: str


@dataclass(frozen=True)
class AgentState:
    """Immutable state snapshot."""
    step_count: int
    max_steps: int
    history: tuple[Mapping[str, str], ...]
    trace: tuple[TransitionReceipt, ...]
    is_terminal: bool = False
    terminal_reason: str | None = None
    policy: Any = field(default_factory=lambda: MappingProxyType({}))
    suspended: bool = False

    @classmethod
    def initial(cls, system_prompt: str, max_steps: int = 25,
                policy: dict[str, Any] | None = None) -> AgentState:
        """Create the genesis state."""
        if type(max_steps) is not int or max_steps < 1:
            raise ValueError("max_steps must be a positive integer")
        return cls(
            step_count=0,
            max_steps=max_steps,
            history=(MappingProxyType({"role": "system", "content": system_prompt}),),
            trace=(),
            is_terminal=False,
            terminal_reason=None,
            policy=_freeze(_json_copy(policy or {})),
            suspended=False,
        )

    def current_hash(self) -> str:
        """Return the current Merkle root hash."""
        if not self.trace:
            # v0.4 policy frame. Older log versions require their own verifier.
            return _digest({"system_prompt": self.history[0]["content"],
                            "max_steps": self.max_steps, "policy": _plain(self.policy)})
        return self.trace[-1].state_hash


def compute_step_hash(prev_hash: str, step_index: int, event: AgentEvent, actions: tuple[ToolAction, ...]) -> str:
    """Compute cryptographic hash of the transition.

    Canonical framed v0.4 serialization binds metadata and action fields.
    """
    return _digest({
        "prev_hash": prev_hash,
        "step_index": step_index,
        "event": {
            "event_type": event.event_type,
            "payload": event.payload,
            "metadata": _plain(event.metadata),
        },
        "actions": [
            {"tool_name": a.tool_name, "args": a.args, "content": a.content}
            for a in actions
        ],
    })


def _json_copy(value: Any) -> Any:
    return json.loads(json.dumps(value, allow_nan=False))


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(v) for v in value)
    return value


def _plain(value: Any) -> Any:
    if isinstance(value, (dict, MappingProxyType)):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, allow_nan=False).encode("utf-8")).hexdigest()


def agent_reducer(state: AgentState, event: AgentEvent) -> tuple[AgentState, list[ToolAction]]:
    """Pure mathematical transition function: (State, Event) -> (State, Actions).

    Referentially transparent: contains ZERO IO, network calls, or process mutations.
    """
    if state.is_terminal:
        return state, []

    # Defensive guard for manually constructed exhausted states.
    if state.step_count >= state.max_steps:
        term_state = AgentState(
            step_count=state.step_count,
            max_steps=state.max_steps,
            history=state.history,
            trace=state.trace,
            is_terminal=True,
            terminal_reason="BOUNDED_MAX_STEPS_REACHED",
            policy=state.policy,
            suspended=False,
        )
        return term_state, []

    if state.suspended and event.event_type not in ("USER_INPUT", "ALARM", "TERMINATION"):
        return state, []

    new_history = list(state.history)
    actions: list[ToolAction] = []
    is_terminal = False
    term_reason = None
    suspended = state.suspended

    if event.event_type == "USER_INPUT":
        new_history.append(MappingProxyType({"role": "user", "content": event.payload}))
        suspended = False

    elif event.event_type == "TOOL_RESULT":
        new_history.append(MappingProxyType({"role": "user", "content": f"--- tool result ---\n{event.payload}"}))

    elif event.event_type == "MODEL_REPLY":
        new_history.append(MappingProxyType({"role": "assistant", "content": event.payload}))
        # Parse tool actions deterministically
        from .toolcall import parse
        parsed = parse(event.payload)
        if not parsed:
            # No tool calls: normal conversation turn completed
            is_terminal = False
        else:
            for call in parsed:
                actions.append(ToolAction(tool_name=call.tool.lower(), args=call.args, content=call.content))

    elif event.event_type == "ESCALATE":
        new_history.append(MappingProxyType({
            "role": "user", "content": f"--- action escalated for human review ---\n{event.payload}",
        }))
        suspended = True

    elif event.event_type in ("TERMINATION", "ALARM"):
        is_terminal = True
        term_reason = event.payload
        suspended = False

    # Cryptographic transition sealing
    step_idx = state.step_count + 1
    prev_h = state.current_hash()
    act_tuple = tuple(actions)
    step_hash = compute_step_hash(prev_h, step_idx, event, act_tuple)

    receipt = TransitionReceipt(
        step_index=step_idx,
        prev_hash=prev_h,
        event=event,
        actions=act_tuple,
        state_hash=step_hash,
    )
    if step_idx == state.max_steps and not is_terminal:
        is_terminal = True
        term_reason = "BOUNDED_MAX_STEPS_REACHED"
        suspended = False
    new_state = AgentState(
        step_count=step_idx,
        max_steps=state.max_steps,
        history=tuple(new_history),
        trace=state.trace + (receipt,),
        is_terminal=is_terminal,
        terminal_reason=term_reason,
        policy=state.policy,
        suspended=suspended,
    )
    return new_state, [] if new_state.is_terminal else actions


reduce_agent_step = agent_reducer

_UNSET = object()


class FunctionalMachine:
    """Convenience class wrapper around pure agent_reducer."""

    @staticmethod
    def step(state: AgentState, event: AgentEvent) -> tuple[AgentState, list[ToolAction]]:
        return agent_reducer(state, event)


def replay_trace(
    system_prompt: str,
    events: list[AgentEvent],
    max_steps: int = 25,
    *legacy_fourth: object,
    recorded_hashes: object = _UNSET,
    policy: object = _UNSET,
) -> tuple[AgentState, bool]:
    """Replay an event stream deterministically from genesis.

    Returns (final_state, is_valid).

    `max_steps` must match the recorded run's budget — a run configured
    for 50 steps replays all of its events; one left at the default 25
    silently truncates.

    The fourth positional argument was `recorded_hashes` in the active
    Sidekick branch and `policy` in PR18 v0.2. Only that positional slot is
    disambiguated: dict means policy, list means recorded hashes, and None
    is neutral. Keywords retain their exact names. Duplicate assignment,
    extra positional arguments and unsupported shapes raise TypeError.

    `recorded_hashes`: the per-step state_hash list captured when the run
    was generated (e.g. from the event log). With it, replay binds the
    recomputed chain to the recorded one — the actual tamper check.
    Without it, the flag only confirms the recomputation is internally
    consistent, which it always is for a deterministic reducer.

    Events after a terminal step or while suspended are invalid; callers
    must compare the complete replayed length with the supplied length.
    """
    if len(legacy_fourth) > 1:
        raise TypeError("replay_trace accepts at most one fourth positional argument")
    if legacy_fourth:
        value = legacy_fourth[0]
        if isinstance(value, dict):
            if policy is not _UNSET:
                raise TypeError("policy was supplied twice")
            policy = value
        elif isinstance(value, list):
            if recorded_hashes is not _UNSET:
                raise TypeError("recorded_hashes was supplied twice")
            recorded_hashes = value
        elif value is not None:
            raise TypeError("fourth positional argument must be dict, list, or None")
    if recorded_hashes is _UNSET:
        recorded_hashes = None
    if policy is _UNSET:
        policy = None
    if recorded_hashes is not None and not isinstance(recorded_hashes, list):
        raise TypeError("recorded_hashes must be a list or None")
    if policy is not None and not isinstance(policy, dict):
        raise TypeError("policy must be a dict or None")
    state = AgentState.initial(system_prompt, max_steps=max_steps, policy=policy)
    genesis = state.current_hash()
    for ev in events:
        if state.is_terminal:
            return state, False
        previous_count = state.step_count
        state, _ = agent_reducer(state, ev)
        if state.step_count == previous_count:
            return state, False

    if recorded_hashes is not None:
        recomputed = [r.state_hash for r in state.trace]
        return state, recomputed == list(recorded_hashes)

    # Self-consistency check only — verifies the reducer is deterministic,
    # not that this stream matches any external record.
    prev = genesis
    for rec in state.trace:
        expected = compute_step_hash(prev, rec.step_index, rec.event, rec.actions)
        if rec.state_hash != expected:
            return state, False
        prev = rec.state_hash

    return state, True
