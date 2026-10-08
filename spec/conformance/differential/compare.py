"""Compare a port's results with the reference, case by case, as parsed JSON.

    python3 compare.py cases.jsonl out_py.jsonl out_port.jsonl [more ...]

Exits non-zero if any port differs. Prints the first mismatches per op.
"""

import collections
import json
import sys


def load(path):
    return [json.loads(line) for line in open(path, encoding="utf-8")]


cases = load(sys.argv[1])
reference = load(sys.argv[2])
failed = False
for path in sys.argv[3:]:
    got = load(path)
    if len(got) != len(cases):
        print(f"{path}: {len(got)} results for {len(cases)} cases")
        failed = True
        continue
    bad = collections.defaultdict(list)
    for case, want, have in zip(cases, reference, got):
        if want != have:
            bad[case["op"]].append((case, want, have))
    total = collections.Counter(c["op"] for c in cases)
    summary = {op: f"{len(v)}/{total[op]}" for op, v in bad.items()}
    print(f"{path}: {len(cases)} cases, mismatches: {summary or 'none'}")
    for op, rows in bad.items():
        failed = True
        for case, want, have in rows[:3]:
            print("  ", op, "input", json.dumps(case, ensure_ascii=True)[:300])
            print("      reference", json.dumps(want, ensure_ascii=True)[:200])
            print("      port     ", json.dumps(have, ensure_ascii=True)[:200])
sys.exit(1 if failed else 0)
