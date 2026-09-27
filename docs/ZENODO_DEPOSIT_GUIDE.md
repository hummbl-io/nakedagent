# Zenodo Deposit Guide — NakedAgent Research Paper

This guide outlines the exact, paste-ready procedure for publishing the **NakedAgent** preprint and software release to [Zenodo](https://zenodo.org).

---

## 1. Paper Files to Deposit

Located in the `paper/` directory of the `nakedagent` repository:
1. **Primary PDF**: `paper/nakedagent_paper.pdf` (compiled, 4 pages, publication-grade layout)
2. **LaTeX Source**: `paper/nakedagent_paper.tex`
3. **BibTeX References**: `paper/references.bib`
4. **Metadata Specification**: `paper/.zenodo.json`

---

## 2. Paste-Ready Zenodo Metadata

When depositing via [Zenodo New Upload](https://zenodo.org/uploads/new):

| Field | Value |
|---|---|
| **Resource type** | Publication → Preprint |
| **Title** | `NakedAgent: A Zero-Dependency Coding Agent Architecture via Standard-Library Primitives and Provable Replay` |
| **Publication date** | `2026-09-25` (or date of deposit) |
| **Authors** | Family: `Bowlby`, Given: `Reuben` |
| **Affiliation** | `HUMMBL, LLC` |
| **ORCID** | `0009-0002-5620-1103` |
| **License** | `Creative Commons Attribution 4.0 International` (CC-BY-4.0) |
| **Language** | English (`eng`) |
| **Publisher** | Zenodo |

### Keywords
```
autonomous coding agents; zero dependencies; software engineering; standard library; tamper-evident audit logs; mealy state machine; offline replay; merkle state hash; SWE-bench; local LLM inference; Ollama; omakase design
```

### Abstract / Description
```
Autonomous software engineering agents driven by Large Language Models (LLMs) increasingly rely on expansive, multi-tiered dependency trees. Mainstream agent scaffolds (e.g., SWE-agent, Aider, OpenHands) import between 20 and 50+ third-party packages to facilitate HTTP communication, terminal UI rendering, provider protocol abstraction, and telemetry. While feature-rich, this architectural paradigm introduces substantial supply-chain vulnerability attack surfaces, runtime version fragility, and heavy deployment footprints. In this paper, we introduce NakedAgent, an autonomous coding agent engineered under a strict zero-runtime-dependency constraint: it executes entirely upon standard Python 3.10+ library modules (urllib, json, subprocess, re, and hashlib). NakedAgent decouples tool invocation from proprietary JSON function-calling schemas by utilizing a Markdown fenced code-block protocol, enabling consistent tool use across local models (such as Qwen 2.5-Coder and Gemma 3) and hosted endpoints. To establish auditability and non-repudiation, we model agent execution as a pure Mealy state machine reducer (S_t, E_t) -> (S_{t+1}, A_{t+1}), combined with SHA-256 Merkle-linked state hashing recorded in an append-only JSON Lines (JSONL) event log. This architecture enables zero-inference offline replay verification, validating tool execution histories without querying an LLM. We present empirical findings from a SWE-bench Lite pilot with local 12B models, delineating scaffold-induced failure modes from model-inherent reasoning bounds. Finally, we formulate the Omakase extensibility doctrine, demonstrating how clean tool substitution seams empower extensible agent behaviors without framework bloat.
```

### Related Identifiers
| Identifier | Relationship | Scheme |
|---|---|---|
| `https://github.com/hummbl-io/nakedagent` | `isSupplementTo` | URL |
| `https://pypi.org/project/nakedagent/` | `isIdenticalTo` | URL |

---

## 3. Upload & DOI Reservation Procedure

1. Navigate to: **[https://zenodo.org/uploads/new](https://zenodo.org/uploads/new)**
2. In the **Files** section, upload:
   - `paper/nakedagent_paper.pdf`
   - `paper/nakedagent_paper.tex` (optional companion source)
   - `paper/references.bib` (optional companion source)
3. In the **Basic information** section, click **Reserve DOI**.
   - Note the assigned DOI (e.g. `10.5281/zenodo.12345678`).
4. Paste the metadata fields from Section 2 above.
5. Click **Save draft** and inspect the preview.
6. Click **Publish**.

---

## 4. Automatic Software DOI via GitHub Integration (Recommended)

To have Zenodo automatically mint a DOI for every software release of `nakedagent`:
1. Log into Zenodo and go to **Settings → GitHub** ([https://zenodo.org/account/settings/github/](https://zenodo.org/account/settings/github/)).
2. Find `hummbl-io/nakedagent` in the repository list and toggle the switch to **ON**.
3. Whenever a release tag (e.g. `v0.1.0`) is published on GitHub, Zenodo will automatically archive the release tarball and assign a persistent Software DOI using `.zenodo.json`.
