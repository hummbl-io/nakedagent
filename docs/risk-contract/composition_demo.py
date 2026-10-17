"""CO16 local integration demonstration using synthetic fixtures and actual HGK.

No production launch, installation, secret access or network service calls.
"""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from composition import ComposedLabBroker, audit_chain
from kernel_demo import PINNED_HEAD
from test_composition import setup_lab


def run(root, output):
    root, output = root.resolve(), output.resolve()
    head = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    if head != PINNED_HEAD:
        raise ValueError("HGK HEAD changed; review before repinning")
    if subprocess.check_output(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"], text=True).strip():
        raise ValueError("HGK tracked source dirty")
    output.mkdir(parents=True, exist_ok=False)
    calls = []
    outcomes = []

    def kernel(action):
        request = {"kernel_root": str(root), "principal": action["principal"],
                   "fixture": str(output/"public.txt"), "receipt_dir": str(output/"hgk-receipts")}
        proc = subprocess.run([sys.executable, "-I", str(Path(__file__).with_name("hgk_probe.py"))],
                              input=json.dumps(request).encode(), capture_output=True, timeout=20, check=True)
        response = json.loads(proc.stdout)
        receipt = Path(response["receipt_path"])
        if not receipt.resolve().is_relative_to(output):
            raise ValueError("HGK receipt outside scratch output")
        result = {**response["decision"], "receipt_sha256": hashlib.sha256(receipt.read_bytes()).hexdigest(),
                  "receipt_path": str(receipt), "gateway_contract_fields_enforced": False}
        calls.append(result)
        return result

    contract, kwargs, action, _ = setup_lab(output, kernel=kernel)
    lab = ComposedLabBroker(contract, **kwargs)
    outcomes.append({"scenario": "admitted graph and fresh evidence", "result": lab.dispatch(action)})
    lab.clock = lambda: 150
    outcomes.append({"scenario": "evidence expires before next action", "result": lab.dispatch({**action, "action_id": "a2"})})
    lab.export(output/"allowed-and-expired.receipts.json")
    checkpoint = lab.chain.checkpoint
    assert audit_chain(lab.chain.records, checkpoint)
    lab = ComposedLabBroker(contract, **kwargs)
    lab.artifacts["undeclared"] = output/"public.txt"
    outcomes.append({"scenario": "unadmitted attachment", "result": lab.dispatch(action)})
    lab.export(output/"unadmitted.receipts.json")
    model_contract, model_kwargs, model_action, _ = setup_lab(output, kernel=kernel, principal="model")
    model = ComposedLabBroker(model_contract, **model_kwargs)
    outcomes.append({"scenario": "actual HGK model direct access denial", "result": model.dispatch(model_action)})
    model.export(output/"kernel-denied.receipts.json")
    expected = ["completed", "require_more_evidence", "deny", "deny"]
    report = {"schema": "composition-demo/0.1", "kernel_head": head,
              "passed": [o["result"]["decision"] for o in outcomes] == expected and len(calls) == 2,
              "outcomes": outcomes, "kernel_calls": calls, "expected": expected,
              "allowed_chain_checkpoint": checkpoint,
              "limits": ["synthetic authority and source evidence", "lab_in_process_only",
                         "declared subset is not full SBOM", "no install/import path is integrated",
                         "no OS isolation", "no durable replay or budget state",
                         "HGK classifies its existing fixed-read envelope; composition binding remains local"],
              "source_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in Path(__file__).parent.glob("*.py")}}
    for name, value in [("report.json", report), ("contract.json", contract), ("evidence.json", kwargs["cer"])]:
        (output/name).write_text(json.dumps(value, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "scenarios": len(outcomes), "kernel_calls": len(calls),
                      "output": str(output)}, indent=2))
    if not report["passed"]:
        raise RuntimeError("composition expectations failed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kernel-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.kernel_root, args.output)
