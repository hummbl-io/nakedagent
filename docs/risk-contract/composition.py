"""[DERIVED] Bounded composition: declared dependencies -> evidence -> HGK -> receipt.

CO2: Chunking; CO3: Functional Composition; CO9: Interface Contracts;
CO16: System Integration Testing. Lab-only, no executable plugin loading,
credential authentication, complete dependency discovery or OS containment.
"""
import copy
import hashlib
from pathlib import Path

from admission_pilot import LabBroker, Observation
from contract import canonical, digest


def compile_loadout(components):
    """Pure validation of a declared DAG; neither imports nor installs components."""
    if type(components) is not list or not 1 <= len(components) <= 128:
        raise ValueError("component bounds")
    by_id = {}
    for item in components:
        if type(item) is not dict or set(item) != {"id", "sha256", "dependencies"}:
            raise ValueError("component fields")
        name = item["id"]
        if type(name) is not str or name in by_id:
            raise ValueError("duplicate/invalid identity")
        deps = item["dependencies"]
        if type(deps) is not list or any(type(d) is not str for d in deps) or len(set(deps)) != len(deps):
            raise ValueError("invalid dependencies")
        by_id[name] = copy.deepcopy(item)
    done, visiting, ordered = set(), set(), []

    def visit(name):
        if name not in by_id:
            raise ValueError("unresolved dependency")
        if name in visiting:
            raise ValueError("dependency cycle unsupported")
        if name in done:
            return
        visiting.add(name)
        for dep in sorted(by_id[name]["dependencies"]):
            visit(dep)
        visiting.remove(name)
        done.add(name)
        ordered.append(name)

    for name in sorted(by_id):
        visit(name)
    normalized = [dict(by_id[n], dependencies=sorted(by_id[n]["dependencies"])) for n in sorted(by_id)]
    return {"schema": "declared-loadout/0.1", "components": normalized, "order": ordered}


def evidence_record(*, source_bytes, configuration_sha256, loadout_sha256, observed_at, expires_at):
    """Trusted lab fixture builder. This function does NOT authenticate a collector."""
    return {"schema": "lab-cer/0.1", "collector": "lab-fixture-collector",
            "subject": "lab:public-fixture", "predicate": "enrollment-observed",
            "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
            "configuration_sha256": configuration_sha256, "loadout_sha256": loadout_sha256,
            "observed_at": observed_at, "expires_at": expires_at,
            "trust_basis": "synthetic-trusted-lab-setup"}


class ReceiptChain:
    """In-memory chain, audited against a separately retained expected checkpoint."""
    def __init__(self):
        self.records = []

    def append(self, kind, data):
        record = {"sequence": len(self.records), "previous": self.checkpoint,
                  "kind": kind, "data": copy.deepcopy(data)}
        record["sha256"] = digest(record)
        self.records.append(record)
        return record["sha256"]

    @property
    def checkpoint(self):
        return self.records[-1]["sha256"] if self.records else "0" * 64


def audit_chain(records, expected_checkpoint):
    previous = "0" * 64
    for sequence, record in enumerate(records):
        if (type(record) is not dict or set(record) != {"sequence", "previous", "kind", "data", "sha256"}
                or record["sequence"] != sequence or record["previous"] != previous):
            raise ValueError("receipt linkage")
        unsigned = {k: v for k, v in record.items() if k != "sha256"}
        if digest(unsigned) != record["sha256"]:
            raise ValueError("receipt content")
        previous = record["sha256"]
    if previous != expected_checkpoint:
        raise ValueError("checkpoint mismatch")
    return True


class ComposedLabBroker(LabBroker):
    """Reuses existing dispatch lock and pre/post-kernel condition checks.

    Setup objects and callback remain trusted. Receipt chain is NOT durable
    reservation state. Subject/type/freshness gates are not factual truth proofs.
    """
    def __init__(self, contract, *, cer, source, **kwargs):
        self.loadout = compile_loadout(contract["components"])
        self.loadout_sha256 = digest(self.loadout)
        if contract["dependency_graph_sha256"] != self.loadout_sha256:
            raise ValueError("declared graph binding")
        if contract["required_evidence"] != ["fixture-enrollment"]:
            raise ValueError("unsupported evidence requirement")
        self.cer = copy.deepcopy(cer)
        self.source = Path(source)
        # Pin at enrollment; this is synthetic trusted setup, not owner authentication.
        self.enrolled_cer_sha256 = digest(self.cer)
        self.chain = ReceiptChain()
        self.chain.append("loadout", self.loadout)
        self.chain.append("source-evidence", self.cer)
        kernel = kwargs.pop("kernel")

        def traced_kernel(action):
            request_ref = self.chain.append("kernel-request", action)
            try:
                result = kernel(action)
            except Exception:
                self.chain.append("kernel-error", {"request_sha256": request_ref, "status": "unavailable"})
                raise
            self.chain.append("kernel-response", {"request_sha256": request_ref, "response": result})
            return result

        kwargs.pop("observations", None)
        super().__init__(contract, kernel=traced_kernel, observations={}, **kwargs)

    def _conditions(self, now):
        if type(now) is not int:
            return "require_more_evidence", ["invalid_clock"]
        item = self.cer
        expected = {"schema", "collector", "subject", "predicate", "source_sha256",
                    "configuration_sha256", "loadout_sha256", "observed_at", "expires_at", "trust_basis"}
        if (type(item) is not dict or set(item) != expected or digest(item) != self.enrolled_cer_sha256
                or item["schema"] != "lab-cer/0.1" or item["collector"] != "lab-fixture-collector"
                or item["subject"] != "lab:public-fixture" or item["predicate"] != "enrollment-observed"
                or item["trust_basis"] != "synthetic-trusted-lab-setup"
                or item["configuration_sha256"] != self.configuration_sha256
                or item["loadout_sha256"] != self.loadout_sha256
                or type(item["observed_at"]) is not int or type(item["expires_at"]) is not int
                or not item["observed_at"] <= now < item["expires_at"]):
            return "require_more_evidence", ["evidence_binding_or_freshness"]
        try:
            with self.source.open("rb") as source:
                raw = source.read(4097)
        except OSError:
            return "require_more_evidence", ["source_unavailable"]
        if len(raw) > 4096 or hashlib.sha256(raw).hexdigest() != item["source_sha256"]:
            return "require_more_evidence", ["source_drift"]
        self.observations = {"fixture-enrollment": Observation(
            item["observed_at"], item["expires_at"], item["configuration_sha256"], "verified")}
        return super()._conditions(now)

    def _event(self, action, decision, reasons, **extra):
        result = super()._event(action, decision, reasons, **extra)
        ref = self.chain.append("broker-event", result)
        return {**result, "receipt_sha256": ref}

    def export(self, path):
        """Exclusive snapshot export after dispatch. Not a write-ahead transaction."""
        audit_chain(self.chain.records, self.chain.checkpoint)
        with Path(path).open("xb") as target:
            target.write(canonical({"schema": "lab-receipts/0.1", "checkpoint": self.chain.checkpoint,
                                    "records": self.chain.records}))
