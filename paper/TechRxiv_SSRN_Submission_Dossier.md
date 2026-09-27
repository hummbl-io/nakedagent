# Preprint Submission Dossier: NakedAgent

**Paper:** *NakedAgent: A Zero-Dependency Coding Agent Architecture via Standard-Library Primitives and Provable Replay*  
**Canonical Zenodo DOI:** [`https://doi.org/10.5281/zenodo.23001340`](https://doi.org/10.5281/zenodo.23001340)  
**Camera-Ready PDF Location:**  
```text
C:\Users\Owner\PROJECTS\nakedagent\paper\nakedagent_paper.pdf
```

---

## 1. Universal Author & License Metadata

- **Primary Author:** Reuben Bowlby
- **Affiliation:** HUMMBL, LLC
- **Email:** reuben@hummbl.io
- **ORCID:** [0009-0002-5620-1103](https://orcid.org/0009-0002-5620-1103)
- **License:** Creative Commons Attribution 4.0 International (CC-BY-4.0)
- **Competing Interests:** None / Authors declare no competing financial or non-financial interests.
- **Related Identifier (Preprint Link):** `isSupplementTo` https://doi.org/10.5281/zenodo.23001340

---

## 2. Title & Abstract (Copy-Paste Ready)

### Title
```text
NakedAgent: A Zero-Dependency Coding Agent Architecture via Standard-Library Primitives and Provable Replay
```

### Abstract
```text
Autonomous software engineering agents driven by Large Language Models (LLMs) increasingly rely on expansive, multi-tiered dependency trees. Mainstream agent scaffolds (e.g., SWE-agent, Aider, OpenHands) import between 20 and 50+ third-party packages to facilitate HTTP communication, terminal UI rendering, provider protocol abstraction, and telemetry. While feature-rich, this architectural paradigm introduces substantial supply-chain vulnerability attack surfaces, runtime version fragility, and heavy deployment footprints. In this paper, we introduce NakedAgent, an autonomous coding agent engineered under a strict zero-runtime-dependency constraint: it executes entirely upon standard Python 3.10+ library modules (urllib, json, subprocess, re, and hashlib). NakedAgent decouples tool invocation from proprietary JSON function-calling schemas by utilizing a Markdown fenced code-block protocol, enabling consistent tool use across local models (such as Qwen 2.5-Coder and Gemma 3) and hosted endpoints. To establish auditability and tamper-evident transcript integrity, we model agent execution as a pure Mealy state machine reducer (St, Et) -> (St+1, At+1), combined with SHA-256 Merkle-linked state hashing recorded in an append-only JSON Lines (JSONL) event log. This architecture enables zero-inference offline replay verification, validating tool execution histories without querying an LLM. We present empirical findings from a SWE-bench Lite pilot with local 12B models, delineating scaffold-induced failure modes from model-inherent reasoning bounds. Finally, we formulate the Omakase extensibility doctrine, demonstrating how clean tool substitution seams empower extensible agent behaviors without framework bloat.
```

### Keywords (Comma-Separated)
```text
autonomous coding agents, software engineering, zero dependencies, provable replay, state machine, SWE-bench, standard library
```

---

## 3. Venue-Specific Form Fields

### A. TechRxiv (IEEE) — https://www.techrxiv.org/submit
- **Primary Category:** `Computer Science - Software Engineering`
- **Secondary Category:** `Computer Science - Artificial Intelligence`
- **Existing DOI:** Leave BLANK (Do NOT enter Zenodo DOI; TechRxiv requires this to be an unpublished preprint)
- **File to Upload:** Select `nakedagent_paper.pdf` in this directory.

### B. SSRN (Elsevier) — https://hq.ssrn.com/submissions/CreateNewSubmission.cfm
- **Subject Classifications / Networks:**
  - `Information Systems & eBusiness Network (ISN)`
  - `Software Engineering and Architecture`
- **JEL Classification Codes:** `C88, L86, M15`
- **File to Upload:** Select `nakedagent_paper.pdf` in this directory.

### C. Preprints.org (MDPI) — https://www.preprints.org/user/manuscript/submission
- **Field:** `Computer Science and Mathematics > Software Engineering`
- **File to Upload:** Select `nakedagent_paper.pdf` in this directory.

### D. Hugging Face Papers — https://huggingface.co/papers
- **Paper Title:** `NakedAgent: A Zero-Dependency Coding Agent Architecture via Standard-Library Primitives and Provable Replay`
- **PDF URL:** `https://doi.org/10.5281/zenodo.23001340`
- **Repository URL:** `https://github.com/hummbl-io/nakedagent`
- **Framework:** `Python Standard Library`
