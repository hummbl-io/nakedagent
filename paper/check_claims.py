"""Offline paper evidence: source inventory and replay-boundary counterexamples.

Run from the repository root: python paper/check_claims.py
Uses synthetic events, a stub model and stub tool; never loads plugins, calls a
provider, executes a shell tool, or changes runtime source. Temporary logs are
deleted on exit. Passing is evidence about these cases, not a security proof.
"""
from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nakedagent.driver import run_functional
from nakedagent.eventlog import open_log
from nakedagent.functional import AgentEvent, AgentState, agent_reducer
from nakedagent.replay import verify

BASELINE = "0c96f1a8adac035b9d204ebc78c5eb4175c13685"


def make_log(path: Path, events: list[AgentEvent]) -> str:
    system = "Synthetic paper claim check; no external effects."
    policy = {"model": "stub", "workspace": "synthetic", "extra": {}}
    state = AgentState.initial(system, policy=policy)
    writer = open_log(path, system_prompt=system, model="stub", workspace="synthetic", extra={})
    try:
        for event in events:
            state, _ = agent_reducer(state, event)
            writer.write_event(event, state.current_hash())
    finally:
        writer.close(state.step_count, state.current_hash(), state.is_terminal,
                     state.terminal_reason, state.suspended)
    return state.current_hash()


def main() -> int:
    source_paths = sorted((ROOT / "nakedagent").glob("*.py"))
    source_paths += [ROOT / "pyproject.toml"]
    source_matches = {}
    imports: set[str] = set()
    for path in source_paths:
        relative = path.relative_to(ROOT).as_posix()
        data = path.read_bytes()
        archived = subprocess.check_output(
            ["git", "show", f"{BASELINE}:{relative}"], cwd=ROOT)
        # Git stores LF while Windows worktrees may use CRLF.
        normalized = data.replace(b"\r\n", b"\n")
        source_matches[relative] = {
            "sha256_lf": hashlib.sha256(normalized).hexdigest(),
            "matches_baseline": normalized == archived.replace(b"\r\n", b"\n"),
        }
        if path.suffix == ".py":
            for node in ast.walk(ast.parse(data)):
                if isinstance(node, ast.Import):
                    imports.update(n.name.split(".")[0] for n in node.names)
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    imports.add(node.module.split(".")[0])
    external_imports = sorted(imports - sys.stdlib_module_names - {"nakedagent"})
    assert not external_imports, external_imports
    assert all(item["matches_baseline"] for item in source_matches.values())

    events = [AgentEvent("USER_INPUT", "Hello"),
              AgentEvent("MODEL_REPLY", "Hello back"),
              AgentEvent("TERMINATION", "DONE")]
    checks = {}
    with TemporaryDirectory(prefix="nakedagent-paper-") as temp:
        work = Path(temp)
        original = work / "original.jsonl"
        first_hash = make_log(original, events)
        checks["original_accepted"] = verify(original)[0]
        duplicate = work / "duplicate.jsonl"
        checks["same_inputs_same_hash"] = make_log(duplicate, events) == first_hash

        records = [json.loads(x) for x in original.read_text(encoding="utf-8").splitlines()]
        records[2]["payload"] = "Different reply"
        stale = work / "stale.jsonl"
        stale.write_text("".join(json.dumps(x) + "\n" for x in records), encoding="utf-8")
        checks["stale_hash_edit_rejected"] = not verify(stale)[0]

        rewritten = work / "rewritten.jsonl"
        new_hash = make_log(rewritten, [events[0], AgentEvent("MODEL_REPLY", "Different reply"), events[2]])
        checks["coherent_rewrite_accepted"] = verify(rewritten)[0] and new_hash != first_hash

        orphan = work / "orphan.jsonl"
        make_log(orphan, [events[0], AgentEvent("TOOL_RESULT", "Claimed success", {"tool": "write"}), events[2]])
        checks["unrequested_tool_result_accepted"] = verify(orphan)[0]

        truncated = work / "truncated.jsonl"
        truncated.write_text("\n".join(original.read_text(encoding="utf-8").splitlines()[:-1]) + "\n", encoding="utf-8")
        checks["missing_final_rejected"] = not verify(truncated)[0]

        post_terminal = work / "post-terminal.jsonl"
        make_log(post_terminal, events + [AgentEvent("USER_INPUT", "After termination")])
        checks["post_terminal_event_rejected"] = not verify(post_terminal)[0]

        dispatch_counts = {}
        for budget in (2, 3):
            calls: list[str] = []
            def stub_tool(args: str, content: str, workspace: Path, *, _calls=calls) -> str:
                _calls.append(content)
                return "synthetic result"
            def stub_model(*args, **kwargs) -> str:
                return "```probe\nsynthetic request\n```"
            state = run_functional("Hello", "stub", work,
                                   tools={"probe": stub_tool}, llm_fn=stub_model,
                                   max_steps=budget)
            dispatch_counts[str(budget)] = len(calls)
            assert state.step_count == budget and state.is_terminal
        checks["budget_2_dispatches_0_budget_3_dispatches_1"] = dispatch_counts == {"2": 0, "3": 1}

    assert all(checks.values()), checks
    report = {
        "baseline": BASELINE,
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "scope": "synthetic checks; no provider, plugin, shell tool, or benchmark run",
        "external_static_imports": external_imports,
        "source": source_matches,
        "checks": checks,
        "interpretation": "Expected coherent-rewrite and orphan-result acceptance delimit the verifier; they are not authenticated execution evidence.",
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
