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
`(args: str, content: str, workspace: Path) -> str`. Adding a *foundation*
tool is: write a function with that signature, add it to the dict, add its
format to `SYSTEM_PROMPT` in `loop.py`. No registration ceremony, no class
hierarchy. Adding a *user* tool (a substitution, per `DOCTRINE.md`) is: drop
a `.py` file in a plugin dir — see the Plugins section below.

- `shell` — `subprocess.run(shell=True)`, configurable timeout (default 120s,
  via `--shell-timeout`), output truncated at 8000 chars. It now supports the
  interactive confirmation gate and
  non-interactive hardening via `--allow-shell` + `--shell-allowlist`:
  non-interactive calls are denied unless explicitly enabled and matched.
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
  review finding #2). One marker-collision case remains by design: a
  `=======` line *inside* the SEARCH body (e.g. a markdown H1 underline) is
  consumed as the separator, silently splitting at the wrong place. This
  matches aider's own first-`=======`-wins behavior, so it's a SEARCH/REPLACE
  format limitation, not a bug -- the SEARCH text simply can't contain a
  bare `=======` line.

Every tool call is now wrapped in a `try/except Exception` in `loop.step()`
(finding #3) — a bug in a tool reaches the model as an `Error: ...` message,
same as an expected error, instead of crashing the whole session with a raw
traceback.

## Model backend (`nakedagent/llm.py`)

Two wire formats behind one `chat()`: Ollama's `/api/chat` (default) and the
OpenAI-compatible `/chat/completions` shape (`--api openai`), both
`stream=False`. One `urllib.request.urlopen` call, one JSON parse.

The second format is how nakedagent reaches models too large to run locally.
It is one protocol, not per-vendor clients: hosted APIs (OpenAI, Gemini's
OpenAI endpoint, OpenRouter, Groq), self-hosted servers (vLLM, LM Studio,
llama.cpp) and gateways all speak it, and so does Ollama at `/v1`. `--host`
is the base URL including its version path; with `--api openai` there is no
default host, so a prompt is never sent to a server the operator didn't
name. The key is read from the environment variable named by
`--api-key-env` (default `OPENAI_API_KEY`), never from a flag, so it stays out
of shell history and process listings; an unset variable sends no auth
header (local servers need none) and a 401/403 names the variable to check.

It lives in the foundation rather than a plugin because the plugin seam
substitutes tools, not the model call, and a small model is the case where a
user most needs a way out. Errors from either format raise `LLMError`;
`OllamaError` remains as an alias for existing imports. `ponytail:` comment in the source marks the streaming
omission explicitly — upgrade path is NDJSON chunk parsing over
`http.client`, no new dependency required, just more code, deferred until
interactive latency is an actual complaint rather than a hypothetical one.

`--host` is validated (`urllib.parse.urlparse`, scheme must be `http`/`https`
with a real netloc) before being handed to `urlopen` — `urllib` will
otherwise happily open `file://` and other schemes. This is a CLI flag the
*operator* types, not something the model controls, so the severity is low,
but there was no reason to leave it open. Caught in the second review below.

## Plugins (`nakedagent/plugins.py`)

The omakase substitution mechanism (see `DOCTRINE.md`). The foundation ships
four curated tools; a user adds their own by dropping a `.py` file in a
plugin dir. The loader scans at startup, imports each, and merges its `TOOLS`
dict into the runtime registry — no fork, no registration, same
`(args, content, workspace) -> str` signature.

Search order (later dirs win, so user-local overrides repo-local):
1. `<workspace>/.nakedagent/plugins/`
2. `~/.nakedagent/plugins/`

A plugin file is any `*.py` in those dirs (files starting with `_` are
private, not loaded). It must define a module-level
`TOOLS: dict[str, ToolFunc]` and/or `DISABLE: list[str]`. A file that fails
to import or defines neither is skipped with a one-line warning to stderr —
one bad plugin must not brick the agent, same fail-soft posture as a tool
that raises in `loop.step()`. Plugin tool names are lowercased to match the
case-insensitive dispatch.

**Override:** a plugin that reuses a foundation tool's name replaces its
function. Each tool carries a `.usage` attribute (the fenced-block example
shown to the model in the system prompt); a plugin that replaces a tool
should set `.usage` on its replacement too, so the model sees the new syntax
instead of the foundation's. The system prompt is built per session from
the merged registry — each tool with `.usage` contributes its own example,
tools without `.usage` are listed by name only. When no plugins are loaded
this is byte-identical to the old static prompt (all four foundation tools
carry `.usage`).

**Disable:** a plugin that lists a tool name in `DISABLE` removes it from
the registry entirely — "send it back" rather than swap. A read-only agent
disables `shell` and `write`; the model never sees them in the prompt, so
it never tries to call them. `DISABLE` is applied after all `TOOLS` merges,
so it wins over any substitution, including a plugin that both defines and
disables a name.

`ponytail:` no entry-point group, no metadata, no version negotiation. A
plugin is just a Python file that defines `TOOLS` and/or `DISABLE`. If a
plugin needs to declare compatibility or metadata, that is a substitution
someone makes later, not now.

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

The plugin seam (`nakedagent/plugins.py`) is the omakase substitution
mechanism — most of the items below are now *substitutions a user makes via
a plugin*, not foundation work waiting to be done. See `DOCTRINE.md`.

- **Vendor-native APIs** (Anthropic Messages, Gemini `generateContent`).
  Hosted models are reachable today through `--api openai`; a native client
  is only worth adding when it buys something the compatible endpoint
  can't. Ollama stays the default: local-first, zero API-key friction for a
  first `git clone && run`.
- **Streaming output.** See above.
- **Multi-fence-per-turn safety beyond "run each in order."** No rollback if
  call 2 of 3 fails after call 1 already mutated a file.
- **Ranked context selection** (aider's repo-map approach). v1 relies
  entirely on the model choosing to `read` what it needs.
- **`shell` mutation safety in automation.** Added in foundation for v1:
  non-interactive execution is off by default and only runs when
  `--allow-shell` is set and the command matches `--shell-allowlist`.
- **`patch` success without a diff.** The model gets `Patched {path}.` and
  must `read` again to verify. A `difflib`-based diff in the success message
  is a candidate plugin (wrap `tool_patch`), not foundation surface.
- **`read` truncation without continuation.** `MAX_OUTPUT = 8000` truncates
  a large file to its head with no way to read the rest. A line-range
  argument or pagination is a candidate plugin.

A loop-round cap (`MAX_STEPS = 25` in `loop.py`, so a model stuck emitting
tool calls can't run forever) and loop-level test coverage (`tests/test_loop.py`,
mocking `llm.chat` to assert on what `step()` actually does, not just what
the parser returns in isolation) were both added during the GLM-5.2 review
pass and are no longer gaps.

None of these are architecture debt in the sense of "wrong shape, needs a
rewrite" — each is an additive module or a widened interface, consistent
with the zero-dependency discipline the project exists to prove out.
