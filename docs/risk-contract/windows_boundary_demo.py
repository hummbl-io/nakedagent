"""Windows fixed-worker experiment: OS denial versus brokered public-fixture read.

Creates only a new output tree. ACL changes are confined to that tree. Does not
launch arbitrary plugins, change accounts/host policy, or install dependencies.
"""
import argparse
import hashlib
import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

from composition import ComposedLabBroker
from durable_reservations import Reservations, dispatch_reserved
from kernel_demo import PINNED_HEAD
from test_composition import setup_lab


def run(output, kernel_root):
    if sys.platform != "win32":
        raise RuntimeError("Windows required")
    output, kernel_root = output.resolve(), kernel_root.resolve()
    head = subprocess.check_output(["git", "-C", str(kernel_root), "rev-parse", "HEAD"], text=True).strip()
    if head != PINNED_HEAD:
        raise ValueError("review changed HGK HEAD before repinning")
    if subprocess.check_output(["git", "-C", str(kernel_root), "status", "--porcelain", "--untracked-files=no"], text=True).strip():
        raise ValueError("HGK tracked tree dirty")
    output.mkdir(parents=True, exist_ok=False)
    private = output / "private"
    private.mkdir()
    system = Path(os.environ["SystemRoot"])
    env = {"SystemRoot": str(system), "WINDIR": str(system), "TEMP": str(output), "TMP": str(output)}
    compiler = system / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    source = Path(__file__).with_name("WindowsBoundary.cs")
    exe = output / "WindowsBoundary.exe"
    compile_result = subprocess.run([str(compiler), "/nologo", "/platform:x64", "/target:exe",
                                     "/out:" + str(exe), str(source)], capture_output=True, text=True,
                                    timeout=30, env=env, check=False)
    if compile_result.returncode:
        raise RuntimeError(compile_result.stdout + compile_result.stderr)
    llvm = Path("C:/Program Files/LLVM/bin")
    probe_source = Path(__file__).with_name("windows_probe.c")
    subprocess.run([str(llvm/"clang.exe"), "--target=x86_64-pc-windows-msvc", "-fno-stack-protector",
                    "-Wall", "-Wextra", "-Werror", "-c", str(probe_source), "-o", str(output/"probe.obj")],
                   check=True, capture_output=True, timeout=30, env=env)
    subprocess.run([str(llvm/"lld-link.exe"), "/entry:mainCRTStartup", "/subsystem:console", "/nodefaultlib",
                    "/out:"+str(output/"windows_probe.exe"), str(output/"probe.obj"),
                    "C:/Program Files (x86)/Windows Kits/10/Lib/10.0.19041.0/um/x64/kernel32.lib"],
                   check=True, capture_output=True, timeout=30, env=env)
    calls = []

    def kernel(action):
        request = {"kernel_root": str(kernel_root), "principal": action["principal"],
                   "fixture": str(private/"public.txt"), "receipt_dir": str(output/"hgk-receipts")}
        proc = subprocess.run([sys.executable, "-I", str(Path(__file__).with_name("hgk_probe.py"))],
                              input=json.dumps(request).encode(), capture_output=True, timeout=20, check=True)
        response = json.loads(proc.stdout)
        path = Path(response["receipt_path"]).resolve()
        if not path.is_relative_to(output):
            raise ValueError("unexpected receipt path")
        calls.append(response)
        return {**response["decision"], "receipt_path": str(path),
                "receipt_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    contract, kwargs, action, _ = setup_lab(output, kernel=kernel)
    kwargs["fixture"].rename(private/"public.txt")
    kwargs["fixture"] = private/"public.txt"
    lab = ComposedLabBroker(contract, **kwargs)
    state_path = output/"reservations.sqlite"
    store = Reservations(state_path, contract, create=True)
    transcript, outcomes = [], []
    messages = queue.Queue()
    process = subprocess.Popen([str(exe), "launch", str(output)], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env,
                               creationflags=subprocess.CREATE_NO_WINDOW)

    def collect():
        for line in process.stdout:
            messages.put(line.rstrip("\n"))
        messages.put(None)

    reader = threading.Thread(target=collect, daemon=True)
    reader.start()
    try:
        while True:
            line = messages.get(timeout=30)
            if line is None:
                break
            transcript.append(line)
            if not line.startswith("REQUEST|"):
                continue
            case = line.split("|", 1)[1]
            candidate = dict(action)
            if case == "replay":
                # Fresh coordinator objects: in-memory replay/budget state is gone.
                lab.export(output/"before-reopen.receipts.json")
                previous_checkpoint = lab.chain.checkpoint
                lab = ComposedLabBroker(contract, **kwargs)
                store = Reservations(state_path, contract)
                lab.chain.append("coordinator-reopened", {"prior_checkpoint": previous_checkpoint,
                                                         "persistent_binding": store.binding})
            elif case == "expired":
                lab.clock = lambda: 150
                candidate["action_id"] = "expired"
            elif case == "revoked":
                store.revoke()
                store = Reservations(state_path, contract)
                candidate["action_id"] = "revoked"
            elif case == "budget":
                candidate["action_id"] = "over-budget"
            elif case == "wrong-resource":
                candidate.update(action_id="wrong", resource="lab:not-enrolled")
            elif case != "allowed":
                raise ValueError("unexpected request")
            result = dispatch_reserved(store, lab, candidate)
            outcomes.append({"scenario": case, "result": result})
            # Only operation result metadata crosses the pipe, no credentials or file handles.
            process.stdin.write(json.dumps(result, separators=(",", ":")) + "\n")
            process.stdin.flush()
        returncode = process.wait(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()  # closing the launcher's job handle terminates its worker
            process.wait(timeout=5)
        process.stdin.close()
        reader.join(timeout=5)
        process.stdout.close()
    expected = ["completed", "deny", "require_more_evidence", "deny", "deny", "deny"]
    checks = {"child_token_low_integrity": any(x.startswith("TOKEN|low_integrity=true|") for x in transcript),
              "direct_read_access_denied": "DIRECT|5" in transcript,
              "fixture_write_dac_denied": "WRITE_DAC|5" in transcript,
              "private_directory_delete_denied": "DIR_DELETE|5" in transcript,
              "worker_state_write_denied": "STATE_WRITE|5" in transcript,
              "direct_read_still_denied_after_broker": "DIRECT_AFTER|5" in transcript,
              "worker_clean_exit": "EXIT|0" in transcript and returncode == 0,
              "broker_outcomes": [o["result"]["decision"] for o in outcomes] == expected,
              "one_real_hgk_call": len(calls) == 1,
              "responses_reached_worker": sum(x.startswith("RESPONSE|") for x in transcript) == 6,
              "reopened_state_keeps_two_reservations": store.snapshot()["spent_reservations"] == 2,
              "reopened_state_keeps_revocation": store.snapshot()["revoked"]}
    report = {"passed": all(checks.values()), "checks": checks, "outcomes": outcomes,
              "transcript": transcript, "kernel_head": head, "kernel_calls": calls,
              "fixture_sha256": kwargs["fixture_sha256"],
              "launcher_source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
              "launcher_executable_sha256": hashlib.sha256(exe.read_bytes()).hexdigest(),
              "probe_source_sha256": hashlib.sha256(probe_source.read_bytes()).hexdigest(),
              "probe_executable_sha256": hashlib.sha256((output/"windows_probe.exe").read_bytes()).hexdigest(),
              "source_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in Path(__file__).parent.glob("*.py")},
              "state": store.snapshot(),
              "limitations": ["fixed cooperative native worker only; not arbitrary code isolation",
                              "MIC labels protect enrolled objects, not a global filesystem/network allowlist",
                              "private desktop; no GUI escape testing",
                              "synthetic authority/evidence/clock", "revocation gates new reservations; not in-flight cancellation",
                              "responses contain read outcome metadata, not raw file content",
                              "no installer/import isolation or credentials tested"]}
    lab.export(output/"composition.receipts.json")
    (output/"report.json").write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "checks": checks, "output": str(output)}, indent=2))
    if not report["passed"]:
        print(json.dumps(transcript, indent=2))
        raise RuntimeError("boundary acceptance failed; no production claim")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--kernel-root", type=Path, required=True)
    args = parser.parse_args()
    run(args.output, args.kernel_root)
