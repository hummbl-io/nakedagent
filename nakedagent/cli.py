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
    p.add_argument("--version", action="version", version=__version__)
    args = p.parse_args(argv)

    workspace = args.workspace.resolve()
    try:
        if args.prompt:
            run(args.prompt, args.model, workspace, args.host)
        else:
            run_interactive(args.model, workspace, args.host)
    except OllamaError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
