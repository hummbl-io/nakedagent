# Validation — 2026-10-03

This section records the initial 0.1 milestone. See [PILOT-RESULTS.md](PILOT-RESULTS.md) for the subsequent 0.2 lab milestone: 30 focused tests, lint/type checks and six actual local HGK admission scenarios.

- Focused graph-model suite: **9 tests passed**. Composition paths, unchanged effect counts with new paths, exact expiry, future/invalid observations, removal of control evidence, cycles, incomplete/unverified evidence, non-authorizing output and invalid references.
- Existing nakedagent unittest suite: **234 tests passed**. Existing tests emitted ResourceWarnings for HTTPError fixture cleanup; suite result was OK.
- Dashboard inline JavaScript: `node --check` passed. The first check harness hit Windows cp1252 encoding on an arrow character; it was stopped and rerun successfully with UTF-8 bytes. This was a harness issue, not a dashboard syntax failure.
- Browser rendering and interaction have **not** been verified. No live runtime sensors, kernel connection, enforcement, model calls or provider transactions were tested by this prototype.
- `source-inventory.json` records static source/plugin digests. The global plugin was inventoried without import; no credential values were collected.
- No existing agent source or governance policy was changed. New files remain local and uncommitted on `feat/codex/runtime-risk-contract`; nothing pushed or deployed.

Next proof obligation is integration: verify denied effects cannot bypass the kernel/broker, and that contract/config changes invalidate admission before execution. Unit tests for the graph demonstrator cannot establish that guarantee.
