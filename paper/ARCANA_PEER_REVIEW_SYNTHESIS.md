# NakedAgent Independent Peer Review Synthesis

**Method**: 4 independent ARCANA-archetype subagents, blind to author intent, blind to gold labels, explicitly authorized to reject the entire work product.  
**Reviewers**:
1. **Karl Popper** (`popper`): Falsifiability, Conjectures & Refutations, Demarcation, Duty to Refute, Immunization Stratagems.
2. **Bruce Schneier** (`schneier`): Threat Modeling, Security Theater vs. Real Defense, Adversarial Reading, Attack Surfaces.
3. **Measurement & Metrology** (`measurement`): Goodhart's & Campbell's Laws, Proxy vs. Terminal Values, Metrics Gaming, Sample Power, Politics of Quantification.
4. **Paul Feyerabend** (`feyerabend`): Against Method, Epistemological Anarchism, Proliferation vs. Monolithic Method, Incommensurability.

**Target Work Products**:
- `paper/nakedagent_paper.tex` (Scholarly Preprint Manuscript)
- `bench/RESULTS.md` (SWE-bench Lite Pilot Trajectory & Scoring Log)
- `DOCTRINE.md` (NakedAgent Architectural Doctrine)

---

## Headline Verdict

| Reviewer | Lens | Verdict | Strongest Core Objection |
|---|---|---|---|
| **Popper** | Epistemology & Falsifiability | **REJECT** | **The Supply-Chain Externalization Fallacy**: Eliminating PyPI packages merely externalizes dependencies into unversioned ambient system binaries; Table 1 immunizes the core thesis by omitting 0/3 resolved tasks, substituting a "valid patches" proxy, and contradicting DOCTRINE.md. |
| **Schneier** | Security & Threat Modeling | **REJECT** | **The Zero-Click Repo Plugin Backdoor**: Eliminating audited PyPI packages while automatically executing unauthenticated `.nakedagent/plugins/*.py` from cloned untrusted repositories introduces immediate RCE; shell prefix allowlist is trivially bypassed via `write` + allowlisted binary. |
| **Measurement** | Metrology & Quantification | **REVISE** | **The Epistemic Vacuity of Merkle Replay**: Cryptographic hashing verifies internal reducer arithmetic ($A=A$), not external task correctness or environmental execution; Table 1 substitutes a gamed "valid patches" surrogate to obscure 0/3 resolved tasks and conceals an uncontrolled temperature disparity. |
| **Feyerabend** | Methodological Anarchism | **REJECT** | **The Tautological Replay Illusion & Standard-Library Chauvinism**: The Merkle verifier is a self-referential tautology certifying an internal ledger rather than reality; Table 1 presents incommensurable comparisons, category errors, and harness bugs as empirical science. |

### Tally
- **REJECT**: 3
- **REVISE**: 1
- **RETAIN**: 0  
**Overall Synthesis Disposition**: **REJECT IN PRESENT FORM / REVISE WITH MAJOR RE-FOUNDING**.

---

## Convergence: Findings Agreed by $\ge 3$ Reviewers

### C1. The Tautological Replay Illusion / Cryptographic Solipsism ($A = A$)
*(Agreed by 4 reviewers: Popper, Schneier, Measurement, Feyerabend)*

* **The Finding**: The paper repeatedly claims that SHA-256 Merkle-linked state hashing recorded in an append-only JSONL event log enables "provable execution," "mathematical certification," and "zero-inference offline replay verification." All four reviewers converged on the finding that this is a mathematical tautology:
  $$\text{Replay}(e_1 \dots e_N) \implies \text{Hash}(S_N) = H_N$$
  This proves solely that feeding the recorded JSON strings back into the Python dictionary reducer yields the same state values stored in the file.
* **Why Authoritative**: 
  - It does **not** prove tool outputs were authentic or untampered at generation time.
  - It provides **zero non-repudiation** without asymmetric public-key cryptography (e.g. Ed25519) anchored in an external key infrastructure.
  - It is completely blind to environmental execution drift and corruption. The author's own Run C2 proved this: the internal event log showed clean patch transitions that verified offline, while the actual filesystem container had its line endings converted to CRLF, corrupting git.
  - An agent hijacked by indirect prompt injection executing a malicious shell exfiltration will verify with a 100% cryptographic `PASS`.
* **Action Required**: Retract the claims of "provable software engineering" and "mathematical certification." Reframe the Merkle log as a **high-fidelity internal deterministic state reconstruction and regression-testing audit trail**, clearly documenting that it does not certify semantic correctness, external execution veracity, or injection immunity.

---

### C2. Section 6 and Table 1 Metrological Collapse (0/3 Resolved Masked as "Valid Patches")
*(Agreed by 4 reviewers: Popper, Schneier, Measurement, Feyerabend)*

* **The Finding**: Section 6 claims to present an "Empirical Evaluation: SWE-bench Lite Pilot." In reality:
  1. **Primary Benchmark Outcome**: NakedAgent scored **0/3 resolved (0.0%)**. The single patch generated in Run C3 failed 2 targeted bugfix tests and caused **7 unit test regressions**; the other two instances produced zero patches.
  2. **Surrogate Metric Displacement (Campbell's Law)**: Table 1 omits the standard benchmark metric ("Resolved") entirely, inventing the surrogate metric "Valid Patches" (reporting 1/3) to manufacture the visual illusion of progress over mini-swe-agent's 0/3.
  3. **Concealed Temperature Confounder**: The paper formally asserts: *"Model: Google gemma3:12b served locally via Ollama with 4-bit quantization and temperature set to 0."* Yet `bench/RESULTS.md` admits: *"nakedagent's llm.chat sends no temperature (Ollama default, not 0), while mini-swe-agent ran at temperature 0 — a parity gap to close."* Ollama's default temperature is $\approx 0.8$. Comparing mini-swe-agent at $T=0$ (greedy, prone to format loops) against NakedAgent at $T\approx 0.8$ violates measurement invariance.
  4. **Unrepresentative Sample**: $n=3$ on a single repository (Astropy) has zero statistical power (Wilson 95% CI: $[0.00, 0.56]$) and cannot support the sweeping conclusion that NakedAgent is a "production-viable architecture."
* **Why Authoritative**: Presenting an informal, exploratory debugging pilot as a formal empirical evaluation while omitting the ground-truth benchmark metric and misstating the temperature condition represents a failure of scientific reporting.
* **Action Required**: 
  - Retitle Section 6 to *"Exploratory Pilot: Failure Modes of Local Models under Minimal Scaffolding"*.
  - Add the true benchmark metric: **Resolved: 0/3 across all configurations**.
  - Document the test regressions (7 `PASS_TO_PASS` regressions on 12907).
  - Explicitly correct the temperature disclosure: NakedAgent ran at default Ollama temperature, representing an uncontrolled experimental variable.

---

### C3. The Supply-Chain Laundering / Ambient Subprocess Paradox
*(Agreed by 4 reviewers: Popper, Schneier, Measurement, Feyerabend)*

* **The Finding**: The foundational invariant $|\mathcal{D}_{\text{runtime}}| = 0$ is framed as eliminating supply-chain attack surfaces and dependency fragility: *"no supply chain, because there is no supply."* All four reviewers identified this as an externalization fallacy.
* **Why Authoritative**: 
  - Eliminating third-party packages from `sys.modules` does not eliminate dependencies; it shifts them across the `subprocess.run` boundary into unmanaged, unpinned ambient system binaries (`bash`, `git`, `sed`, `docker`, host dynamic libraries, and `$PATH`).
  - Python packages declared in `pyproject.toml` can be pinned by SHA-256 hashes, scanned by pip-audit/Dependabot, and sandboxed in virtual environments. Ambient system binaries called via shell have none of these controls.
  - The pilot itself demonstrated this ambient fragility: Run C1 failed because ambient bash choked on `<...>` angle brackets; Run C2 failed because the ambient Windows text-mode pipe converted line endings to CRLF.
* **Action Required**: Reframe standard-library minimalism from a security panacea into an **engineering trade-off** for ultra-minimal deployment footprints (embedded devices, minimal containers, recovery shells). Acknowledge that the operational security boundary of a coding agent resides in OS-level process sandboxing and file quarantine, not in the absence of PyPI imports.

---

### C4. The Zero-Click Repo-Drop Plugin RCE & Shell Allowlist Bypass
*(Agreed by 3 reviewers: Schneier, Popper, Feyerabend)*

* **The Finding**: In `nakedagent/plugins.py`, `load_plugins()` unconditionally globs and executes every Python file found in `<workspace>/.nakedagent/plugins/*.py` using `importlib` and `exec_module` at startup.
* **Why Authoritative**: 
  - This creates an unauthenticated remote code execution vulnerability. If a developer clones an untrusted repository containing a malicious plugin and runs `nakedagent "explain this code"`, the attacker's Python payload executes immediately with the developer's full host privileges before any prompt is parsed or tool invoked.
  - Furthermore, the prefix-based `--shell-allowlist` check (e.g. `--shell-allowlist "pytest"`) is trivially bypassed: an attacker or injected LLM can invoke `write` to create `tests/evil.py` and invoke `shell: pytest tests/evil.py`. Any allowlisted test runner or interpreter is an instant RCE vector when paired with unrestricted file writing.
  - Writing to `.git/hooks/` allows an agent to install persistent host backdoors.
* **Action Required**: 
  - Delete or strictly gate repo-local plugin loading (`--trust-plugins` required; prompt user with file content before execution).
  - Explicitly restrict the `write` and `patch` tools from modifying `.git/`, `.nakedagent/`, or executable shell scripts.
  - Require OS-level sandboxing (Docker/containers/Landlock) when running in automated modes.

---

## Dissent Map: What Lone Reviewers Surfaced

### D1. Schneier: Lack of Filesystem Rollback and Checkpointing
* **The Objection**: When an LLM hallucinates a broken patch or a destructive shell command, NakedAgent has no transactional rollback mechanism (git tree snapshots, stashes, or filesystem shadow copies). The workspace remains corrupted, driving the agent into self-inflicted error loops.
* **Significance**: While raised by Schneier from a resilience and integrity perspective, this is a critical systems feature that directly explains why small models degenerate into attractor states.

### D2. Feyerabend: Dogmatic Rejection of Superior Instruments (Tree-Sitter / Diff Engines)
* **The Objection**: Banning external libraries prevents the agent from using semantic AST parsers (e.g. Tree-sitter) or tolerant unified-diff engines. The exact substring requirement of the foundation `patch` tool ($count = 1$) acts as an entropy trap for autoregressive models.
* **Significance**: Highlights that standard-library purism actively reduces agent problem-solving capability by denying the agent modern programming language infrastructure.

### D3. Popper: Unfalsifiable Doctrine Rhetoric
* **The Objection**: `DOCTRINE.md` lines 93–95 assert that NakedAgent *"proves a 7B model and four tools are enough to do real work"*. This statement is flatly contradicted by the project's own SWE-bench pilot logs.
* **Significance**: Puts the reputation of the project at risk by asserting proven capability where empirical evidence demonstrates 0% task resolution.

---

## What Survives Independent Review

The review was unsparing, but it was not uniformly negative. Across all four adversarial lenses, the following core contributions **survived with high honors**:

1. **The Algebraic Mealy Machine Reducer (`functional.py`)**:
   Modeling the agent loop as a pure, referentially transparent state transition $\delta(S_t, E_t) \to (S_{t+1}, [A_{t+1}])$ strictly separating logic from side-effecting I/O drivers (`driver.py`) is exemplary, robust, and clean software architecture.
2. **Markdown Code-Fence Tool Dispatch over Vendor JSON Schemas**:
   The architectural choice to use Markdown triple-backtick blocks (` ```patch `, ` ```read `) instead of provider-native JSON function-calling schemas is an authentic, reproducible insight that allows open-weights models (7B–12B) to invoke tools without decoding crashes.
3. **The Fail-Closed Patch Invariant**:
   Enforcing that `patch` SEARCH blocks must match uniquely ($count == 1$) prevents silent multi-site corruption.
4. **The Zero-Dependency MCP Client**:
   A stdlib-only JSON-RPC 2.0 client over `stdio` implementing the Model Context Protocol is a valuable, lightweight utility for agent mesh interoperability.
5. **The Candor of `RESULTS.md`**:
   The internal engineering notes in `RESULTS.md` demonstrated genuine scientific integrity in capturing real-world harness bugs (CRLF conversions, bracket echoing, temperature gaps).

---

## What Does NOT Survive

1. **The "Zero Supply-Chain Vulnerability" Claim**: Did not survive. The attack surface is simply externalized to the shell and ambient system binaries, and compounded by the repo-local plugin loader.
2. **The "Provable Execution / Mathematical Certification" Claims for Merkle Replay**: Did not survive. Replay proves only internal dictionary arithmetic, not external execution validity or security.
3. **Table 1 and Section 6 as an "Empirical Benchmark"**: Did not survive. An $n=3$ trial with 0/3 resolved tasks, gamed surrogate metrics, and an uncontrolled temperature variable cannot be published as empirical validation.
4. **The Claim that 4 Tools and a 7B/12B Model Are Proven "Enough for Real Work"**: Did not survive. Refuted by the pilot's 0% resolution score.
5. **Unauthenticated Repo-Local Plugin Loading**: Did not survive. Must be excised as a zero-click RCE backdoor.

---

## Recommended Next Actions (Priority Order)

### P1. Scientific & Metrological Manuscript Remediation
1. **Retitle Section 6** of `paper/nakedagent_paper.tex` to: *"Exploratory Pilot: Failure Modes of Local Models under Minimal Scaffolding"*.
2. **Add Ground-Truth Benchmark Results**: Include the true resolution metric: **0/3 resolved (0%)**, and explicitly report the 7 unit test regressions on instance 12907.
3. **Correct Temperature Disclosure**: Transparently state that NakedAgent ran at Ollama's default temperature ($\approx 0.8$) while mini-swe-agent ran at $T=0$, acknowledging this as an uncontrolled variable.
4. **Demystify the Replay Verifier**: In Section 3, explicitly state that the Merkle log certifies **internal transcript causality and reducer determinism**, NOT external environment execution or semantic safety.

### P2. Critical Security Fixes
1. **Neutralize Repo-Local Plugin Execution**: In `nakedagent/plugins.py`, disable automatic loading of `<workspace>/.nakedagent/plugins/`. Require an explicit `--trust-plugins` flag and display a confirmation prompt before executing workspace code.
2. **Defend File Modification Boundaries**: In `nakedagent/tools.py`, explicitly forbid `write` and `patch` operations targeting `.git/`, `.nakedagent/`, or executable shell scripts.
3. **Document Sandboxing Prerequisite**: In `README.md` and `DOCTRINE.md`, state explicitly that running `nakedagent` with `--allow-shell` requires an OS-level container sandbox (e.g. Docker or Podman) to protect the host.

### P3. Doctrine & Reputational Alignment
1. **Amend `DOCTRINE.md`**: Strike line 94 (*"proves a 7B model and four tools are enough to do real work"*). Replace with an honest framing of an ongoing empirical investigation into the lower bounds of agent scaffolding.
2. **Re-compile Paper & Update Zenodo Package**: Once `nakedagent_paper.tex` is amended with these honest disclosures, re-compile `paper/nakedagent_paper.pdf` and update `.zenodo.json` prior to public submission.
