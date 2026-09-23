"""Migrate v0.2/v0.3 event logs to the strict v0.4 format.

The legacy and current seals differ (v0.4 binds declared policy, freezes
metadata, and signs with `sha256-json-v4-policy-escalate`), so migration is
not a reformat -- it replays the recorded events through the current reducer
and writes a new v0.4 log. The result attests "these events, re-sealed under
v0.4", not "the original run was verified": the source log's own hashes are
never trusted, and the source file's SHA-256 is recorded in `extra.migrated_from`
for provenance.

Migration refuses when:
  - the source is not a recognized v0.2/v0.3 log
  - an event type is unknown to the current reducer
  - replay disagrees with the recorded trailer (terminal/suspended/step_count)
  - the log is truncated (no final record)

Usage: python -m nakedagent.migrate_log <old.jsonl> <new.jsonl>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from .eventlog import open_log
from .functional import AgentEvent, AgentState, FunctionalMachine

LEGACY_VERSIONS = frozenset({"nakedagent.eventlog@v0.2", "nakedagent.eventlog@v0.3"})
KNOWN_EVENT_TYPES = frozenset(
    {"USER_INPUT", "MODEL_REPLY", "TOOL_RESULT", "TERMINATION", "ALARM", "ESCALATE"}
)


class MigrationError(RuntimeError):
    pass


def _read_legacy(path: Path) -> tuple[dict, list[AgentEvent], dict]:
    header: dict[str, Any] | None = None
    events: list[AgentEvent] = []
    trailer: dict[str, Any] | None = None
    with open(path, encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as e:
                raise MigrationError(f"{path}:{lineno}: malformed JSON: {e}") from e
            if not isinstance(rec, dict):
                raise MigrationError(f"{path}:{lineno}: record is not an object")
            kind = rec.get("kind")
            if kind == "header":
                if header is not None:
                    raise MigrationError(f"{path}:{lineno}: duplicate header")
                if rec.get("version") not in LEGACY_VERSIONS:
                    raise MigrationError(
                        f"{path}:{lineno}: not a v0.2/v0.3 log "
                        f"(version {rec.get('version')!r})"
                    )
                header = rec
            elif kind == "event":
                if header is None:
                    raise MigrationError(f"{path}:{lineno}: event before header")
                et = rec.get("event_type")
                if et not in KNOWN_EVENT_TYPES:
                    raise MigrationError(f"{path}:{lineno}: unknown event type {et!r}")
                if not isinstance(rec.get("payload"), str):
                    raise MigrationError(f"{path}:{lineno}: invalid payload")
                meta = rec.get("metadata") or {}
                if not isinstance(meta, dict):
                    raise MigrationError(f"{path}:{lineno}: invalid metadata")
                events.append(AgentEvent(event_type=et, payload=rec["payload"], metadata=meta))
            elif kind == "final":
                if trailer is not None:
                    raise MigrationError(f"{path}:{lineno}: duplicate final")
                trailer = rec
            else:
                raise MigrationError(f"{path}:{lineno}: unknown record kind {kind!r}")
    if header is None:
        raise MigrationError(f"{path}: no header record")
    if trailer is None:
        raise MigrationError(f"{path}: truncated log, no final record")
    return header, events, trailer


def migrate(src_path: Path, dst_path: Path) -> dict[str, Any]:
    src_bytes = src_path.read_bytes()
    header, events, trailer = _read_legacy(src_path)

    system_prompt = header.get("system_prompt")
    if not isinstance(system_prompt, str):
        raise MigrationError("header missing string system_prompt")
    for f in ("model", "workspace"):
        if not isinstance(header.get(f), str):
            raise MigrationError(f"header missing string {f!r}")
    max_steps = header.get("max_steps")
    if type(max_steps) is not int or max_steps < 1:
        raise MigrationError("header missing positive int max_steps")

    # The written header's `extra` is replay-bound into genesis policy, so the
    # migration provenance must be part of the same dict used for both.
    extra = dict(header.get("extra") or {})
    extra["migrated_from"] = {
        "version": header["version"],
        "source_sha256": hashlib.sha256(src_bytes).hexdigest(),
    }
    policy = {"model": header["model"], "workspace": header["workspace"],
              "extra": extra}
    state = AgentState.initial(system_prompt, max_steps=max_steps, policy=policy)

    writer = open_log(
        dst_path,
        system_prompt=system_prompt,
        model=header["model"],
        workspace=header["workspace"],
        max_steps=max_steps,
        extra=extra,
    )
    ok = False
    try:
        for ev in events:
            if state.is_terminal or (state.suspended and ev.event_type != "USER_INPUT"):
                raise MigrationError(
                    "legacy stream contains an event the v0.4 reducer cannot admit "
                    "(post-terminal or suspended) — source is not replayable"
                )
            state, _ = FunctionalMachine.step(state, ev)
            writer.write_event(ev, state.current_hash())

        recorded_terminal = trailer.get("is_terminal")
        recorded_suspended = trailer.get("suspended", False)
        if (recorded_terminal is not None and recorded_terminal != state.is_terminal) or \
           (recorded_suspended != state.suspended):
            raise MigrationError(
                f"trailer mismatch: recorded terminal={recorded_terminal} "
                f"suspended={recorded_suspended}, replayed "
                f"terminal={state.is_terminal} suspended={state.suspended} "
                "— refusing to launder an inconsistent log"
            )
        recorded_steps = trailer.get("step_count")
        if type(recorded_steps) is int and recorded_steps != state.step_count:
            raise MigrationError(
                f"trailer step_count {recorded_steps} != replayed {state.step_count}"
            )
        writer.close(state.step_count, state.current_hash(), state.is_terminal,
                     state.terminal_reason, state.suspended)
        ok = True
    finally:
        if not ok:
            writer.fh.close()  # release the handle before unlink (Windows lock)
            dst_path.unlink(missing_ok=True)
    return {
        "source_version": header["version"],
        "events": len(events),
        "step_count": state.step_count,
        "is_terminal": state.is_terminal,
        "suspended": state.suspended,
        "state_hash": state.current_hash(),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="migrate a v0.2/v0.3 event log to v0.4")
    ap.add_argument("source", type=Path)
    ap.add_argument("dest", type=Path)
    args = ap.parse_args(argv)
    if args.dest.exists():
        print(f"refusing to overwrite {args.dest}", file=sys.stderr)
        return 2
    try:
        summary = migrate(args.source, args.dest)
    except (MigrationError, OSError) as e:
        print(f"migration failed: {e}", file=sys.stderr)
        return 1
    print(f"migrated {summary['events']} events -> {args.dest} "
          f"(from {summary['source_version']}; final hash {summary['state_hash'][:16]}...)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
