# AAR: nakedagent Docker pilot — bootstrap egress unresolved; verify before secrets | INTERNAL | 20261003-2213Z | codex

Scope: Docker client setup and cloud pilot A only. Earlier Windows-boundary,
Unicode, prior-art and 1Password work are adjacent operations, not claimed as
completed by this AAR. Author=codex; host=anvil; surface=desktop-codex;
lane=nakedagent-docker-sandbox. Owner=Reuben.

## 1. Mission & Intent

Use the operator's Docker credit grant to run nakedagent in an isolated cloud
environment and collect evidence for its risk contract. Success meant a bounded
functional run, tested outbound restrictions, exported evidence and verified stop.
The owner ratified a $10 compute envelope, one initial Small sandbox with 30-minute
TTL, and $0 paid model calls. The intended controller remains outside the guest.

This was a functional/boundary pilot, not production approval or an HGK integration
deployment. Budget ratification: conversation and canonical bus ACK at 21:57:54Z.
Plan: [PILOT.md](PILOT.md).

## 2. Chronology

Evidence root **E** is
`C:/Users/Owner/.codex/artifacts/nakedagent-risk/docker-20261003-a/`.
Canonical bus entries were reread with `bus-global.py search nakedagent-docker-sandbox`.

| Time UTC / receipt | Action | Result |
|---|---|---|
| 21:40:45, bus PROPOSAL | Claimed pilot lane after product and host inspection | Legacy command removed; sbx absent from PATH. Receipt: bus request `0cd8d1337b074548af6894c686cc7754`, prior command output recorded in PILOT.md. |
| By 21:44:26, bus SITREP | Installed per-user sbx 0.46.0; ran local smoke fixture | Installer hash verified; four smoke checks passed; authentication pending. Receipt: bus request `ada60c617e9c420eae400f89558107d0`, PILOT.md installation record. |
| Before 21:57:54, session commands | Operator signed in; diagnostics checked | All five checks passed, subscribed, no existing sandboxes. Receipt: `sbx --cloud diagnose` and `ls` tool output in this session. |
| 21:57:54, bus ACK | Recorded ratified $10 cap and $0 model budget | Authorized one Small/30-minute run. Receipt: request `36c64f9736ac42f5a987389aab9f5a4b`. |
| 21:57:59.695879, E/running.json | Created pilot with explicit deny-all pattern and stop-on-timeout | ID `sbx_001m41wc6e1etbcq67cce2g4y47`, 2 CPU/4096 MiB, expiry 22:27:56.98611Z. Receipt: creation command output, E/running.json. |
| 21:57:59–21:58:00, E/policy-log-final.json | Provider startup network activity recorded | Three package-repository destinations allowed; cause unknown. This precedes the workload probes. |
| Guest run, E/manifest.json and E/probes.json | Uploaded an allowlisted snapshot and verified its hashes | 41 source/fixture files matched; source commit `105061c4674a4e0666c4515c99476abe214a145a`. |
| Guest run, E/tests.txt and E/smoke.json | Ran unit suite and deterministic CLI task | 234 tests passed in reported 3.321s; four smoke checks passed. |
| 21:59:52, E/policy-log-final.json | Tested example.com and api.github.com HTTPS | TLS denied, both corroborated as sandbox-policy blocks. |
| Follow-up, E/transport-probes.json | Investigated successful raw TCP connect | TLS with SNI denied; no-SNI TLS ended with EOF; no HTTP response. Policy export did not corroborate these additional attempts. |
| By 22:02:24.9016148, E/stopped.json | Requested stop and polled past stopping | Stopped confirmed; guest state preserved. Receipt: E/summary.json observation timestamp and session command output. |
| 22:03:31, bus SITREP | Published conditional result and checkpoint | Receipt `9494deda88f644abac670fc02f6755d7`; E/checkpoint.json. |
| AAR turn, 22:13:17 | Rechecked cloud state and local evidence | Guest still stopped; all 13 receipt hashes subsequently reverified. Receipts: live `ls --json` output and receipt-verifier output in this turn. |

## 3. Outcome vs Plan

- **Functional goal met:** 234 tests and four smoke checks passed. This used a
  deterministic localhost HTTP fixture, not a real-model quality evaluation.
  Evidence: E/tests.txt, E/smoke.json and [smoke.py](smoke.py).
- **Boundary goal only partially met:** two HTTPS denials were corroborated;
  startup egress was allowed. TCP acceptance did not yield an HTTP response in
  the follow-up tests. This is neither zero-egress proof nor a demonstrated
  exfiltration exploit. Evidence: E/probes.json, E/transport-probes.json,
  E/policy-log-final.json.
- **Lifecycle goal met for explicit stop:** final state stopped, no second
  sandbox created. TTL-expiration enforcement was not exercised. Evidence:
  E/stopped.json and live AAR-turn `ls --json`.
- **Budget result incomplete:** [inferred] approximately $0.01031 for the
  creation-to-observed-stop interval at the recorded $0.140/hour rate. Actual
  charge and credit balance remain unknown. The $0.07 reservation is accounting
  intent, not an enforced billing ceiling. Evidence: E/summary.json,
  E/running.json, [RESULTS.md](RESULTS.md), and the operator's ratification.
- **Preflight deviations:** launch used a mutable image tag without a digest,
  and account credit was not verified despite the plan requiring it. Owner
  attestation and subscription entitlement were available, but neither supplies
  a balance receipt. Evidence: PILOT.md, E/running.json, E/summary.json.
- **Change scope:** six pilot files were untracked before this AAR; tracked and
  staged diffs were empty, HEAD remained the source commit above. Other
  untracked risk-contract files predated this pilot. No commits, PR or CI run
  occurred. Evidence: AAR-turn git log/status/diff outputs. Six-file inventory:
  PILOT.md 106 lines/6618 bytes; RESULTS.md 77/4600; smoke.py 80/3054;
  package.py 33/1534; guest_probe.py 29/1339; transport_probe.py 26/1097.

No swarm fan-out or multi-lane re-run occurred in this scoped operation. No
concurrency-cap signals were observed. Side effects include the installed client,
authenticated local session, cloud compute use, startup network traffic and a
preserved stopped guest. Passing tests do not undo those effects. No destructive
target operation, account-wide policy change or paid model call was performed
by the pilot commands. Receipts: command history, PILOT.md and RESULTS.md.

## 4. Root Causes

**Startup egress:** logs establish allowed destinations and timestamps, not why
the deny rule did not govern them. Initialization order, kit policy and provider
exceptions are hypotheses only [unverified]. No provider implementation trace was
obtained. Root cause remains unknown; do not label this a confirmed platform bypass.

**Incomplete preflight:** the agent proceeded although two evidence fields
(image digest and account credit) were absent. This is a workflow failure: the
written requirements were not enforced as a blocking launch gate. Receipt:
PILOT.md requirements compared with E/running.json and E/summary.json. Why that
choice was made is not independently evidenced; no deeper causal claim is made.

**TCP interpretation gap:** the first probe measured socket establishment only;
its source contains no application exchange. That test cannot establish external
HTTP delivery. The follow-up narrowed the claim by testing TLS. Receipts:
[guest_probe.py](guest_probe.py), [transport_probe.py](transport_probe.py).

**Accounting/control gap:** the process used one bounded launch and a local
reservation, but did not connect the durable risk ledger/HGK to Docker or obtain
a provider billing receipt. No integrated enforcement should be inferred from
the architecture diagram. Receipt: PILOT.md and executed command history.

## 5. Sustains

- Keep model credentials and production data out of first boundary trials;
  deterministic fixtures exercised real nakedagent CLI behavior. Evidence: smoke.py.
- Export an explicit source allowlist from an exact Git ref and verify hashes
  after transfer. Evidence: package.py, E/manifest.json, E/probes.json.
- Corroborate network failures with policy decisions and separate transport
  success from data exchange. Evidence: both probe files and policy logs.
- Confirm terminal stopped state rather than treating a stop acknowledgment as
  completion. Evidence: live transition output and E/stopped.json.
- Preserve evidence locally and verify it before reporting. Evidence: 13-file
  chain reverified in this AAR turn; no historical receipt was rewritten.

## 6. Improves

- Preflight was advisory in practice: missing immutable image identity and
  verified credit did not block launch. Evidence: planned checks versus running.json.
- Creation-time deny-all did not establish whole-lifecycle zero egress;
  startup allowed destinations remain unexplained. Evidence: policy-log-final.json.
- The first raw-TCP probe was too weak to support an egress conclusion; the
  additional TLS attempts lack provider-log corroboration. Evidence: probe outputs.
- The $10 envelope is not a provider dollar limit or an integrated broker quota;
  actual billing and expiration/revocation behavior are untested. Evidence: summary.json.
- Shell-kit provenance and guest authority remain broad: mutable image, sudo/docker
  group membership; no independent boundary review. Receipts: running.json,
  session `id` output, RESULTS.md. Unsigned local receipts prove byte linkage only.

## 7. Recommendations

1. **[HIGH] Make preflight executable and fail closed.** Owner: codex next build.
   Require immutable image reference, account/billing evidence or an explicit
   recorded exception, bounded TTL, network configuration and atomic budget
   reservation before create. Acceptance: missing fields reject without cloud
   resource creation. Addresses improves 1 and 4.
2. **[HIGH] Resolve bootstrap egress before secrets or appendages.** Owner: codex
   investigation; external support contact only if the operator directs it.
   Acceptance: explain the three logged allows and reproduce lifecycle policy
   behavior with harmless fixtures; if an exception is inherent, represent its
   destinations and phase explicitly in the contract. Addresses improve 2.
3. **[MED] Test lifecycle and protocol boundaries separately.** Owner: codex,
   within remaining ratified budget only after a concrete next-run plan.
   Acceptance: corroborated denied application exchanges, TTL and controller-loss
   cases, revocation behavior, and confirmed terminal state. No assumption that
   the present run already covered those cases. Addresses improves 3 and 4.
4. **[MED] Reconcile billing and request independent boundary review.** Owner:
   codex preparation; reviewer must be assigned. Acceptance: actual usage receipt,
   reconciled reservation, image provenance, evidence packet and non-empty diff
   for new helper code. Addresses improves 4 and 5. No review is claimed here.

---
Base120 Applied: none; no canonical model lookup or coded transformation was performed in this AAR.
Evidence: E/receipts.jsonl; E/checkpoint.json; E/tests.txt; E/policy-log-final.json; PILOT.md; RESULTS.md; AAR-turn git and cloud state commands; canonical bus receipts cited above.
Bus: Y (SITREP c52b2bea459045068a4fd30cf47833dd at 2026-10-03T22:16:22Z)
