"""Bounded, advisory reachability assessment. Never authorizes execution.

Input is a caller-supplied graph snapshot, not authenticated telemetry.
Every edge is potentially traversable; no declared control silently removes it.
"""
import argparse
import json
import math
from pathlib import Path


def assess(snapshot, now):
    if type(now) not in (int, float) or not math.isfinite(now):
        raise ValueError("now must be finite")
    if snapshot.get("schema") != "nakedagent-risk-graph/0.1.0":
        raise ValueError("unsupported schema")
    nodes = snapshot["nodes"]
    if not isinstance(nodes, list) or any(not isinstance(n, str) or not n for n in nodes):
        raise ValueError("nodes must be nonempty strings")
    if len(nodes) != len(set(nodes)) or snapshot["root"] not in nodes:
        raise ValueError("duplicate nodes or absent root")
    effects = snapshot["effects"]
    if not isinstance(effects, list) or any(n not in nodes for n in effects):
        raise ValueError("effects must reference nodes")
    edges = snapshot["edges"]
    for edge in edges:
        if len(edge) != 2 or any(n not in nodes for n in edge):
            raise ValueError("edge must reference two nodes")
    reachable = {snapshot["root"]}
    witnesses = {snapshot["root"]: [snapshot["root"]]}
    changed = True
    while changed:
        changed = False
        for source, target in edges:
            if source in reachable and target not in reachable:
                reachable.add(target)
                witnesses[target] = witnesses[source] + [target]
                changed = True
    gaps = []
    if snapshot.get("inventory_complete") is not True:
        gaps.append("inventory incomplete: no total upper bound")
    evidence = snapshot.get("evidence", {})
    for name in snapshot.get("required_evidence", []):
        item = evidence.get(name)
        if not isinstance(item, dict):
            gaps.append(f"{name}: missing")
            continue
        observed, ttl = item.get("observed_at"), item.get("ttl_seconds")
        def valid_number(v):
            return type(v) in (int, float) and math.isfinite(v)
        if not valid_number(observed) or not valid_number(ttl) or ttl <= 0:
            gaps.append(f"{name}: invalid time/TTL")
        elif observed > now or now - observed >= ttl:
            gaps.append(f"{name}: stale or future-dated")
        if item.get("status") != "verified":
            gaps.append(f"{name}: not verified")
    reached = sorted(set(effects) & reachable)
    return {
        "mode": "advisory snapshot; evidence supplied, not authenticated",
        "authorizes_execution": False,
        "reachable_effects": reached,
        "witness_paths": {n: witnesses[n] for n in reached},
        "gaps": gaps,
        "review_state": "hold" if gaps else "ready for external policy review",
        "risk_probability": None,
    }


def compare(before, after, now):
    a, b = assess(before, now), assess(after, now)
    # Same resource count can conceal a newly connected path. Report edge deltas too.
    old_edges = {tuple(e) for e in before["edges"]}
    new_edges = {tuple(e) for e in after["edges"]}
    return {
        "added_effects": sorted(set(b["reachable_effects"]) - set(a["reachable_effects"])),
        "removed_effects": sorted(set(a["reachable_effects"]) - set(b["reachable_effects"])),
        "added_edges": sorted(new_edges - old_edges),
        "removed_edges": sorted(old_edges - new_edges),
        "assessment": b,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--now", required=True, type=float, help="explicit epoch seconds for reproducibility")
    args = parser.parse_args()
    print(json.dumps(assess(json.loads(args.snapshot.read_text(encoding="utf-8")), args.now), indent=2))
