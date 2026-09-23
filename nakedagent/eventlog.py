"""JSONL event-log persistence for the functional agent trace.

A log is three record kinds, one JSON object per line:

    {"kind": "header", "version": ..., "system_prompt": ..., "model": ..., ...}
    {"kind": "event",  "seq": n, "event_type": ..., "payload": ...,
     "metadata": {...}, "state_hash": ...}
    {"kind": "final",  "step_count": n, "state_hash": ..., "is_terminal": ...,
     "suspended": ...}

The `state_hash` on each event line is the hash-linked transition value
*after* that event was applied by `agent_reducer`. Replay checks internal
consistency of supplied records; it cannot authenticate their origin or prove
that reported external effects occurred. A required `final` trailer allows
the verifier to reject missing or truncated endings.

stdlib only; no third-party anything.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from .functional import AgentEvent, _plain

SCHEMA_VERSION = "nakedagent.eventlog@v0.4"
HASH_ALG = "sha256-json-v4-policy-escalate"
LEGACY_VERSIONS = frozenset({"nakedagent.eventlog@v0.2", "nakedagent.eventlog@v0.3"})


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
            "metadata": _plain(event.metadata),
            "state_hash": state_hash,
        }
        self.fh.write(json.dumps(record, allow_nan=False) + "\n")
        self.fh.flush()

    def close(self, step_count: int, state_hash: str, is_terminal: bool,
              terminal_reason: str | None, suspended: bool = False) -> None:
        if self.closed:
            return
        record = {
            "kind": "final",
            "step_count": step_count,
            "state_hash": state_hash,
            "is_terminal": is_terminal,
            "terminal_reason": terminal_reason,
            "suspended": suspended,
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
    max_steps: int = 25,
) -> EventLogWriter:
    """Open a new event log and write the header record."""
    fh = open(path, "w", encoding="utf-8", newline="\n")  # noqa: SIM115 -- handle outlives the call; closed by EventLogWriter.close()
    header: dict[str, Any] = {
        "kind": "header",
        "version": SCHEMA_VERSION,
        "hash_alg": HASH_ALG,
        "system_prompt": system_prompt,
        "system_prompt_sha256": hashlib.sha256(system_prompt.encode("utf-8")).hexdigest(),
        "model": model,
        "workspace": workspace,
        "max_steps": max_steps,
    }
    header["extra"] = extra or {}
    fh.write(json.dumps(header, allow_nan=False) + "\n")
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

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key {key!r}")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise ValueError(f"nonfinite JSON number {value}")

    def finite_float(value: str) -> float:
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("nonfinite JSON number")
        return number

    with open(path, "r", encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, start=1):
            line = raw.strip()
            if not line:
                raise EventLogError(f"{path}:{lineno}: blank record")
            try:
                rec = json.loads(line, object_pairs_hook=unique,
                                 parse_constant=reject_constant, parse_float=finite_float)
            except (ValueError, TypeError) as e:
                raise EventLogError(f"{path}:{lineno}: malformed JSON: {e}") from e
            if not isinstance(rec, dict):
                raise EventLogError(f"{path}:{lineno}: record must be an object")
            kind = rec.get("kind")
            if kind == "header":
                if header is not None or events or trailer is not None:
                    raise EventLogError(f"{path}:{lineno}: misplaced header")
                _validate_header(path, rec)
                header = rec
            elif kind == "event":
                if header is None or trailer is not None:
                    raise EventLogError(f"{path}:{lineno}: event outside header/final")
                required = {"kind", "seq", "event_type", "payload", "metadata", "state_hash"}
                if set(rec) != required:
                    missing = required - set(rec)
                    if missing:
                        raise EventLogError(f"{path}:{lineno}: event missing {', '.join(sorted(missing))}")
                    raise EventLogError(f"{path}:{lineno}: event fields mismatch")
                if type(rec["seq"]) is not int or rec["seq"] != len(events) + 1:
                    raise EventLogError(f"{path}:{lineno}: noncontiguous event sequence")
                if rec["event_type"] not in ("USER_INPUT", "MODEL_REPLY", "TOOL_RESULT", "TERMINATION", "ALARM", "ESCALATE"):
                    raise EventLogError(f"{path}:{lineno}: unknown event type {rec['event_type']!r}")
                if not isinstance(rec["payload"], str) or not isinstance(rec["metadata"], dict):
                    raise EventLogError(f"{path}:{lineno}: invalid event payload/metadata")
                if not _hash_string(rec["state_hash"]):
                    raise EventLogError(f"{path}:{lineno}: invalid event hash")
                events.append(
                    AgentEvent(
                        event_type=rec["event_type"],
                        payload=rec["payload"],
                        metadata=rec["metadata"],
                    )
                )
                hashes.append(rec["state_hash"])
            elif kind == "final":
                if header is None or trailer is not None:
                    raise EventLogError(f"{path}:{lineno}: duplicate or misplaced final")
                trailer = rec
            else:
                raise EventLogError(f"{path}:{lineno}: unknown record kind {kind!r}")

    if header is None:
        raise EventLogError(f"{path}: no header record")
    if trailer is None:
        raise EventLogError(f"{path}: truncated log: missing final record")
    _validate_trailer(path, trailer)
    return EventLog(header=header, events=events, event_hashes=hashes, trailer=trailer)


def _validate_header(path: Path, header: dict[str, Any]) -> None:
    version = header.get("version")
    if not isinstance(version, str):
        raise EventLogError(f"{path}: schema version must be a string")
    if version != SCHEMA_VERSION:
        if version in LEGACY_VERSIONS:
            raise EventLogError(f"{path}: legacy {version} has a different hash contract; strict v0.4 verification unavailable")
        raise EventLogError(f"{path}: unsupported schema version {version!r}")
    if set(header) != {"kind", "version", "hash_alg", "system_prompt", "system_prompt_sha256", "model", "workspace", "max_steps", "extra"}:
        raise EventLogError(f"{path}: header fields mismatch")
    if header["hash_alg"] != HASH_ALG:
        raise EventLogError(f"{path}: unsupported hash_alg")
    if not all(isinstance(header[k], str) for k in ("system_prompt", "model", "workspace")):
        raise EventLogError(f"{path}: invalid policy fields")
    if type(header["max_steps"]) is not int or header["max_steps"] < 1:
        raise EventLogError(f"{path}: invalid max_steps")
    if not isinstance(header["extra"], dict):
        raise EventLogError(f"{path}: invalid extra")
    if header["system_prompt_sha256"] != hashlib.sha256(header["system_prompt"].encode("utf-8")).hexdigest():
        raise EventLogError(f"{path}: system_prompt_sha256 mismatch")


def _validate_trailer(path: Path, trailer: dict[str, Any]) -> None:
    if set(trailer) != {"kind", "step_count", "state_hash", "is_terminal", "terminal_reason", "suspended"}:
        raise EventLogError(f"{path}: final fields mismatch")
    if type(trailer["step_count"]) is not int or trailer["step_count"] < 0:
        raise EventLogError(f"{path}: invalid final step_count")
    if not _hash_string(trailer["state_hash"]) or type(trailer["is_terminal"]) is not bool or type(trailer["suspended"]) is not bool:
        raise EventLogError(f"{path}: invalid final hash/status")
    if trailer["terminal_reason"] is not None and not isinstance(trailer["terminal_reason"], str):
        raise EventLogError(f"{path}: invalid final reason")
    if trailer["is_terminal"] and trailer["suspended"]:
        raise EventLogError(f"{path}: terminal and suspended cannot both be true")
    # A failed model call can close a parseable but incomplete log. The
    # verifier rejects it; parsing must preserve its partial evidence.


def _hash_string(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)
