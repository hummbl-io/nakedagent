# nakedagent for Node.js

The Node.js port of the nakedagent foundation (`spec/SPEC.md` v0.1). ES modules, no dependencies: the code imports only
`node:` built-ins and uses the global `fetch`. `package.json` declares no `dependencies` and CI fails if one appears.
Requires Node >= 22.14.

    cd ports/node
    node --test                          # runs every vector in spec/conformance/vectors
    node bin/nakedagent.js "list the files here" -m qwen2.5-coder:7b

Flags follow the Python CLI where the foundation defines them: `-m/--model`, `-w/--workspace`, `--host`,
`--api ollama|openai`, `--api-key-env`, `--allow-shell`, `--shell-allowlist` (repeatable), `--shell-timeout`,
`--version`. The prompt may appear before, between or after flags. API keys are read only from the named
environment variable.

The package is marked `"private": true` so it cannot be published by accident. Publishing (npm trusted publishing needs the
package to exist first) is a separate decision: see `docs/TRUSTED_PUBLISHING_MATRIX.md` (added by PR #33).

## Built-in modules used

`node:fs`, `node:path`, `node:os`, `node:child_process`, `node:readline/promises`, `node:util` (`parseArgs`), `node:url` and
the globals `fetch`, `URL`, `AbortSignal`, `TextDecoder`, `Buffer`. Tests also use `node:test`, `node:assert/strict` and
`node:http`.

## Library use and the plugin seam

    import { run, defaultRegistry } from './src/index.js';
    const registry = defaultRegistry().set('stamp', { usage: '```stamp\n```', fn: () => new Date().toISOString() });
    await run('what time is it?', { model: 'qwen2.5-coder:7b', workspace: process.cwd(), registry });

The `Registry` (`set`, `disable`) is the port's plugin seam (spec section 9). Tool functions may be async. There is no
directory-based plugin loading.

## Differences from the Python reference

* **Shell tool is non-interactive only.** No TTY confirmation prompt; `--allow-shell` plus an allowlist is required, as in the
  reference's non-interactive mode. No `.nakedagent/shell_audit.jsonl` is written (the spec does not define it yet).
* **POSIX word splitting on every OS**; the reference uses a different splitter on Windows and the vectors define only POSIX.
* **Redirects are followed by hand** (301/302/303 become a GET with no body and no credentials; other 3xx are errors) so that
  credentials can never reach a second request. `fetch`'s own redirect handling keeps same-origin credentials.
* **No CR translation**: files are read and written as bytes (spec section 11, quirk 2).
* **No event log, replay, resume, MCP or sidekick**: out of scope for spec v0.1.
* `patch` reproduces the reference's `splitlines()` behaviour (spec section 11, quirk 3) so the two agree, quirk included.
