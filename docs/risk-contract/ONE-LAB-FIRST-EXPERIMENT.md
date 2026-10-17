# One Lab: first experiment and market hypothesis

Date: 2026-10-03. Author: codex. Status: proposed experiment, not a release,
implemented integration, novelty claim, or authorization for new spending.

## Strategic choice

Keep diverse agency as the research scope. Start with a narrow practical use:
help an operator determine what changes when a capability is attached to an
agent, and verify that revocation prevents subsequent effects.

The agent need not use language, resemble a person, or contain a neural network.
The existing nakedagent repository is a terminal coding agent. This experiment
is a separate laboratory specimen; it does not silently redefine that product.
One Lab is a working concept name. Andrew Alliance already markets OneLab
laboratory software; distinct public naming remains unresolved.

Candidate user: a fleet operator admitting tools and dependencies. Candidate
value: one reviewable record connecting authority, attempted actions, actual
effects, and uncertainty. Neither customer demand nor willingness to pay is
validated yet.

## E0: bounded regulation with one attachable actuator

Use a deterministic simulated environment with one integer variable x in
[0, 10], initially 5. Target x=5. A controller observes x and requests the
single action `adjust(delta)`, where delta is -1 or +1 toward the target.
The actuator is the attached capability. At the target the controller requests
no action. The environment applies a scripted disturbance to x=2.

The broker owns the environment state. The controller proposes actions only.
Each request must bind experiment ID, grant ID/version, action, delta, sequence
number, and the expected state version. The broker validates authority at
execution, atomically reserves one action unit, applies the effect, and records
the resulting state. Record attempts separately from effects.

Use a logical clock for reproducibility. Initial grant allows three successful
adjustments, expires at tick 20, and permits no other effect. Empty authority is
the starting state. An experiment supervisor, outside the tested controller,
attaches or revokes the grant according to the script.

The first implementation may demonstrate these semantics in one process, but
must label that as cooperative simulation. Process separation and the existing
HGK/Windows broker must be tested separately before claiming containment.
No network, shell, real actuator, secrets, model calls, or paid compute are
needed for E0. Resource units are simulated actions, not currency.

## Paired conditions and acceptance criteria

Run each condition from an identical reset; preserve the controller and
disturbance, changing only the stated intervention.

| Condition | Expected observation |
|---|---|
| No grant | Requests are refused; x remains 2 after disturbance |
| Valid attached grant | Three accepted actions restore x from 2 to 5 |
| Revoke after first accepted action | x reaches 3; every subsequent requested adjustment is refused |
| Expired grant | No state mutation after expiry |
| Budget of two actions | x reaches 4; further requests are refused |
| Replayed request ID | At most one effect for that ID; replay is explicitly reported |
| Stale state version or malformed action | No mutation; explicit refusal reason |
| Missing required authority evidence | No mutation; unknown is not treated as permission |

Measures: absolute target error per tick, accepted effects, refused attempts,
action units reserved/consumed, first recovery tick, and post-revocation effects.
Success is both observed recovery when permitted and observed refusal when
not permitted. Failure to restore the target under revoked authority is the
expected contract outcome, not a controller malfunction.

Revocation takes effect at the broker's recorded decision boundary. A request
already committed before that boundary is not retroactively undone. Concurrent
execution and crashes require later transactional tests; do not infer those
guarantees from a deterministic single-thread run.

## Experiment record v0.1, proposed

Record specimen and environment identifiers; source revision/content hashes;
target and observation units; controller rule; disturbance schedule; clock and
seed where applicable; authority provenance; grant changes; each request,
decision, reservation and effect; acceptance criteria fixed before the run;
results; missing evidence; and reviewer findings.

Keep observations separate from derived judgments. Keep author interpretation
separate from independent review. A hash establishes byte identity; an unsigned
hash chain does not establish truthful observations or trusted authorship.

Map exported records to Workflow Run RO-Crate where appropriate. Do not present
a custom JSON file as compliant until a documented mapping and validation exist.

## Comparative experiment, before product claims

1. Implement E0 with standard-library Python and inspect its actual effects.
2. Represent the same conditions in Inspect; assess what requires extensions.
3. Map environment interactions to Gymnasium semantics without making an RL
   training algorithm mandatory.
4. Compare the evidence/review workflow with Braintrust or LangSmith using
   documentation first. Any account, upload, installation or paid trial is a
   separate action; no trial is initiated by this plan.
5. Compare capability-composition checks with Invariant's policy/data-flow work.

Use the same cases and report omissions. Measure setup steps/time, reproducible
results, missed violations, false refusals, and independent reviewer time to
locate supporting evidence. Define improvement thresholds before collecting
comparative results; no arbitrary superiority threshold is established here.

If existing tools cover the workflow well, build an adapter and reusable
experiment package instead of another general evaluation platform. Continue
standalone product work only if a repeatable operator need and measurable
advantage emerge. Cross-substrate applicability remains a hypothesis until
additional, materially different specimens are tested.

## Relationship to existing work

- E0 gives the contract and broker a small, falsifiable use case.
- The One Lab map's dataset/view separation applies to experiment records:
  timeline, dependency graph and dashboard can view the same evidence.
- Perspective-first learning suggests independent accounts before comparison;
  a second model reading the author's conclusions is not automatically an
  independent review.
- The current Docker Pilot 2 remains unchanged. Its parser/invariant soak is
  separate evidence and does not validate E0 or the HGK integration.
- Freeze the record format after working examples and review, not beforehand.

## Sources checked for the strategy

- Levin, TAME (2022), homeostasis as a minimal component of agency:
  https://www.frontiersin.org/journals/systems-neuroscience/articles/10.3389/fnsys.2022.768201/full
- Ashby archive, control-theoretic prior art: https://www.ashby.info/
- Inspect evaluations and sandboxing: https://inspect.aisi.org.uk/
  and https://inspect.aisi.org.uk/sandboxing.html
- Gymnasium environment interface: https://gymnasium.farama.org/main/api/env/
- PettingZoo multi-agent interfaces: https://pettingzoo.farama.org/index.html
- Workflow Run RO-Crate: https://www.researchobject.org/workflow-run-crate/profiles/
- OSF frozen registrations: https://help.osf.io/article/330-welcome-to-registrations
- Braintrust: https://www.braintrust.dev/
- LangSmith evaluation: https://www.langchain.com/langsmith/evaluation
- Invariant composition analysis: https://invariantlabs.ai/blog/toxic-flow-analysis
- Existing OneLab product: https://www.andrewalliance.com/

The landscape search was preliminary. This document makes no patent, trademark,
market-share, scientific-priority, or verified product-superiority claim.
