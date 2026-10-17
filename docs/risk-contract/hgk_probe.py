"""Lab-only local HGK process bridge. Inputs originate from the trusted demo.

HGK dependencies remain in its interpreter environment, outside nakedagent.
All receipts go to the demo's scratch directory, never HGK's default directory.
"""
import importlib
import json
import sys
from pathlib import Path


def main():
    request = json.loads(sys.stdin.buffer.read(65537).decode("utf-8"))
    root = Path(request["kernel_root"]).resolve()
    sys.path.insert(0, str(root))
    gateway = importlib.import_module("src.gateway.action_gateway")
    action = {
        "actor": request["principal"], "tool": "filesystem.read",
        "requested_action": "Read enrolled public lab fixture",
        "target_paths": [request["fixture"]], "scope": "risk_contract_lab",
        "writes": False, "deletes": False, "network_access": False,
        "owner_instruction_present": False,  # no claim of real owner delegation
        "timestamp": "2026-10-03T00:00:00Z",  # reproducible fixture timestamp
    }
    result = gateway.process_action(action, receipt_output_dir=request["receipt_dir"])
    print(json.dumps({"decision": result.decision, "receipt_path": result.receipt_path}))


if __name__ == "__main__":
    main()
