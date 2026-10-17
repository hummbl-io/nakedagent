"""One-shot Pilot 2 controller. Runs on Anvil, never inside the guest.

No create retries, no auto-resume, no credential transfer. Provider TTL remains
the backstop if this controller or its host disappears. Actual billing is external.
"""
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

SBX = "C:/Users/Owner/AppData/Local/DockerSandboxes/bin/sbx.exe"
ART = Path("C:/Users/Owner/.codex/artifacts/nakedagent-risk/docker-pilot2-20261003")
SOURCE = Path("C:/Users/Owner/.codex/artifacts/nakedagent-risk/docker-20261003-a/source.tar")
NAME = "nakedagent-p2-soak"
IMAGE = "docker.io/docker/sandbox-templates@sha256:5bbe8539825fe1cace6dda2fb66919ef819324d905bea2795b8516aee0198222"
GUEST = "/home/agent/workspace/nakedagent"
RATE = Decimal("0.00031111")
TTL = 31800
CAP = Decimal("10.00")


def stamp():
    return datetime.now(timezone.utc).isoformat()


def write(name, value):
    tmp = ART / (name + ".tmp")
    tmp.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    tmp.replace(ART / name)


def call(*args, timeout=90, required=True):
    proc = subprocess.run([SBX, "--cloud", *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)
    row = {"at": stamp(), "args": list(args), "returncode": proc.returncode,
           "stdout": proc.stdout, "stderr": proc.stderr}
    with (ART / "controller-commands.jsonl").open("a", encoding="utf-8") as log:
        log.write(json.dumps(row) + "\n")
    if required and proc.returncode:
        raise RuntimeError(f"sbx {args[0]} failed; see command log")
    return proc


def state():
    data = json.loads(call("ls", "--json").stdout)
    return next((item for item in data["sandboxes"] if item["name"] == NAME), None)


def main():
    # Exclusive guard stays in place even on failure. A human-reviewed new pilot
    # is required to retry creation; a crash is never treated as zero spend.
    with (ART / "controller.lock").open("x") as lock:
        lock.write(stamp())
    if hashlib.sha256(SOURCE.read_bytes()).hexdigest() != "9fdda1609cff4395d12de8d83a91b731dad6ca7e9de8a345bd0211903f0408f1":
        raise RuntimeError("source snapshot mismatch")
    preflight = json.loads((ART / "preflight-expiry.json").read_text(encoding="utf-8-sig"))
    short = next(x for x in preflight["sandboxes"] if x["name"] == "nakedagent-p2-preflight")
    if short["status"] != "stopped" or short["image"] != IMAGE:
        raise RuntimeError("preflight was not stopped on the pinned image")
    if RATE * TTL + Decimal("0.05") > CAP:
        raise RuntimeError("reservation exceeds ratified budget")
    billing = json.loads((ART / "billing-baseline.json").read_text())
    if Decimal(billing["available_credit_usd"]) < CAP or Decimal(billing["xl_rate_per_second_usd"]) != RATE:
        raise RuntimeError("billing evidence insufficient or rate differs")
    if state() is not None:
        raise RuntimeError("name already exists; refusing reuse or auto-resume")
    write("admission.json", {"at": stamp(), "cap_usd": str(CAP),
          "preflight_reserve_usd": "0.05", "main_reserve_usd": "9.95",
          "rate_per_second_usd": str(RATE), "ttl_seconds": TTL,
          "ttl_compute_estimate_usd": str(RATE * TTL), "image": IMAGE,
          "model_budget_usd": "0", "workers": 16,
          "billing_evidence": "billing-baseline.json",
          "exceptions": ["policy-log API empty in direct-image preflight despite TLS denial",
                         "runtime budget is not a provider-enforced dollar cap",
                         "no HGK integration; controller enforces this fixed plan"]})
    attempted = False
    terminal = None
    error = None
    try:
        attempted = True
        call("create", "--name", NAME, "--image-ref", IMAGE, "--cpus", "16",
             "--memory", "32g", "--platform", "linux/amd64", "--ttl", "8h50m",
             "--on-timeout", "stop", "--deny-network", "**", timeout=180)
        current = state()
        if (not current or current["status"] != "running" or current["cpus"] != 16
                or current["memory_mib"] != 32768 or current["image"] != IMAGE):
            raise RuntimeError("created resource mismatches admission")
        expiry = datetime.fromisoformat(current["expires_at"].replace("Z", "+00:00"))
        if (expiry - datetime.now(timezone.utc)).total_seconds() > TTL + 10:
            raise RuntimeError("provider expiry exceeds contract")
        write("main-running.json", current)
        policy = call("policy", "ls", NAME).stdout
        if "DENY" not in policy or "**" not in policy:
            raise RuntimeError("deny rule missing")
        call("policy", "log", NAME, "--json")
        call("cp", str(SOURCE), NAME + ":/tmp/source.tar")
        call("exec", NAME, "mkdir", "-p", GUEST)
        call("exec", NAME, "tar", "-xf", "/tmp/source.tar", "-C", GUEST)
        helper = Path(__file__).with_name("soak.py")
        call("cp", str(helper), NAME + ":" + GUEST + "/docs/risk-contract/docker-sandbox/soak.py")
        expected = hashlib.sha256(helper.read_bytes()).hexdigest()
        actual = call("exec", NAME, "sha256sum", GUEST + "/docs/risk-contract/docker-sandbox/soak.py").stdout.split()[0]
        if actual != expected:
            raise RuntimeError("soak helper hash mismatch")
        write("soak-provenance.json", {"sha256": expected, "source": str(helper)})
        probe = call("exec", NAME, "python3", GUEST + "/docs/risk-contract/docker-sandbox/guest_probe.py")
        observed = json.loads(probe.stdout)
        write("main-probes.json", observed)
        if not observed["source_hashes_match"] or any(
                x["connected"] for x in observed["network_probes"] if x["kind"] == "https"):
            raise RuntimeError("source verification or HTTPS denial failed")
        call("exec", NAME, "sh", "-c", f"cd {GUEST} && python3 -m unittest discover -s tests", timeout=120)
        smoke = call("exec", NAME, "python3", GUEST + "/docs/risk-contract/docker-sandbox/smoke.py")
        write("main-smoke.json", json.loads(smoke.stdout))
        if not json.loads(smoke.stdout)["passed"]:
            raise RuntimeError("smoke failure")
        # Leave two minutes for export and stopping before provider expiration.
        seconds = int((expiry - datetime.now(timezone.utc)).total_seconds()) - 120
        if seconds < 60:
            raise RuntimeError("insufficient admitted time remains")
        command = (f"cd {GUEST} && nohup python3 docs/risk-contract/docker-sandbox/soak.py "
                   f"--seconds {seconds} --workers 16 --output /tmp/pilot2-soak "
                   ">/tmp/pilot2-soak.stdout 2>&1 </dev/null &")
        call("exec", NAME, "sh", "-c", command)
        misses = 0
        previous_elapsed = -1
        stagnant = 0
        while datetime.now(timezone.utc) < expiry:
            time.sleep(30)
            if (ART / "STOP").exists():
                error = "operator stop marker"
                break
            current = state()
            if current is None or current["status"] != "running":
                break
            response = call("exec", NAME, "cat", "/tmp/pilot2-soak/summary.json", required=False)
            if response.returncode:
                misses += 1
                if misses >= 3:
                    raise RuntimeError("three consecutive missing checkpoints")
                continue
            latest = json.loads(response.stdout)
            misses = 0
            stagnant = stagnant + 1 if latest["elapsed_seconds"] <= previous_elapsed else 0
            previous_elapsed = latest["elapsed_seconds"]
            if stagnant >= 3:
                raise RuntimeError("guest checkpoint stopped advancing")
            latest["observed_at"] = stamp()
            write("live-summary.json", latest)
            if latest["status"] != "running" or latest["failures"]:
                if latest["failures"]:
                    error = "soak invariant failure"
                break
            if (expiry - datetime.now(timezone.utc)).total_seconds() < 90:
                error = "export margin reached"
                break
    except BaseException as exc:
        error = repr(exc)
    finally:
        if attempted:
            try:
                current = state()
                if current and current["status"] == "running":
                    try:
                        call("cp", NAME + ":/tmp/pilot2-soak", str(ART / "guest-results"), required=False)
                        call("policy", "log", NAME, "--json", required=False)
                    except BaseException as exc:
                        error = f"{error}; export error: {exc!r}"
                if current and current["status"] not in ("stopped", "paused"):
                    call("stop", NAME, required=False)
                until = time.monotonic() + 180
                while time.monotonic() < until:
                    terminal = state()
                    if terminal is None or terminal["status"] in ("stopped", "paused"):
                        break
                    time.sleep(10)
            except BaseException as exc:
                error = f"{error}; shutdown observation error: {exc!r}"
        write("controller-final.json", {"at": stamp(), "state": terminal, "error": error,
              "actual_compute_charge_usd": None, "no_auto_retry": True,
              "billing_reconciliation_required": True})
    return 1 if error else 0


if __name__ == "__main__":
    sys.exit(main())
