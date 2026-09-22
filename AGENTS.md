# AGENTS.md — nakedagent

## Project

**nakedagent** — a zero-runtime-dependency terminal coding agent. `python -m nakedagent` runs on a stock Python 3.10+ interpreter; `nakedagent/` imports only the standard library (`urllib`, `json`, `subprocess`, `re`).

## Scope

- In scope: the agent loop (`loop.py`), fenced-block tool-call parser (`toolcall.py`), the four foundation tools (`tools.py`: read/write/patch/shell), the plugin seam (`plugins.py`), Ollama + OpenAI-compatible wire clients (`llm.py`), the SWE-bench harness (`bench/`).
- Out of scope: provider SDKs, streaming UX, hosted telemetry, non-stdlib dependencies.

## Setup

```bash
# Clone and enter
git clone https://github.com/hummbl-io/nakedagent.git
cd nakedagent
python -m nakedagent           # interactive (needs a running Ollama, or --api openai --host ...)
python -m nakedagent "prompt"  # one-shot
```

## Testing

```bash
python -m unittest discover -s tests   # stdlib unittest — no pytest dependency
```

### Python baseline (gap-8 fleet-wide standard)

If this repo contains Python, the fleet-wide baseline applies:

```bash
ruff check .          # lint
mypy .                # type check
pytest tests/ -v      # tests
```

Config files: `ruff.toml`, `mypy.ini`. CI runs these as advisory (Phase 1);
they will become required (Phase 2) after fleet cleanup.

## Conventions

- Commit format: Conventional Commits
- Branch naming: `type/agent/short-desc`
- License: MIT (see `LICENSE`)
- `.gitattributes` is required — the canonical fleet version normalizes text files to LF and marks binary types. Without it, Windows clones accumulate CRLF noise that pollutes diffs, blocks hooks, and creates phantom merge conflicts. Do not remove or weaken it.
- AI agents may assist with research, review, patch preparation, and operational coordination, but must not be credited in Git commit authorship metadata or commit-message trailers. Do not add `Co-authored-by`, `Generated-by`, `Authored-with`, or equivalent AI/vendor/agent attribution to commits. Agent activity belongs in internal receipts, bus messages, handoffs, or PR notes, not commit credit.

## Security-sensitive surfaces

- `tools.py` shell tool: non-interactive execution is gated by `--allow-shell` + `--shell-allowlist`; metachar blocking lives in `_split_command`.
- `plugins.py`: `<workspace>/.nakedagent/plugins/` only loads with `--trust-workspace-plugins`; `~/.nakedagent/plugins/` always loads. See `SECURITY.md` § Trust boundaries.
- `llm.py`: API keys come from named env vars (`--api-key-env`), never CLI values.

## Pre-PR-creation checklist

Before creating a PR branch, always:

1. **Fetch latest**: `git fetch origin` to ensure local refs are current
2. **Rebase on target**: `git rebase origin/main` so the PR branch starts from the latest commit
3. **Verify merge-base**: `git merge-base HEAD origin/main` should return the same SHA as `git rev-parse origin/main`
4. **Run pre-push CI check** (if available)
5. **Run local tests** (if available)

## CI

`.github/workflows/ci.yml` — `python -m unittest discover -s tests` on
ubuntu-latest × Python 3.10/3.14 + windows-latest × Python 3.12, plus a
pinned gitleaks secret scan.
