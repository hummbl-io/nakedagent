from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .llm import DEFAULT_HOST, OllamaError
from .loop import run, run_interactive


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="nakedagent", description=__doc__)
    p.add_argument("prompt", nargs="?", help="run once with this prompt, then exit")
    p.add_argument("-m", "--model", default="qwen2.5-coder:7b", help="Ollama model tag")
    p.add_argument("-w", "--workspace", type=Path, default=Path.cwd())
    p.add_argument("--host", default=DEFAULT_HOST, help="Ollama server URL")
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
    p.add_argument("--version", action="version", version=__version__)
    args = p.parse_args(argv)

    workspace = args.workspace.resolve()
    shell_allowlist = tuple(
        pattern.strip() for pattern in args.shell_allowlist if pattern.strip()
    )
    if args.shell_timeout <= 0:
        print("error: --shell-timeout must be greater than 0", file=sys.stderr)
        return 1
    try:
        if args.prompt:
            run(
                args.prompt,
                args.model,
                workspace,
                args.host,
                allow_shell=args.allow_shell,
                shell_allowlist=shell_allowlist,
                shell_timeout=args.shell_timeout,
            )
        else:
            run_interactive(
                args.model,
                workspace,
                args.host,
                allow_shell=args.allow_shell,
                shell_allowlist=shell_allowlist,
                shell_timeout=args.shell_timeout,
            )
    except OllamaError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
