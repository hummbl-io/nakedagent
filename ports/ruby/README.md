# nakedagent for Ruby

The Ruby port of the nakedagent foundation (`spec/SPEC.md` v0.1). No gems: the library requires only the standard library
(`json`, `net/http`, `uri`, `open3`, `fileutils`, `optparse` and the core). Tests use `minitest`, which ships with Ruby. There is no
`Gemfile` and CI fails if one appears. Requires Ruby >= 3.3 (developed on 4.0).

    cd ports/ruby
    ruby test/conformance_test.rb                    # every vector in spec/conformance/vectors
    ruby exe/nakedagent "list the files here" -m qwen2.5-coder:7b

Flags follow the Python CLI where the foundation defines them: `-m/--model`, `-w/--workspace`, `--host`, `--api ollama|openai`,
`--api-key-env`, `--allow-shell`, `--shell-allowlist` (repeatable), `--shell-timeout`, `--version`. The prompt may appear before,
between or after flags. API keys are read only from the named environment variable.

There is no `.gemspec` yet: the gem name and the publishing route (RubyGems trusted publishing, which allows a "pending" publisher for a
gem that does not exist yet) are a separate decision, see `docs/TRUSTED_PUBLISHING_MATRIX.md` (added by PR #33).

## Library use and the plugin seam

    require_relative "lib/nakedagent"
    registry = Nakedagent::Prompt.default_registry
    registry.set("stamp", usage: "```stamp\n```") { |_args, _content, _workspace| Time.now.utc.iso8601 }
    Nakedagent::Agent.run("what time is it?", Nakedagent::Options.new(model: "qwen2.5-coder:7b", workspace: Dir.pwd, registry: registry))

`Registry#set` and `Registry#disable` are the port's plugin seam (spec section 9). There is no directory-based plugin loading.

## Differences from the Python reference

* **Shell tool is non-interactive only.** No TTY confirmation prompt; `--allow-shell` plus an allowlist is required, as in the
  reference's non-interactive mode. No `.nakedagent/shell_audit.jsonl` is written (the spec does not define it yet).
* **POSIX word splitting on every OS**; the reference uses a different splitter on Windows and the vectors define only POSIX. Ruby's
  `Shellwords` is not used because its edge cases differ from Python's `shlex`.
* **Redirects are followed by hand** (301/302/303 become a GET with no body and no credentials; other 3xx are errors) so that
  credentials can never reach a second request.
* **The program is started with the `[command, argv0]` form.** With a single string and no arguments Ruby's `spawn` may hand the string to a
  shell or split it at spaces (it failed on `C:\Program Files\...` before this was fixed), so the port always uses the array form.
* **No CR translation**: files are read and written as bytes (spec section 11, quirk 2).
* **No event log, replay, resume, MCP or sidekick**: out of scope for spec v0.1.
* `patch` reproduces the reference's `splitlines()` behaviour (spec section 11, quirk 3) so the two agree, quirk included.

## Testing notes

`ruby test/conformance_test.rb` skips the 7 vectors marked `requires: posix` on Windows and any symlink case where symlinks cannot be
created. Set `NAKEDAGENT_FORCE_POSIX_VECTORS=1` to run them anyway on Windows when POSIX tools (`echo`, `sh`, `sleep`, `head`, `tr`)
are on `PATH`, for example from Git for Windows. Differential test: `ruby tools/diff_harness.rb cases.jsonl`.
