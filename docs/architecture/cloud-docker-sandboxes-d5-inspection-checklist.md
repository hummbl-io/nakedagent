# Docker Cloud Sandboxes (sbx) — D5 Inspection Checklist

**Purpose:** close the "cloud-uninspected=2" gap left by the 2026-10-06
docker-daemons audit and codex's 2026-10-03 `nakedagent` cloud pilot, **before
loading more compute** onto Docker Cloud Sandboxes.

**Origin:** proposal `39397efc` item D5 ("Cloud audit first"); pilot evidence in
`~/.codex/artifacts/nakedagent-risk/docker-20261003-a/` (RESULTS.md) and
`docker-pilot2-20261003/`.

**Scope:** read-only inspection + a single bounded admission. Non-destructive.
**Agents do not handle Docker credentials.** `sbx login` is operator-only.

---

## 0. Preflight (operator logs in first)

- [ ] Operator: `sbx login` (browser, or `--username` + `--password-stdin`).
- [ ] `sbx version` — record version (>= v0.47.0; pilot ran v0.46.0).
- [ ] `sbx diagnose` — record pass/fail; daemon reachable, auth OK.
- [ ] `sbx --cloud ls` — inventory of existing cloud sandboxes (expect none/orphaned).
- [ ] Record the credit balance from the Docker console (Usage & billing);
      note the up-to-48h usage lag.

## 1. Image identity (pilot gap: mutable tag)

- [ ] Resolve an **immutable** template identity — pin
      `docker/sandbox-templates@sha256:<digest>` (pilot used the mutable tag
      `shell-docker`).
- [ ] Create two sandboxes from the pin; confirm the resolved guest digest matches
      (reproducibility).
- [ ] Record the digest in the receipt.

## 2. Billing reconciliation (pilot gap: balance unverified)

- [ ] Read settled / available / accrued USD + timestamp.
- [ ] Reconcile against the pilot reservation (~$0.07 compute).
- [ ] Confirm the Small rate ($0.140/hr) and XL rate ($1.12/hr) against the receipt.
- [ ] Set/confirm a **compute budget** and a hard stop before running.

## 3. Network policy (pilot gap: bootstrap egress not zero)

- [ ] Create with `--deny-network '**'`; export the startup policy log.
- [ ] Determine whether bootstrap egress still occurs to `archive.ubuntu.com:80`,
      `security.ubuntu.com:80`, `download.docker.com:443`; classify allowed vs denied.
- [ ] Confirm the **workload** egress is denied (probe after startup).
- [ ] Decide: acceptable, or block at the host/egress layer.

## 4. Lifecycle & revocation (pilot gap: TTL untested)

- [ ] `sbx stop` and `sbx rm` behavior; verify state after each.
- [ ] `sbx ttl <id>` — inspect and (on a throwaway) test extend/expiry.
- [ ] Independent force-stop path (controller kills the sandbox) — verify.
- [ ] `sbx secret` — confirm no secrets stored; confirm the guest cannot read host secrets.

## 5. Isolation proof (state what is and is not tested)

- [ ] Confirm no host paths, volumes, credentials, plugins, or MCP servers supplied.
- [ ] `sbx volume` / `sbx ports` — confirm none attached/published unless intended.
- [ ] Explicitly list untested: full VM-escape, cross-tenant, DoS, exhaustive protocols.

## 6. Admission gate (only after 1–5 pass)

- [ ] Admit **one** appendage; route effects through the outside broker/ledger (HGK)
      with budget reservation, expiry, and revocation.
- [ ] Write a receipt per action; hash-chain them.
- [ ] Do **not** auto-consume remaining credit on retries.

## Rollback / safety

- [ ] Every step reversible: `sbx stop` then `sbx rm`; no host mutation.
- [ ] Abort conditions defined; stop-on-first-inconclusive.

## Evidence

- [ ] Save every command output to a receipt directory; record the CLI version,
      image digest, policy-log hash, and billing snapshot with timestamps.

---

_Prepared by opencode. Status: ready to run once the operator completes `sbx login`._
