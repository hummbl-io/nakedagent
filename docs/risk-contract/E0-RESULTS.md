# E0: a bounded permission-to-effect loop

Date: 2026-10-03. Implemented and locally exercised; independent review pending.
This is a cooperative simulation, not a production integration or containment certification.

## Run it

From the nakedagent repository root, on stock Python:

```powershell
python -m unittest discover -s docs/risk-contract -p test_e0.py -v
python docs/risk-contract/e0.py --output e0-report.json
```

The output path must not already exist. The runner creates one JSON record;
the nine tests also cover boundary behavior beyond the eight scripted conditions.
No third-party package, model, network service, or paid compute is required for E0.

Implementation: `e0.py`. Checks: `test_e0.py`. Prerecorded acceptance criteria:
`ONE-LAB-FIRST-EXPERIMENT.md`. The original plan remains a proposal for the wider
program; this report records completion of its local E0 implementation only.

## Observations

Every condition starts at x=5, receives the same scripted disturbance to x=2,
and uses the same controller. Normal proposals move one unit toward five.
The replay and malformed cases deliberately alter delivery at the test boundary.
Each condition has three attempted requests at logical ticks 1, 2, and 3.

| Condition | Final x | Effects | Refusals | Result |
|---|---:|---:|---:|---|
| No grant | 2 | 0 | 3 | Pass |
| Valid grant | 5 | 3 | 0 | Pass |
| Revoke after first effect | 3 | 1 | 2 | Pass |
| Expired at tick 1 | 2 | 0 | 3 | Pass |
| Two-action budget | 4 | 2 | 1 | Pass |
| Same accepted request replayed twice | 3 | 1 | 2 | Pass |
| Stale state, wrong action, boolean delta | 2 | 0 | 3 | Pass |
| Missing authority evidence | 2 | 0 | 3 | Pass |

The valid condition first reaches its target at tick 3. Across these cases:
24 attempts, seven effects, 17 refusals, seven reserved and consumed action
units, and zero effects after revocation. These are simulated units, not dollars.

Validation on Anvil: nine focused unittest tests passed; the existing 234-test
repository suite passed. The latter emitted ResourceWarnings from HTTP-error
fixtures; its exit status was zero. No production source was changed.

Local run record:
`C:/Users/Owner/.codex/artifacts/nakedagent-risk/e0-20261003/report.json`.
It includes content hashes of implementation, tests, and original plan; Python
version; expected outcomes; actual decisions; reservations; state versions; and
an ordered event trace. Preserve this record outside the governance repository.

## What the logic establishes

Let x be the state, v its version, and u the consumed action budget. For a
well-formed, bound request, admission requires a present, unrevoked, unexpired
grant, required evidence, remaining budget, matching state version, and an
effect that stays in [0,10]. Denial preserves (x,v,u). Admission changes it to
(x+delta,v+1,u+1), and records the accepted request identity.

The controller's error is |5-x|. Starting from x=2, each permitted controller
action reduces that error by one. A three-action grant therefore suffices for
recovery. The broker does not derive authority from the desirability of recovery:
without permission it leaves the state unchanged, even when error remains.

Within one broker lifetime, a repeated accepted sequence cannot produce another
effect. A changed payload using that sequence is refused as a collision.
Reattachment is refused, so it cannot reset budget or revocation. The trusted
supervisor controls a monotonic clock; request data cannot supply its own time.
An additional test creates a proposal, then revokes permission before dispatch,
and confirms that execution uses current authority.

These invariants follow from the guarded transition in the implementation and
are exercised by the tests. This is not an exhaustive formal verification of
Python or every possible input. Request inputs in this experiment are ordinary
in-memory, JSON-compatible data; there is no exposed transport or deserializer.

## Deliberate limits and next boundary

The supervisor, broker, grant evidence, and receipt writer are trusted parts of
one process. A malicious Python controller could bypass this convention and
mutate memory. Reservations and effects are sequential operations, not a
crash-safe transaction; replay history disappears with the broker. A hash binds
bytes and does not authenticate the author or prove that an observation is true.
The record format remains a draft, without a RO-Crate compliance claim.

The existing HGK fixed-fixture broker and SQLite reservation ledger were
inspected. They address different effect and durability boundaries. E0 does not
wrap or generalize them merely to share code: doing so would add dependencies
and obscure the particular claim tested here. Their integration remains work.

The next experiment should preserve these acceptance cases while putting the
controller in a separate process and the actuator behind the existing admitted
broker. It must attempt direct effects and verify their refusal, then test
concurrent requests, revocation races, and crash recovery separately. Passing
E0 does not establish those properties. Docker Pilot 2 is unrelated soak
evidence and contributes no validation to these claims.
