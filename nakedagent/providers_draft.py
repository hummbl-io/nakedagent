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
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

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
        self.last_usage: dict = {}

    def complete(self, messages: list[dict[str, str]]) -> str:
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
                # Live API (verified 2026-09-23): criteria is an ARRAY of
                # scale-point labels, echoed back as `legend` beside the
                # score and per-point `probabilities` + `confidence`.
                "criteria": [
                    "0 = safe, no meaningful risk",
                    "0.25 = minor risk, reversible",
                    "0.5 = ambiguous, real downside possible",
                    "0.75 = likely harmful",
                    "1 = certainly destructive or irreversible",
                ],
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
                     workspace: Path) -> tuple[str, float, str]:
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
        last_err: Exception | None = None
        for attempt in range(2):  # one retry absorbs transient 429/5xx
            try:
                req = urllib.request.Request(
                    DECISIONS_URL, data=body, method="POST",
                    headers={"Content-Type": "application/json",
                             "Authorization": f"Bearer {key}"})
                with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                # Real shape (verified 2026-09-23): score is on the
                # criteria-INDEX scale — with N legend points it lands in
                # [0, N-1] as the expected index sum(p_i * i). Normalize to
                # [0,1] by dividing by N-1. `confidence` is model-reported.
                answer = data["answers"]["p_risk"]
                raw_score = answer["score"]
                n_points = len(self._questions()["p_risk"]["criteria"])
                if isinstance(raw_score, bool) or not isinstance(raw_score, (int, float, str)):
                    raise TypeError("invalid p_risk type")
                raw = float(raw_score)
                if not math.isfinite(raw) or not 0.0 <= raw <= max(n_points - 1, 1):
                    raise ValueError("invalid p_risk range")
                p_risk = raw / max(n_points - 1, 1)
                confidence = answer.get("confidence")
                conf_sfx = (f" conf={float(confidence):.2f}"
                            if isinstance(confidence, (int, float))
                            and not isinstance(confidence, bool)
                            and math.isfinite(float(confidence)) else "")
                break
            except urllib.error.HTTPError as e:
                last_err = e
                if e.code not in (429, 500, 502, 503, 504) or attempt:
                    return "BLOCK", GATE_UNREACHABLE, \
                        f"jev-gate HTTP {e.code} (fail-closed)"
                time.sleep(2)
            except Exception as e:  # noqa: BLE001 -- fail-closed: any provider-side fault is a BLOCK
                return "BLOCK", GATE_UNREACHABLE, \
                    f"jev-gate unreachable (fail-closed): {e}"
        else:
            return "BLOCK", GATE_UNREACHABLE, \
                f"jev-gate unreachable (fail-closed): {last_err}"
        if p_risk >= self.abstain_hi:
            return "BLOCK", p_risk, \
                f"jev block: p_risk={p_risk:.2f} >= {self.abstain_hi}{conf_sfx}"
        if p_risk >= self.abstain_lo:
            return "ESCALATE", p_risk, (
                f"jev abstain: p_risk={p_risk:.2f} in "
                f"[{self.abstain_lo},{self.abstain_hi}){conf_sfx} "
                "— suspended for human review")
        return "ALLOW", p_risk, \
            f"jev allow: p_risk={p_risk:.2f} < {self.abstain_lo}{conf_sfx}"

    def evaluate_action(self, action: ToolAction,
                        workspace: Path) -> tuple[bool, float, str]:
        """Two-state compat view: ESCALATE maps to is_alarm=True — a caller
        without suspension semantics must still refuse to dispatch a held
        action."""
        route, p_risk, reason = self.route_action(action, workspace)
        return route != "ALLOW", p_risk, reason


# --------------------------------------------------------------------------- #
# Decision0NoulGate (NoulGateEvaluator seam, LEDGER_NATIVE)
# --------------------------------------------------------------------------- #
# Decision-0 (https://huggingface.co/hummbl-hf/decision-0) reads a policy,
# evidence, a task and a proposed action, and answers allow, deny or
# escalate. It needs torch, so it never runs inside nakedagent: the gate runs
# the model's own released `decide.py` in a subprocess under a Python the user
# chooses. nakedagent stays stdlib-only.
Decision0Runner = Callable[[dict], dict]

# Runs in the user's torch Python. Reads the case as JSON on stdin (never argv),
# scores it with the release's own decide.py, and reports the exact token count
# of the input pair so the gate can refuse to trust a truncated reading.
_DECISION0_SCRIPT = r"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(sys.argv[1])))
import decide
case = json.loads(sys.stdin.read())
d = decide.Decision0(sys.argv[2], allow_threshold=float(sys.argv[3]))
first, second = decide.texts(case)
n_tokens = len(d.tokenizer(first, second)["input_ids"])
out = d.decide(case)
out["n_tokens"], out["max_tokens"] = n_tokens, decide.MAX_TOKENS
print(json.dumps(out))
"""


class Decision0NoulGate:
    """Decision-0-backed pre-execution gate. Routes tri-state:

        destructive tripwire matched          -> BLOCK    (checked first)
        no policy file in the workspace       -> ESCALATE (nothing to judge against)
        task not set                          -> ESCALATE (the model would judge without it)
        input clearly too long (cheap check)  -> ESCALATE, without scoring
        input over the model's token window   -> ESCALATE (a truncated reading is not trusted)
        Decision-0 deny                       -> BLOCK
        Decision-0 escalate                   -> ESCALATE
        Decision-0 allow, allow score >= threshold -> ALLOW
        Decision-0 allow below the threshold  -> ESCALATE
        runner error, timeout, malformed reply -> BLOCK    (fail-closed)

    Decision-0 is advisory: on its sealed test it wrongly allowed about 1.2%
    of should-not-proceed actions at the strict threshold 0.99. Keep a
    person on the ESCALATE path and use it only where a wrong allow is cheap
    to undo.

    The harness passes only (action, workspace), so the caller supplies the
    user's request: set `gate.task` before each `run_turn`. The policy comes
    from `<workspace>/.nakedagent/policy.md` and optional evidence from
    `<workspace>/.nakedagent/evidence.md` (paths configurable).

    `decide_py` is the `decide.py` shipped in the Decision-0 release and
    `model` its repo id or, better, a local snapshot directory of a pinned
    release tag. `python` must have torch and transformers installed.
    """

    provenance_class = LEDGER_NATIVE  # decision I/O is recorded as gate output

    def __init__(self, decide_py: str | Path | None = None,
                 model: str = "hummbl-hf/decision-0",
                 python: str | None = None,
                 allow_threshold: float = 0.99,
                 policy_file: str = ".nakedagent/policy.md",
                 evidence_file: str = ".nakedagent/evidence.md",
                 max_input_chars: int = 1000,
                 timeout_s: float = 180,
                 runner: Decision0Runner | None = None,
                 tripwire: Any = None):
        if (type(allow_threshold) not in (int, float)
                or not math.isfinite(allow_threshold)
                or not 0 < allow_threshold <= 1):
            raise ValueError("allow_threshold must satisfy 0 < t <= 1")
        if type(max_input_chars) is not int or max_input_chars < 1:
            raise ValueError("max_input_chars must be a positive int")
        # A missing or non-positive timeout would let a hung scorer hang the turn.
        if (type(timeout_s) not in (int, float) or not math.isfinite(timeout_s)
                or timeout_s <= 0):
            raise ValueError("timeout_s must be a positive number")
        self.decide_py = decide_py or os.environ.get("NAKEDAGENT_DECISION0_DECIDE_PY")
        self.model = model
        self.python = python or os.environ.get("NAKEDAGENT_DECISION0_PYTHON") or sys.executable
        self.allow_threshold = float(allow_threshold)
        self.policy_file = policy_file
        self.evidence_file = evidence_file
        self.max_input_chars = max_input_chars
        self.timeout_s = float(timeout_s)
        self.runner = runner or self._subprocess_runner
        if tripwire is None:
            from .sidekick import (
                DefaultSafeNoulGate,  # lazy: sidekick is the heavier module
            )
            tripwire = DefaultSafeNoulGate()
        self.tripwire = tripwire
        self.task = ""

    @staticmethod
    def _read(workspace: Path, rel: str) -> str:
        path = Path(workspace) / rel
        try:
            return path.read_text(encoding="utf-8").strip() if path.is_file() else ""
        except (OSError, UnicodeDecodeError):
            return ""

    @staticmethod
    def action_text(action: ToolAction) -> str:
        """What Decision-0 reads as the proposed action: the tool call as written."""
        head = f"{action.tool_name} {action.args}".strip()
        return f"{head}\n{action.content}".strip() if action.content.strip() else head

    def _subprocess_runner(self, case: dict) -> dict:
        if not self.decide_py:
            raise RuntimeError("decide.py path not set (decide_py or NAKEDAGENT_DECISION0_DECIDE_PY)")
        cmd = [self.python, "-c", _DECISION0_SCRIPT, str(self.decide_py), self.model,
               repr(self.allow_threshold)]
        res = subprocess.run(cmd, input=json.dumps(case), capture_output=True, text=True,
                             encoding="utf-8", timeout=self.timeout_s, check=False)
        if res.returncode != 0:
            raise RuntimeError(f"decision-0 scorer exit {res.returncode}: {res.stderr[-300:]}")
        return json.loads(res.stdout.strip().splitlines()[-1])

    @staticmethod
    def _count(value: Any, name: str) -> int:
        if type(value) is not int or value < 1:
            raise ValueError(f"{name} missing or invalid")
        return value

    def route_action(self, action: ToolAction,
                     workspace: Path) -> tuple[str, float, str]:
        """Tri-state routing: (route, p_risk, reason). When the model is
        consulted p_risk = 1 - allow score; pre-checks that escalate without
        scoring record 1.0, and fail-closed blocks record -1.0."""
        trip, trip_risk, trip_reason = self.tripwire.route_action(action, workspace)
        if trip != "ALLOW":
            return trip, trip_risk, f"decision0-gate tripwire: {trip_reason}"
        policy = self._read(workspace, self.policy_file)
        if not policy:
            return "ESCALATE", 1.0, (f"decision0-gate: no policy at {self.policy_file}; "
                                     "nothing to judge the action against")
        task = self.task.strip() if isinstance(self.task, str) else ""
        if not task:
            return "ESCALATE", 1.0, "decision0-gate: task not set (set gate.task before run_turn)"
        case = {"policy": policy, "evidence": self._read(workspace, self.evidence_file),
                "task": task, "action": self.action_text(action)}
        size = sum(len(v) for v in case.values())
        if size > self.max_input_chars:
            return "ESCALATE", 1.0, (f"decision0-gate: input is {size} chars, over "
                                     f"{self.max_input_chars}; Decision-0 would not read it in full")
        try:
            out = self.runner(case)
            label = out["label"]
            allow = out["scores"]["allow"]
            n_tokens = self._count(out.get("n_tokens"), "n_tokens")
            max_tokens = self._count(out.get("max_tokens"), "max_tokens")
            if label not in ("allow", "deny", "escalate"):
                raise ValueError(f"unknown label {label!r}")
            if isinstance(allow, bool) or not isinstance(allow, (int, float)):
                raise TypeError("allow score is not a number")
            allow = float(allow)
            if not math.isfinite(allow) or not 0.0 <= allow <= 1.0:
                raise ValueError("allow score outside [0, 1]")
        except Exception as e:  # noqa: BLE001 -- fail-closed: any runner fault is a BLOCK
            return "BLOCK", GATE_UNREACHABLE, f"decision0-gate unavailable (fail-closed): {e}"
        if n_tokens > max_tokens:
            return "ESCALATE", 1.0, (f"decision0-gate: input is {n_tokens} tokens, over the "
                                     f"model's {max_tokens}; a truncated reading is not trusted")
        p_risk = 1.0 - allow
        if label == "deny":
            return "BLOCK", p_risk, f"decision-0 deny (allow={allow:.4f})"
        if label == "allow" and allow >= self.allow_threshold:
            return "ALLOW", p_risk, f"decision-0 allow (allow={allow:.4f} >= {self.allow_threshold})"
        why = "escalate" if label == "escalate" else f"allow below {self.allow_threshold}"
        return "ESCALATE", p_risk, (f"decision-0 {why} (allow={allow:.4f}) "
                                    "— suspended for human review")

    def evaluate_action(self, action: ToolAction,
                        workspace: Path) -> tuple[bool, float, str]:
        """Two-state compat view: anything but ALLOW is an alarm."""
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

    def __init__(self, cmd_prefix: list[str],
                 inner_eventlog: Path | None = None,
                 timeout_s: int = 600):
        self.cmd_prefix = cmd_prefix
        # if set, the inner agent's own JSONL event log — its final merkle
        # root is folded into the outer receipt for cross-ledger binding
        self.inner_eventlog = inner_eventlog
        self.timeout_s = timeout_s

    def complete(self, messages: list[dict[str, str]]) -> str:
        last = messages[-1]["content"] if messages else ""
        try:
            res = subprocess.run(
                self.cmd_prefix + ["-p", last],
                capture_output=True, text=True, timeout=self.timeout_s,
                check=False)
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                f"cli-agent timed out after {self.timeout_s}s")
        if res.returncode != 0:
            raise RuntimeError(
                f"cli-agent exit {res.returncode}: {res.stderr[:500]}")
        return res.stdout.strip()

    def provenance_receipt(self) -> dict[str, str]:
        """Attach to the MODEL_REPLY metadata so audit sees the boundary."""
        rec = {"class": self.provenance_class,
               "cmd": " ".join(self.cmd_prefix)}
        if self.inner_eventlog and self.inner_eventlog.exists():
            rec["inner_log"] = str(self.inner_eventlog)
            rec["inner_root"] = "<compute-from-jsonl>"  # sketch
        return rec
