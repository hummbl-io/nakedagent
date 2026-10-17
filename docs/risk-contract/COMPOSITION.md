# CO Pass | Three priorities, one tested local composition

2026-10-03. [DERIVED] Design and tests; [IMPORTED] existing LabBroker and HGK behavior, canonical Base120 operator definitions. Author verification only; independent review pending.

**A bounded composition now runs end to end:** declared dependency DAG → bound source evidence → fresh-evidence admission → actual local HGK classification → fixed public-fixture read → linked receipt snapshot. This is a laboratory advance, not production enrollment or OS containment.

## Parts received and chunks — CO2: Chunking

1. Existing risk-contract validator and fixed-effect LabBroker, including dispatch lock, pre/post-kernel checks and memory-resident budget/replay state.
2. Declared component graph and a small synthetic source-observation record.
3. Existing local subprocess HGK bridge, plus a new hash-linked composition receipt stream.

The shared governance checkout was dirty and on `feat/devin/model-changelog-collector`; it was left untouched. All code changes are new files in the existing isolated `feat/codex/runtime-risk-contract` worktree. No branch switch, commit, push, plugin installation, secret access or provider activation occurred. No PR was returned for this branch by the current PR lookup.

## Composition — CO3: Functional Composition

`compile_loadout` validates a supplied component DAG without importing or installing it. It rejects unresolved dependencies and cycles (cycles are explicitly unsupported in this bounded model), normalizes dependency ordering, and produces a digest-bound graph. It does not discover the complete graph of arbitrary Python code.

`evidence_record` produces a narrow `lab-cer/0.1` record. It binds the public fixture's enrollment observation to its source digest, resource, predicate, collector label, configuration digest, loadout digest and validity interval. Collector identity and authority are synthetic trusted setup. This is not the general CER schema from the discovery packet, nor an authenticated production collector.

`ComposedLabBroker` reuses the existing broker rather than replacing its dispatch path. Before the kernel and again afterward, it checks evidence binding, source digest and freshness, then the existing contract/artifact/configuration/budget/revocation conditions. Only the already supported fixed public read can dispatch. Pure compilation and binding stages feed an explicit imperative boundary; the kernel call and file read are effects, not pure functions.

The receipt stream links the declared graph, source-evidence record, kernel request, response, reservation and final broker outcome. Actual HGK responses include the scratch receipt path and digest. HGK still receives its existing fixed-read action envelope: the new contract and CER fields are enforced by this local composition wrapper, **not newly enforced inside HGK**. This preserves an important propagation boundary instead of assuming it away.

## Interfaces — CO9: Interface Contracts

| Seam | Input / output | Failure behavior |
|---|---|---|
| Dependency declaration → contract | Declared component IDs, digests and dependencies → normalized DAG digest | Missing references/cycles fail setup; changed artifact set/digests deny dispatch. |
| Evidence → admission | Enrolled `lab-cer/0.1` + bounded source bytes + lab clock → prerequisite observation | Wrong subject, collector label, configuration, digest, future timestamp or expiry holds dispatch. |
| Kernel → effect | Existing action envelope → supported allow with no required controls | Deny and other non-supported decisions prevent dispatch; callback error holds. |
| Effect → provenance | Broker event → digest-linked record | Snapshot audits detect changed content, reordering and truncation relative to the expected checkpoint. |

Source content is not executed or interpreted as an instruction. A well-formed record is not automatically relevant evidence, and evidence never supplies owner authority. Changing evidence after enrollment requires new enrollment; this pass has no renewal API.

## Integration test — CO16: System Integration Testing

**PASS within the stated laboratory scope.**

- **40 focused tests pass:** the previous 30 plus 10 new composition tests. Some tests contain multiple subcases; these are not counted as extra tests.
- Ruff passes for the three new Python files. Default mypy passes for the two new implementation/demo modules; this is not a fully annotated proof.
- **Four actual-HGK scenario expectations pass, with two HGK calls:** admitted read completes; evidence expiry blocks the next effect; an undeclared attachment denies before another kernel call; HGK denies direct model access.
- Integration tests also exercise expiry during a kernel callback, source drift, wrong evidence scope/collector/configuration/time, enrollment mutation, revocation, graph errors, and receipt tampering/truncation with a known checkpoint.

Final retained run: [report.json](C:/Users/Owner/.codex/artifacts/nakedagent-risk/2026-10-03-compose02/report.json). The earlier `compose01` run preceded a lint-only test-fixture correction; `compose02` pins the final Python source bytes. HGK HEAD remains `4e7a06359eae81b3c48f2a57cd82c5fca7e0bf40`, with clean tracked state checked before execution. Receipt snapshots, contract and source-evidence fixture are retained alongside that report. The new demo intentionally reuses the test fixture factory, not a production enrollment system.

Reproduce from the worktree root:

```powershell
python -m unittest discover -s docs/risk-contract -p 'test_*.py'
ruff check docs/risk-contract/composition.py docs/risk-contract/composition_demo.py docs/risk-contract/test_composition.py
mypy docs/risk-contract/composition.py docs/risk-contract/composition_demo.py
python docs/risk-contract/composition_demo.py --kernel-root C:/Users/Owner/PROJECTS/hummbl-governance-kernel --output C:/Users/Owner/.codex/artifacts/nakedagent-risk/NEW-UNUSED-DIRECTORY
```

The demo requires a new output directory. No full nakedagent suite was rerun in this pass: production agent code is unchanged. Previous suite results remain historical, not newly verified.

## What matured across the three priorities

| Priority | Demonstrated now | Still required |
|---|---|---|
| Admit dependencies before use | Supplied graph is compiled and artifact-set drift blocks the fixed dispatch; no candidate plugin is imported. | Actual installer/import hooks, transitive discovery, immutable execution artifacts, and restricted worker. The marker test demonstrates no import on this path, not interception of all Python imports. |
| Invalidate permissions on evidence changes | Expiry/source mutation/binding mismatch/revocation hold the next effect; expiry during callback defeats a prior allow. | Authenticated collectors, trusted enrollment/time, renewal protocol, durable revocation/replay/reservation state, real provider cost accounting. |
| Preserve provenance through decision and outcome | Evidence/loadout → kernel request/response → broker outcome form an auditable chain with actual HGK receipt digest. | Durable write-ahead intent/outcome protocol, independently protected checkpoints, signer policy, complete gateway field propagation and effect observation. |

## Limits and counterclaims

- **No OS isolation:** this class can be bypassed by ordinary same-process Python. Private naming or hashing does not change that.
- **No authenticated authority or evidence:** constructor and callbacks remain trusted lab setup. `lab-fixture-collector` is a label, not a credential. The local synthetic grant does not establish real owner authorization.
- **No durable enforcement state:** exported JSON is a post-run snapshot, not an atomic write-ahead log. A restart can reset the inherited replay and budget state. A crash can lose the receipt stream. There is no distributed exactly-once claim.
- **Checkpoint trust remains external:** if both chain and expected checkpoint are maliciously replaced, an unsigned local audit does not establish authenticity. The report's checkpoint is on the same host, not an independently protected anchor.
- **TOCTOU remains:** source/artifact rechecks reduce detectable drift but do not eliminate changes after validation. The existing fixed-read fixture checks detect a changed value after a read; they cannot undo that read.
- **Incomplete dependency scope:** the declared components are a selected lab subset, not a full SBOM of Python, HGK, its third-party packages or the OS. No installation or general plugin execution is supported.
- **Cryptography does not prove truth:** receipt verification checks representation/linkage under a known checkpoint, not source accuracy, completeness, consent or causal correctness.

## Operator provenance and tooling discrepancy

The configured Base120 server was verified as a local stdio adapter importing the local canonical engine. `base120_list(family="CO")` and individual `base120_get` calls verified **CO2: Chunking**, **CO3: Functional Composition**, **CO9: Interface Contracts**, and **CO16: System Integration Testing** on this turn. The operator definitions supply structure; all component designs and values are derived/imported as labeled above.

The invoked skill's UTF shortlist was queried through configured local stdio. It returned a keyword-inferred Tier 1 and labeled CO5 “Modularity” and CO7 “Value Chain,” conflicting with the canonical Base120 roster's CO5 “Emergence” and CO7 “Network Effects.” Those recommendations were not adopted. No UTF data/configuration was rewritten. This discrepancy needs a separate canonical-data review; it is not evidence that this risk work is simple. No BIF cross-domain ingestion session was needed: this pass assembled one software-control path and imported no separate domain corpus.

## Emergence noted — CO5: Emergence

No emergence was forced or claimed. A specific compositional property was observed: evidence expiry between a kernel allow and dispatch still prevents the effect. Neither a standalone receipt chain nor an isolated policy decision provides that property alone.

## Handoff to RECURSE

Ready for a separately scoped versioned iteration **after independent review**: use this tested composition as the behavioral baseline for one restricted worker and one enrolled resource. Acceptance must demonstrate that direct worker access fails while the admitted broker effect succeeds. Then test restart-safe reservations, replay, revoke, and evidence enrollment. Keep the owner recovery path explicit.

The RECURSE skill was not invoked automatically, no agent was spawned, and no platform abstraction was added. Independent review is a quality gate before consequential adoption, not a second authority above Reuben.

**Stop signal:** CO16 passes for this one declared-loadout/evidence/HGK/receipt composition. The three priorities remain broader production workstreams; their laboratory seams are now tested together.
