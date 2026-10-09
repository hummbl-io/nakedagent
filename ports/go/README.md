# nakedagent for Go

The Go port of the nakedagent foundation (`spec/SPEC.md` v0.1). Standard library only: `go.mod` has no
`require` lines and CI fails if one appears.

    cd ports/go
    go test ./...                       # runs every vector in spec/conformance/vectors
    go build -o nakedagent ./cmd/nakedagent
    ./nakedagent "list the files here" -m qwen2.5-coder:7b

Flags follow the Python CLI where the foundation defines them: `-m/--model`, `-w/--workspace`, `--host`,
`--api ollama|openai`, `--api-key-env`, `--allow-shell`, `--shell-allowlist` (repeatable), `--shell-timeout`,
`--version`. The prompt may come before, between or after flags. API keys are read only from the named
environment variable.

## Standard-library modules used

Library and command: `bufio`, `bytes`, `context`, `encoding/json`, `errors`, `flag`, `fmt`, `io`, `net/http`, `net/url`,
`os`, `os/exec`, `path/filepath`, `regexp`, `runtime`, `sort`, `strings`, `time`, `unicode`, `unicode/utf8`.
Tests additionally use `encoding/base64`, `net`, `net/http/httptest`, `reflect` and `testing`.

## Library use and the plugin seam

`nakedagent.Run(prompt, &Options{...})` runs one turn; `Step`, `RunUntilDone` and `NewConversation` give finer control.
The registry (`DefaultRegistry`, `Registry.Set`, `Registry.Disable`) is the port's plugin seam: add or replace a tool, or send a
foundation tool back, before the run (spec section 9). Go cannot load source files at runtime, so there is no directory-based
plugin loading.

## Differences from the Python reference

* **Shell tool is non-interactive only.** There is no TTY confirmation prompt; `--allow-shell` plus an allowlist is required, as
  in the reference's non-interactive mode. No `.nakedagent/shell_audit.jsonl` is written (the spec does not define it yet).
* **POSIX word splitting on every OS.** The reference switches to a different splitter on Windows; the vectors only define POSIX.
* **Exit status of signalled processes** is Go's `ExitCode()` (-1), not Python's negative signal number.
* **No CR translation.** The reference reads files in text mode (folding `\r\n` to `\n`, and on Windows writing `\n` as `\r\n`); this
  port reads and writes bytes as they are (spec section 11, quirk 2).
* **No event log, replay, resume, MCP or sidekick**: out of scope for spec v0.1.
* `patch` reproduces the reference's `splitlines()` behaviour (spec section 11, quirk 3) so the two agree, quirk included.
