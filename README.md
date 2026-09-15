# nakedagent

A coding agent with **zero runtime dependencies**. `pip install`-free by
construction: `python -m nakedagent` runs on a stock Python 3.10+ interpreter,
nothing else.

```
$ python -m nakedagent
nakedagent -- workspace: /home/you/myproject -- model: qwen2.5-coder:7b
Ctrl-D to exit.

> add a .gitignore for a Python project
```

## Why

Every other agent in this space — gptme, aider, OpenHands, langchain-based
tools — pulls in 20-40+ packages: HTTP clients, CLI-formatting libraries,
provider SDKs, telemetry. That's not a criticism of them; those dependencies
buy real capability (multi-provider abstraction, rich terminal rendering,
robust malformed-output recovery). But it also means every install inherits
whatever CVEs are sitting in that dependency tree, and updating any one
package can break the agent.

nakedagent takes the other side of that trade on purpose: `urllib` + `json` +
`subprocess` + `re`, all from the standard library, are enough to drive a
local model through a working tool-use loop. No supply chain, because there
is no supply.

## What you get for that

- **Tools**: `shell`, `read`, `write`, `patch` (search/replace edits, aider's
  simplest edit format). That's the whole *foundation* tool surface.
  `shell` is confirmation-first in interactive mode and requires `--allow-shell`
  in non-interactive mode, with optional command filtering via
  `--shell-allowlist`.
- **Model backend**: [Ollama](https://ollama.com) only, for now — local-first,
  no API key required to try it.
- **Tool-call format**: the model writes a fenced code block whose language
  tag is the tool name; nakedagent parses it out of the response text after
  each turn. Works with any model that can write a code fence — no dependency
  on a provider's native function-calling API.
- **Plugins**: drop a `.py` file in `.nakedagent/plugins/` (repo-local) or
  `~/.nakedagent/plugins/` (user-global) that defines a `TOOLS` dict (add or
  override tools) and/or a `DISABLE` list (remove tools entirely — e.g. a
  read-only agent disables `shell` and `write`). Each tool carries a `.usage`
  attribute that controls its prompt example, so a plugin replacing a tool
  replaces its syntax too. No registration, no framework — see
  [`DOCTRINE.md`](DOCTRINE.md) for the omakase framing.

See [`docs/architecture.md`](docs/architecture.md) for how the loop and tool
parser work, including what was learned from reading gptme's and aider's
actual source before writing this.

## Quick start

```bash
git clone https://github.com/hummbl-io/nakedagent.git
cd nakedagent
ollama pull qwen2.5-coder:7b   # or any model you like
python -m nakedagent           # interactive
python -m nakedagent "explain what this repo does"   # one-shot
```

## Shell safety for automation

For one-shot runs and other non-interactive use-cases, the shell tool is denied
unless explicit shell allowances are provided:

```bash
python -m nakedagent "run project checks" --allow-shell --shell-allowlist "git status" --shell-allowlist "ls"
```

`--shell-allowlist` is prefix-based. If you pass `--allow-shell` with an empty
allowlist, all non-interactive shell commands are blocked.

No `pip install` step. That's not an oversight — `nakedagent/` only imports
the standard library, so running it in place works.

## Status

MVP. Single model backend, four foundation tools, no streaming. The plugin
seam is the one extension surface — see [`DOCTRINE.md`](DOCTRINE.md).
Went through two independent peer reviews (headless GLM-5.2, and a
separately-running devin session, both 2026-09-09) before this first push —
between them they found five real bugs, all fixed with regression tests,
documented in [`docs/architecture.md`](docs/architecture.md) alongside what's
still genuinely not here and why.

## License

MIT. See [LICENSE](LICENSE).
