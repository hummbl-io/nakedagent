"""JSONL event-log persistence for the functional agent trace.

A log is three record kinds, one JSON object per line:

    {"kind": "header", "version": ..., "system_prompt": ..., "model": ..., ...}
    {"kind": "event",  "seq": n, "event_type": ..., "payload": ...,
     "metadata": {...}, "state_hash": ...}
    {"kind": "final",  "step_count": n, "state_hash": ..., "is_terminal": ...}

The `state_hash` on each event line is the Merkle root of the AgentState
*after* that event was applied by `agent_reducer`, so a replay can verify
every transition, not just the chain shape. The `final` trailer pins the
terminal snapshot so truncation is detectable.

stdlib only; no third-party anything.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from .functional import AgentEvent

SCHEMA_VERSION = "nakedagent.eventlog@v0.1"


class EventLogError(RuntimeError):
    pass


@dataclass
class EventLogWriter:
    """Append-only writer. One instance per run; close() writes the trailer."""

    fh: TextIO
    seq: int = 0
    closed: bool = False

    def write_event(self, event: AgentEvent, state_hash: str) -> None:
        if self.closed:
            raise EventLogError("write to closed event log")
        self.seq += 1
        record = {
            "kind": "event",
            "seq": self.seq,
            "event_type": event.event_type,
            "payload": event.payload,
            "metadata": event.metadata,
            "state_hash": state_hash,
        }
        self.fh.write(json.dumps(record, default=str) + "\n")
        self.fh.flush()

    def close(self, step_count: int, state_hash: str, is_terminal: bool, terminal_reason: str | None) -> None:
        if self.closed:
            return
        record = {
            "kind": "final",
            "step_count": step_count,
            "state_hash": state_hash,
            "is_terminal": is_terminal,
            "terminal_reason": terminal_reason,
        }
        self.fh.write(json.dumps(record) + "\n")
        self.fh.flush()
        self.fh.close()
        self.closed = True


def open_log(
    path: Path,
    *,
    system_prompt: str,
    model: str,
    workspace: str,
    extra: dict[str, Any] | None = None,
) -> EventLogWriter:
    """Open a new event log and write the header record."""
    fh = open(path, "w", encoding="utf-8", newline="\n")  # noqa: SIM115 -- handle outlives the call; closed by EventLogWriter.close()
    header: dict[str, Any] = {
        "kind": "header",
        "version": SCHEMA_VERSION,
        "system_prompt": system_prompt,
        "model": model,
        "workspace": workspace,
    }
    if extra:
        header["extra"] = extra
    fh.write(json.dumps(header, default=str) + "\n")
    fh.flush()
    return EventLogWriter(fh=fh)


@dataclass
class EventLog:
    header: dict[str, Any]
    events: list[AgentEvent]
    event_hashes: list[str]
    trailer: dict[str, Any] | None


def read_log(path: Path) -> EventLog:
    """Parse an event log. Strict: a malformed line raises with its number."""
    header: dict[str, Any] | None = None
    events: list[AgentEvent] = []
    hashes: list[str] = []
    trailer: dict[str, Any] | None = None

    with open(path, "r", encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as e:
                raise EventLogError(f"{path}:{lineno}: malformed JSON: {e}") from e
            kind = rec.get("kind")
            if kind == "header":
                if header is not None:
                    raise EventLogError(f"{path}:{lineno}: duplicate header")
                header = rec
            elif kind == "event":
                if header is None:
                    raise EventLogError(f"{path}:{lineno}: event before header")
                for req in ("seq", "event_type", "payload", "state_hash"):
                    if req not in rec:
                        raise EventLogError(f"{path}:{lineno}: event missing '{req}'")
                events.append(
                    AgentEvent(
                        event_type=rec["event_type"],
                        payload=rec["payload"],
                        metadata=rec.get("metadata") or {},
                    )
                )
                hashes.append(rec["state_hash"])
            elif kind == "final":
                trailer = rec
            else:
                raise EventLogError(f"{path}:{lineno}: unknown record kind {kind!r}")

    if header is None:
        raise EventLogError(f"{path}: no header record")
    return EventLog(header=header, events=events, event_hashes=hashes, trailer=trailer)
