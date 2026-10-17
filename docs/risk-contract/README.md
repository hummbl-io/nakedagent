# nakedagent risk contract prototype

Start with [CONTRACT.md](CONTRACT.md), then open [dashboard.html](dashboard.html) in a browser. Fleet operations is the first audience; a developer audience toggle keeps the same evidence requirements.

[KERNEL-LINK.md](KERNEL-LINK.md) maps the contract into the existing governance kernel and explains the difference between admission decisions and effect enforcement.

**Latest milestone:** [WINDOWS-BOUNDARY.md](WINDOWS-BOUNDARY.md) records a low-integrity native worker denied direct access to one enrolled public fixture while the HGK-gated broker read succeeds, plus persistent attempt reservations. Twelve live acceptance checks and 48 focused tests pass. This is scoped OS enforcement for the tested objects, not a general agent sandbox. [COMPOSITION.md](COMPOSITION.md) and [PILOT-RESULTS.md](PILOT-RESULTS.md) retain the earlier milestones; authority and evidence remain synthetic.

This directory adds a draft contract, source inventory, offline dashboard and bounded laboratory demonstrators. It does not modify the production agent or install monitoring. The Windows demo explicitly creates labeled scratch objects and a restricted fixed child process; it is not a production engine or general sandbox. The dashboard remains offline.

Run the focused tests from the repository root:

```powershell
python -m unittest discover -s docs/risk-contract -p 'test_*.py' -v
```

`risk_model.py` accepts a caller-supplied JSON snapshot and explicit epoch time. See the test fixture for the graph format. `inventory_complete` and `verified` are untrusted input assertions in this demonstrator, not attestations. Graph edges are unconditional potential transitions: typed scopes, conditions, deny rules, authentication, collector health, budget accounting, authority validation and production dispatch are specified in the contract but not implemented. Therefore even a fresh complete snapshot never yields execution authorization.

Release posture: architecture 0.1.0 draft, bounded pilot schema 0.2.0; local uncommitted worktree; not a frozen or signed release. Full runtime implementation requires the review and containment gates in the contract.
