"""E0: deterministic cooperative permission-to-effect experiment, stdlib only.

Supervisor and broker are trusted. No OS isolation, HGK integration, durable
transactions, concurrency, or independent attestation is claimed.
"""
import argparse
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import platform


@dataclass(frozen=True)
class Grant:
    experiment: str = "e0"
    id: str = "actuator"
    version: int = 1
    budget: int = 3
    expires: int = 20
    evidence: bool = True  # Synthetic supervisor attestation, not external proof.


class Broker:
    # ponytail: single trusted thread only; use transactional/process boundaries
    # before attempting concurrency, crash recovery, or hostile controllers.
    def __init__(self):
        self.x, self.version, self.tick = 5, 0, 0
        self.grant = None
        self.revoked = False
        self.used = 0
        self.accepted = {}
        self.events = []

    def record(self, kind, **data):
        self.events.append(dict(index=len(self.events), tick=self.tick, kind=kind,
                                x=self.x, state_version=self.version,
                                error=abs(5-self.x), **deepcopy(data)))

    def disturb(self):
        self.x, self.version = 2, self.version + 1
        self.record("disturbance", target=5)

    def attach(self, grant):
        if self.grant is not None:
            raise ValueError("one grant per experiment; reset only with a new broker")
        if (type(grant) is not Grant or grant.experiment != "e0"
                or grant.id != "actuator" or type(grant.version) is not int or grant.version != 1
                or type(grant.budget) is not int or not 0 <= grant.budget <= 3
                or type(grant.expires) is not int or grant.expires < 0
                or type(grant.evidence) is not bool):
            raise ValueError("invalid supervisor grant")
        self.grant = grant
        self.record("attach", grant=grant.__dict__)

    def advance(self, tick):
        if type(tick) is not int or tick < self.tick:
            raise ValueError("logical clock must be monotonic")
        self.tick = tick

    def revoke(self):
        self.revoked = True
        self.record("revoke")

    def dispatch(self, request):
        self.record("attempt", request=request)
        fields = {"experiment", "grant", "grant_version", "action", "delta",
                  "sequence", "expected_state_version"}
        valid = (type(request) is dict and set(request) == fields
                 and all(type(request[k]) is int for k in
                         ("grant_version", "delta", "sequence", "expected_state_version"))
                 and all(type(request[k]) is str for k in ("experiment", "grant", "action"))
                 and request["sequence"] > 0 and request["expected_state_version"] >= 0
                 and request["action"] == "adjust" and request["delta"] in (-1, 1))
        reason = "malformed"
        if valid:
            g = self.grant
            previous = self.accepted.get(request["sequence"])
            if previous is not None:
                reason = "replay" if previous == request else "sequence_collision"
            elif g is None:
                reason = "no_grant"
            elif (request["experiment"], request["grant"], request["grant_version"]) != (g.experiment, g.id, g.version):
                reason = "unbound"
            elif self.revoked:
                reason = "revoked"
            elif self.tick >= g.expires:
                reason = "expired"
            elif not g.evidence:
                reason = "missing_evidence"
            elif self.used >= g.budget:
                reason = "budget_exhausted"
            elif request["expected_state_version"] != self.version:
                reason = "stale_state"
            elif not 0 <= self.x + request["delta"] <= 10:
                reason = "out_of_bounds"
            else:
                reason = "allowed"
        self.record("decision", reason=reason)
        if reason == "allowed":
            self.accepted[request["sequence"]] = deepcopy(request)
            self.used += 1
            self.record("reservation", sequence=request["sequence"], units=1, used=self.used)
            self.x += request["delta"]
            self.version += 1
            self.record("effect", sequence=request["sequence"], delta=request["delta"], units=1)
        return reason


def propose(x, version, sequence):
    """Controller sees state and proposes; it never mutates broker state."""
    if x == 5:
        return None
    return dict(experiment="e0", grant="actuator", grant_version=1,
                action="adjust", delta=1 if x < 5 else -1, sequence=sequence,
                expected_state_version=version)


EXPECTED = {
    "no_grant": (2, ["no_grant"] * 3),
    "valid": (5, ["allowed"] * 3),
    "revoked": (3, ["allowed", "revoked", "revoked"]),
    "expired": (2, ["expired"] * 3),
    "budget_two": (4, ["allowed", "allowed", "budget_exhausted"]),
    "replay": (3, ["allowed", "replay", "replay"]),
    "stale_or_malformed": (2, ["stale_state", "malformed", "malformed"]),
    "missing_evidence": (2, ["missing_evidence"] * 3),
}


def experiment():
    results = []
    for name, (expected_x, expected_reasons) in EXPECTED.items():
        b = Broker()
        b.disturb()
        if name != "no_grant":
            b.attach(Grant(budget=2 if name == "budget_two" else 3,
                           expires=1 if name == "expired" else 20,
                           evidence=name != "missing_evidence"))
        original = propose(b.x, b.version, 1)
        reasons = []
        for tick in range(1, 4):
            b.advance(tick)
            request = propose(b.x, b.version, tick)
            if name == "replay":
                request = deepcopy(original)
            if name == "stale_or_malformed":
                request.update(({"expected_state_version": 0}, {"action": "shell"}, {"delta": True})[tick-1])
            reasons.append(b.dispatch(request))
            if name == "revoked" and tick == 1:
                b.revoke()
        effects = [e for e in b.events if e["kind"] == "effect"]
        revocations = [e["index"] for e in b.events if e["kind"] == "revoke"]
        after_revoke = sum(e["index"] > revocations[0] for e in effects) if revocations else 0
        passed = (b.x == expected_x and reasons == expected_reasons
                  and b.used == len(effects) == reasons.count("allowed") and after_revoke == 0)
        results.append(dict(condition=name, expected_x=expected_x,
                            expected_reasons=expected_reasons, passed=passed,
                            final_x=b.x, reasons=reasons, accepted_effects=len(effects),
                            refused_attempts=3-len(effects), reserved_units=b.used,
                            consumed_units=len(effects), post_revocation_effects=after_revoke,
                            first_recovery_tick=next((e["tick"] for e in effects if e["x"] == 5), None),
                            events=b.events))
    return dict(schema="e0-experiment/0.1-draft", mode="cooperative single-thread simulation",
                authority="synthetic supervisor grant", python=platform.python_version(),
                controller="one unit toward target; no action at target", target=5,
                clock="supervisor logical ticks", seed=None,
                limitations=["No HGK or OS boundary", "No concurrency or crash safety",
                             "Unsigned self-reported evidence; no independent review"],
                passed=all(r["passed"] for r in results), results=results)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="new JSON file; never overwritten")
    args = parser.parse_args()
    report = experiment()
    report["source_sha256"] = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                               for name in ("e0.py", "test_e0.py", "ONE-LAB-FIRST-EXPERIMENT.md")}
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(json.dumps(dict(passed=report["passed"], conditions=len(report["results"]), output=str(args.output))))
    raise SystemExit(0 if report["passed"] else 1)
