"""Provider adapter sketches — DRAFT, uncommitted, additive.

Three adapters for the Sidekick seams, each declaring its provenance class
so the event ledger records honestly what it does and does not cover:

- LEDGER_NATIVE: every effect is represented in the outer Merkle trace.
- OPAQUE_EXTERNAL: the provider runs its own agent/effects off-ledger;
  the trace records only (request, response). Requires an explicit bridge
  or a documented audit boundary.

Stdlib-only. No secrets in code — keys come from env at call time.

Mapping (from mount-matrix + peer-review R2):
    ModelProvider.complete()          <- text-generation seam (Ollama,
                                         OpenRouter, CLI agents)
    NoulGateEvaluator.route_action    <- decision seam (Jev, heuristics);
                                         tri-state ALLOW/BLOCK/ESCALATE.
                                         evaluate_action remains for
                                         two-state compat callers.
    Jev does NOT fit ModelProvider: it evaluates decisions, it does not
    generate text. Generating and deciding are two protocols.

Peer-review fixes applied (crab 4749f357):
    - Jev answers are {"answers": {"<q>": {"score"|"choice"|"noul": v}}} —
      index by question type key, not the value directly.
    - Abstention band [abstain_lo, abstain_hi) routes ESCALATE — the
      run suspends for a human verdict rather than silently blocking.
      (The tri-state seam landed in schema v0.3; eventlog is now v0.4.)
    - Fail-closed returns p=-1.0 (out-of-range sentinel) so a gate outage
      is distinguishable from a real verdict in ledger stats.
    - Gate judges the same content the tool executes: full content up to
      a cap; beyond it, head+tail+sha256+truncated flag — truncation
      evasion is declared in the decision state.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .functional import ToolAction

LEDGER_NATIVE = "ledger_native"
OPAQUE_EXTERNAL = "opaque_external"

DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"
CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
JEV_MODEL = "typesafe/jev-1.13"

# Out-of-range sentinel: a gate that never produced a verdict is not a
# verdict of 1.0. Ledger stats must be able to separate outages from risk.
GATE_UNREACHABLE = -1.0

# Jev sees the same bytes the tool runs, up to this cap. Past it the state
# carries head+tail+digest and a truncation flag the policy can price.
GATE_CONTENT_CAP = 2048


# --------------------------------------------------------------------------- #
# OpenRouterProvider (ModelProvider seam, LEDGER_NATIVE)
# --------------------------------------------------------------------------- #
class OpenRouterProvider:
    """Any chat model via OpenRouter. Response text enters the trace as a
    MODEL_REPLY event -> ledger-native, replayable. Token usage and billed
    cost land on `last_usage` for the receipt's declared-cost field."""

    provenance_class = LEDGER_NATIVE

    def __init__(self, model: str = "deepseek/deepseek-chat-v3.1",
                 api_key_env: str = "OPENROUTER_API_KEY",
                 timeout_s: int = 120):
        self.model = model
        self.api_key_env = api_key_env
        self.timeout_s = timeout_s
        self.last_usage: Dict = {}

    def complete(self, messages: List[Dict[str, str]]) -> str:
        key = os.environ.get(self.api_key_env)
        if not key:
            raise RuntimeError(f"{self.api_key_env} not set")
        body = json.dumps({
            "model": self.model,
            "messages": messages,
            "temperature": 0,
        }).encode("utf-8")
        req = urllib.request.Request(
            CHAT_URL, data=body, method="POST",
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {key}"})
        with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        self.last_usage = data.get("usage") or {}
        return data["choices"][0]["message"]["content"]


# --------------------------------------------------------------------------- #
# JevNoulGate (NoulGateEvaluator seam, LEDGER_NATIVE)
# --------------------------------------------------------------------------- #
class JevNoulGate:
    """Jev-backed pre-execution gate. Maps a ToolAction to a typed `score`
    question and routes tri-state:

        p_risk >= abstain_hi          -> BLOCK   (confident stop)
        abstain_lo <= p < abstain_hi  -> ESCALATE (suspend for human review)
        p_risk <  abstain_lo          -> ALLOW
        unreachable / no key          -> BLOCK   (fail-closed; outages never
                                                  escalate — escalation is for
                                  adjudicated uncertainty, not transport failure)

    ESCALATE suspends the turn in the functional machine (non-terminal);
    the human verdict re-enters as a USER_INPUT. `evaluate_action` is kept
    for compat: ESCALATE maps to is_alarm=True there, since a two-state
    caller's only safe interpretation of "held" is "do not dispatch".
    """

    provenance_class = LEDGER_NATIVE  # decision I/O is recorded as gate output

    def __init__(self, abstain_lo: float = 0.30, abstain_hi: float = 0.55,
                 api_key_env: str = "OPENROUTER_API_KEY",
                 model: str = JEV_MODEL, timeout_s: int = 60):
        # A nonempty abstention band is part of the tri-state contract.
        # Check the unit interval before float() so huge integers cannot
        # overflow during validation or accidentally bypass the band.
        if (type(abstain_lo) not in (int, float) or
                type(abstain_hi) not in (int, float) or
                not 0 <= abstain_lo < abstain_hi <= 1):
            raise ValueError("abstention thresholds must satisfy 0 <= lo < hi <= 1")
        self.abstain_lo = float(abstain_lo)  # allow/escalate boundary
        self.abstain_hi = float(abstain_hi)  # escalate/block boundary
        self.api_key_env = api_key_env
        self.model = model
        self.timeout_s = timeout_s

    def _questions(self) -> dict:
        return {
            "p_risk": {
                "type": "score",
                "instructions": (
                    "Probability that executing this tool action causes "
                    "data loss, credential exposure, spend, destructive "
                    "filesystem mutation outside the workspace, or an "
                    "irreversible external side effect. If the decision "
                    "state marks content as truncated, price the unseen "
                    "bytes conservatively."
                ),
                "criteria": {"min": 0.0, "max": 1.0},
            }
        }

    def _content_state(self, content: str) -> dict:
        if len(content) <= GATE_CONTENT_CAP:
            return {"content": content, "content_truncated": False}
        half = GATE_CONTENT_CAP // 2
        return {
            "content_head": content[:half],
            "content_tail": content[-half:],
            "content_len": len(content),
            "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "content_truncated": True,
        }

    def route_action(self, action: ToolAction,
                     workspace: Path) -> Tuple[str, float, str]:
        """Tri-state routing: (route, p_risk, reason)."""
        key = os.environ.get(self.api_key_env)
        if not key:
            return "BLOCK", GATE_UNREACHABLE, "jev-gate: no API key (fail-closed)"
        state = {
            "tool": action.tool_name,
            "args": action.args,
            "workspace": str(workspace),
            **self._content_state(action.content),
        }
        body = json.dumps({
            "model": self.model,
            "state": state,
            "questions": self._questions(),
        }).encode("utf-8")
        last_err: Optional[Exception] = None
        for attempt in range(2):  # one retry absorbs transient 429/5xx
            try:
                req = urllib.request.Request(
                    DECISIONS_URL, data=body, method="POST",
                    headers={"Content-Type": "application/json",
                             "Authorization": f"Bearer {key}"})
                with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                # real shape: {"answers": {"p_risk": {"score": 0.xx}}}
                raw_score = data["answers"]["p_risk"]["score"]
                if isinstance(raw_score, bool) or not isinstance(raw_score, (int, float, str)):
                    raise TypeError("invalid p_risk type")
                p_risk = float(raw_score)
                if not math.isfinite(p_risk) or not 0.0 <= p_risk <= 1.0:
                    raise ValueError("invalid p_risk range")
                break
            except urllib.error.HTTPError as e:
                last_err = e
                if e.code not in (429, 500, 502, 503, 504) or attempt:
                    return "BLOCK", GATE_UNREACHABLE, \
                        f"jev-gate HTTP {e.code} (fail-closed)"
                time.sleep(2)
            except Exception as e:
                return "BLOCK", GATE_UNREACHABLE, \
                    f"jev-gate unreachable (fail-closed): {e}"
        else:
            return "BLOCK", GATE_UNREACHABLE, \
                f"jev-gate unreachable (fail-closed): {last_err}"
        if p_risk >= self.abstain_hi:
            return "BLOCK", p_risk, f"jev block: p_risk={p_risk:.2f} >= {self.abstain_hi}"
        if p_risk >= self.abstain_lo:
            return "ESCALATE", p_risk, (
                f"jev abstain: p_risk={p_risk:.2f} in "
                f"[{self.abstain_lo},{self.abstain_hi}) — suspended for human review")
        return "ALLOW", p_risk, f"jev allow: p_risk={p_risk:.2f} < {self.abstain_lo}"

    def evaluate_action(self, action: ToolAction,
                        workspace: Path) -> Tuple[bool, float, str]:
        """Two-state compat view: ESCALATE maps to is_alarm=True — a caller
        without suspension semantics must still refuse to dispatch a held
        action."""
        route, p_risk, reason = self.route_action(action, workspace)
        return route != "ALLOW", p_risk, reason


# --------------------------------------------------------------------------- #
# CLI providers (ModelProvider seam, OPAQUE_EXTERNAL — R2 fix shape)
# --------------------------------------------------------------------------- #
class CliAgentProvider:
    """Headless coding-agent CLI (devin/claude/codex etc.) as a ModelProvider.

    OPAQUE_EXTERNAL: the spawned process runs its own agent loop with its own
    tools; those effects are NOT in the outer Merkle trace (peer-review R2).
    Two honest options:
      1. Declare opacity -> trace records (cmd, stdout, exit, declared class).
      2. Provide a trace bridge: if the inner harness emits its own event
         log (sidekick-shaped), mount it so the outer ledger can include the
         inner chain by reference (inner merkle root in the outer receipt).
    """

    provenance_class = OPAQUE_EXTERNAL

    def __init__(self, cmd_prefix: List[str],
                 inner_eventlog: Optional[Path] = None,
                 timeout_s: int = 600):
        self.cmd_prefix = cmd_prefix
        # if set, the inner agent's own JSONL event log — its final merkle
        # root is folded into the outer receipt for cross-ledger binding
        self.inner_eventlog = inner_eventlog
        self.timeout_s = timeout_s

    def complete(self, messages: List[Dict[str, str]]) -> str:
        last = messages[-1]["content"] if messages else ""
        try:
            res = subprocess.run(
                self.cmd_prefix + ["-p", last],
                capture_output=True, text=True, timeout=self.timeout_s)
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                f"cli-agent timed out after {self.timeout_s}s")
        if res.returncode != 0:
            raise RuntimeError(
                f"cli-agent exit {res.returncode}: {res.stderr[:500]}")
        return res.stdout.strip()

    def provenance_receipt(self) -> Dict[str, str]:
        """Attach to the MODEL_REPLY metadata so audit sees the boundary."""
        rec = {"class": self.provenance_class,
               "cmd": " ".join(self.cmd_prefix)}
        if self.inner_eventlog and self.inner_eventlog.exists():
            rec["inner_log"] = str(self.inner_eventlog)
            rec["inner_root"] = "<compute-from-jsonl>"  # sketch
        return rec
