"""Verify exported soak byte linkage and counts; not an authenticity attestation."""
import hashlib
import json
from pathlib import Path
import sys


def verify(root):
    summary = json.loads((root / "summary.json").read_text())
    previous = "0" * 64
    counts = dict(batches=0, invariant_tests=0, parser_cases=0, failures=0)
    seeds = set()
    with (root / "events.jsonl").open() as stream:
        for line in stream:
            row = json.loads(line)
            recorded = row.pop("sha256")
            if row["previous"] != previous:
                raise ValueError("broken previous hash")
            previous = hashlib.sha256(json.dumps(row, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            if previous != recorded:
                raise ValueError("event hash mismatch")
            if row["seed"] in seeds:
                raise ValueError("duplicate batch seed")
            seeds.add(row["seed"])
            counts["batches"] += 1
            counts["invariant_tests"] += row["invariant_tests"]
            counts["parser_cases"] += row["parser_cases"]
            counts["failures"] += int(not row["passed"])
    if previous != summary["previous"] or any(counts[key] != summary[key] for key in counts):
        raise ValueError("summary does not match exported events")
    return {"chain_verified": True, "status": summary["status"], **counts,
            "head": previous, "authenticity_verified": False}


if __name__ == "__main__":
    print(json.dumps(verify(Path(sys.argv[1])), indent=2))
