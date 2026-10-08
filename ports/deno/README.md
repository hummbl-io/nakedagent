# nakedagent for Deno

The Deno port of the nakedagent foundation (`spec/SPEC.md` v0.1). TypeScript, no dependencies: the code uses the `Deno`
namespace, web APIs (`fetch`, `URL`, `TextDecoder`, `AbortSignal`) and `node:` built-ins that ship inside the Deno runtime.
There are no `jsr:`, `npm:` or `https:` imports (not even `@std`), `deno.json` maps no imports, and CI fails if that changes.

    cd ports/deno
    deno task test                                   # every vector in spec/conformance/vectors
    deno run --allow-read --allow-write --allow-run --allow-net --allow-env main.ts "list the files here" -m qwen2.5-coder:7b

## Permissions

Deno is deny-by-default, so the agent needs these flags (the test task uses all of them):

| Flag | Why |
|---|---|
| `--allow-read`, `--allow-write` | the `read`, `write` and `patch` tools (scope them to the workspace: `--allow-read=. --allow-write=.`) |
| `--allow-run` | the `shell` tool, only used with `--allow-shell` (it can be narrowed to specific executables; the port passes Deno the full path it resolved from `PATH`, so check Deno's permission docs for how executables are matched before relying on a narrow list) |
| `--allow-net` | the model server (scope it, for example `--allow-net=localhost:11434`) |
| `--allow-env` | `PATH` lookup for the shell tool and the API-key variable named by `--api-key-env` (for example `--allow-env=PATH,OPENAI_API_KEY`) |

Narrow flags make Deno itself a second guard behind the agent's own workspace and allowlist checks.

Flags follow the Python CLI where the foundation defines them: `-m/--model`, `-w/--workspace`, `--host`, `--api ollama|openai`,
`--api-key-env`, `--allow-shell`, `--shell-allowlist` (repeatable), `--shell-timeout`, `--version`. API keys are read only from
the named environment variable.

## Library use and the plugin seam

    import { defaultRegistry, run } from "./mod.ts";
    const registry = defaultRegistry().set("stamp", { usage: "```stamp\n```", fn: () => new Date().toISOString() });
    await run("what time is it?", { model: "qwen2.5-coder:7b", workspace: Deno.cwd(), registry });

The `Registry` (`set`, `disable`) is the port's plugin seam (spec section 9). Tool functions may be async. There is no
directory-based plugin loading.

Publishing to JSR (tokenless OIDC from GitHub Actions) needs a package name and scope, which `deno.json` deliberately does not
set yet; see `docs/TRUSTED_PUBLISHING_MATRIX.md` (added by PR #33).

## Differences from the Python reference

* **Shell tool is non-interactive only.** No TTY confirmation prompt; `--allow-shell` plus an allowlist is required, as in the
  reference's non-interactive mode. No `.nakedagent/shell_audit.jsonl` is written (the spec does not define it yet).
* **POSIX word splitting on every OS**; the reference uses a different splitter on Windows and the vectors define only POSIX.
* **Redirects are followed by hand** (301/302/303 become a GET with no body and no credentials; other 3xx are errors) so that
  credentials can never reach a second request.
* **The shell timeout kills the child by hand.** `Deno.Command`'s `signal` option did not stop a running child on Windows
  (found by running the POSIX vectors there), so the port spawns, starts a timer and calls `kill()`.
* **No CR translation**: files are read and written as bytes (spec section 11, quirk 2).
* **No event log, replay, resume, MCP or sidekick**: out of scope for spec v0.1.
* `patch` reproduces the reference's `splitlines()` behaviour (spec section 11, quirk 3) so the two agree, quirk included.

## Testing notes

`deno task test` ignores the 7 vectors marked `requires: posix` on Windows and skips symlink cases where symlinks cannot be created.
Set `NAKEDAGENT_FORCE_POSIX_VECTORS=1` to run them anyway on Windows when POSIX tools (`echo`, `sh`, `sleep`, `head`, `tr`) are on
`PATH`, for example from Git for Windows. Differential test: `deno run --allow-read tools/diff-harness.ts cases.jsonl`.
