import tempfile
import unittest
from pathlib import Path

from nakedagent.plugins import load_plugins
from nakedagent.tools import TOOLS


def _write_plugin(d: Path, name: str, body: str) -> None:
    (d / name).write_text(body)


class TestPluginLoad(unittest.TestCase):
    """The seam is the omakase substitution mechanism (DOCTRINE.md). The
    load-bearing invariants: plugins merge into the registry, a broken
    plugin is skipped not fatal, user-global overrides repo-local, and the
    foundation tools survive untouched when no plugins exist."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_no_plugin_dirs_returns_foundation_unchanged(self):
        merged = load_plugins(self.workspace)
        self.assertEqual(set(merged.keys()), set(TOOLS.keys()))

    def test_plugin_tool_is_dispatchable(self):
        d = self.workspace / ".nakedagent" / "plugins"
        d.mkdir(parents=True)
        _write_plugin(d, "upper.py",
            "def to_upper(args, content, workspace):\n"
            "    return content.upper()\n"
            "TOOLS = {'upper': to_upper}\n")
        merged = load_plugins(self.workspace)
        self.assertIn("upper", merged)
        self.assertEqual(merged["upper"]("", "hi", self.workspace), "HI")
        # foundation tools still present
        self.assertIn("shell", merged)

    def test_broken_plugin_is_skipped_not_fatal(self):
        d = self.workspace / ".nakedagent" / "plugins"
        d.mkdir(parents=True)
        _write_plugin(d, "broken.py", "raise RuntimeError('boom')\n")
        _write_plugin(d, "good.py",
            "def ok(args, content, workspace):\n"
            "    return 'ok'\n"
            "TOOLS = {'ok': ok}\n")
        merged = load_plugins(self.workspace)
        self.assertNotIn("broken", merged)
        self.assertIn("ok", merged)  # the good plugin still loaded

    def test_plugin_without_tools_dict_is_skipped(self):
        d = self.workspace / ".nakedagent" / "plugins"
        d.mkdir(parents=True)
        _write_plugin(d, "notools.py", "x = 1\n")
        merged = load_plugins(self.workspace)
        self.assertEqual(set(merged.keys()), set(TOOLS.keys()))

    def test_plugin_can_override_foundation_tool(self):
        # a substitution: a plugin named 'shell' replaces the foundation shell.
        # This is the omakase "send it back" path -- the seam lets a user
        # swap a curated default without forking the foundation.
        d = self.workspace / ".nakedagent" / "plugins"
        d.mkdir(parents=True)
        _write_plugin(d, "safe_shell.py",
            "def safe(args, content, workspace):\n"
            "    return 'blocked by plugin'\n"
            "TOOLS = {'shell': safe}\n")
        merged = load_plugins(self.workspace)
        self.assertEqual(merged["shell"]("", "rm -rf /", self.workspace),
                         "blocked by plugin")

    def test_underscore_files_are_not_plugins(self):
        d = self.workspace / ".nakedagent" / "plugins"
        d.mkdir(parents=True)
        _write_plugin(d, "_helper.py",
            "def h(args, content, workspace):\n"
            "    return 'should not load'\n"
            "TOOLS = {'hidden': h}\n")
        merged = load_plugins(self.workspace)
        self.assertNotIn("hidden", merged)

    def test_tool_names_are_case_insensitive(self):
        # matches the case-insensitive dispatch in loop.step()
        d = self.workspace / ".nakedagent" / "plugins"
        d.mkdir(parents=True)
        _write_plugin(d, "mixed.py",
            "def f(args, content, workspace):\n"
            "    return 'r'\n"
            "TOOLS = {'MyTool': f}\n")
        merged = load_plugins(self.workspace)
        self.assertIn("mytool", merged)


class TestPluginDisable(unittest.TestCase):
    """DISABLE is the omakase autonomy half (DOCTRINE.md): a user who wants a
    read-only agent disables `shell` and `write`; the model never sees them
    in the prompt, so it never tries to call them. DISABLE is applied after
    all TOOLS merges, so it wins over any substitution."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_disable_removes_foundation_tool(self):
        d = self.workspace / ".nakedagent" / "plugins"
        d.mkdir(parents=True)
        _write_plugin(d, "readonly.py", "DISABLE = ['shell', 'write']\n")
        merged = load_plugins(self.workspace)
        self.assertNotIn("shell", merged)
        self.assertNotIn("write", merged)
        self.assertIn("read", merged)
        self.assertIn("patch", merged)

    def test_disable_removes_plugin_tool(self):
        d = self.workspace / ".nakedagent" / "plugins"
        d.mkdir(parents=True)
        _write_plugin(d, "add.py",
            "def f(args, content, workspace):\n"
            "    return 'r'\n"
            "TOOLS = {'upper': f}\n")
        _write_plugin(d, "disable_upper.py", "DISABLE = ['upper']\n")
        merged = load_plugins(self.workspace)
        self.assertNotIn("upper", merged)

    def test_plugin_with_only_disable_is_valid(self):
        # a plugin that defines DISABLE but no TOOLS is a valid "disable these"
        # plugin -- it should not be skipped as a no-op.
        d = self.workspace / ".nakedagent" / "plugins"
        d.mkdir(parents=True)
        _write_plugin(d, "noshell.py", "DISABLE = ['shell']\n")
        merged = load_plugins(self.workspace)
        self.assertNotIn("shell", merged)
        self.assertIn("read", merged)

    def test_disable_wins_over_substitution(self):
        # a plugin that both defines a tool AND another plugin disables that
        # name: DISABLE is applied after all merges, so it wins.
        d = self.workspace / ".nakedagent" / "plugins"
        d.mkdir(parents=True)
        _write_plugin(d, "add.py",
            "def f(args, content, workspace):\n"
            "    return 'replaced'\n"
            "TOOLS = {'shell': f}\n")
        _write_plugin(d, "noshell.py", "DISABLE = ['shell']\n")
        merged = load_plugins(self.workspace)
        self.assertNotIn("shell", merged)

    def test_disable_is_case_insensitive(self):
        d = self.workspace / ".nakedagent" / "plugins"
        d.mkdir(parents=True)
        _write_plugin(d, "noshell.py", "DISABLE = ['SHELL']\n")
        merged = load_plugins(self.workspace)
        self.assertNotIn("shell", merged)


if __name__ == "__main__":
    unittest.main()
