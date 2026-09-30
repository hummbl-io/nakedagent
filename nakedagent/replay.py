"""Replay an event log through the pure reducer and verify its Merkle chain.

    python -m nakedagent.replay path/to/run.jsonl

Reconstructs the AgentState from recorded events -- no model calls, no tool
execution -- then verifies:
  1. the Merkle chain itself (every state_hash recomputed from genesis), and
  2. that each recorded per-event hash matches the recomputed one, and
  3. the required `final` trailer matches the terminal or suspended state.

Exit 0 on a fully verified trace, 1 on any mismatch or malformed log.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .eventlog import EventLogError, read_log, require_matching_final
from .functional import replay_trace


def verify(path: Path) -> tuple[bool, str]:
    """Verify one log. Returns (ok, human-readable detail)."""
    try:
        log = read_log(path)
    except (EventLogError, OSError, UnicodeError) as e:
        return False, f"cannot read log: {e}"

    state, chain_ok = replay_trace(
        log.header["system_prompt"], log.events, max_steps=log.header["max_steps"],
        policy={"model": log.header["model"], "workspace": log.header["workspace"],
                "extra": log.header.get("extra", {})},
    )
    if not chain_ok:
        return False, "Merkle chain invalid: a state_hash does not recompute"

    if len(state.trace) != len(log.event_hashes):
        return False, "trace length mismatch with recorded events"
    for i, (rec, want) in enumerate(zip(state.trace, log.event_hashes), start=1):
        if rec.state_hash != want:
            return False, f"event {i}: recorded hash does not match recomputed state"

    try:
        require_matching_final(log, state)
    except EventLogError as e:
        return False, str(e)

    tools_used = sum(
        1 for rec in state.trace if rec.event.event_type == "TOOL_RESULT"
    )
    return True, (
        f"verified {state.step_count} events "
        f"({tools_used} tool results; {'terminal' if state.is_terminal else 'suspended'}); final hash {state.current_hash()[:16]}…"
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="nakedagent.replay", description=__doc__)
    p.add_argument("log", type=Path, help="event log written by --event-log")
    args = p.parse_args(argv)

    ok, detail = verify(args.log)
    print(("PASS" if ok else "FAIL") + f" {args.log}: {detail}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
