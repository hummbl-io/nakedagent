# NakedAgent research notebook

## Provenance

This is a **post-hoc source audit**, begun October 10, 2026. It is not the notebook of the September 14 pilot and not a preregistration. The baseline is `0c96f1a8adac035b9d204ebc78c5eb4175c13685`. Runtime code and archived paper artifacts are preserved.

Question: which architectural and replay claims are supported by the current source, and what can be reproduced without a model service or unavailable pilot logs?

## Findings and revision decisions

1. Retained the constructive standard-library architecture and Omakase substitution contribution. Scoped zero dependencies to the foundation's third-party Python runtime packages; the build backend, interpreter, providers, commands and plugins are separate dependencies.
2. Distinguished the default imperative loop, optional event-log driver and Sidekick harness. Corrected event-budget semantics, terminal budget exhaustion, default gate heuristics and the absence of automatic Sidekick gating in the CLI functional path.
3. Replaced a fictitious state tuple and hash formula with the actual v0.4 fields. The state is not finite in the strict automata-theoretic sense. The linear chain is not a Merkle tree with inclusion proofs; the reducer's receipt can record proposed actions suppressed at terminal exhaustion.
4. Corrected replay's claim to internal consistency. Rehashing a complete modified transcript is possible; a reported TOOL_RESULT needs no matched pending request. Neither authenticated origin nor tool-effect truth follows from a PASS result.
5. Corrected atomic-write, numbered-read, single-regex parser and universal read-only claims. Disabling shell/write leaves patch active. Even disabling all three mutating built-ins does not constrain arbitrary plugin imports.
6. Preserved the pilot's useful debugging sequence while identifying C1/C2 as invalid harness configurations. The narrative reports C3 zero of three resolved and seven regressions on one patch; no raw trajectories or test output are tracked at the baseline. The manuscript does not claim those results were reproduced or establish a local-model capability ceiling.
7. Preserved historical PDF, HTML, BBL, bundle, submission dossier and Zenodo metadata. Added an explicit distinction from the living TeX. No submission, deposit update or DOI minting occurred.

## Primary-source checks

Opened on October 10, 2026:

- [SWE-bench paper](https://arxiv.org/abs/2310.06770): task/evaluation context and bibliographic metadata.
- [SWE-agent paper](https://arxiv.org/abs/2405.15793): interface-design motivation; no numerical comparison with NakedAgent inferred.
- [gptme project](https://github.com/gptme/gptme): provenance for the acknowledged terminal-tool architecture; exact inheritance is stated by local source comments, not inferred from current upstream behavior.
- [Aider edit-format documentation](https://aider.chat/docs/more/edit-formats.html): SEARCH/REPLACE precedent.
- [RFC 9162](https://www.rfc-editor.org/rfc/rfc9162): distinction between local hash chaining and a transparency protocol with signed checkpoints/consistency mechanisms. No conformance claimed.
- [MCP 2024-11-05 stdio transport](https://modelcontextprotocol.io/specification/2024-11-05/basic/transports): version matches the local client constant. No remote MCP was connected.

The remote historical Zenodo deposit was not independently verified. The DOI is attributed to repository records.

## Executable evidence

`paper/check_claims.py` uses only synthetic events, a stub model and a stub tool. It checks LF-normalized runtime source hashes against the baseline and eight named cases. Complete command output and build products are kept outside the repository in the operator's run directory; observed results are recorded below after execution.

The checks are post-hoc examples selected from this audit. They are not a test sample for an estimated security failure rate, and they do not demonstrate externally executed effects.

## Prospective study

Before a new empirical run, freeze source/plugin versions, dataset task selection, model digest/quantization, provider settings, prompt variants, container images and scoring version. Define matched sampling and repeated-run counts before inspecting outcomes. Predetermine invalid-infrastructure classifications and rerun rules. Archive exact patch bytes, predictions, trajectories and full grader outputs.

Keep parse compliance, successful dispatch, patch applicability, resolved tests, regressions and final task success separate. Use one-factor comparisons for fence/native calls, prompt examples and shell/file tools. This protocol is proposed and has not been executed here.

## Observed checks, October 10, 2026

Environment: Windows, Python 3.14.6. No model benchmark or provider request was made.

| Check | Observed result | Limits |
|---|---|---|
| `python paper/check_claims.py` | Exit 0; eight expected outcomes; runtime/metadata files match the pinned baseline; no external static imports | Synthetic examples and static import inventory, not complete execution verification |
| `python -m examples.replay_demo` | Exit 0; original three-event trace accepted; changed payload rejected | Partial-edit detection with hashes held fixed |
| `python -m unittest discover -s tests` | 498 tests run, OK, 45 skipped, 31.746 s | Windows/environment skips remain; suite emits existing mock HTTP resource warnings |
| `ruff check paper/check_claims.py` | Passed | Companion script only; runtime unchanged |
| `git diff --check -- paper` | Passed | Whitespace validation |
| PDFLaTeX + BibTeX + two PDFLaTeX passes | Five-page review PDF; no undefined citations or overfull boxes | A build check, not scientific validation; ordinary underfull-line warnings remain |
| Preserved artifact comparison | All seven historical PDF/HTML/BBL/bundle/metadata/dossier/review files byte-identical to baseline | Remote deposit not checked |
| Visual inspection | Pages 1, 3 and 5 readable, tables/equations/references fit | Sampled layout review |

The first TeX build inadvertently selected the archived BBL because compilation started in `paper/`. The corrected build runs entirely in a separate build directory with an explicit bibliography search path; the README documents this requirement. No archived output was overwritten. MiKTeX emitted an update-check reminder; no package installation or update was performed.

Local review outputs are in `C:/Users/Owner/PROJECTS/_runs/coronal-papers-20261010/`: `nakedagent-claims.json`, `nakedagent-demo.txt`, `nakedagent-tests.txt`, `nakedagent-archived-artifacts.json`, `nakedagent-validation-manifest.json`, and `nakedagent-build/`. These local outputs are not a published dataset or release archive.
