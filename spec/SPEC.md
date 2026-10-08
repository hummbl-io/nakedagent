# nakedagent specification, v0.1 (foundation)

Status: draft, extracted from the Python reference implementation (`nakedagent/`).
Where this document is silent or ambiguous, the Python reference is normative and the
gap is a bug in this document. Open questions where the reference itself looks wrong are
listed in [Known reference quirks](#known-reference-quirks-and-open-questions).

This spec exists so nakedagent can be re-implemented in any language that has a standard
library, with the same observable behaviour and **zero third-party dependencies**
(see `DOCTRINE.md`: no supply chain, because there is no supply).

## 1. Scope

In scope (v0.1, the "foundation"):

| Component | Reference | Conformance suite |
|---|---|---|
| Fenced tool-call parser | `nakedagent/toolcall.py` | `toolcall` |
| `read` / `write` / `patch` tools and the path guard | `nakedagent/tools.py` | `fs_tools`, `patch_split` |
| `shell` tool policy and execution | `nakedagent/tools.py` | `shell_allowlist`, `shell_policy` |
| System prompt builder | `nakedagent/loop.py` | `prompt` |
| Model chat client (Ollama and OpenAI-compatible wire formats) | `nakedagent/llm.py` | `llm_wire` |
| Agent loop | `nakedagent/loop.py` | `loop` |

Out of scope for v0.1 (a port may add them later; each needs its own suite first): the
functional driver, event log and replay (`driver.py`, `eventlog.py`, `functional.py`,
`replay.py`), MCP mounting (`mcp.py`), sidekick (`sidekick.py`), SWE-bench harness (`bench/`),
and dynamic plugin loading (see section 9).

## 2. Port requirements

A port is conformant when:

1. It passes **every non-skipped case** in `spec/conformance/vectors/*.json` for the
   platform it runs on (cases marked `"requires": "posix"` may be skipped on Windows).
2. It uses **only the language's standard library** at runtime *and* in its test runner.
   No package registry fetches, no vendored third-party code. A hand-written JSON
   parser or HTTP/1.1 client inside the port is acceptable where the stdlib has none
   (section 8); it must itself be covered by the vectors.
3. It lives in `ports/<language>/` in this repository, builds with that language's
   stock toolchain, and documents the single command that runs the vectors.
4. It reads API keys only from a named environment variable, never from a flag value
   (`--api-key-env`), exactly like the reference.

Passing the vectors is necessary, not sufficient: the vectors cover the foundation
contract above, not every behaviour of the reference.

## 3. Vector value encoding

Every text or byte value in a vector is one of:

* a JSON string (UTF-8 text);
* `{"repeat": [string, count]}`: `string` repeated `count` times (keeps large cases small);
* `{"concat": [value, ...]}`: concatenation of text values;
* `{"b64": string}`: raw bytes, base64 (used for invalid UTF-8).

"Characters" in this spec always means **Unicode code points**, not bytes and not UTF-16
code units. Truncation lengths, `Wrote N chars` and sorting are all in code points.

## 4. Tool-call grammar (`toolcall`)

Input: the model's reply text. Output: an ordered list of `{tool, args, content}`.

1. Normalise `\r\n` to `\n`, then split **only on `\n`** (not on U+2028, U+0085, `\f`, `\v`...).
2. A line opens a call iff it matches `^```(?<tool>[A-Za-z0-9_]+)(?: (?<args>[^\n`]*))?$`
   at column 0. `tool` keeps its original casing; `args` is trimmed of surrounding whitespace.
3. After an opener, scan lines with a stack of fence lengths, initially `[3]`:
   * a line made only of backticks (after right-trimming whitespace; column 0) whose length
     equals the top of the stack pops it; popping to empty closes the call, otherwise the line
     is body text;
   * any other all-backtick line is body text;
   * a column-0 line starting with 3 or more backticks (and anything else) pushes its backtick
     count and is body text.
4. Body lines are joined with `\n` (no trailing newline). An empty body is `""`.
5. A call that never closes yields a single `{tool: "__refused__", args: <tool name>,
   content: "unclosed fence for '<tool>'; call refused"}` and consumes the rest of the input.
6. Indented fences are never openers or closers. Untagged fences (` ``` ` alone) are not openers.

## 5. File tools (`fs_tools`, `patch_split`)

All three take `(args, content, workspace)` and return a string that is fed back to the
model. Errors are returned, never thrown. Messages are part of the contract (the model reads them).

Common to `read`, `write`, `patch`:

* `path = args` trimmed. Empty path returns `Error: <tool> tool needs a path, e.g. ```<tool> path/to/file.py```` (exact text in vectors).
* The target is `workspace/path` **fully resolved (symlinks followed)**. If it is not inside
  the resolved workspace the result is `Error: <path> is outside the workspace.`
* `write` and `patch` additionally refuse targets whose **first path component** (relative
  to the workspace) is `.git` or `.nakedagent`: `Error: <path> is in protected directory '<name>'.`
  Only the first component counts (`a/.git/x` and `.github/x` are allowed).

`read`: missing -> `Error: <path> does not exist.`; a directory -> `<path> is a directory:` then
the entry names (not paths), sorted by code point, one per line; a file -> its text decoded as UTF-8
with invalid bytes replaced by U+FFFD, truncated per section 5.1.

`write`: creates parent directories, writes UTF-8, returns `Wrote <N> chars to <path>.` with N in
code points.

`patch`: the target must exist (`Error: <path> does not exist. Use write to create it.`). The body is
a search/replace block (5.2). The file is read as UTF-8; invalid UTF-8 returns `Error: <path> is not valid
UTF-8; patch refused without changing the file.` The search text is counted with non-overlapping
substring search: 0 matches -> `Error: SEARCH text not found in <path>. It must match exactly, including
whitespace.`; more than 1 -> `Error: SEARCH text matches <n> locations in <path>; make it more specific.`;
exactly 1 -> replaced, file written, `Patched <path>.` A malformed block returns
`Error: malformed patch block (<reason>).`

### 5.1 Truncation

Tool output longer than `MAX_OUTPUT = 8000` code points is cut to the first 8000 and gets
`\n...[truncated, <k> more chars]` appended, where `k` is the number of dropped code points.
Output of exactly 8000 is not truncated. Applies to `read` and `shell`.

### 5.2 Search/replace block

Lines are found in order: a line equal (after trimming) to `<<<<<<< SEARCH`; then, after it, a line equal to
`=======`; then, after that, a line equal to `>>>>>>> REPLACE`. Missing/out-of-order markers ->
`expected <<<<<<< SEARCH / ======= / >>>>>>> REPLACE markers, in that order`. A line starting with
`<<<<<<<` (after trim) between start and end -> `a second <<<<<<< marker appears before the matching >>>>>>>`.
Any non-blank line after the end marker -> `unexpected content after >>>>>>> REPLACE; use one patch block per call`.
`search` = lines between start and separator joined by `\n`; `replace` = lines between separator and end.
Text before the start marker is ignored.

## 6. Shell tool (`shell_allowlist`, `shell_policy`)

Non-interactive mode only is specified here (no TTY prompt). Checks run in this order, each returning
the quoted string:

1. command = body trimmed, else args trimmed; empty -> `Error: shell tool got no command.`
2. timeout <= 0 -> `Error: --shell-timeout must be a positive integer.`
3. not `allow_shell` -> `Error: shell execution blocked (non-interactive shell execution requires --allow-shell).`
4. command not matched by the allowlist -> `Error: shell execution blocked (non-interactive command is not in --shell-allowlist).`
5. word-split the command (POSIX rules below); on error -> `Error: malformed command (<reason>).`
6. resolve `argv[0]` on `PATH`; absent -> the long `is not an executable on PATH` message (exact text in vectors).
7. run `argv` **directly, with no shell**, working directory = workspace, stdin closed (empty), captured stdout and stderr,
   the timeout applied (-> `Error: command timed out after <n>s.`).
8. result = `(exit <code>)`, then `\n` + stdout if non-empty, then `\n--- stderr ---\n` + stderr if non-empty; truncated per 5.1.
   (Note stdout and the separator are joined with `\n`, which is why output ending in a newline shows a blank line before `--- stderr ---`.)

**Allowlist match:** the command and each non-blank pattern are word-split; the command matches when its first
`len(pattern)` tokens equal the pattern's tokens. A pattern or command that fails to split never matches. An empty
allowlist never matches. This is a token-prefix match, so `git status; rm x` (token `status;`) does not match `git status`.

**POSIX word splitting** (as Python's `shlex.split` with defaults): whitespace separates tokens; `'...'` is literal;
inside `"..."` a backslash escapes only `\` and `"`; outside quotes a backslash escapes the next character; `#` is not a
comment; an unterminated quote or trailing backslash is an error. Windows splitting differs and is not part of v0.1 vectors.

## 7. System prompt (`prompt`)

Built from the tool registry in insertion order: the fixed header line; each tool's `usage` example joined by blank
lines; if any tool has no `usage`, one line listing those names, sorted, in backticks; then the fixed rules block.
The exact bytes for the four foundation tools are in `vectors/prompt.json`.

## 8. Model client (`llm_wire`)

`chat(messages, model, host, api, api_key_env) -> reply text`, non-streaming, 300 s timeout.

* `api` must be `ollama` or `openai`; the host must be `http(s)://` with a network location.
* **ollama:** `POST <host>/api/chat`, body `{"model", "messages", "stream": false, "think": false}`; reply = `message.content`.
* **openai:** `POST <host without trailing slash>/chat/completions`, body `{"model", "messages", "stream": false}`; reply = `choices[0].message.content`.
  If the environment variable named by `api_key_env` (default `OPENAI_API_KEY`) is non-empty, send `Authorization: Bearer <value>`.
  Ollama never sends credentials.
* `null` content becomes `""`. Credentials are sent on the initial request only and **never forwarded on a redirect**, even
  to the same origin. (Following redirects is optional; if followed, later requests must carry no Authorization.)
* Errors surface as one error kind carrying the messages checked by substring in the vectors: HTTP status errors
  (`<Name> at <host> returned HTTP <code> <reason>` plus `: <first 200 chars of body>`, and for openai 401/403 a
  `(check the key in $<api_key_env>)` hint), unreachable (`could not reach <Name> at <host>`; the Ollama variant adds
  ``Is `ollama serve` running?``), non-JSON body, and unexpected response shape. `<Name>` is `Ollama` or
  `OpenAI-compatible API`.

## 9. Agent loop (`loop`)

`run(prompt, model, workspace, host, ...)`: messages start as `[system(prompt builder), user(prompt)]`. Repeat up to
`MAX_STEPS = 25` rounds: request the model; append the reply as `assistant`; parse tool calls; if none, stop. For each call,
in order, look the tool up by **lower-cased** name; unknown -> `Error: unknown tool '<name as written>'.`; a tool that
throws -> `Error: <ExceptionType>: <message>` (type names are language-specific and not checked by the vectors); append `user` message `[<name as written> output]\n<result>`. All calls in a
reply run before the next request. After 25 rounds control returns to the human.

**Plugin seam.** The reference loads `*.py` files at startup. Compiled languages cannot do that; a port must instead expose an
equivalent *registration seam* (a way for the embedding program to add tools and disable foundation tools by name, with `DISABLE`
winning over additions) and document how. Dynamic loading is optional and out of v0.1 conformance.

## 10. Language stdlib notes

Every listed language has the pieces below in its standard library unless noted. "Hand-roll" means the port ships its own
implementation, under the zero-dependency rule.

| Language | JSON | HTTPS client | Process spawn | Notes |
|---|---|---|---|---|
| Go | `encoding/json` | `net/http` | `os/exec` | straightforward |
| Rust | **none** (hand-roll) | **none** (hand-roll HTTP/1.1 over `TcpStream`; **no TLS**) | `std::process` | hosted HTTPS APIs are unreachable from `std` alone; v0.1 may cover plain-HTTP servers (local Ollama, LAN gateways) and must say so |
| Node.js | `JSON` | `fetch` (global) | `child_process` | `node:test` for vectors |
| Deno | `JSON` | `fetch` | `Deno.Command` | needs `--allow-*` flags documented |
| Ruby | `json` (bundled) | `net/http` | `Open3` / `Process` | |
| Java | **none in JDK** (hand-roll) | `java.net.http.HttpClient` | `ProcessBuilder` | |
| C# | `System.Text.Json` | `HttpClient` | `System.Diagnostics.Process` | |
| Swift | `Foundation` JSON | `URLSession` (Foundation) | `Process` (Foundation) | Foundation on Linux is part of the toolchain, not a package |

Review any "stdlib" claim before adopting it: for each port, name the exact modules used in its README.

## 11. Known reference quirks and open questions

These are **not** covered by vectors because they look like bugs or platform accidents rather than a contract. Each needs an
owner decision before it is fixed in the reference or frozen into the spec.

1. **Refusals never reach the model by name.** `toolcall.parse` emits a `__refused__` call whose docstring says the refusal is
   "surfaced to the model", but the loop looks up `__refused__` in the registry, finds nothing and tells the model
   `Error: unknown tool '__refused__'.` The explanatory text is dropped.
2. **Platform newline translation.** `write` and `patch` write text in text mode, so on Windows `\n` becomes `\r\n`; `read`/`patch`
   read in text mode and fold `\r\n` to `\n`. Behaviour differs by OS and CR-bearing files are not round-trippable. The vectors avoid CR.
3. **`patch` splits lines with `str.splitlines()`**, which also breaks on U+2028, U+0085, `\f` and `\v`, silently rewriting such
   characters to `\n` inside SEARCH/REPLACE text. The tool-call parser deliberately avoids this; `patch` does not.
4. **Empty SEARCH text matches everywhere** (`n + 1` locations for an `n`-character file), so it always reports "matches N locations".
   Harmless but surprising; one vector pins it.
5. **No symlink-escape vector.** The workspace guard resolves symlinks (section 5) but the vectors cannot create symlinks portably.
   Each port must add a native test for a symlink pointing outside the workspace.
6. **Directory listing order** is by code point (`sorted()`), which differs from UTF-16 code-unit order for non-BMP names (JavaScript, Java, C#).
7. **Interactive shell confirmation** (TTY prompt and `shell=True`) is not specified; only the non-interactive policy is.
