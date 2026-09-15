# nakedagent vs mini-swe-agent — SWE-bench Lite pilot (2026-09-14)

Hardware: RTX 3080 Ti 12 GB, Docker Desktop (WSL2) VM 3.8 GB RAM, Ollama local.
Model: `gemma3:12b` (no native tool calling in Ollama), temperature 0 where settable.
Instances: SWE-bench Lite test `0:3` — astropy__astropy-12907, -14182, -14365.
Caps: 30 steps, 60 s command timeout, one worker.
nakedagent source: worktree `PROJECTS/nakedagent-basics` (branch
`fix/claude-code/test-isolation-think-license`, uncommitted: think=false, test isolation).

| Config | 12907 | 14182 | 14365 | Patches |
|---|---|---|---|---|
| A1 mini-swe-agent 2.4.6, default (native tools) | BadRequest: model does not support tools | same | same | 0/3 |
| A2 mini-swe-agent, `swebench_backticks.yaml` + `litellm_textbased` | RepeatedFormatError (9 calls) | LimitsExceeded (30 calls) | RepeatedFormatError (11 calls) | 0/3 |
| B nakedagent, bash-only parity | stopped after failed multi-line `sed` (3 turns) | searched wrong file, invalid `sed` regex (9 turns) | found bug, explained, no edit (6 turns) | 0/3 |
| C nakedagent system mode: container `read`/`patch` + empty-diff verifier (3 nudges) | no patch; 17 turns, 3 nudges used, invented `tool_code` tag (69 s) | no patch; 21 turns, 3 nudges, shell only (78 s) | no patch; 12 turns, 3 nudges; model reports `read` attempts failing (48 s) | 0/3 (invalid: harness bug) |
| C2 system mode, placeholder fix | patch, wrong file | patch, broken | patch, plausible fix | 3/3 patches (invalid: CRLF rewrite) |
| C3 system mode, binary write fix | clean 1-hunk patch in `modeling/separable.py` (12 turns, 1 nudge); likely not the upstream fix | no patch (3 nudges) | no patch (3 nudges) | 1/3 patches; **0/3 resolved** |

## Failure modes
- **A1:** Ollama rejects tool-calling requests for gemma3 — agent never starts.
- **A2:** strict "exactly one bash block" format; small model breaks it, agent aborts.
- **B:** fenced format works, but small model cannot author edits through bash
  quoting, and stops at the first failure or after explaining.

- **C (invalid run — harness bug):** the adapter's shell usage example was
  `<a bash command to run in /testbed>`; gemma3 copied the angle brackets, so
  every command was sent as `<cmd>` and bash failed with exit 2. The model never
  saw file contents; `read`/`patch` were never invoked. Fix: concrete usage
  examples + strip a wrapping `<...>`. Rerun as C2. Same placeholder-copy failure
  seen in the hexad plugin; nakedagent's foundation `read`/`patch` usage also
  uses `<...>` placeholders — candidate upstream issue.

- **C2 (placeholder fix; still invalid for scoring — second harness bug):**
  tools used as intended (12907: read 1 / patch 1; 14182: read 6 / patch 6,
  2 nudges; 14365: read 1 / patch 1). Patches 3/3, but the container write used a
  Windows text-mode pipe, converting every `\n` to `\r\n`, so each diff rewrote
  the whole file. Real semantic changes:
  - 14365: `_command_re = r"READ [TS]ERR..."` -> `r"(?i)READ [TS]ERR..."` — plausibly correct.
  - 12907: edited a regex in `io/ascii/qdp.py` — wrong file (bug is in `modeling/separable.py`).
  - 14182: added `self.header_rows = header_rows` with a stray leading `+` — broken.
  Fix: binary stdin for writes. Rerun as C3.

- **C3 (binary write fix):** diffs are now clean. 12907 edited the right file
  (`cright = right` in `_cstack`); 14182 and 14365 produced no patch despite 3
  nudges, although C2 found a plausible 14365 fix. Run-to-run variance is
  expected: **nakedagent's `llm.chat` sends no temperature (Ollama default, not
  0), while mini-swe-agent ran at temperature 0** — a parity gap to close before
  any larger run.

## Scoring (official harness test spec + grader, in pulled instance images)

Scored with `score_preds.py` against `SWE-bench/SWE-bench_Lite` (the swebench>=5
schema; `princeton-nlp/SWE-bench_Lite` lacks `image`/`eval_script`/`log_parser`).

| Run | 12907 | 14182 | 14365 | Resolved |
|---|---|---|---|---|
| C3 | applied; FAIL_TO_PASS 2 still failing (`test_separable[compound_model6/9]`), 7 PASS_TO_PASS regressions | empty | empty | 0/3 |
| C2 | applied; same 2 FAIL_TO_PASS failing | applied; not resolved | applied; `test_roundtrip[True]` still failing, 2 PASS_TO_PASS regressions | 0/3 |

The "plausible" 14365 fix (`(?i)` on the command regex) is incomplete: the
upstream fix also handles lowercase in the roundtrip path.

## Interpretation (pilot, n=3 — not a benchmark claim)
Neither minimal scaffold produces patches from a 12B local model. Failures are
scaffold/format-shaped, not purely capability-shaped — which is what C tests.

## Artifacts
- `mini-gemma3/`, `mini-gemma3-text/`, `naked-gemma3/`, `naked-gemma3-system/` (preds.json + trajectories)
- `run_nakedagent_swebench.py` (adapter; `--mode bash|system`)
- logs: `*.log`
