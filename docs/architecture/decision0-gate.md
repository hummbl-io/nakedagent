# Decision-0 gate

`Decision0NoulGate` (in `nakedagent/providers_draft.py`) lets the Sidekick harness ask
[HUMMBL Decision-0](https://huggingface.co/hummbl-hf/decision-0) whether a proposed tool call may go
ahead. Decision-0 is a small classifier (about 71 million parameters) that reads a policy, evidence, a
task and a proposed action and answers allow, deny or escalate. It maps onto the harness's tri-state
gate: allow → `ALLOW`, deny → `BLOCK`, escalate → `ESCALATE`.

Decision-0 needs torch and transformers, so it never runs inside nakedagent. The gate runs the
model's own released `decide.py` in a subprocess, under a Python you choose. nakedagent itself stays
stdlib-only.

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
| Action text longer than `max_action_chars` (600) | `ESCALATE`: Decision-0 reads at most 192 tokens and would judge a cut-off action |
| Decision-0 deny | `BLOCK` |
| Decision-0 escalate | `ESCALATE` |
| Decision-0 allow with allow score ≥ `allow_threshold` (0.99) | `ALLOW` |
| Decision-0 allow below the threshold | `ESCALATE` |
| `decide.py` fails, times out or replies in an unexpected shape | `BLOCK` with risk -1.0 (fail-closed) |

The risk recorded in the ledger is 1 minus Decision-0's allow score.

## Limits

- **Advisory.** On Decision-0's sealed test it wrongly allowed 4 of 335 actions that should not have
  gone ahead (1.2%) at the strict threshold. Keep a person on the `ESCALATE` path, and use the gate only
  where a wrong allow is cheap to undo.
- **Slow.** Each check starts a new process and loads the model: about 25 seconds per action on a
  laptop CPU (one decision takes about 72 ms once the model is loaded). A long-running scorer process
  would remove most of that; it is not built yet.
- **Over-cautious on some permitted actions.** In a live check, "run the test suite" under a policy that
  permits it was escalated (allow score 0.92).
