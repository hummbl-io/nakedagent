# Pilot 2: seeded nakedagent reliability soak

Operator authorization: additional $10 Docker compute, $0 paid model usage,
confirmed 2026-10-03 in the conversation. Aim: use approximately the $10 allocation
for a sustained, reproducible property test, not claim that a short smoke trial
spent $10. Never run idle work just to hit an exact invoice amount.

## Budget and launch gate

Docker account console, Usage & billing, read on 2026-10-03: $250.00 settled
credit; $249.99 available; $0.01 accrued. Small: 185.505237 metered seconds at
$0.00003889/s. XL: $0.00031111/s (about $1.12/h), which differs from the earlier
promotion's $1.118/h. Account rate governs this plan. Console warns usage may
take 48 hours to update; these are current displayed figures, not a final invoice.

Reservation: $0.05 for completed two-minute Small preflight; $9.95 for one XL
soak. Main TTL 8h50m = 31,800 seconds, estimated $9.893298 at account rate.
Unused margin covers setup/shutdown uncertainty. Exact $10 billed cannot be
guaranteed from the delayed usage display; no top-up/retry to burn the remainder.
The controller stops on workload failure or stale checkpoints. Actual cost must
be reconciled later. This is an operational ceiling, not a provider dollar cap.

Image pinned to linux/amd64 manifest:
`docker.io/docker/sandbox-templates@sha256:5bbe8539825fe1cace6dda2fb66919ef819324d905bea2795b8516aee0198222`.
Resolved through `docker buildx imagetools inspect`; no local daemon build needed.
Direct `--image-ref` avoids the shell-kit configure step; it does not prove the
cause of Pilot 1 startup egress. No worker model credentials, fleet plugins,
host paths, volumes, published ports, or MCP gateway are supplied.

## Preflight evidence

Sandbox `nakedagent-p2-preflight`, ID `sbx_001m41xn35fqy27etjtbmd49k3d`:
2 CPU/4096 MiB, created 22:20:20.12824Z; expiry 22:22:17.553323Z, action stop.
Observed running -> stopping -> stopped without issuing a stop command.
This exercises provider TTL independently of the later local controller.
Python 3.14.4, 41 snapshot hashes matched; two HTTPS requests returned TLS
access-denied. Raw TCP was accepted as in Pilot 1. Policy-log responses remained
empty, including after stopping: no corroborating denial record is claimed.
No allowed traffic appeared in those responses, but empty logs do not prove
zero traffic or establish the previous run's cause.

## Useful work and failure behavior

One XL guest, 16 vCPU/32 GiB, runs 16 ordinary Python worker processes (no AI
subagents). Each batch records a distinct seed. It runs nakedagent's 13 existing
invariant tests with the test module's random seed varied, then 256 generated
nested-fence parser cases checking body preservation, CRLF equivalence and
refusal of unclosed calls. Existing generator default length stays 40; the
runtime STREAM_LEN setting does not override bound default arguments.

The fixed 234-test suite and credential-free CLI smoke run first. Worker evidence
is hash-linked and checkpointed atomically; the outside controller copies live
summaries every 30 seconds. Failures retain seed and bounded diagnostic text,
stop further batch submissions, and cause the controller to export and stop.
Repeated missing/stale checkpoints also stop. The STOP file in the local artifact
directory is an operator-controlled stop signal. No automatic restart or new
sandbox creation after an error; an exclusive controller lock prevents duplicates.

The workload ends two minutes before provider expiration for export and stop.
Provider TTL still applies if Anvil/controller disconnects. Anvil must remain
available for live collection; guest state is preserved on stop. The controller
does not run through HGK yet. It checks a fixed admitted recipe and reservation;
the earlier SQLite action ledger is not silently represented as a money ledger.

## Validation before main launch

Short local harness: 30 batches, 390 invariant-test executions, 7,680 generated
parser cases, zero failures, 5.294 seconds. This validates harness execution only;
it is not evidence for the full cloud soak or exhaustive safety.
Controller safety tests: budget overflow rejects before create; existing name
not reused; exclusive lock blocks duplicate controller; export timeout still
issues stop and does not recreate. Four tests pass, no paid calls in those tests.

## Evidence and completion

Local artifact directory:
`C:/Users/Owner/.codex/artifacts/nakedagent-risk/docker-pilot2-20261003/`.
Watch `live-summary.json`, `controller-commands.jsonl`, and ultimately
`controller-final.json`. A running checkpoint is not completion. Completion
requires final guest outcomes, exported chain verification, stopped cloud state
and later billing reconciliation. Record early stop honestly even if it spends
less than $10. Findings remain candidates for independent review.

## Launch receipt — ongoing, not final

Main sandbox `nakedagent-p2-soak`, ID `sbx_001m41y4jgjc9ft0fr59rm6d7s3`, created
2026-10-03 22:28:48.156389Z; expires 2026-10-04 07:18:44.77482Z
(03:18 EDT). Reported shape 16 CPU / 32768 MiB and image digest match admission.
234 baseline tests and four smoke checks passed in this guest. First captured
running checkpoint at 22:29:46Z: 1,811 batches, 23,543 invariant-test executions,
463,616 generated parser cases, zero failures. These are repeated test executions
with recorded seeds, not 23,543 different test definitions or a completed soak.

The local controller is running in foreground tool session 47258. An attempted
bundled hidden-background launch was rejected by automatic approval review with
only `blocked by policy`; it did not execute. Preparation and tests were then
separated, and an observable foreground launch succeeded. No scheduled task,
service, auto-restart or hidden background launcher was installed. Provider TTL
is independent of the controller host/session, as exercised by preflight.

Use `verify_soak.py <exported-directory-containing-summary-and-events>` after
completion. The verifier passed on the local harness's 30-batch evidence; main
cloud evidence is still in progress. Billing reconciliation may lag by 48 hours.
