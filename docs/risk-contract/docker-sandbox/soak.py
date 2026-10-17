"""Finite, seeded nakedagent property soak. No model or external network calls."""
import argparse
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import random
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def batch(seed):
    from nakedagent.toolcall import parse
    spec = importlib.util.spec_from_file_location("soak_invariants", ROOT / "tests/test_invariants.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rng = random.Random(seed)
    module.SEED = seed
    module.N_STREAMS = 200
    module.STREAM_LEN = rng.randint(1, 80)
    # Default arguments in the existing test module bind its original length;
    # record that fact instead of pretending all generated streams vary length.
    suite = unittest.defaultTestLoader.loadTestsFromModule(module)
    output = io.StringIO()
    result = unittest.TextTestRunner(stream=output, verbosity=0).run(suite)
    parser_cases = 0
    error = None
    try:
        for _ in range(256):
            payload = "".join(rng.choice("abcXYZ0123 ;éλ中\u2028\u2029") for _ in range(rng.randint(0, 2048)))
            text = "```write sample.txt\n```python\n" + payload + "\n```\n```"
            calls = parse(text)
            if len(calls) != 1 or calls[0].tool != "write" or calls[0].content != "```python\n" + payload + "\n```":
                raise AssertionError("nested body generated an unexpected call")
            if parse(text.replace("\n", "\r\n")) != calls:
                raise AssertionError("CRLF normalization changed calls")
            refused = parse("```write sample.txt\n" + payload)
            if len(refused) != 1 or refused[0].tool != "__refused__":
                raise AssertionError("unclosed outer call was not refused")
            parser_cases += 1
    except Exception as exc:
        error = repr(exc)
    return {"seed": seed, "invariant_tests": result.testsRun,
            "stream_count_setting": module.N_STREAMS,
            "stream_default_length": 40, "parser_cases": parser_cases,
            "passed": result.wasSuccessful() and error is None,
            "failure": (output.getvalue()[-16000:] if not result.wasSuccessful() else error)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, required=True)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 31800 or not 1 <= args.workers <= 16:
        parser.error("duration or workers outside contract")
    args.output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    deadline = started + args.seconds
    summary = {"started_at": datetime.now(timezone.utc).isoformat(), "status": "running",
               "duration_limit_seconds": args.seconds, "workers": args.workers,
               "batches": 0, "invariant_tests": 0, "parser_cases": 0, "failures": 0,
               "previous": "0" * 64, "model_calls": 0}

    def checkpoint():
        summary["elapsed_seconds"] = round(time.monotonic() - started, 3)
        temp = args.output / "summary.tmp"
        temp.write_text(json.dumps(summary, indent=2) + "\n")
        os.replace(temp, args.output / "summary.json")

    checkpoint()
    seed = 20261003000000
    with (args.output / "events.jsonl").open("x") as log:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            pending = {}
            for _ in range(args.workers):
                pending[pool.submit(batch, seed)] = seed
                seed += 1
            abort = False
            while pending:
                ready, _ = wait(pending, timeout=10, return_when=FIRST_COMPLETED)
                for future in ready:
                    used_seed = pending.pop(future)
                    try:
                        row = future.result()
                    except Exception as exc:
                        row = {"seed": used_seed, "passed": False, "failure": repr(exc),
                               "invariant_tests": 0, "parser_cases": 0}
                    row["previous"] = summary["previous"]
                    digest = hashlib.sha256(json.dumps(row, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                    log.write(json.dumps({**row, "sha256": digest}, sort_keys=True) + "\n")
                    log.flush()
                    summary["previous"] = digest
                    summary["batches"] += 1
                    summary["invariant_tests"] += row["invariant_tests"]
                    summary["parser_cases"] += row["parser_cases"]
                    if not row["passed"]:
                        summary["failures"] += 1
                        abort = True
                    if not abort and time.monotonic() < deadline:
                        pending[pool.submit(batch, seed)] = seed
                        seed += 1
                if (args.output / "STOP").exists():
                    abort = True
                checkpoint()
            summary["status"] = "failed" if summary["failures"] else "cancelled" if abort else "completed"
            summary["finished_at"] = datetime.now(timezone.utc).isoformat()
            checkpoint()
    return 1 if summary["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
