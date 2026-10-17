# Docker cloud pilot A — results

2026-10-03. One Small sandbox, 2 vCPU / 4096 MiB, model budget $0.
Operator ratified total pilot compute limit $10; this is an operational limit,
not a verified provider-enforced dollar cap. No second sandbox was launched.

Sandbox: `nakedagent-pilot-20261003-a`, ID `sbx_001m41wc6e1etbcq67cce2g4y47`.
Created 21:57:59.695879Z; provider expiration 22:27:56.98611Z, requested action stop.
Image returned `docker/sandbox-templates:shell-docker` (mutable tag; digest unknown).
Python 3.14.4. Guest UID 1000, groups agent, sudo and docker.

## Measured outcomes

- **234 unit tests passed** in the cloud guest (3.321 seconds reported by unittest).
- **Four smoke checks passed**: clean CLI exit, expected file written, exactly two
  deterministic local HTTP model requests, fresh home without global plugins.
- **41 transferred source/fixture file hashes matched** in the guest. Runtime and
  tests exported from fixed Git commit `105061c4674a4e0666c4515c99476abe214a145a`.
- No published ports reported. No host paths, credentials, model API keys,
  fleet plugins, persistent volumes or MCP servers were supplied by the controller.
  This is a statement about provisioning, not an exhaustive guest secret scan.
- HTTPS requests to example.com and api.github.com failed with TLS access-denied;
  Docker policy logs corroborate both as `sandbox deny` decisions.
- Raw TCP to 1.1.1.1:443 was accepted. Subsequent TLS with SNI was denied and
  without SNI ended with EOF; neither probe received an HTTP response. TCP success
  is not evidence of successful external data exchange. Raw/UDP/IPv6/DNS and all
  possible protocols were not exhaustively tested. Later policy-log export did
  not contain the new IP/TLS attempts; do not invent that corroboration.

## Finding: bootstrap egress is not zero

Despite a creation-time `--deny-network '**'`, Docker logs record allowed traffic
to archive.ubuntu.com:80, security.ubuntu.com:80 and download.docker.com:443 at
21:57:59–21:58:00, during startup. The listed sandbox policy subsequently read
`Default: allow-all` plus `DENY **`; account default read deny-all with no rules.
The workload probes occurred afterward and were denied. This supports the tested
workload denials, **not an assertion of zero egress throughout the lifecycle**.
Whether initialization order, kit behavior or a provider exception caused the
bootstrap traffic is unresolved. No external vulnerability report was sent.

## Admission outcome

Functional pilot passed. Production/security admission remains conditional.
HGK was not wired into this cloud run; the outside controller applied the operator
scope manually. No claim that nakedagent's Python tool policy contains guest root.
No full VM-escape, cross-tenant, DoS, credential-isolation or revocation test.

Before admitting secrets or appendages: resolve startup policy behavior, obtain
an immutable image identity, verify provider billing, test independent shutdown
and revocation, then connect the outside broker/ledger and admit a single appendage.
Do not automatically consume the remainder of the $10 on retries.

Evidence directory:
`C:/Users/Owner/.codex/artifacts/nakedagent-risk/docker-20261003-a/`

Files: manifest.json, source.tar, probes.json, tests.txt, smoke.json,
transport-probes.json, policy-log.json, policy-log-final.json, running.json,
stopped.json. The transport probe was separately transferred after the 41-file
snapshot; its source is retained beside this document, not included in that count.

## Lifecycle closure and budget

The stop request first returned `stopping`; the controller then observed `stopped`
at 22:02:24.9016148Z. State is preserved. No deletion or automatic restart was
performed. TTL expiry itself was not tested; only explicit stop was verified.

Creation to observed stopped is approximately 265.21 seconds. At Docker's listed
Small rate of $0.140/hour, that interval estimates $0.01031 compute. This is not a
billing receipt and does not establish the provider's exact billing boundaries.
Retain the planned $0.07 reservation pending invoice reconciliation, leaving
$9.93 unallocated within the ratified $10 pilot envelope. Paid model calls: zero.
Provider credit balance remains unverified; the $250 grant is operator-attested.

[Docker promotion and compute pricing](https://www.docker.com/c/sbx-promo/),
checked 2026-10-03. A local evidence hash chain is recorded in receipts.jsonl;
it detects modification relative to its checkpoint, is unsigned, and does not
prove the provider's claims or protect against rewriting the whole local chain.
