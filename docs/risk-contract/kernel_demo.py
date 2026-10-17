"""Run a bounded, local HGK admission experiment against public scratch data.

Synthetic owner-grant/evidence setup; real local gateway decisions and fixture
reads. No nakedagent launch, plugin loading, provider calls or OS containment.
"""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from admission_pilot import LabBroker, Observation
from contract import VERSION, digest, validate

PINNED_HEAD = "4e7a06359eae81b3c48f2a57cd82c5fca7e0bf40"


def run(root, output):
    root, output = root.resolve(), output.resolve()
    head = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    if head != PINNED_HEAD:
        raise ValueError("HGK head changed: review before updating pin")
    if subprocess.check_output(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"], text=True).strip():
        raise ValueError("HGK tracked tree dirty: review exact source first")
    output.mkdir(parents=True, exist_ok=False)
    fixture = output / "public.txt"
    fixture.write_bytes(b"HUMMBL public lab fixture\n")
    # Include selected gateway implementation and policy inputs, not a complete SBOM.
    names = ["src/gateway/action_gateway.py", "src/gateway/proposal_adapter.py",
             "src/policy/classifier.py", "src/policy/registry.py",
             "src/policy/runtime_profile.py", "registries/policies/epistemic_calibration.yaml"]
    artifacts = {"hgk/" + name: root / name for name in names}
    artifacts.update({"pilot/" + name: Path(__file__).with_name(name)
                      for name in ["contract.py", "admission_pilot.py", "hgk_probe.py"]})
    components = [{"id": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "dependencies": []}
                  for name, path in artifacts.items()]
    config_hash = digest({"profile": "lab-fixed-read", "network": False, "plugins": False})
    graph_hash = digest({"root": "lab-worker", "edges": [["lab-worker", "lab:public-fixture"]]})
    policy_hash = next(c["sha256"] for c in components if c["id"].endswith("epistemic_calibration.yaml"))
    probe_calls = []
    def broker(principal="lab-worker"):
        contract = {"schema": VERSION, "run_id": "public-fixture-pilot", "principal": principal,
                    "policy_sha256": policy_hash, "configuration_sha256": config_hash,
                    "dependency_graph_sha256": graph_hash, "components": components,
                    "grants": [{"operation": "read_fixture", "resource": "lab:public-fixture"}],
                    "required_evidence": ["fixture-enrollment"], "max_actions": 1, "expires_at": 200}
        validate(contract)
        def kernel(action):
            request = {"kernel_root": str(root), "principal": action["principal"],
                       "fixture": str(fixture), "receipt_dir": str(output / "hgk-receipts")}
            proc = subprocess.run([sys.executable, "-I", str(Path(__file__).with_name("hgk_probe.py"))],
                                  input=json.dumps(request).encode("utf-8"), capture_output=True, timeout=20, check=False)
            if proc.returncode:
                raise RuntimeError("HGK lab probe failed: " + proc.stderr.decode("utf-8", errors="replace")[:1000])
            response = json.loads(proc.stdout)
            probe_calls.append(response)
            return response["decision"]
        lab = LabBroker(contract, owner_grant_sha256=digest(contract), fixture=fixture,
                        fixture_sha256=hashlib.sha256(fixture.read_bytes()).hexdigest(),
                        artifacts=artifacts, configuration_sha256=config_hash, graph_sha256=graph_hash,
                        observations={"fixture-enrollment": Observation(90, 150, config_hash, "verified")},
                        kernel=kernel, clock=lambda: 100)
        action = {"action_id": "action-1", "run_id": contract["run_id"], "principal": principal,
                  "contract_sha256": digest(contract), "operation": "read_fixture", "resource": "lab:public-fixture"}
        return lab, action
    results = []
    lab, action = broker()
    (output / "contract.json").write_text(json.dumps(lab.contract, indent=2) + "\n", encoding="utf-8")
    results.append({"scenario": "allowed fixed read", "result": lab.dispatch(action)})
    results.append({"scenario": "replayed action", "result": lab.dispatch(action)})
    results.append({"scenario": "spent budget", "result": lab.dispatch({**action, "action_id": "action-2"})})
    lab, action = broker("model")
    results.append({"scenario": "HGK model direct access denial", "result": lab.dispatch(action)})
    lab, action = broker()
    lab.clock = lambda: 150
    results.append({"scenario": "expired evidence", "result": lab.dispatch(action)})
    lab, action = broker()
    lab.artifacts["unadmitted-plugin"] = fixture
    results.append({"scenario": "new attachment", "result": lab.dispatch(action)})
    expected = ["completed", "deny", "deny", "deny", "require_more_evidence", "deny"]
    actual = [r["result"]["decision"] for r in results]
    report = {"mode": "local lab with synthetic authority/evidence", "kernel_head": head,
              "scope": "fixed public fixture only; not production integration or OS isolation",
              "kernel_calls": probe_calls, "scenarios": results, "expected": expected,
              "passed": actual == expected and len(probe_calls) == 2,
              "dependencies_complete": False,
              "durable_broker_receipts": False, "runtime_sensors_connected": False}
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "scenarios": len(results), "kernel_calls": len(probe_calls),
                      "output": str(output)}, indent=2))
    if not report["passed"]:
        raise RuntimeError("pilot did not meet expected outcomes; inspect report")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kernel-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="new directory, never overwritten")
    args = parser.parse_args()
    run(args.kernel_root, args.output)
