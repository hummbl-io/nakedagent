# nakedagent risk contract — 0.1.0 draft

Prepared 2026-10-03 for Reuben's review. Fleet operations first; developer-facing configuration second. This is an engineering contract proposal, not an activated policy, legal agreement, security certification, or grant of authority.

## Decision and boundary

Every run needs a baseline contract. Every attachment needs a dependency contract. Admission must evaluate their composition against the run's allowed effects before loading code or releasing data. Runtime observations must update that assessment. Unknown is an explicit state, never a synonym for safe.

Define **bare source** as the CLI, loop, four foundation tools and provider client with no plugins. Define **bare deployment** separately: exact source digest, Python executable, OS, effective principal, filesystem, environment, model endpoint, model and deployment controls. Bare source is not a runnable dependency-free system. The package declares no third-party runtime Python packages, but build requirements include setuptools. Python, its native libraries, OS, model server/weights, DNS, certificates, proxies, packaging and update channels remain dependencies.

The current implementation does not meet the proposed contained deployment contract below. Source inspection establishes available behaviors; it does not establish the permissions or activity of an actual nakedagent run. The existing user-global plugin directory contains `hexad.py`; the ordinary launch on this host must not be described as demonstrably bare. We did not execute that plugin or inspect credentials.

## Source evidence and baseline exposure

Inspected nakedagent revision: `105061c4674a4e0666c4515c99476abe214a145a`. Paths below refer to that revision. A source inventory with SHA-256 digests accompanies this document. No provider request or production agent run was made for this assessment.

| Surface | Observed implementation | Potential impact and limit of evidence |
|---|---|---|
| Runtime/build | `pyproject.toml`: Python >=3.10, dependencies=[], setuptools>=68 for build | Small package dependency surface; neither supply-chain immunity nor a complete runtime inventory |
| Read | `tools.py:tool_read` resolves paths and checks workspace membership | Workspace contents, including secrets present there, can enter tool output; returned text is truncated after reading |
| Write/patch | `tools.py:tool_write`, `tool_patch` check resolved workspace and top-level `.git`/`.nakedagent` protection | Other workspace files may be overwritten. These application checks are not an OS sandbox or proof against every path race/platform edge case |
| Shell | `tools.py:tool_shell` prompts interactively; unattended use requires flag and command-prefix allowlist | Approved executables inherit process authority and environment. Working directory is not confinement. Prefix matching does not bound command effects. Timeout is not verified descendant-tree revocation |
| Plugins | `plugins.py` executes modules during import; global plugins always load; workspace plugins are opt-in | Arbitrary imported code has process authority, before tool declarations are validated. Tool names can override foundation tools. Registry removal does not undo import effects |
| Shell substitution | `loop.py:_build_tools` wraps shell only when the registered function is the original `tool_shell` | A replacement plugin's shell semantics are not automatically governed by the foundation wrapper |
| Model data flow | `loop.py:step` appends tool results to messages; `llm.py:chat` sends messages to configured host | Readable task data can cross the provider boundary. HTTP and HTTPS hosts are accepted; actual TLS, proxies, redirect path, retention and downstream forwarding were not verified |
| Resource use | `loop.py` bounds rounds at 25; shell and HTTP have timeouts; output truncation follows capture/read | Not a total token, dollar, child-process, memory or provider-spend ceiling |
| Records | `cli.py` makes functional event logging optional; shell audit is best effort in `tools.py` | A receipt can support integrity/replay of recorded events, not completeness, truthful sensors, enforcement or absence of hidden effects |
| Optional sidekick/MCP | Separate `sidekick.py` and `mcp.py` surfaces exist | Require distinct launch profiles and review. Local stdio transport alone does not restrict a server's network access |

**Total blast radius today: not bounded by the evidence collected.** Under ordinary tool behavior, the workspace and model destination are exposed. With admitted shell, imported plugins, or compromised in-process code, the outer boundary is the OS principal's accessible resources, inherited credentials and reachable services. We have not enumerated that principal's complete resource graph. This is not a claim that compromise or data loss occurred.

## Proposed contained baseline (target, not current behavior)

| Dimension | Baseline requirement | Required proof |
|---|---|---|
| Identity | Exact run/session, owner authority reference, executable and source digests | Launcher attestation bound to run |
| Files | Dedicated workspace; explicit read/write resources; exclude secret and governance stores | OS isolation probe plus positive/negative file tests |
| Execution | Shell and dynamic imports absent unless separately admitted | Pre-import gate; executable resolution and digest; process containment test |
| Environment | Minimal allowlisted environment; credentials scoped to a broker/action | Names/scopes only in records; credential broker policy and revocation test |
| Network | Explicit endpoint and data-class allowlist; no ambient egress | OS/proxy boundary with redirect/DNS handling, negative egress tests |
| Model | Explicit provider, endpoint, model identity and data handling assumptions | Provider descriptor, routing evidence, model digest where available |
| Spend/resources | Finite duration, request, concurrency, CPU/memory and provider-spend budgets | Enforcing counters; outstanding/in-flight reservations; provider quota when available |
| Persistence | Explicit output/log paths, retention and access policy | Write boundary and deletion/retention tests; no raw secrets in receipts |
| Delegation | No children or new authority by default | Parent budget and authority clamps inherited and tested |
| Shutdown | Deny new dispatches, revoke leases, stop descendants, reconcile in-flight work | Measured revocation delay; external effects that cannot be undone listed |
| Evidence | Required observations fresh and collector health known | Authenticated collector identity, monotonic sequence, gap detection, expiry |

These requirements need a launcher and enforcement adapters outside untrusted plugin code. A Python decorator or a model verdict cannot contain arbitrary code running in the same process.

## Attachment contract (language and provider neutral)

An attachment is any package, skill procedure, executable, model, service, MCP server, credential broker, or delegated agent that changes behavior, authority, data flow or dependencies. Keep skills and agent identities separate. This risk contract is a companion to candidate `edc.v0`, not a modification of its four tools or Hexad's place in the check procedure.

Each attachment record MUST include:

- Stable ID, kind, exact version, immutable artifact digest where possible, source/provenance and update channel; unknown version is recorded explicitly.
- Direct/transitive dependency references, including build/install hooks, native code, interpreter, provider and subprocesses. A package lockfile is one input, not the complete graph.
- Required, requested, granted and **effectively enforced** capabilities separately: resource, operation, scope, data class, principal, destination and delegation limit.
- Data inputs/outputs, retention, trust boundaries, credential scope/reference (never value), network routes and model/provider selection rules.
- Failure behavior, kill/revoke mechanism and measured latency, irreversible effects, budgets and outstanding reservations.
- Evidence source, observation time, sequence, validity interval, collector trust/coverage, tests, known gaps, and owner-authorized policy reference.
- Admission binding to run + contract digest + artifact digest + effective configuration digest; changing any invalidates the previous result.

### First EDC candidates

| Candidate | What to assess next | Initial disposition |
|---|---|---|
| Hexad | Pin procedure + shim + harness + selected model/provider. Inspect all six stages, handback limits, output retention, child calls | Needs containment and explicit routing |
| Decide-0 | User called this Decision-O; mapping to local Decide-0 remains a naming assumption. Verify actual current implementation/checkpoint, policy inputs, error modes and disagreement handling | Advisory assessment only; cannot grant authority or override deterministic denial |
| Python packages | Resolve complete lock/environment including native libraries and install-time effects; import may execute code | Review before installation AND import; separate build environment |
| Other language packages | Same contract for npm lifecycle hooks, native builds, Java classpaths, Go/Rust binaries and dynamic loads | No exemption based on language or package count |
| Service/provider | Endpoint identity, scopes, billing, data handling, retries, redirects, changes and revoke path | Route/data/budget admission before request |
| MCP server | Executable/package and child dependency tree, tools, credentials, egress and downstream provider | Local stdio by fleet policy; transport is not sandboxing |

**Hexad routing finding:** local `C:/Users/Owner/.agents/scripts/nakedagent_hexad.py` describes itself as local-only but selects OpenRouter defaults when `OPENROUTER_API_KEY` is present; `HEXAD_*` overrides also affect routing. It writes problem and results under `.nakedagent/hexad`. This is static evidence of possible routing and persistence, not evidence that a request was sent. Contract policy: provider selection must be explicit and frozen before admission; mere credential presence must not expand permitted egress.

## Logic and mathematics

Let G(t) be a typed, directed graph of principals, code, tools, resources, credentials, providers and services. Edges encode operations, scope, conditions and trust boundaries. Reachability MUST include composable transitions (read -> tool result -> model request; credential -> subprocess -> remote service), not only declared dependency edges.

For a run root a, define potential blast radius B(t) = effects reachable from a in G(t), under the stated threat model and effective controls. Store effects as resource/operation pairs with impact classes; do not sum files, dollars and disclosure into one unlabeled number. Report counts only for enumerated inventories. An incomplete graph cannot justify an upper bound for the real system.

For appendage p: delta B(p|G) = B(G plus p) minus B(G). This is conditional on the existing composition. Two attachments that each add no new resource may together add a harmful data path. Also report new paths and boundary crossings, not just new nodes. Removing an attachment can remove a protective gate; recompute the whole graph after detach.

Observed effects O(t) are events verified by available sensors. O(t) is not B(t); no event does not imply no exposure. Unknown paths, collector blind spots, stale evidence and compromised sensors remain explicit.

Expected loss could be written E[L|evidence, horizon, scenario], but probability and impact require calibrated data and assumptions. This initial contract provides no defensible probability estimator, universal risk score or numeric confidence score. A severity ranking is a policy judgment, labeled as such. Likelihood is **unknown**, not zero.

The proposed admission predicate is the conjunction of valid owner authority, artifact/config binding, permitted composition, verified controls, fresh required evidence and available budget. Any failed condition denies the proposed effect. Missing evidence holds it for review. Neither an LLM's approval nor a valid receipt can make a failed predicate true. Source review alone cannot evaluate that predicate for a deployment.

## Runtime protocol and measurements

1. **Discover before import:** inventory exact launch inputs, global/workspace plugins, packages, executable resolution and external dependencies without executing them.
2. **Preview composition:** show added resources AND added paths; compare requested access with grants, budgets and data policy.
3. **Admit through trusted broker:** bind decision to exact run/artifact/config/action. Use short-lived capability leases. Dispatch and check share one boundary to reduce time-of-check/time-of-use gaps.
4. **Observe effects:** process creation/exit, file operations, network connections/requests, credential lease use, tool actions, provider usage, model identity, budgets, collector health and changes. Instrumentation must not collect raw prompts or secrets by default.
5. **Re-evaluate on events and expiry:** plugin/model/provider change, new executable, endpoint redirect, tool-schema change, privilege change, dependency drift, collector loss, budget exhaustion or policy update invalidates affected admissions.
6. **Contain and reconcile:** deny new effects; revoke credentials/leases; stop child processes through the OS boundary; account for already committed remote work and irreversible disclosures.

Measurement display: observation age, event lag, sequence gaps, enumerated scope coverage, denied attempts, new reachable paths, active leases, in-flight actions, usage versus budget, source/model drift, and time to stop. Show numerator/denominator and an unknown denominator when coverage cannot be established. Proposed freshness/response targets are policy parameters, not measured guarantees. Acceptance requires timestamped end-to-end tests under load and failure injection.

Required runtime receipt: schema + run + event ID + collector + monotonic sequence + observation/receipt times + action ID + previous hash + contract/artifact/config digests + policy result/reasons + effect summary + evidence references. Sign/anchor externally where needed. Hash chaining alone cannot prevent a writer rewriting an entire unanchored chain, prove wall-clock time, detect omitted events, or establish truth or safety.

## Create a player and dashboard

Fleet workflow: select mission and principal -> select contained foundation -> attach EDC modules -> inspect capability and data-path differences -> set scopes/budgets/revoke conditions -> validate evidence -> review run contract -> launch only when enforcement is available. Developer workflow later offers the same engine with simpler presets and details on demand.

Use an equipment/loadout metaphor without implying a component is safe because it is familiar or highly rated. Slots: foundation, reasoning procedure, advisory decision helper, tools, models/providers and integrations. Hexad occupies a procedure slot, not an agent identity.

Dashboard panes: current composition; potential reach; observed activity; evidence gaps/freshness; budgets and in-flight work; controls and revoke status; receipt timeline. Every value carries declared/source-reviewed/observed/enforced/simulated provenance. A green score must never stand in for absent evidence. A removal preview must show lost controls too.

`dashboard.html` is an offline interactive **scenario prototype**, with no live sensors, no agent launch, no external requests and no production configuration changes. Its graph calculations use synthetic edges, not a scan of Anvil. `risk_model.py` provides the same kind of bounded graph assessment for JSON evidence snapshots; it is not a sandbox or deployment admission service.

## What is impossible or not yet established

- Impossible as a universal guarantee: exact real-time probability of every failure/attack; complete foresight over arbitrary program behavior; zero risk; receipts proving semantic correctness; undoing disclosed secrets or already committed remote effects.
- Possible with explicit bounds: inventory known dependencies, check typed capability paths, enforce finite policies at external boundaries, measure instrumented effects and control latency, and estimate scenario risk with calibrated evidence.
- Not established here: host-wide blast-radius upper bound, full transitive dependency inventory, live runtime monitoring, trusted collector deployment, OS containment, provider retention/billing guarantees, calibrated risk probabilities or deployed kill switch.

## Implementation and review gates

P0 before unrestricted fleet rollout: pre-import admission/explicit plugin inventory; isolate execution and credential/egress brokers; explicit Hexad provider routing; prevent model advice from granting authority. These are priorities, not incident severity findings.

P1: schema/descriptor validation, source/config drift, resource budgets including outstanding requests, collector health and freshness, effect receipts and anchored integrity, tested descendant shutdown.

P2: fleet dashboard adapters, package/SaaS inventory interoperability, historical calibration, then developer onboarding.

Acceptance tests: unlisted plugin never executes; replacement tool cannot bypass broker; read-plus-egress composition is surfaced; stale/missing/forged sensor data never yields approval; model-provider drift invalidates lease; removal of a control triggers reassessment; spend reserved before dispatch; denied action produces no effect; revoke stops descendants within a measured bound; remote irreversible effects clearly reported. Parallax reviewers should challenge threat-model completeness, graph soundness, authority boundaries, Windows path/process behavior, and any claimed upper bounds.

## References and scope

The dependency/service inventory should interoperate with existing standards rather than claim a novel BOM format. CycloneDX SaaSBOM represents services, endpoints, dependencies and classified data flows: https://cyclonedx.org/capabilities/saasbom/ . Risk-assessment framing has established prior art, including NIST SP 800-30 Rev. 1: https://csrc.nist.gov/pubs/sp/800/30/r1/final . Neither source certifies this design.

Local design inputs: `.agents/docs/schemas/edc/EDC.md` (candidate/non-canonical), `.agents/docs/schemas/edc/examples/naked-parent.edc.yaml`, `.agents/scripts/nakedagent_hexad.py`, and `.agents/docs/bizdev/2026-09-30_decide-0-scoping.md` (historical proposal; current model deployment not verified). Reject the earlier synthesis document's supply-chain-immunity claim. No existing governance, authority or launch behavior is changed by this draft.
