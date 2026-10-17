# nakedagent-sandbox: Docker cloud pilot

2026-10-03. Operator ratified a $10 compute pilot cap and $0 model usage.
One cloud run has now executed; see [RESULTS.md](RESULTS.md). Credit balance and
actual invoice remain unverified. The design below is retained as the pilot plan;
the results distinguish executed controls from proposed HGK integration.

## Product and budget

The matching [Docker promotion](https://www.docker.com/c/sbx-promo/) covers cloud
compute, including idle/setup/retries, not model calls. Credits expire six months
after redemption; usage exceeding them can charge the card. Listed Micro rate:
$0.070/hour; Small: $0.140/hour; Medium: $0.280/hour.

Proposed first run: one Small (2 CPU, 4 GiB), 30-minute TTL, no retries or parallel
workers. Estimated compute $0.07 if running for the entire TTL at that rate. This
estimate is not a billing cap or guarantee. Confirm account credit, actual shape,
rate and expiration before creation. Use provider-side expiration; a local timer
alone cannot stop cloud billing if Anvil disconnects. Confirm terminal state and
reconcile billed usage afterward. Separate model budget remains zero.

## Contract and kernel link

Owner authority -> admitted run contract -> trusted controller/HGK -> Docker
control plane -> untrusted nakedagent microVM -> exported evidence.

Keep Docker account credentials, HGK authority, reservation ledger, revocation,
and receipt checkpoint outside the worker. Docker supplies a provider-managed
isolation boundary; it does not automatically integrate HGK. The existing Windows
fixture result does not attest this cloud boundary. The controller alone owns
create/stop, grants and budget. No worker-originated TTL extension or cloud API
credential. Arbitrary code inside the guest may bypass Python tool wrappers;
external network controls and a narrowly provisioned guest must carry the limit.

Transfer only reviewed source and fixture files. Never copy the fleet checkout,
home directory, .git credentials, provider variables or global nakedagent plugins.
No host mounts, published ports, MCP gateway, persistent volumes, account-wide
policy edits, autonomous installs, Git pushes or production inputs in phase one.

## Concrete pilot sequence

1. Verify `sbx` >=0.45, authenticated Docker account, subscription/credit and
   installed CLI help. `sbx --cloud diagnose` checks access without a local daemon.
2. Resolve and record a shell kit/image identity and Python >=3.10 availability.
   No named third-party agent is necessary: nakedagent is the guest workload.
3. Before creation, validate a per-sandbox deny rule covering outbound traffic
   against current CLI syntax. Agent/kit/account rules combine; a deny-all default
   alone is insufficient proof. Do not alter account-wide rules to get the test
   working. Abort if initial isolation cannot be established before workload starts.
4. Create one uniquely named sandbox, explicit Small shape, platform linux/amd64,
   TTL 30m, explicit supported stop action. Do not silently substitute restart.
   Record ID, image/kit, creation time, TTL and effective policy. If stop is not
   supported, resolve the disposable sandbox lifecycle before creation.
5. Transfer an allowlisted source snapshot pinned to nakedagent HEAD
   `105061c4674a4e0666c4515c99476abe214a145a` plus this smoke fixture; hash every file.
   The earlier uncommitted risk prototypes are not implicitly included.
6. Run `python -m unittest discover -s tests` and
   `python docs/risk-contract/docker-sandbox/smoke.py` in the guest checkout.
   The smoke test uses a local fake HTTP model and a fresh home; it is not a model
   quality benchmark and does not itself verify Docker isolation.
7. Probe intended denied external destinations with timeouts and inspect Docker
   policy decision logs. A failed connection alone may be DNS/server failure;
   without supporting policy evidence, label the result indeterminate. Inspect
   published ports, attached volumes and actual guest identity independently.
8. Export bounded test output, source manifest, cloud configuration and policy
   decisions to the controller. Verify there, hash/receipt there, then stop and
   verify the stopped state. A stop-request acknowledgment is not terminal proof.
9. Only after phase-one evidence passes, admit one appendage at a time (Hexad,
   Decision-O, then a separately budgeted model endpoint). Compare reachable data,
   destinations, capabilities, credentials, time/cost and evidence gaps for each.

## Current evidence and open limits

Anvil has Docker CLI 29.8.1; `docker sandbox --help` reports that command removed.
`sbx` was absent from PATH and both documented installation directories at initial
inspection. Installed the official per-user `Docker.sbx` 0.46.0 through WinGet;
installer hash verification passed. Published installer SHA256:
`1b7414c5b8c5fad2718f6325d772ffefc48b8bcf456a25f4441eebc4ad1d06dc`.
Live client reports v0.46.0, commit 991967dc90ce0d9a440cd1df1bdf3e395c5a2693.
Initial `sbx --cloud diagnose` lacked authentication. After operator sign-in,
all five diagnostics passed: CLI, version, authentication, cloud API, subscription.

Local `smoke.py` execution passed four checks: CLI exit zero, expected marker
written, exactly two fake model HTTP calls, and fresh home without global plugins.
Those were local functional results. The guest subsequently passed 234 tests
and the same smoke test; boundary observations are recorded in RESULTS.md.

Cloud CLI/API are experimental. Cloud HTTP method/path restrictions are not
supported; host/path network permissions cannot express a per-action HGK grant.
Allowed model endpoints remain possible exfiltration channels. Provider control
plane compromise, guest supply chain, account identity and billing are new
appendages requiring evidence. Zero risk and exact universal runtime risk are not
measurable promises. Record exposure and uncertainty, not an invented risk score.

Sources, checked 2026-10-03:
- https://docs.docker.com/ai/sandboxes/install/
- https://docs.docker.com/ai/sandboxes/cloud/
- https://docs.docker.com/ai/sandboxes/cloud/usage/
- https://docs.docker.com/ai/sandboxes/cloud/network-policy/
- https://docs.docker.com/ai/sandboxes/cloud/local-vs-cloud/
- https://docs.docker.com/reference/cli/sbx/create/

Execution deviations: image resolved to a mutable shell-template tag, without a
reported digest; provider bootstrap network traffic was allowed before the probes;
credit balance is operator-attested, not account-verified. These remain evidence
gaps and prevent treating the first pilot as a production admission.
