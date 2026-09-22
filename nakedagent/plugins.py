"""Plugin seam: load user tools without touching the foundation.

This is the omakase substitution mechanism (see DOCTRINE.md). The foundation
ships four curated tools; a user drops a `.py` file in a plugin dir and its
`TOOLS` dict merges into the runtime registry at startup -- no fork, no
registration ceremony, same `(args, content, workspace) -> str` signature.

A plugin can also define `DISABLE = ["shell", "write"]` to remove tools from
the registry entirely -- "send it back" rather than swap. This is the omakase
autonomy half: a user who wants a read-only agent disables `shell` and
`write`; the model never sees them in the prompt, so it never tries to call
them. DISABLE is applied after all TOOLS merges, so it wins over any
substitution, including a plugin that both defines and disables a name.

Search order (later dirs win, so user-local overrides repo-local):
  1. <workspace>/.nakedagent/plugins/   -- checked first
  2. ~/.nakedagent/plugins/              -- checked second, overrides (1)

A plugin file is any `*.py` in those dirs. It must define a module-level
`TOOLS: dict[str, ToolFunc]` and/or `DISABLE: list[str]`. Anything else in
the module is the plugin's business. A file that fails to import or defines
neither is skipped with a one-line warning to stderr -- one bad plugin must
not brick the agent.

ponytail: no entry-point group, no metadata, no version negotiation. A plugin
is just a Python file that defines TOOLS and/or DISABLE. If a plugin needs to
declare compatibility or metadata, that's a substitution someone makes
later, not now.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from .tools import TOOLS, ToolFunc


def _plugin_dirs(workspace: Path) -> list[Path]:
    """Dirs to scan, in load order. Missing dirs are skipped silently."""
    return [
        workspace / ".nakedagent" / "plugins",
        Path.home() / ".nakedagent" / "plugins",
    ]


def _load_one(path: Path):
    """Import a single plugin file and return the module, or None.

    Returns None (and warns to stderr) on any failure so one broken plugin
    can't kill the whole agent -- same fail-soft posture as tool exceptions
    in loop.step(). A plugin with neither TOOLS nor DISABLE is also skipped.
    """
    modname = f"nakedagent_plugin_{path.stem}"
    spec = importlib.util.spec_from_file_location(modname, path)
    if spec is None or spec.loader is None:
        print(f"warning: could not load plugin {path.name}", file=sys.stderr)
        return None
    module = importlib.util.module_from_spec(spec)
    try:
        sys.modules[modname] = module  # so plugins can import each other by name
        spec.loader.exec_module(module)
    except Exception as e:  # noqa: BLE001 -- any plugin error is reported, not fatal
        # don't leave a half-loaded module shadowing a future good one
        sys.modules.pop(modname, None)
        print(
            f"warning: plugin {path.name} failed to load ({type(e).__name__}: {e})",
            file=sys.stderr,
        )
        return None
    has_tools = isinstance(getattr(module, "TOOLS", None), dict)
    has_disable = isinstance(getattr(module, "DISABLE", None), list)
    if not has_tools and not has_disable:
        print(
            f"warning: plugin {path.name} defines no TOOLS or DISABLE; skipped",
            file=sys.stderr,
        )
        return None
    return module


def load_plugins(workspace: Path, registry: dict[str, ToolFunc] | None = None) -> dict[str, ToolFunc]:
    """Scan plugin dirs, merge every plugin's TOOLS into `registry` (default:
    the foundation TOOLS), apply every plugin's DISABLE, and return the
    merged registry.

    Later dirs override earlier, and within a dir later files override
    earlier -- deterministic, last-write-wins. Tool names are lowercased to
    match the case-insensitive dispatch in loop.step(). DISABLE is applied
    after all merges, so it wins over any substitution.
    """
    merged: dict[str, ToolFunc] = dict(registry if registry is not None else TOOLS)
    disabled: set[str] = set()
    for path in _plugin_files(workspace):
        module = _load_one(path)
        if module is None:
            continue
        plugin_tools = getattr(module, "TOOLS", None)
        if isinstance(plugin_tools, dict):
            for name, func in plugin_tools.items():
                merged[name.lower()] = func
        disable = getattr(module, "DISABLE", None)
        if isinstance(disable, list):
            disabled.update(n.lower() for n in disable)
    for name in disabled:
        merged.pop(name, None)
    return merged


def _plugin_files(workspace: Path):
    for d in _plugin_dirs(workspace):
        if not d.is_dir():
            continue
        for path in sorted(d.glob("*.py")):
            if not path.name.startswith("_"):  # _foo.py is private, not a plugin
                yield path
