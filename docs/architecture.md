# Architecture

## The loop (`nakedagent/loop.py`)

One call to `step()` = one model call, plus executing whatever tool calls
appear in that reply. The outer loop (`run` / `run_interactive`) keeps
calling `step()` — without new human input — for as long as the model's last
reply still contained a tool call. Control returns to the human (or, in
one-shot mode, the process exits) the first time a reply has no tool calls
left.

This shape is a straight read of gptme's `chat.py` (`_process_message_conversation`
/ `step`), reimplemented from scratch here rather than copied — the mechanism
is public knowledge about how a tool-loop is structured, not gptme's code.
Aider's repo-map ranking algorithm was read too during design (see the
session's research doc for full notes) but isn't used here: v1's context
strategy is "whatever the model asks `read` for," not a precomputed ranked
map. That's the biggest capability gap versus aider on anything but a small
repo — tracked below, not solved.

## Tool-call format (`nakedagent/toolcall.py`)

A tool call is a fenced code block whose language tag is the tool name:

```
```shell
ls -la
```
```

Parsed with a depth-tracking line scanner, not a JSON-schema/function-calling
integration. This is deliberately the least capable, most portable format:
it works with a local 7B model that has no native tool-calling support at
all, which native function-calling (Option B considered and rejected during
design) would have excluded.

**Revision note (post-review):** the first version used a single lazy regex
that closed on the *first* ``` it saw, with no concept of nesting. A GLM-5.2
peer review (headless devin session, 2026-09-09) caught this at MVP review
time, before any wider release: a `write` call whose body contained its own
nested code-fence example (e.g. documenting a shell command) would silently
truncate the written file at the first inner fence, and if a *second* inner
fence happened to be tagged with a real tool name (e.g. an example
` ```shell ` block in generated docs), it would be mis-parsed as a second,
genuinely executable tool call -- meaning the model could unintentionally
trigger `rm -rf /` or similar just by writing documentation that mentions it.
The parser is now a proper line-by-line scanner that tracks fence depth:
a body line that opens its own nested fence increments depth instead of
ending the block, and only a bare ` ``` ` line (nothing else on it) at
depth 1 closes the outer call. A block whose depth never returns to 0 is
refused rather than guessed at. See `tests/test_toolcall.py` and
`tests/test_loop.py` for the regression coverage this added, including a
test that mocks the model reply and asserts the fabricated shell call never
actually runs -- not just that the parser returns the right thing.

## Tools (`nakedagent/tools.py`)

Four functions, one dict (`TOOLS`), same signature:
`(args: str, content: str, workspace: Path) -> str`. Adding a tool is: write
a function with that signature, add it to the dict, add its format to
`SYSTEM_PROMPT` in `loop.py`. No registration ceremony, no class hierarchy.

- `shell` — `subprocess.run(shell=True)`, 120s timeout, output truncated at
  8000 chars. Still no allowlist or resource limits (that's an intentional
  v1 trade-off, per the review below), but as of the same review pass it
  gates on an interactive y/N confirmation whenever stdin is a real TTY —
  and fails safe (declines, doesn't crash) if `isatty()` says yes but the
  read still fails, which happens in some sandboxed shells.
- `read` — exact file dump (no line numbers — an earlier version prefixed
  `N\t` per line, but that meant a model copying `read` output straight into
  a `patch` SEARCH block copied the numbers too, so every patch attempt
  failed to match; caught in a second, independent review, see below).
  Rejects paths that resolve outside the workspace.
- `write` — full-file overwrite (creates parent dirs). Same workspace
  containment check.
- `patch` — aider-style `SEARCH`/`REPLACE` block. Rejects (with an error
  message fed back to the model, not a crash) if the search text isn't
  found, or isn't unique — the model gets to see the error and retry with a
  more specific search string. Markers (`<<<<<<<`/`=======`/`>>>>>>>`) are
  found in sequential order, not independently from the top of the block —
  the original independent-from-0 search let a marker-shaped line *inside*
  the SEARCH or REPLACE text (e.g. patching a file that itself contains
  git conflict markers) hijack the split and silently write the wrong
  content while still reporting "Patched." A second `<<<<<<<` before the
  matching `>>>>>>>` is rejected outright for the same reason (GLM-5.2
  review finding #2).

Every tool call is now wrapped in a `try/except Exception` in `loop.step()`
(finding #3) — a bug in a tool reaches the model as an `Error: ...` message,
same as an expected error, instead of crashing the whole session with a raw
traceback.

## Model backend (`nakedagent/llm.py`)

Ollama's `/api/chat` only, `stream=False`. One `urllib.request.urlopen` call,
one JSON parse. `ponytail:` comment in the source marks the streaming
omission explicitly — upgrade path is NDJSON chunk parsing over
`http.client`, no new dependency required, just more code, deferred until
interactive latency is an actual complaint rather than a hypothetical one.

`--host` is validated (`urllib.parse.urlparse`, scheme must be `http`/`https`
with a real netloc) before being handed to `urlopen` — `urllib` will
otherwise happily open `file://` and other schemes. This is a CLI flag the
*operator* types, not something the model controls, so the severity is low,
but there was no reason to leave it open. Caught in the second review below.

## Two independent reviews, same day

The MVP was reviewed twice before this first push, by two separately-running
agent sessions that picked up the same bus request concurrently: a headless
`devin --model glm-5.2` instance launched specifically for this, and another
already-running devin session (unprompted, via the bus). Between them:
GLM-5.2 found the nested-fence parser hazard, the patch-marker independent-
search bug, and the uncaught-exception crash path (all covered above). The
second review independently confirmed the shell-tool risk and the marker
bug, and caught two things GLM's pass missed: `read`'s line numbers silently
breaking `patch` round-trips, and the unvalidated `--host` scheme. Both are
fixed, both above. Full raw output: `_review/glm-5-2-review-output.txt` and
`review-devin-delta-20260909.md` (repo root — written directly by the second
reviewer, not by this session).

## What's not here yet, on purpose

- **Cloud providers** (Anthropic/OpenAI/etc). Ollama-only was the explicit v1
  scope decision — local-first, zero API-key friction for a first
  `git clone && run`. Adding one is a new module in the same shape as
  `llm.py`'s `chat()`, no architecture change.
- **Streaming output.** See above.
- **Multi-fence-per-turn safety beyond "run each in order."** No rollback if
  call 2 of 3 fails after call 1 already mutated a file.
- **Ranked context selection** (aider's repo-map approach). v1 relies
  entirely on the model choosing to `read` what it needs.
- **`shell`'s lack of an allowlist.** The confirmation gate (see Tools,
  above) covers interactive use; a one-shot/piped run still executes
  unconfirmed. Real gating (allowlist, dry-run mode) is future work.

A loop-round cap (`MAX_STEPS = 25` in `loop.py`, so a model stuck emitting
tool calls can't run forever) and loop-level test coverage (`tests/test_loop.py`,
mocking `llm.chat` to assert on what `step()` actually does, not just what
the parser returns in isolation) were both added during the GLM-5.2 review
pass and are no longer gaps.

None of these are architecture debt in the sense of "wrong shape, needs a
rewrite" — each is an additive module or a widened interface, consistent
with the zero-dependency discipline the project exists to prove out.
