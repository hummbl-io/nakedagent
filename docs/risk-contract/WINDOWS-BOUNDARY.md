# Windows boundary pilot — direct denied, broker admitted

2026-10-03 · codex · host=anvil · surface=desktop-codex · lane=risk-windows-worker-boundary.

**PASS for one enrolled public fixture and one fixed native worker.** Windows denied the worker's direct read access before and after the broker operation, denied its request for fixture ACL-write access and private-directory delete access, and denied write access to the reservation database. The broker completed one actual public-fixture read after a local HGK allow. Replay, expired evidence, exhausted reservation budget, persisted revocation and unsupported resource requests were denied or held for their respective reasons.

This is a new OS-enforced boundary for the tested objects. It is not a general sandbox for arbitrary nakedagent code, credentials, plugins, provider calls or network traffic. Independent review remains pending.

## Reproducible evidence

Final run: [windows11/report.json](C:/Users/Owner/.codex/artifacts/nakedagent-risk/2026-10-03-windows11/report.json).

| Check | Observed result |
|---|---|
| Actual child token inspected by launcher | Low integrity SID `S-1-16-4096` |
| Worker attempts `GENERIC_READ` on public fixture | Win32 `ERROR_ACCESS_DENIED` (5) |
| Worker attempts fixture `WRITE_DAC` | Win32 error 5; no ACL mutation attempted |
| Worker attempts `DELETE` access to private directory | Win32 error 5; no deletion attempted |
| Worker attempts `GENERIC_WRITE` on reservation database | Win32 error 5; no mutation attempted |
| Correct broker action | Actual HGK allow, broker reads and verifies fixture digest |
| Exact replay after coordinator objects reopen | `deny / durable_replay` |
| Evidence expiry | `require_more_evidence / evidence_binding_or_freshness` |
| Third reservation after two spent attempts | `deny / durable_budget_exhausted` |
| Revocation after storage reopen | `deny / durably_revoked` |
| Wrong resource | `deny / unsupported_effect_scope` |
| Direct read after broker responses | Still Win32 error 5 |

The report has **12 grouped acceptance checks**, six broker-request scenarios, one actual HGK call, six responses echoed by the fixed worker and a clean worker exit. These counts describe different things; they must not be summed as test cases. The live worker receives outcome metadata (including byte count/digest when successful), not raw file contents or an open fixture handle.

**48 focused Python tests pass:** prior 40 composition/contract/graph tests plus eight durable-reservation tests. These include a fresh subprocess terminating with `os._exit` after a reservation and another after a simulated effect. On reopening, both unfinished reservations stay spent and `indeterminate`; neither can be retried with the same ID. Six competing reservation clients cannot spend a one-reservation budget twice. These are process-crash and concurrency tests, not power-loss/storage-hardware tests.

Ruff passes on the three new Python files. Default mypy passes on the demo and reservation module. Native C builds with `-Wall -Wextra -Werror`. The .NET Framework C# compiler builds the launcher. No tools or dependencies were installed. Production nakedagent sources remain unchanged; its full suite was not rerun in this pass.

## Boundary mechanics

1. Python exclusively creates a new scratch output directory and a harmless public text fixture. The runner refuses an existing output directory and checks the previously pinned HGK HEAD plus clean tracked source.
2. A C# launcher applies explicit ACLs to the new worker executable, private directory and fixture. It protects children before their parent. The broker retains its explicit owner-user access; the OWNER RIGHTS ACE suppresses implicit owner `WRITE_DAC`. Recovery access is retained for the operator and SYSTEM.
3. The fixture and private directory receive a **medium-integrity mandatory label with both no-read-up and no-write-up**. Windows evaluates mandatory integrity controls separately from DACL permissions. Low integrity alone normally provides no-write-up protection, not the read protection needed here. [Microsoft MIC documentation](https://learn.microsoft.com/en-us/windows/win32/secauthz/mandatory-integrity-control), [mandatory label masks](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-system_mandatory_label_ace).
4. The launcher derives a token with maximum privilege removal (Windows retains traverse privilege under this flag), then lowers its integrity. It creates the native worker suspended, assigns it to a kill-on-close job with an active-process limit of one, inspects its actual token, and resumes it. Only two pipe handles are on the inheritance allowlist. The child environment contains only `SystemRoot` and `WINDIR`. [Restricted-token API](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-createrestrictedtoken), [handle-list API](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute).
5. A temporary, randomly named low-integrity desktop is created within the existing window station for this child. The operator's desktop ACL is not modified. The final implementation does not create a new window station. Desktop and process/job handles are closed after execution; no worker or launcher processes remained in the final process-name check. GUI attacks were not tested.
6. The worker performs fixed native `CreateFileW` access probes and sends a finite set of requests over inherited pipes. The Python coordinator maps these test requests to the existing fixed-read action envelope, checks durable reservations, invokes the composed broker and returns result metadata. This fixture protocol is not a general authenticated RPC service.

The final ACL readback for the fixture showed Owner and SYSTEM full access, OWNER RIGHTS read permissions, and medium-integrity `(NW,NR)`. The OS-denial evidence comes from fixed, source-hashed native probes; it is not an arbitrary worker's self-attested safety report.

## Durable attempt reservations

`durable_reservations.py` adds a local SQLite ledger outside the worker's write authority. Each transaction uses `BEGIN IMMEDIATE` and `synchronous=FULL`. State is bound to the exact contract digest and maximum. Opening existing state uses `mode=rw`: a missing database is an error, not permission to recreate a fresh budget. Creation uses an exclusive file open and refuses existing state.

The order is:

`validate supported resource → commit reservation → broker checks/kernel/effect → commit result`.

Reservations are an **attempt ceiling**, including an expired or otherwise denied broker attempt after reservation. They are not automatically refunded. This is deliberately more restrictive than a completed-effects counter: final run spent one reservation on the completed read and one on the expired attempt. A denied replay consumes no additional reservation. Unsupported resources are rejected before reservation.

An action ID binds the full action digest. An identical ID/body is a replay; changed content under the same ID is a collision. A crash after reservation leaves the phase `reserved`, surfaced as `indeterminate`. The stored state does not pretend to know whether an effect happened, and no automatic retry occurs. The tests demonstrate this before and after a simulated effect.

Revocation is persistent and gates **new reservations**. It does not cancel an already reserved/in-flight operation atomically. The original broker still rechecks evidence around the kernel call; a separate cross-process revocation linearization design is needed before promising immediate cancellation. SQLite durability depends on the host/filesystem and is not protection against a compromised medium-integrity broker or operator.

## Provenance through reopening

`before-reopen.receipts.json` contains the first coordinator's linked loadout, source evidence, durable reservation, kernel request/response, broker outcome and finalization. `composition.receipts.json` belongs to the reopened coordinator and references the prior checkpoint. The report retains the outcomes, native transcript, contract-bound reservation snapshot, actual HGK receipt reference, and source/executable hashes.

HGK HEAD: `4e7a06359eae81b3c48f2a57cd82c5fca7e0bf40`. Its existing action classifier is exercised; it does not newly enforce the composition's full contract or CER fields. Those bindings remain broker responsibilities. Existing `lab_in_process_only` result labels are preserved for the Python checks; the external Windows resource tests are reported separately rather than upgrading every control to OS enforcement.

The JSON receipt exports are post-run snapshots, not an atomic transaction with the physical effect. If the broker crashes after a read but before recording its outcome, the durable reservation remains indeterminate. There is no exactly-once effect guarantee, signature infrastructure, externally anchored checkpoint or automatic recovery adjudication.

## Experiments that failed, and why they do not count as success

The retained output directories are separate attempts, never overwritten:

- `windows01`: compiler could not create output when the minimal compiler environment lacked a writable TEMP/TMP. The compiler environment now points these to the new scratch directory. No security product or host policy was disabled.
- `windows02`: parent-first ACL protection stripped inherited child-file access before explicit child protection. The final code protects children first and supplies inheritable broker/SYSTEM grants. Owner access to the affected public scratch artifacts was restored with exact-target `icacls` grants; no unrelated paths were changed. This early exception did not produce a complete report.
- `windows03`–`windows08`: alternative restricting-SID setups failed during startup, or at required logon-SID/private-window-station setup. Exit codes included `0xC0000022` and `0xC0000142`. Their precise loader causes were not established; they are not evidence that this mechanism is impossible. A native worker alone did not solve that startup path. None passed the direct-denied/broker-allowed criterion.
- `windows09`: the MIC-based fixed-worker boundary passed before durable reservations were integrated.
- `windows10`: durable integration passed, preceding final scope-validation, receipt-link and source-cleanup changes.
- **`windows11`: final reviewed-by-author source snapshot and all 12 acceptance checks pass.**

The first two failures are described from captured tool output. Later attempts retain machine-readable reports. No claim is made that failed attempts have complete forensic logs.

## Current limits and next lane

- Only one known public file and one fixed native worker were tested. No arbitrary hostile plugin, Python interpreter, package installer, model runtime or credential store was enrolled.
- No network requests were made by the test worker; **network blocking is not enforced or tested**. Low integrity does not prevent all reads of the user's other medium-integrity data. Explicit no-read-up labels apply only to the new enrolled fixture/directory.
- Job limits and handle inheritance were configured successfully, but child-spawn, handle-stealing and GUI escape attempts were not comprehensively tested. Read-time races, links/reparse points, executable replacement and hostile broker-host compromise require separate treatment before accepting arbitrary callers or artifacts.
- Authority, source evidence, time and principal mapping remain synthetic trusted laboratory inputs. A named collector is not an authenticated collector. User control over this experiment is not a deployable capability credential.
- The source-selected component graph is not a complete dependency inventory of .NET, LLVM, Windows, Python or HGK. Build/runtime dependencies are explicit in this report but not all admitted by the prototype contract.
- A successful broker read returns only result metadata here. A future content-delivery capability needs explicit data-flow, size, recipient and retention policy.
- The database's replay/budget invariants survived tested process crashes; reservation/effect/outcome atomicity, in-flight cancellation and failover remain open.

**Next:** independent review of the Windows token/label/handle boundary and durable state protocol, then enroll a narrowly authenticated evidence collector. Any general Python/plugin worker needs a stronger allowlist/isolation design and adversarial tests first. Keep recovery operations owner-controlled and logged; do not infer production readiness from this public-fixture result.

## Run locally

From the isolated worktree root, with the already installed Windows tools:

```powershell
python -m unittest discover -s docs/risk-contract -p 'test_*.py'
ruff check docs/risk-contract/windows_boundary_demo.py docs/risk-contract/durable_reservations.py docs/risk-contract/test_durable_reservations.py
mypy docs/risk-contract/windows_boundary_demo.py docs/risk-contract/durable_reservations.py
python docs/risk-contract/windows_boundary_demo.py --kernel-root C:/Users/Owner/PROJECTS/hummbl-governance-kernel --output C:/Users/Owner/.codex/artifacts/nakedagent-risk/NEW-UNUSED-DIRECTORY
```

The demo expects .NET Framework 4 C# compiler, LLVM clang/lld-link and the Windows 10.0.19041.0 x64 import library at their pinned local paths. Missing prerequisites fail rather than trigger installation. All permission changes are confined to the newly created output directory. No commits or pushes were made.
