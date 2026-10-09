# Differential testing

The vectors pin the cases someone thought of. This directory checks the rest: it feeds the same seeded random inputs to the
Python reference and to a port and demands identical answers. It covers the pure functions where ports most often drift:
the tool-call parser, the SEARCH/REPLACE splitter, shlex-style word splitting through the allowlist, Python's `strip()`
whitespace set, lossy UTF-8 decoding, and code-point truncation.

    python3 gen.py 60000 7 > cases.jsonl
    python3 harness_py.py <repo root> cases.jsonl > out_py.jsonl      # on Linux
    <port harness> cases.jsonl > out_port.jsonl
    python3 compare.py cases.jsonl out_py.jsonl out_port.jsonl

A port harness reads `cases.jsonl` (one JSON object per line, `op` selects the function; see `gen.py`) and writes one JSON
value per line in the same order. Output is compared after JSON parsing, so escaping style does not matter. Harnesses in this repo:

* Go: `DIFF_IN=cases.jsonl DIFF_OUT=out_go.jsonl go test -run TestDifferentialHarness ./ports/go` (skipped unless `DIFF_IN` is set)
* Node: `node ports/node/tools/diff-harness.mjs cases.jsonl > out_node.jsonl`
* Deno: `deno run --allow-read ports/deno/tools/diff-harness.ts cases.jsonl > out_deno.jsonl`

When a mismatch is real, add the failing input to `build_vectors.py` so it becomes a permanent vector, then fix the port.
