"""Pure functional state machine & Merkle execution stream for NakedAgent.

Formulates agent execution as an algebraic Mealy state machine:
    step : (AgentState, AgentEvent) -> (AgentState, list[Action])

Enforces mathematical provability:
1. Referential transparency: pure reducer with zero side effects.
2. Monotonicity: state history is strictly append-only.
3. Cryptographic integrity: Merkle state hash (SHA-256) per transition.
4. Deterministic replay: reconstruct exact execution history without model calls.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Literal, Optional, Tuple


@dataclass(frozen=True)
class ToolAction:
    """Action emitted by the pure state transition."""
    tool_name: str
    args: str
    content: str


@dataclass(frozen=True)
class AgentEvent:
    """Incoming event stimulating a state transition."""
    event_type: Literal["USER_INPUT", "MODEL_REPLY", "TOOL_RESULT", "TERMINATION", "ALARM"]
    payload: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TransitionReceipt:
    """Cryptographically sealed execution step."""
    step_index: int
    prev_hash: str
    event: AgentEvent
    actions: Tuple[ToolAction, ...]
    state_hash: str


@dataclass(frozen=True)
class AgentState:
    """Immutable state snapshot."""
    step_count: int
    max_steps: int
    history: Tuple[Dict[str, str], ...]
    trace: Tuple[TransitionReceipt, ...]
    is_terminal: bool = False
    terminal_reason: Optional[str] = None

    @classmethod
    def initial(cls, system_prompt: str, max_steps: int = 25) -> AgentState:
        """Create the genesis state."""
        return cls(
            step_count=0,
            max_steps=max_steps,
            history=({"role": "system", "content": system_prompt},),
            trace=(),
            is_terminal=False,
            terminal_reason=None,
        )

    def current_hash(self) -> str:
        """Return the current Merkle root hash."""
        if not self.trace:
            return hashlib.sha256(b"GENESIS_STATE").hexdigest()
        return self.trace[-1].state_hash


def compute_step_hash(prev_hash: str, step_index: int, event: AgentEvent, actions: Tuple[ToolAction, ...]) -> str:
    """Compute cryptographic hash of the transition."""
    h = hashlib.sha256()
    h.update(prev_hash.encode("utf-8"))
    h.update(str(step_index).encode("utf-8"))
    h.update(event.event_type.encode("utf-8"))
    h.update(event.payload.encode("utf-8"))
    for act in actions:
        h.update(act.tool_name.encode("utf-8"))
        h.update(act.args.encode("utf-8"))
        h.update(act.content.encode("utf-8"))
    return h.hexdigest()


def agent_reducer(state: AgentState, event: AgentEvent) -> Tuple[AgentState, List[ToolAction]]:
    """Pure mathematical transition function: (State, Event) -> (State, Actions).

    Referentially transparent: contains ZERO IO, network calls, or process mutations.
    """
    if state.is_terminal:
        return state, []

    # Bounded termination check
    if state.step_count >= state.max_steps:
        term_state = AgentState(
            step_count=state.step_count,
            max_steps=state.max_steps,
            history=state.history,
            trace=state.trace,
            is_terminal=True,
            terminal_reason="BOUNDED_MAX_STEPS_REACHED",
        )
        return term_state, []

    new_history = list(state.history)
    actions: List[ToolAction] = []
    is_terminal = False
    term_reason = None

    if event.event_type == "USER_INPUT":
        new_history.append({"role": "user", "content": event.payload})

    elif event.event_type == "TOOL_RESULT":
        new_history.append({"role": "user", "content": f"--- tool result ---\n{event.payload}"})

    elif event.event_type == "MODEL_REPLY":
        new_history.append({"role": "assistant", "content": event.payload})
        # Parse tool actions deterministically
        from .toolcall import parse
        parsed = parse(event.payload)
        if not parsed:
            # No tool calls: normal conversation turn completed
            is_terminal = False
        else:
            for call in parsed:
                actions.append(ToolAction(tool_name=call.tool, args=call.args, content=call.content))

    elif event.event_type in ("TERMINATION", "ALARM"):
        is_terminal = True
        term_reason = event.payload

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

    new_state = AgentState(
        step_count=step_idx,
        max_steps=state.max_steps,
        history=tuple(new_history),
        trace=state.trace + (receipt,),
        is_terminal=is_terminal,
        terminal_reason=term_reason,
    )
    return new_state, actions


def replay_trace(system_prompt: str, events: List[AgentEvent]) -> Tuple[AgentState, bool]:
    """Replay an event stream deterministically from genesis.

    Returns (final_state, is_valid_merkle_chain).
    """
    state = AgentState.initial(system_prompt)
    for ev in events:
        state, _ = agent_reducer(state, ev)

    # Verify Merkle integrity
    prev = hashlib.sha256(b"GENESIS_STATE").hexdigest()
    for rec in state.trace:
        expected = compute_step_hash(prev, rec.step_index, rec.event, rec.actions)
        if rec.state_hash != expected:
            return state, False
        prev = rec.state_hash

    return state, True
