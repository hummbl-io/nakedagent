# Conformance vectors

Language-neutral JSON test vectors for the nakedagent foundation contract (`../SPEC.md`).
Each `vectors/<suite>.json` is `{"suite": name, "cases": [...]}`. Value encoding
(`repeat`, `concat`, `b64`) is defined in SPEC section 3. A case with `"requires": "posix"`
may be skipped on Windows, and one with `"requires": "symlink"` may be skipped where symlinks cannot be created; the whole `shell_allowlist` and `shell_policy` suites are POSIX-only.

| Suite | Case fields | How a port runner checks it |
|---|---|---|
| `toolcall` | `input` | parse `input`; result equals `expect` (list of `{tool,args,content}`) |
| `patch_split` | `input` | split the search/replace block; `expect` is `{search,replace}` or `{error}` (exact message) |
| `fs_tools` | `tool`, `args`, `content`, `files`, `outside`, `symlinks` | create a temp root holding the workspace `ws/` (filled from `files`) and, when the case has `outside` or `symlinks`, a sibling directory `outside/` (filled from `outside`); create each `symlinks` entry as a symlink at that workspace path pointing at the given target text (for example `../outside`), skipping the case if symlinks cannot be created; call the tool; compare the returned string to `expect.result`, every regular file under `ws/` (ignoring `.nakedagent/` and the symlinks themselves) to `expect.files`, and every file under `outside/` to `expect.outside_files` |
| `shell_allowlist` | `command`, `allowlist` | allowlist match equals `expect` (boolean) |
| `shell_policy` | `args`, `content`, `allow_shell`, `shell_allowlist`, `shell_timeout` | non-interactive shell tool in a temp workspace with stdin not a TTY; returned string equals `expect` |
| `prompt` | `extra_tools_without_usage` | build the system prompt over the four foundation tools plus the extra usage-less tools; equals `expect` |
| `llm_wire` | `api`, `model`, `messages`, `env`, `api_key_env`, `host_path`, `server`, `unreachable`, `host` | start a local HTTP server that replays `server` (`status`, `headers`, `body`) in order and records requests; set `env` for the call; compare recorded requests (`method`, `path`, `body`, `authorization`) and the reply, or check each `error_contains` substring is in the error message and each `error_absent` is not. `HOST:PORT` in a message stands for the server's address. `unreachable` means a closed local port; `host` means use that literal host string with no server. With `lenient_requests`, only `expect.first_request` is exact and any later request must have no authorization. |
| `loop` | `prompt`, `replies`, `files`, `allow_shell`, `shell_allowlist` | serve `replies` as successive Ollama-format assistant messages, run the loop in a temp workspace with an empty home directory (no user plugins), then compare the number of requests, the message list of the **last** request (the system message is replaced by `$SYSTEM`) and the final files |

Regenerate (Linux, Python 3.10+) after changing the reference:

    python3 spec/conformance/build_vectors.py

Inputs are authored in `build_vectors.py`; expected results are recorded from the Python reference and then
reviewed in the diff. A few expectations are authored by hand and checked against the reference instead
(truncation, error substrings, POSIX execution). Verify the vectors against the reference with:

    python -m unittest tests.test_conformance_vectors
