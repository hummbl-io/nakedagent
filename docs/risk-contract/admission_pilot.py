"""Single-process lab admission boundary. NOT an OS sandbox or trusted service.

Only effect supported: read a pre-enrolled public fixture. Constructor inputs
and kernel callback are trusted lab setup; action input is untrusted. No model,
plugin imports, shell, network or caller-selected paths are exposed by dispatch.
"""
import copy
import hashlib
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from contract import digest, validate


@dataclass(frozen=True)
class Observation:
    observed_at: int
    expires_at: int
    configuration_sha256: str
    status: str


class LabBroker:
    def __init__(self, contract, *, owner_grant_sha256, fixture, fixture_sha256,
                 artifacts, configuration_sha256, graph_sha256, observations,
                 kernel, clock=None):
        validate(contract)
        self.contract = copy.deepcopy(contract)
        self.bound_digest = digest(self.contract)
        self.owner_grant_sha256 = owner_grant_sha256
        self.fixture = Path(fixture)
        self.fixture_sha256 = fixture_sha256
        self.artifacts = dict(artifacts)
        self.configuration_sha256 = configuration_sha256
        self.graph_sha256 = graph_sha256
        self.observations = dict(observations)
        self.kernel = kernel
        self.clock = clock or (lambda: int(time.time()))
        self.lock = threading.Lock()
        self.used = 0
        self.seen = set()
        self.events = []
        self.revoked = False

    def _event(self, action, decision, reasons, **extra):
        event = {"sequence": len(self.events), "run_id": self.contract["run_id"],
                 "action_id": action.get("action_id") if type(action) is dict else None,
                 "contract_sha256": self.bound_digest, "decision": decision,
                 "reasons": reasons, **extra}
        self.events.append(event)
        return copy.deepcopy(event)

    def _conditions(self, now):
        c = self.contract
        if type(now) is not int:
            return "require_more_evidence", ["invalid_clock"]
        if self.revoked:
            return "deny", ["revoked"]
        if digest(c) != self.bound_digest or self.owner_grant_sha256 != self.bound_digest:
            return "deny", ["contract_or_owner_grant_binding"]
        if now >= c["expires_at"]:
            return "deny", ["contract_expired"]
        if self.configuration_sha256 != c["configuration_sha256"] or self.graph_sha256 != c["dependency_graph_sha256"]:
            return "deny", ["configuration_or_graph_drift"]
        if set(self.artifacts) != {x["id"] for x in c["components"]}:
            return "deny", ["component_set_drift"]
        for component in c["components"]:
            try:
                actual = hashlib.sha256(Path(self.artifacts[component["id"]]).read_bytes()).hexdigest()
            except OSError:
                return "require_more_evidence", ["artifact_unavailable"]
            if actual != component["sha256"]:
                return "deny", ["artifact_drift"]
        for name in c["required_evidence"]:
            item = self.observations.get(name)
            if (not isinstance(item, Observation) or item.status != "verified"
                    or type(item.observed_at) is not int or type(item.expires_at) is not int
                    or not item.observed_at <= now < item.expires_at
                    or item.configuration_sha256 != c["configuration_sha256"]):
                return "require_more_evidence", ["evidence_missing_stale_or_unbound"]
        if self.used >= c["max_actions"]:
            return "deny", ["budget_exhausted"]
        return None

    def dispatch(self, action):
        with self.lock:
            if type(action) is dict:
                action = dict(action)  # bind a snapshot, not a caller-mutated envelope
            expected = {"action_id", "run_id", "principal", "contract_sha256", "operation", "resource"}
            if (type(action) is not dict or set(action) != expected
                    or any(type(v) is not str or not 0 < len(v) <= 128 for v in action.values())):
                return self._event({}, "deny", ["malformed_action"])
            if (action["run_id"] != self.contract["run_id"] or action["principal"] != self.contract["principal"]
                    or action["contract_sha256"] != self.bound_digest):
                return self._event(action, "deny", ["action_binding"])
            if action["action_id"] in self.seen:
                return self._event(action, "deny", ["replayed_action"])
            grant = {"operation": action["operation"], "resource": action["resource"]}
            if grant not in self.contract["grants"] or grant != {"operation": "read_fixture", "resource": "lab:public-fixture"}:
                return self._event(action, "deny", ["effect_not_permitted_or_supported"])
            failure = self._conditions(self.clock())
            if failure:
                return self._event(action, *failure)
            try:
                result = self.kernel(copy.deepcopy(action))
            except Exception:  # noqa: BLE001 - any callback failure must prevent dispatch
                return self._event(action, "require_more_evidence", ["kernel_unavailable"])
            # Do not trust self-reported allow or silently interpret constraints.
            if (type(result) is not dict or result.get("decision") != "allow"
                    or result.get("required_controls") != []):
                decision = result.get("decision") if type(result) is dict else None
                if decision not in {"ask", "deny", "constrain", "escalate", "require_more_evidence"}:
                    decision = "require_more_evidence"
                return self._event(action, decision, ["kernel_did_not_grant_supported_effect"])
            # Recheck after the kernel callback, before budget reservation/effect.
            failure = self._conditions(self.clock())
            if failure:
                return self._event(action, *failure)
            self.used += 1
            self.seen.add(action["action_id"])
            self._event(action, "reserved", [], enforcement_status="lab_in_process_only")
            try:
                with self.fixture.open("rb") as source:
                    content = source.read(4097)
                if len(content) > 4096 or hashlib.sha256(content).hexdigest() != self.fixture_sha256:
                    return self._event(action, "deny", ["fixture_changed"], attempted=True)
            except OSError:
                return self._event(action, "require_more_evidence", ["fixture_unavailable"], attempted=True)
            return self._event(action, "completed", [], bytes_read=len(content),
                               content_sha256=self.fixture_sha256,
                               kernel_enforcement_status=result.get("enforcement_status", "unknown"),
                               enforcement_status="lab_in_process_only")
