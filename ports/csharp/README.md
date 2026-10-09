# nakedagent for .NET (C#)

The C# port of the nakedagent foundation (`spec/SPEC.md` v0.1). Base class library only: `System.Text.Json`, `System.Net.Http`,
`System.Diagnostics.Process`, `System.Text.RegularExpressions` and the core. No NuGet packages (not even a test framework: the tests are
a small console runner) and no `FrameworkReference`; CI fails if either appears. Targets .NET 9 by default.

    cd ports/csharp
    dotnet run --project Nakedagent.Tests               # every vector in spec/conformance/vectors
    dotnet run --project Nakedagent.Cli -- "list the files here" -m qwen2.5-coder:7b

Where only another SDK is installed, override the target: `-p:NG_TFM=net10.0`.

The command-line assembly is `nakedagent-dotnet` (a project named `nakedagent` would collide with the `Nakedagent` library on case-insensitive
file systems). Flags follow the Python CLI where the foundation defines them: `-m/--model`, `-w/--workspace`, `--host`, `--api ollama|openai`,
`--api-key-env`, `--allow-shell`, `--shell-allowlist` (repeatable), `--shell-timeout`, `--version`. API keys are read only from the named
environment variable.

There is no `.nuspec` or package metadata yet; the package id and publishing route (NuGet trusted publishing) are a separate decision, see
`docs/TRUSTED_PUBLISHING_MATRIX.md` (added by PR #33).

## Library use and the plugin seam

    var registry = Prompt.DefaultRegistry().Set("stamp", new Tool((a, c, w) => DateTime.UtcNow.ToString("o"), "```stamp\n```"));
    await Agent.RunAsync("what time is it?", new Options { Model = "qwen2.5-coder:7b", Workspace = Directory.GetCurrentDirectory(), Registry = registry });

`Registry.Set` and `Registry.Disable` are the port's plugin seam (spec section 9). There is no directory-based plugin loading.

## Differences from the Python reference

* **Shell tool is non-interactive only.** No TTY confirmation prompt; `--allow-shell` plus an allowlist is required, as in the
  reference's non-interactive mode. No `.nakedagent/shell_audit.jsonl` is written (the spec does not define it yet).
* **POSIX word splitting on every OS**; the reference uses a different splitter on Windows and the vectors define only POSIX.
* **Redirects are followed by hand** (301/302/303 become a GET with no body and no credentials; other 3xx are errors) so that credentials
  can never reach a second request (`AllowAutoRedirect` is off).
* **Arguments go through `ProcessStartInfo.ArgumentList`** with `UseShellExecute = false`, so nothing is re-parsed by a shell or by Windows
  command-line splitting.
* **No CR translation**: files are read and written as bytes (spec section 11, quirk 2).
* **No event log, replay, resume, MCP or sidekick**: out of scope for spec v0.1.
* `patch` reproduces the reference's `splitlines()` behaviour (spec section 11, quirk 3) so the two agree, quirk included.

## Testing notes

The runner skips the 7 vectors marked `requires: posix` on Windows and any symlink case where symlinks cannot be created. Set
`NAKEDAGENT_FORCE_POSIX_VECTORS=1` to run them anyway on Windows when POSIX tools (`echo`, `sh`, `sleep`, `head`, `tr`) are on `PATH`.
Differential test: build, then `dotnet Nakedagent.Tests/bin/Debug/net9.0/Nakedagent.Tests.dll --diff cases.jsonl > out.jsonl`
(`dotnet run -- --diff` did not pass the arguments through in my tests).
