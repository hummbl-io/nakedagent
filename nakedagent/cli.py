"""nakedagent -- a zero-dependency terminal coding agent."""

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
        "--temperature",
        type=float,
        default=None,
        metavar="T",
        help="sampling temperature for the model (default: the server's own default)",
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
        "--trust-workspace-plugins",
        action="store_true",
        help=(
            "Load <workspace>/.nakedagent/plugins/*.py at startup. Off by "
            "default: workspace plugins are repo-controlled code running with "
            "your privileges. Only set this in workspaces you trust. "
            "User-global ~/.nakedagent/plugins/ always loads."
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
    if args.temperature is not None:
        llm_options["temperature"] = args.temperature
    try:
        if args.prompt:
            run(
                args.prompt,
                args.model,
                workspace,
                host,
                allow_shell=args.allow_shell,
                shell_allowlist=shell_allowlist,
                shell_timeout=args.shell_timeout,
                llm_options=llm_options,
                trust_workspace_plugins=args.trust_workspace_plugins,
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
                trust_workspace_plugins=args.trust_workspace_plugins,
            )
    except LLMError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
