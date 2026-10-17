# Maturation 0.2 — a bounded admission pilot

2026-10-03. Author-run verification; independent parallax review remains pending.

The contract now has an executable, deliberately narrow schema and a local laboratory connection to the existing HGK gateway. Production nakedagent, HGK source, host permissions, credentials and provider configuration are unchanged.

## What was added

- `contract.schema.json`: a portable JSON Schema for a bounded run, principal, policy/config/graph commitments, component digests/dependency references, exact operation/resource grants, required evidence, action count and expiry.
- `contract.py`: stdlib validation, duplicate-key rejection, byte/collection/identifier/integer limits, dependency-reference validation and deterministic contract digest. Schema validation never grants authority. This is not a generic JSON Schema implementation; its exported schema is checked separately with `jsonschema` in development.
- `admission_pilot.py`: a serialized lab broker that snapshots untrusted action input; checks a separately supplied synthetic grant, exact binding, component hashes, configuration/graph drift, evidence age, revocation and budget; asks the kernel; rechecks conditions; reserves one action; performs only a fixed public-fixture read. Unsupported kernel controls and all non-allow routes prevent dispatch.
- `hgk_probe.py` and `kernel_demo.py`: local subprocess bridge exercising actual HGK `process_action()` in an isolated Python invocation. HGK receipts are directed into the experiment directory. No remote MCP or provider call is involved. This exercises the action path, not proposal-field propagation through `process_proposal()`.

## Measured outcomes

Final code run: `C:/Users/Owner/.codex/artifacts/nakedagent-risk/2026-10-03-pilot02/`.

HGK source HEAD: `4e7a06359eae81b3c48f2a57cd82c5fca7e0bf40`. The runner refused a changed HEAD or tracked dirty HGK checkout. Selected implementation/policy inputs and pilot source files are hash-bound in the retained contract. This selection is not a complete transitive dependency inventory; HGK's environment includes dependencies such as jsonschema and PyYAML.

| Scenario | Observed result |
|---|---|
| Correct grant/binding, fresh lab evidence, fixed read | HGK returned allow; broker reserved and completed the public read |
| Same action replayed | Denied before another kernel call or fixture read |
| New action after one-action budget spent | Denied before dispatch |
| Model actor requesting direct tool access | Actual HGK deny; broker did not dispatch fixture read |
| Observation at its expiry boundary | require_more_evidence; no kernel call or fixture dispatch |
| Additional unadmitted component | Denied for component-set drift before dispatch |

Six scenario expectations passed; two real local HGK calls occurred. HGK reported `registered_guard_only`, which is preserved rather than relabeled as production binding enforcement. Broker outcomes are labeled `lab_in_process_only`.

**Validation:** 30 focused unit tests pass (21 contract/admission plus nine graph tests); Ruff passes for this directory; default mypy check passes for four new source modules. The exported schema passes `Draft202012Validator.check_schema`, and the retained contract passes both the stdlib validator and that independent schema implementation. The original 234-test nakedagent suite passed in the preceding milestone; it was not rerun because this milestone changes only the new prototype directory.

The tests cover expired/future/missing/unbound observations, unknown fields, forged action claims, wrong principal/grant, new components, changed artifacts, configuration drift during a kernel callback, unsupported controls, gateway failure, replay, concurrent budget contention, and mutation of the caller's action object. These are bounded tests, not proofs over arbitrary code.

## Self-review and limits

1. **No OS isolation.** The worker, broker, callback and observations are trusted setup inside one Python process. The caller could bypass this class using ordinary filesystem APIs. This experiment proves behavior through this dispatch path only.
2. **Authority is synthetic.** `owner_grant_sha256` is supplied by the test harness. It is neither an authenticated owner instruction nor a production capability. Matching a digest does not prove authority. A production broker must resolve authenticated grants independently.
3. **Evidence is synthetic.** Observation times/status come from the test harness. No trusted collectors, collector identity authentication or protected clocks were deployed. Evidence trust cannot come from a `verified` string.
4. **Crash/restart safety is absent.** Budget, replay set, revoke state and broker events are memory-resident. Recreating the broker resets them. HGK writes scratch receipts, but broker intent/outcome records have no durable transaction protocol. No production budget or replay guarantee is claimed.
5. **Artifact races remain.** Hashes are rechecked before and after the gateway, but external processes can still mutate files afterward. Production needs immutable execution artifacts or handle-bound validation plus OS controls. A changed fixture is detected after a bounded read and reported as an attempted, failed operation; that detection cannot undo a read.
6. **This schema is a subset.** It does not yet encode the full typed capability graph, data classifications, retention, provider billing, inherited authority, recovery procedures or all EDC metadata in CONTRACT.md. `dependency_graph_sha256` is a binding to a supplied graph, not independent discovery of the graph.
7. **Gateway integration is partial.** Only fixed-read action classification was exercised. Full proposal propagation, constrained grants, all nakedagent execution paths and pre-import admission remain unimplemented. Callback failure holds rather than allowing a best-effort fallback.
8. **No live UI.** The dashboard remains an offline scenario prototype. It does not read these results or display real-time measurements. Browser rendering/interaction and accessibility review remain pending.

A self-review correction was implemented: the action envelope is copied before validation so another caller reference cannot change the action identity recorded after the kernel callback. A regression test passes. This is an author correction, not an independent review verdict.

## Next bounded milestone

Perform independent review of this schema and admission path, then build a restricted worker + local broker pilot for one enrolled resource. Acceptance must show that direct access to that resource fails while its admitted broker operation succeeds. Add durable reservation/replay/revocation handling and trusted enrollment before expanding to filesystem writes, plugins, credentials or egress. Preserve the owner recovery path.

Reproduce the local experiment with a **new** output directory:

```powershell
python docs/risk-contract/kernel_demo.py --kernel-root C:/Users/Owner/PROJECTS/hummbl-governance-kernel --output C:/Users/Owner/.codex/artifacts/nakedagent-risk/a-new-run
```

The runner never overwrites an existing experiment directory. The selected source revision and interpreter dependencies must be reviewed before using a different kernel checkout.
