"""Run nakedagent on SWE-bench instances with parity to mini-swe-agent.

Parity choices: bash-only tool surface (read/write/patch disabled, shell runs
via `docker exec` in the official instance image at /testbed), same model,
temperature from the model default, step cap = 30, 60s command timeout.
Output: <out>/preds.json in the SWE-bench predictions format.

Usage:
  python run_nakedagent_swebench.py --naked-src <nakedagent checkout> \
      --model gemma3:12b --slice 0:3 --out <dir>
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

PROMPT = """You are solving a GitHub issue in the repository at /testbed.

<issue>
{problem}
</issue>

Every shell command runs in /testbed inside a Linux container. Explore the
code, reproduce the issue if practical, and edit the source files to fix it
(use sed, python, or cat heredocs to edit). Do not modify tests.
When the fix is complete, stop making tool calls and reply with a short summary.
"""


def image_name(iid: str) -> str:
    return f"docker.io/swebench/sweb.eval.x86_64.{iid.replace('__', '_1776_')}:latest".lower()


def sh(cmd: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                          encoding="utf-8", errors="replace", check=False)


def make_shell(container: str, timeout: int = 60):
    def docker_shell(args: str, content: str, workspace: Path) -> str:
        cmd = content.strip() or args.strip()
        # Small models copy placeholder brackets: "<cat foo.py>" -> "cat foo.py".
        if cmd.startswith("<") and cmd.endswith(">") and "\n" not in cmd:
            cmd = cmd[1:-1].strip()
        if not cmd:
            return "Error: shell tool got no command."
        try:
            p = sh(["docker", "exec", "-w", "/testbed", container, "bash", "-lc", cmd], timeout=timeout)
        except subprocess.TimeoutExpired:
            return f"Error: command timed out after {timeout}s."
        out = f"(exit {p.returncode})\n{p.stdout}"
        if p.stderr:
            out += f"\n--- stderr ---\n{p.stderr}"
        return out if len(out) <= 8000 else out[:8000] + "\n...[truncated]"

    # Concrete examples, no angle-bracket placeholders (a 12B model copies them literally).
    docker_shell.usage = "```shell\ngrep -rn \"def _line_type\" astropy/io/ascii/\n```"
    return docker_shell


def make_container_file_tools(container: str):
    """System mode: nakedagent's read + patch semantics, executed in the container.

    Small models fail at multi-line sed quoting; exact SEARCH/REPLACE avoids it.
    """
    from nakedagent.tools import _split_search_replace

    def _path(args: str) -> str:
        p = args.strip()
        return p if p.startswith("/") else f"/testbed/{p}"

    def c_read(args: str, content: str, workspace: Path) -> str:
        if not args.strip():
            return "Error: read needs a path, e.g. ```read astropy/io/ascii/qdp.py```"
        p = sh(["docker", "exec", container, "cat", _path(args)])
        if p.returncode != 0:
            return f"Error: {p.stderr.strip()[:300]}"
        return p.stdout if len(p.stdout) <= 8000 else p.stdout[:8000] + "\n...[truncated; use shell with sed -n 'A,Bp' for more]"

    def c_patch(args: str, content: str, workspace: Path) -> str:
        path = _path(args)
        try:
            search, replace = _split_search_replace(content)
        except ValueError as e:
            return f"Error: malformed patch block ({e})."
        p = sh(["docker", "exec", container, "cat", path])
        if p.returncode != 0:
            return f"Error: {p.stderr.strip()[:300]}"
        n = p.stdout.count(search)
        if n != 1:
            return (f"Error: SEARCH text matches {n} locations in {args.strip()}; "
                    "read the file and copy the exact lines.")
        new = p.stdout.replace(search, replace, 1)
        # Binary stdin: text-mode pipes on Windows turn "\n" into "\r\n", which
        # rewrote every line of the file and produced whole-file diffs.
        w = subprocess.run(["docker", "exec", "-i", container, "bash", "-c", f"cat > '{path}'"],  # nosec B603 B607 -- docker on PATH is the bench contract, fixed argv
                           input=new.encode("utf-8"), capture_output=True, timeout=60, check=False)
        return (f"Patched {args.strip()}." if w.returncode == 0
                else f"Error: write failed: {w.stderr.decode('utf-8', 'replace')[:300]}")

    c_read.usage = "```read astropy/io/ascii/qdp.py\n```"
    c_patch.usage = (
        "```patch astropy/io/ascii/qdp.py\n"
        "<<<<<<< SEARCH\n"
        "    x = old_value\n"
        "=======\n"
        "    x = new_value\n"
        ">>>>>>> REPLACE\n"
        "```\n"
        "(Paths are relative to /testbed. SEARCH must copy existing lines exactly.)"
    )
    return {"read": c_read, "patch": c_patch}


NUDGE = ("[verifier] `git diff` in /testbed is still empty: no source change has been made. "
         "The task is not done. Use `read` to view the relevant code and `patch` to edit it, "
         "then stop.")


def _parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--naked-src", required=True)
    ap.add_argument("--model", default="gemma3:12b")
    ap.add_argument("--subset", default="princeton-nlp/SWE-bench_Lite")
    ap.add_argument("--revision", default="6ec7bb89b9342f664a54a6e0a6ea6501d3437cc2",
                    help="dataset revision (pin for reproducibility)")
    ap.add_argument("--split", default="test")
    ap.add_argument("--slice", default="0:3")
    ap.add_argument("--steps", type=int, default=30)
    ap.add_argument("--out", required=True)
    ap.add_argument("--mode", choices=["bash", "system"], default="bash",
                    help="bash: parity with mini-swe-agent; system: container read/patch + diff verifier")
    ap.add_argument("--nudges", type=int, default=3)
    return ap.parse_args()


def _nudge_loop(name, a, ws, messages, tools, loop) -> tuple[str, int]:
    """Run the agent, optionally nudging until a diff appears. Returns (status, nudges_used)."""
    status = "ok"
    nudges_used = 0
    try:
        loop._run_until_done(messages, a.model, ws, loop.DEFAULT_HOST, tools=tools)
        while a.mode == "system" and nudges_used < a.nudges:
            if sh(["docker", "exec", "-w", "/testbed", name, "git", "diff"]).stdout.strip():
                break
            nudges_used += 1
            print(f"--- verifier nudge {nudges_used}/{a.nudges} ---", flush=True)
            messages.append({"role": "user", "content": NUDGE})
            loop._run_until_done(messages, a.model, ws, loop.DEFAULT_HOST, tools=tools)
    except (OSError, ValueError, TypeError, RuntimeError, KeyError, AttributeError, IndexError) as e:  # record, still collect whatever diff exists
        status = f"error: {type(e).__name__}: {e}"
    return status, nudges_used


def _run_instance(row, a, out, ws, preds, preds_path, loop):
    iid = row["instance_id"]
    if iid in preds:
        print(f"skip {iid} (done)")
        return
    name = f"naked-{iid.replace('__', '-')}-{int(time.time())}"
    print(f"=== {iid}: pulling/starting {image_name(iid)}", flush=True)
    t0 = time.time()
    r = sh(["docker", "run", "-d", "--name", name, image_name(iid), "sleep", "infinity"], timeout=1800)
    if r.returncode != 0:
        print(f"container start failed: {r.stderr[:500]}")
        return
    try:
        tools = {"shell": make_shell(name)}
        if a.mode == "system":
            tools.update(make_container_file_tools(name))
        messages = [
            {"role": "system", "content": loop._system_prompt(tools)},
            {"role": "user", "content": PROMPT.format(problem=row["problem_statement"])},
        ]
        status, nudges_used = _nudge_loop(name, a, ws, messages, tools, loop)
        diff = sh(["docker", "exec", "-w", "/testbed", name, "git", "diff"]).stdout
        turns = sum(1 for m in messages if m["role"] == "assistant")
        preds[iid] = {"instance_id": iid, "model_name_or_path": f"nakedagent/{a.model}",
                      "model_patch": diff}
        (out / f"{iid}.traj.json").write_text(json.dumps(
            {"status": status, "mode": a.mode, "nudges_used": nudges_used,
             "turns": turns, "elapsed_s": round(time.time() - t0, 1),
             "messages": messages}, indent=1), encoding="utf-8")
        preds_path.write_text(json.dumps(preds, indent=1), encoding="utf-8")
        print(f"=== {iid}: {status}, turns={turns}, patch_chars={len(diff)}, "
              f"{time.time() - t0:.0f}s", flush=True)
    finally:
        sh(["docker", "rm", "-f", name])


def main() -> int:
    a = _parse_args()

    sys.path.insert(0, a.naked_src)
    from datasets import load_dataset

    from nakedagent import loop
    lo, hi = (int(x) for x in a.slice.split(":"))
    rows = load_dataset(a.subset, split=a.split, revision=a.revision).select(range(lo, hi))

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    # preds.json is a dict keyed by instance_id (makes resume/skip trivial), not
    # SWE-bench's list-of-predictions format; score_preds.py accepts both.
    preds_path = out / "preds.json"
    preds = json.loads(preds_path.read_text()) if preds_path.exists() else {}
    loop.MAX_STEPS = a.steps
    ws = out / "_ws"
    ws.mkdir(exist_ok=True)

    for row in rows:
        _run_instance(row, a, out, ws, preds, preds_path, loop)
    return 0


if __name__ == "__main__":
    sys.exit(main())
