"""Score SWE-bench predictions inside already-pulled instance images.

Uses the official harness's test spec (eval_script) and grader
(get_eval_report), but skips local image builds: runs in
docker.io/swebench/sweb.eval.x86_64.<id>:latest, applies the patch with the
harness's git-apply fallbacks, runs /eval.sh, grades the log.

Usage: python score_preds.py <preds.json> <out_dir> [--dataset SWE-bench/SWE-bench_Lite]

The dataset must carry the swebench>=5 eval fields (image, eval_script,
log_parser, eval_type); princeton-nlp/SWE-bench_Lite does not.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from datasets import load_dataset
from swebench.harness.grading import get_eval_report
from swebench.harness.utils import make_test_spec

APPLY_CMDS = ["git apply --verbose", "git apply --verbose --3way", "patch --batch --fuzz=5 -p1 -i"]


def run(cmd: list[str], data: bytes | None = None, timeout: int = 1800) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, input=data, capture_output=True, timeout=timeout)


def image(iid: str) -> str:
    return f"docker.io/swebench/sweb.eval.x86_64.{iid.replace('__', '_1776_')}:latest".lower()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("preds")
    ap.add_argument("out")
    ap.add_argument("--dataset", default="SWE-bench/SWE-bench_Lite")
    ap.add_argument("--split", default="test")
    a = ap.parse_args()

    preds = json.loads(Path(a.preds).read_text(encoding="utf-8"))
    if isinstance(preds, list):  # standard SWE-bench predictions list
        preds = {p["instance_id"]: p for p in preds}
    ds = {r["instance_id"]: r for r in load_dataset(a.dataset, split=a.split)}
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    summary = {}

    for iid, pred in preds.items():
        if not pred.get("model_patch", "").strip():
            summary[iid] = {"resolved": False, "status": "empty_patch"}
            print(f"{iid}: empty patch -> not resolved")
            continue
        spec = make_test_spec(ds[iid])
        name = f"score-{iid.replace('__', '-')}-{int(time.time())}"
        r = run(["docker", "run", "-d", "--name", name, image(iid), "sleep", "infinity"])
        if r.returncode != 0:
            summary[iid] = {"resolved": False, "status": "container_failed"}
            print(f"{iid}: container failed: {r.stderr.decode()[:300]}")
            continue
        try:
            run(["docker", "exec", "-i", name, "bash", "-c", "cat > /tmp/patch.diff"],
                data=pred["model_patch"].encode("utf-8"))
            applied = None
            for c in APPLY_CMDS:
                p = run(["docker", "exec", "-w", "/testbed", name, "bash", "-c", f"{c} /tmp/patch.diff"])
                if p.returncode == 0:
                    applied = c
                    break
            if not applied:
                summary[iid] = {"resolved": False, "status": "patch_apply_failed"}
                print(f"{iid}: patch did not apply")
                continue
            run(["docker", "exec", "-i", name, "bash", "-c", "cat > /eval.sh"],
                data=spec.eval_script.encode("utf-8"))
            t0 = time.time()
            ev = run(["docker", "exec", name, "bash", "/eval.sh"], timeout=3600)
            log = out / f"{iid}.test_output.txt"
            log.write_bytes(ev.stdout + b"\n" + ev.stderr)
            report = get_eval_report(spec, pred, str(log), include_tests_status=True)
            res = report.get(iid, {})
            summary[iid] = {"resolved": bool(res.get("resolved")), "status": "evaluated",
                            "applied_with": applied, "eval_s": round(time.time() - t0, 1),
                            "tests_status": res.get("tests_status")}
            print(f"{iid}: resolved={res.get('resolved')} applied_with={applied!r} "
                  f"({time.time() - t0:.0f}s)")
        finally:
            run(["docker", "rm", "-f", name])

    (out / "score_summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    resolved = sum(1 for v in summary.values() if v["resolved"])
    print(f"RESOLVED {resolved}/{len(summary)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
