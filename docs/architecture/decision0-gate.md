# Decision-0 gate

`Decision0NoulGate` (in `nakedagent/providers_draft.py`) lets the Sidekick harness ask
[HUMMBL Decision-0](https://huggingface.co/hummbl-hf/decision-0) whether a proposed tool call may go
ahead. Decision-0 is a small classifier (about 71 million parameters) that reads a policy, evidence, a
task and a proposed action and answers allow, deny or escalate. It maps onto the harness's tri-state
gate: allow → `ALLOW`, deny → `BLOCK`, escalate → `ESCALATE`.

Decision-0 needs torch and transformers, so it never runs inside nakedagent. The gate scores each case
in a subprocess, under a Python you choose, using the model's own released `decide.py`. nakedagent
itself stays stdlib-only.

## Use

```python
from pathlib import Path
from nakedagent.providers_draft import Decision0NoulGate
from nakedagent.sidekick import SidekickHarness

gate = Decision0NoulGate(
    decide_py="/models/decision-0/decide.py",  # from a downloaded release, e.g. tag v0.1.1
    model="/models/decision-0",                 # the same local snapshot, so the version is pinned
    python="/venvs/torch/bin/python",           # has torch + transformers
)
harness = SidekickHarness(Path("."), provider, noul_gate=gate)

gate.task = user_request      # the harness passes the gate only the action, so set the task each turn
state = harness.run_turn(user_request)
```

Put the policy the agent works under in `<workspace>/.nakedagent/policy.md`, and optional evidence
(approvals, ticket numbers) in `<workspace>/.nakedagent/evidence.md`. `decide_py` and `python` can also
come from `NAKEDAGENT_DECISION0_DECIDE_PY` and `NAKEDAGENT_DECISION0_PYTHON`.

## Routing

| Situation | Route |
|---|---|
| The default destructive-pattern tripwire matches | `BLOCK`, before the model is asked |
| No policy file | `ESCALATE`: there is nothing to judge the action against |
| `gate.task` not set | `ESCALATE`: the model would judge the action without the request it serves |
| Policy, evidence, task and action together over `max_input_chars` (1000) | `ESCALATE`, without starting the model |
| The input pair is over the model's 192-token window (counted exactly with its tokenizer) | `ESCALATE`: the model would have judged a cut-off case, so its answer is not used |
| Decision-0 deny | `BLOCK` |
| Decision-0 escalate | `ESCALATE` |
| Decision-0 allow with allow score ≥ `allow_threshold` (0.99) | `ALLOW` |
| Decision-0 allow below the threshold | `ESCALATE` |
| The scorer fails, times out or replies in an unexpected shape | `BLOCK` with risk -1.0 (fail-closed) |

When the model is consulted, the risk recorded in the ledger is 1 minus its allow score. The checks
that escalate without the model record 1.0, and fail-closed blocks record -1.0.

The 192-token window covers all four fields together, so a long policy uses up most of it. Dense text
(paths, digits, URLs) can take a token for every one or two characters: in one test a 739-character policy
made a 466-token input. The character limit is only a cheap first check; the exact token count decides.

The case reaches the scorer as JSON on standard input, never on the command line.

## Limits

- **Advisory.** On Decision-0's sealed test it wrongly allowed 4 of 335 actions that should not have
  gone ahead (1.2%) at the strict threshold. Keep a person on the `ESCALATE` path, and use the gate only
  where a wrong allow is cheap to undo.
- **Slow.** Each check starts a new process and loads the model. In one live run on a laptop CPU that
  took about 25 seconds per action; a single decision takes about 72 ms once the model is loaded. A
  long-running scorer process would remove most of that; it is not built yet.
- **Short policies only.** Anything that does not fit in 192 tokens escalates, so a long policy file
  escalates every action. Keep the policy to the rules that matter for the agent's work.
- **Over-cautious on some permitted actions.** In the same live run, "run the test suite" under a policy
  that permits it was escalated (allow score 0.92).
