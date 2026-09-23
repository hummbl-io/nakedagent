from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .llm import APIS, DEFAULT_API_KEY_ENV, DEFAULT_HOST, LLMError
from .loop import run, run_interactive


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="nakedagent", description=__doc__)
    p.add_argument("prompt", nargs="?", help="run once with this prompt, then exit")
    p.add_argument("-m", "--model", default="qwen2.5-coder:7b", help="model name or Ollama tag")
    p.add_argument("-w", "--workspace", type=Path, default=Path.cwd())
    p.add_argument(
        "--host",
        default=None,
        help=(
            f"model server URL (default: {DEFAULT_HOST} for ollama; required for "
            "--api openai, including the version path, e.g. https://api.openai.com/v1)"
        ),
    )
    p.add_argument(
        "--api",
        choices=APIS,
        default="ollama",
        help="wire format: ollama (local, default) or openai (any OpenAI-compatible server)",
    )
    p.add_argument(
        "--api-key-env",
        default=DEFAULT_API_KEY_ENV,
        metavar="VAR",
        help=(
            "environment variable holding the API key for --api openai "
            f"(default: {DEFAULT_API_KEY_ENV}); the key itself is never a flag"
        ),
    )
    p.add_argument(
        "--allow-shell",
        action="store_true",
        help="Allow shell tool execution in non-interactive contexts.",
    )
    p.add_argument(
        "--shell-allowlist",
        action="append",
        default=[],
        metavar="PATTERN",
        help=(
            "Allowed shell command prefixes when --allow-shell is set. "
            "Repeatable. Example: --shell-allowlist 'git status' "
            "--shell-allowlist 'ls'"
        ),
    )
    p.add_argument(
        "--shell-timeout",
        type=int,
        default=120,
        help="Timeout in seconds for shell tool execution.",
    )
    p.add_argument(
        "--event-log",
        type=Path,
        metavar="PATH",
        help=(
            "Run through the functional driver and append every agent event "
            "to a JSONL log at PATH. One-shot mode only. Verify with "
            "`python -m nakedagent.replay PATH`."
        ),
    )
    p.add_argument("--version", action="version", version=__version__)
    args = p.parse_args(argv)

    workspace = args.workspace.resolve()
    shell_allowlist = tuple(
        pattern.strip() for pattern in args.shell_allowlist if pattern.strip()
    )
    if args.shell_timeout <= 0:
        print("error: --shell-timeout must be greater than 0", file=sys.stderr)
        return 1
    if args.event_log and not args.prompt:
        print("error: --event-log requires a one-shot prompt", file=sys.stderr)
        return 1
    host = args.host
    if host is None:
        if args.api != "ollama":
            # No default: silently sending a prompt (and a key) to a server
            # the user didn't name is worse than asking.
            print("error: --api openai needs --host (e.g. https://api.openai.com/v1)", file=sys.stderr)
            return 1
        host = DEFAULT_HOST
    llm_options = {}
    if args.api != "ollama":
        llm_options = {"api": args.api, "api_key_env": args.api_key_env}
    try:
        if args.prompt:
            if args.event_log:
                from .driver import run_functional

                run_functional(
                    args.prompt,
                    args.model,
                    workspace,
                    host,
                    event_log_path=args.event_log,
                    allow_shell=args.allow_shell,
                    shell_allowlist=shell_allowlist,
                    shell_timeout=args.shell_timeout,
                    llm_options=llm_options,
                )
            else:
                run(
                    args.prompt,
                    args.model,
                    workspace,
                    host,
                    allow_shell=args.allow_shell,
                    shell_allowlist=shell_allowlist,
                    shell_timeout=args.shell_timeout,
                    llm_options=llm_options,
                )
        else:
            run_interactive(
                args.model,
                workspace,
                host,
                allow_shell=args.allow_shell,
                shell_allowlist=shell_allowlist,
                shell_timeout=args.shell_timeout,
                llm_options=llm_options,
            )
    except LLMError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
