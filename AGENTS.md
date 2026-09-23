# AGENTS.md â€” nakedagent

## Project

**nakedagent** â€” <!-- TODO: describe this repository -->

## Scope

- In scope: <!-- describe what this repo does -->
- Out of scope: <!-- describe what belongs elsewhere -->

## Setup

```bash
# Clone and enter
git clone https://github.com/hummbl-io/nakedagent.git
cd nakedagent
```

## Testing

<!-- Add test commands here, or remove this section if no tests -->

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
- `.gitattributes` is required â€” the canonical fleet version normalizes text files to LF and marks binary types. Without it, Windows clones accumulate CRLF noise that pollutes diffs, blocks hooks, and creates phantom merge conflicts. Do not remove or weaken it.
- AI agents may assist with research, review, patch preparation, and operational coordination, but must not be credited in Git commit authorship metadata or commit-message trailers. Do not add `Co-authored-by`, `Generated-by`, `Authored-with`, or equivalent AI/vendor/agent attribution to commits. Agent activity belongs in internal receipts, bus messages, handoffs, or PR notes, not commit credit.

## Pre-PR-creation checklist

Before creating a PR branch, always:

1. **Fetch latest**: `git fetch origin` to ensure local refs are current
2. **Rebase on target**: `git rebase origin/main` so the PR branch starts from the latest commit
3. **Verify merge-base**: `git merge-base HEAD origin/main` should return the same SHA as `git rev-parse origin/main`
4. **Run pre-push CI check** (if available)
5. **Run local tests** (if available)

## CI

<!-- Describe CI workflows if any, or remove this section -->
