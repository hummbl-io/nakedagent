# Peer Review: nakedagent MVP

- **Reviewer:** devin (delta)
- **Target:** claude-code / `C:/Users/Owner/PROJECTS/nakedagent`
- **Date:** 2026-09-09
- **Verdict:** `adopt-with-edits`
- **Overall risk:** **P1** — the unrestricted shell tool and uncaught `OSError` paths can crash the agent or allow arbitrary code execution under the user's account.

## Scope

Reviewed the source tree (`nakedagent/*.py`, tests, `pyproject.toml`, `README.md`, `docs/architecture.md`).
Ran:
- `python -m unittest discover -s tests` — 13/13 pass
- `python -m nakedagent --version` / `--help` — OK
- `python -m nakedagent -w /tmp --host http://127.0.0.1:1 "list files"` — exits 1 with clean stderr (Ollama unreachable)
- AST import scan — only stdlib + package-internal imports
- `bandit -r nakedagent -ll`
- `semgrep --config auto nakedagent`
- Targeted manual tests for path traversal, exception handling, nested fences, and shell exit-code reporting.

## Findings

### P1

1. **Unrestricted `subprocess.run(..., shell=True)` in `tool_shell`**  
   `nakedagent/tools.py:31-38`
   - The shell tool runs arbitrary commands with the user's privileges, not confined to the workspace (only `cwd` is set). A malicious or prompt-injected model can `rm -rf /`, exfiltrate data, or run any binary. The README/architecture doc acknowledges this, but it is still a P1 for anything that will touch untrusted code or be run by non-expert users.
   - Evidence: `bandit B602 (HIGH)`, `semgrep ERROR python.lang.security.audit.subprocess-shell-true`.
   - Recommendation: For v1, treat this as an *explicit opt-in* (`--dangerous-shell` / `allow-shell` flag, off by default). For a safer default, use `shell=False` with a small allowlist of safe commands, or run inside a sandbox/restricted user. Document the risk in README prominently.

2. **Tool I/O functions do not catch `OSError`/`PermissionError`/`IsADirectoryError`, crashing the loop**  
   `nakedagent/tools.py:45-60` (`read`), `:63-72` (`write`), `:75-106` (`patch`)
   - The module docstring says errors are returned to the model so it can fix them, but only the workspace-traversal guard and `tool_patch` malformed-block check return error strings. `PermissionError`, `IsADirectoryError`, `FileNotFoundError` races, and `UnicodeDecodeError` propagate and crash the agent.
   - Evidence: manual test of `tool_write('dir', 'x', ws)` where `dir` exists raised `IsADirectoryError`; `tool_read` on a `000` permission file raised `PermissionError`.
   - Recommendation: wrap `target.read_text`, `target.write_text`, `target.parent.mkdir`, `subprocess.run`, and the file existence check in `try/except OSError as e` and return `f"Error: {e}"`.

### P2

3. **`tool_shell` swallows command exit codes when any output exists**  
   `nakedagent/tools.py:41-42`
   - `return _truncate(out) or f"(exit {proc.returncode}, no output)"` only shows the exit code if both stdout and stderr are empty. If a command fails and prints to stderr, the model sees the error text but not the exit status and may believe the command succeeded.
   - Evidence: `tool_shell('', 'cat /nonexistent-file 2>&1; exit 1', ws)` returned only the stderr text, no `(exit 1, ...)` prefix.
   - Recommendation: always include the exit code, e.g. `return _truncate(f"[exit {proc.returncode}]\n{out}")`.

4. **`tool_read` returns line-numbered output, but `patch`/`write` expect exact file content**  
   `nakedagent/tools.py:59-60`, `nakedagent/loop.py:20-52`
   - `read` prepends `1\t`, `2\t`, etc. `patch` requires exact (non-numbered) search text. The `SYSTEM_PROMPT` does not tell the model to ignore line numbers when constructing `patch` blocks, so the model is likely to fail patches on the first try.
   - Recommendation: either remove line numbers from `read` output (simplest and matches aider/gptme defaults) or add a rule in `SYSTEM_PROMPT` telling the model to strip the `N\t` prefix before using text in `patch`.

5. **Tool-call parser cannot handle nested/inner code fences**  
   `nakedagent/toolcall.py:24-29` (acknowledged in `docs/architecture.md:37-41`)
   - `_FENCE_RE` is non-greedy and stops at the first ` ``` ` it sees. Writing a markdown file that contains its own code fence will truncate the content and/or produce a malformed second tool call. Manual test: `parse('```write out.md\n# Header\n```python\nprint(1)\n```\n```')` returned only a `write` with content `# Header`, swallowing the rest.
   - This is a known limitation, but it is a *correctness* bug in any docs-heavy project.
   - Recommendation: implement fence-depth counting before using this on repos with markdown docs, or at minimum document the limitation clearly in `README.md` (not just `architecture.md`).

6. **`_split_search_replace` accepts malformed `patch` blocks and can default `start` to 0**  
   `nakedagent/tools.py:109-121`
   - It does not verify that a line actually starts with `<<<<<<< SEARCH`; if the marker is missing it defaults `start` to 0, dropping the first line of the block. It also accepts any `>>>>>>>` suffix, not `>>>>>>> REPLACE`.
   - Evidence: `tool_patch('foo.py', 'x\n=======\ny\n>>>>>>> REPLACE', ws)` produced `Error: SEARCH text matches 7 locations` because the search became an empty string.
   - Recommendation: require `<<<<<<< SEARCH` on a line, `=======` on a line, and `>>>>>>> REPLACE` exactly. Raise `ValueError` with a clear message if not.

7. **`llm.py` passes user-controlled `--host` to `urllib.request.urlopen` without scheme validation**  
   `nakedagent/llm.py:26-38`
   - `urllib` supports `file://` and other schemes, so a malicious `host` could read local files. Bandit flags this as B310 (MEDIUM); Semgrep flags it as WARNING.
   - Recommendation: validate `host` with `urllib.parse.urlparse`, reject schemes other than `http`/`https`, and require a network location.

### P3

8. **No `stdin=subprocess.DEVNULL` in `tool_shell`**  
   `nakedagent/tools.py:31-38`
   - Commands that try to read from stdin may hang or behave unexpectedly in non-interactive use.

9. **Unit tests do not cover OSError handling, shell exit-code reporting, or nested fences**  
   `tests/test_tools.py`, `tests/test_toolcall.py`
   - Tests are correct as far as they go, but they miss the failure modes above.

10. **Hard-coded timeouts (LLM 300s, shell 120s) with no operator override**  
    Not a bug, just an inflexibility.

## Strengths

- True zero third-party runtime dependencies; only stdlib imports.
- Clean module separation (`cli`, `llm`, `loop`, `toolcall`, `tools`).
- Workspace path-traversal guard on `read`/`write`/`patch` using `resolve()` + `is_relative_to()`.
- `patch` correctly rejects non-unique and missing search text.
- Unit tests pass and cover the happy path well.
- CLI surfaces Ollama connection errors cleanly (exit 1, non-traceback stderr).

## Suggested next steps

1. Fix P1.2 (OSError handling) and P2.3 (exit code reporting) before any public use — these are genuine bugs, not design choices.
2. Decide on P1.1 (shell sandboxing) explicitly: either gate it behind `--allow-shell`, document it as "same power as your shell, only run on code you trust", or add a sandbox.
3. Fix P2.4 (line numbers vs patch) and P2.6 (patch marker validation) to reduce model retry loops.
4. Address P2.5 (nested fences) before marketing the agent as suitable for docs/projects with markdown.
5. Add negative/exception tests for the cases above.

## Conclusion

The code is a credible v1 MVP that does what it says on the tin. The design is intentionally minimal. However, the shell tool and the uncaught `OSError` paths are P1 — the agent can be crashed or abused by a malicious prompt. Fix those and the P2 parser/UX issues before positioning it as a daily-driver coding agent for untrusted repos.
