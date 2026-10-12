# NakedAgent paper

The **unreleased living manuscript** is [nakedagent_paper.tex](nakedagent_paper.tex), revised October 10, 2026, with [references.bib](references.bib). Its title is *NakedAgent: Standard-Library Coding Agents with Explicit Effect Boundaries and Offline Replay*. It describes the Python reference at commit `0c96f1a8adac035b9d204ebc78c5eb4175c13685`, not every port or deployment.

The repository-recorded historical DOI is [10.5281/zenodo.23001340](https://doi.org/10.5281/zenodo.23001340). This revision does not create a DOI or claim the remote deposit was independently checked.

## Artifact status

| File | Status |
|---|---|
| `nakedagent_paper.tex`, `references.bib` | Current review source; changes include substantive corrections to earlier claims |
| `check_claims.py` | New offline source inventory and eight synthetic checks; no model or real tool execution |
| [nakedagent.notebook.md](nakedagent.notebook.md) | Post-hoc audit record and prospective evaluation plan |
| `nakedagent_paper.pdf`, `nakedagent_paper.html`, `nakedagent_paper.bbl` | Preserved historical renderings; **do not describe the revised manuscript** |
| `NakedAgent_arxiv_bundle.tar.gz` | Preserved historical source bundle; not regenerated |
| `.zenodo.json`, `TechRxiv_SSRN_Submission_Dossier.md` | Historical deposit/submission material; not approved metadata for this revision |
| `ARCANA_PEER_REVIEW_SYNTHESIS.md` | Historical review record; its verdict does not apply to the new source |

Historical metadata and renderings contain claims narrowed in the living manuscript, including non-repudiation, supply-chain elimination and execution proof. Do not use them to submit the new version. A future release needs consistent new renderings, reviewed metadata and a complete source/check archive. The original artifacts remain unchanged so the correction is traceable.

## Source-to-claim map

All paths below refer to the pinned commit. The claim checker rejects runtime source that differs from that baseline, after normalizing Git/worktree line endings.

| Claim | Source | What it does not establish |
|---|---|---|
| No declared third-party Python runtime packages | `pyproject.toml`; static imports in `nakedagent/*.py` | No build requirements, no interpreter/provider risk, or dependency-free plugins |
| Ordered, nesting-aware fenced-call parsing | `nakedagent/toolcall.py`; `spec/SPEC.md` | Superior model compliance or injection resistance |
| File and shell tool behavior | `nakedagent/tools.py` | Atomic writes, universal path isolation, or safe semantics for every allowed program |
| Registry substitution updates prompt examples | `nakedagent/plugins.py`, `nakedagent/loop.py` | Plugin sandboxing or correctness of `.usage` text |
| Optional functional driver | `nakedagent/cli.py`, `nakedagent/driver.py` | All CLI paths use the reducer or install Sidekick policy |
| Hash-linked events and replay | `nakedagent/functional.py`, `eventlog.py`, `replay.py` | Authenticated origin, full effect causality, genuine model identity or actual tool effects |
| Tri-state extension point | `nakedagent/sidekick.py` | A calibrated risk estimate or cryptographic approval protocol |
| Historical pilot observations | `bench/RESULTS.md`, `bench/run_nakedagent_swebench.py`, `bench/score_preds.py` | Reproduced raw trajectories, controlled comparison or general task-success rate |

The current foundation conformance specification excludes replay, the functional driver, Sidekick and MCP. Foundation port conformance therefore cannot be cited as evidence for those features.

## Offline checks

From the repository root, on Python 3.10+:

```text
python paper/check_claims.py
python -m examples.replay_demo
python -m unittest discover -s tests
git diff --check -- paper
```

The claim checker writes JSON to stdout and creates only temporary synthetic logs. It imports pinned runtime functions directly without loading plugins. Expected cases include stale-hash edit rejection, coherent rewritten-history acceptance, acceptance of a reported tool result without a prior request, missing-final and post-terminal rejection, and event-budget dispatch boundaries. These are small falsifiable examples of the paper's scope, not exhaustive verification or a benchmark rerun.

## Build the living paper

Use an already installed TeX distribution with `pdflatex`, `bibtex` and the packages listed in the preamble. Run **all build commands from a separate build directory**, giving the TeX source's absolute path and setting the bibliography search path. Compiling from `paper/` can accidentally load the archived BBL instead of the new bibliography.

PowerShell example; substitute the actual paths and create an empty build directory first:

```powershell
$env:BIBINPUTS = 'C:/absolute/path/to/nakedagent/paper;'
Push-Location 'C:/absolute/path/to/build'
pdflatex -no-shell-escape -interaction=nonstopmode -halt-on-error C:/absolute/path/to/nakedagent/paper/nakedagent_paper.tex
bibtex nakedagent_paper
pdflatex -no-shell-escape -interaction=nonstopmode -halt-on-error C:/absolute/path/to/nakedagent/paper/nakedagent_paper.tex
pdflatex -no-shell-escape -interaction=nonstopmode -halt-on-error C:/absolute/path/to/nakedagent/paper/nakedagent_paper.tex
Pop-Location
```

On MiKTeX, `--disable-installer` can additionally prevent automatic package installation. Do not overwrite the historical PDF or BBL. Review the generated `nakedagent_paper.pdf` and log in the build directory; a successful compile does not validate scientific claims. The revision notebook records the observed build/test results and unresolved data limitations.
