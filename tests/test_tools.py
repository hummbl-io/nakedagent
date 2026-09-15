import tempfile
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from nakedagent.tools import (
    _split_command,
    _split_search_replace,
    tool_patch,
    tool_read,
    tool_shell,
    tool_write,
)


class TestTools(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self._tmp.name)
        # Portable stand-in for `echo`: non-interactive shell runs programs
        # directly (shell=False), and on Windows `echo` is a cmd.exe built-in,
        # not an executable. A tiny script run by this interpreter behaves the
        # same on every platform.
        (self.workspace / "echo.py").write_text(
            "import sys\nprint(' '.join(sys.argv[1:]))\n", encoding="utf-8"
        )
        self.echo = f'"{sys.executable}" echo.py'

    def tearDown(self):
        self._tmp.cleanup()

    def test_write_then_read(self):
        tool_write("hello.txt", "hi there", self.workspace)
        out = tool_read("hello.txt", "", self.workspace)
        self.assertIn("hi there", out)

    def test_read_missing_file(self):
        out = tool_read("nope.txt", "", self.workspace)
        self.assertIn("does not exist", out)

    def test_write_rejects_path_outside_workspace(self):
        out = tool_write("../escape.txt", "x", self.workspace)
        self.assertIn("outside the workspace", out)

    def test_patch_replaces_unique_match(self):
        tool_write("f.py", "def f():\n    return 1\n", self.workspace)
        block = "<<<<<<< SEARCH\n    return 1\n=======\n    return 2\n>>>>>>> REPLACE"
        out = tool_patch("f.py", block, self.workspace)
        self.assertIn("Patched", out)
        self.assertEqual(
            (self.workspace / "f.py").read_text(), "def f():\n    return 2\n"
        )

    def test_patch_rejects_no_match(self):
        tool_write("f.py", "abc\n", self.workspace)
        block = "<<<<<<< SEARCH\nzzz\n=======\nyyy\n>>>>>>> REPLACE"
        out = tool_patch("f.py", block, self.workspace)
        self.assertIn("not found", out)

    def test_patch_rejects_ambiguous_match(self):
        tool_write("f.py", "x = 1\nx = 1\n", self.workspace)
        block = "<<<<<<< SEARCH\nx = 1\n=======\nx = 2\n>>>>>>> REPLACE"
        out = tool_patch("f.py", block, self.workspace)
        self.assertIn("2 locations", out)

    @patch("nakedagent.tools.sys.stdin.isatty", return_value=False)
    def test_shell_runs_and_captures_output(self, _mock_isatty):
        # non-interactive path: no confirmation gate, matches -p/piped use
        out = tool_shell(
            "", f"{self.echo} hello-nakedagent", self.workspace,
            allow_shell=True,
            shell_allowlist=(self.echo,),
        )
        self.assertIn("hello-nakedagent", out)

    @patch("nakedagent.tools.sys.stdin.isatty", return_value=False)
    def test_shell_requires_allow_flag(self, _mock_isatty):
        out = tool_shell("", "echo denied", self.workspace)
        self.assertIn("requires --allow-shell", out)

    @patch("nakedagent.tools.sys.stdin.isatty", return_value=False)
    def test_shell_requires_allowlist_match(self, _mock_isatty):
        out = tool_shell(
            "",
            "rm -rf /tmp/forbidden",
            self.workspace,
            allow_shell=True,
            shell_allowlist=(self.echo,),
        )
        self.assertIn("not in --shell-allowlist", out)

    @patch("nakedagent.tools.sys.stdin.isatty", return_value=False)
    def test_shell_audit_log_records_blocked_and_allowed_calls(self, _mock_isatty):
        # A blocked call should still be auditable.
        blocked = tool_shell(
            "",
            "rm -rf /tmp/forbidden",
            self.workspace,
            allow_shell=True,
            shell_allowlist=("ls",),
        )
        self.assertIn("blocked", blocked)
        allowed = tool_shell(
            "",
            f"{self.echo} allowed",
            self.workspace,
            allow_shell=True,
            shell_allowlist=(self.echo,),
        )
        self.assertIn("exit 0", allowed)
        log = self.workspace / ".nakedagent" / "shell_audit.jsonl"
        events = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        self.assertGreaterEqual(len(events), 2)
        self.assertEqual(events[0]["allowed"], False)
        self.assertEqual(events[1]["allowed"], True)

    @patch("nakedagent.tools.subprocess.run")
    @patch("nakedagent.tools.sys.stdin.isatty", return_value=False)
    def test_shell_passes_timeout(self, _mock_isatty, mock_run):
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = "ok"
        proc.stderr = ""
        mock_run.return_value = proc

        out = tool_shell(
            "",
            f"{self.echo} hi",
            self.workspace,
            allow_shell=True,
            shell_allowlist=(self.echo,),
            shell_timeout=3,
        )
        self.assertIn("ok", out)
        called_kwargs = mock_run.call_args.kwargs
        self.assertEqual(called_kwargs["timeout"], 3)

    @patch("nakedagent.tools.subprocess.run")
    @patch("nakedagent.tools.sys.stdin.isatty", return_value=False)
    def test_shell_exposes_configured_timeout_in_error(
        self, _mock_isatty, mock_run
    ):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="echo hi", timeout=7)

        out = tool_shell(
            "",
            f"{self.echo} slow",
            self.workspace,
            allow_shell=True,
            shell_allowlist=(self.echo,),
            shell_timeout=7,
        )
        self.assertIn("command timed out after 7s", out)

    @patch("nakedagent.tools.sys.stdin.isatty", return_value=True)
    @patch("builtins.input", return_value="n")
    def test_shell_declines_when_user_says_no(self, _mock_input, _mock_isatty):
        out = tool_shell("", "echo should-not-run", self.workspace)
        self.assertIn("declined", out)

    @patch("nakedagent.tools.sys.stdin.isatty", return_value=True)
    @patch("builtins.input", side_effect=EOFError)
    def test_shell_fails_safe_on_unreadable_confirmation(self, _mock_input, _mock_isatty):
        # isatty() can lie (true but not actually readable, as happens in
        # some sandboxed/CI shells) -- must decline, not crash.
        out = tool_shell("", "echo should-not-run", self.workspace)
        self.assertIn("Error", out)

    @patch("nakedagent.tools.sys.stdin.isatty", return_value=False)
    def test_shell_blocks_semicolon_injection(self, _mock_isatty):
        # "git status; rm -rf /" must not match allowlist "git status"
        out = tool_shell(
            "", f"{self.echo} hi; echo injected", self.workspace,
            allow_shell=True, shell_allowlist=(f"{self.echo} hi",),
        )
        self.assertIn("not in --shell-allowlist", out)

    @patch("nakedagent.tools.sys.stdin.isatty", return_value=False)
    def test_shell_blocks_command_substitution(self, _mock_isatty):
        out = tool_shell(
            "", f"{self.echo} $(echo injected)", self.workspace,
            allow_shell=True, shell_allowlist=(self.echo,),
        )
        # With shell=False, $(echo injected) is a literal arg — no injection.
        # But the allowlist matches "echo" so it runs; the arg is literal.
        self.assertIn("exit 0", out)
        self.assertIn("$(echo injected)", out)

    @patch("nakedagent.tools.sys.stdin.isatty", return_value=False)
    def test_shell_pipe_is_literal_with_shell_false(self, _mock_isatty):
        # "echo hi | cat" matches allowlist "echo hi" by argv prefix, but
        # with shell=False the pipe is a literal arg — no pipe injection.
        out = tool_shell(
            "", f"{self.echo} hi | cat", self.workspace,
            allow_shell=True, shell_allowlist=(f"{self.echo} hi",),
        )
        self.assertIn("hi | cat", out)

    @patch("nakedagent.tools.sys.stdin.isatty", return_value=False)
    def test_shell_and_chain_is_literal_with_shell_false(self, _mock_isatty):
        # "echo hi && echo injected" matches "echo hi" by argv prefix, but
        # with shell=False "&&" is a literal arg — the second echo never runs.
        out = tool_shell(
            "", f"{self.echo} hi && echo injected", self.workspace,
            allow_shell=True, shell_allowlist=(f"{self.echo} hi",),
        )
        # echo outputs "hi && echo injected" as a literal string — the &&
        # did not chain a second command.
        self.assertIn("hi && echo injected", out)

    @patch("nakedagent.tools.sys.stdin.isatty", return_value=False)
    def test_shell_allowlist_matches_argv_prefix(self, _mock_isatty):
        # "git status --short" should match allowlist "git status"
        out = tool_shell(
            "", f"{self.echo} hello world", self.workspace,
            allow_shell=True, shell_allowlist=(self.echo,),
        )
        self.assertIn("hello world", out)

    @patch("nakedagent.tools.subprocess.run")
    @patch("nakedagent.tools.sys.stdin.isatty", return_value=False)
    def test_shell_noninteractive_uses_shell_false(self, _mock_isatty, mock_run):
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = "ok"
        proc.stderr = ""
        mock_run.return_value = proc

        tool_shell(
            "", f"{self.echo} hi", self.workspace,
            allow_shell=True, shell_allowlist=(self.echo,),
        )
        called_kwargs = mock_run.call_args.kwargs
        self.assertFalse(called_kwargs["shell"])

    @patch("nakedagent.tools.subprocess.run")
    @patch("nakedagent.tools.sys.stdin.isatty", return_value=True)
    @patch("builtins.input", return_value="y")
    def test_shell_interactive_uses_shell_true(self, _mock_input, _mock_isatty, mock_run):
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = "ok"
        proc.stderr = ""
        mock_run.return_value = proc

        tool_shell("", "echo hi", self.workspace)
        called_kwargs = mock_run.call_args.kwargs
        self.assertTrue(called_kwargs["shell"])

    @patch("nakedagent.tools.sys.stdin.isatty", return_value=False)
    def test_shell_non_executable_gives_clear_error(self, _mock_isatty):
        # Without a shell, a name that is not a program on PATH (e.g. a cmd.exe
        # built-in) must yield an actionable message, not a bare FileNotFoundError.
        out = tool_shell(
            "", "definitely-not-a-program-7f3a hi", self.workspace,
            allow_shell=True, shell_allowlist=("definitely-not-a-program-7f3a",),
        )
        self.assertIn("not an executable on PATH", out)
        self.assertNotIn("FileNotFoundError", out)

    def test_split_command_windows_keeps_backslashes_and_quoted_spaces(self):
        with patch("nakedagent.tools.os.name", "nt"):
            argv = _split_command(r'"C:\Program Files\x\tool.exe" --flag "a b" plain')
        self.assertEqual(argv, [r"C:\Program Files\x\tool.exe", "--flag", "a b", "plain"])

    def test_split_command_posix_rules_off_windows(self):
        with patch("nakedagent.tools.os.name", "posix"):
            self.assertEqual(_split_command("git commit -m 'two words'"),
                             ["git", "commit", "-m", "two words"])

    @patch("nakedagent.tools.subprocess.run")
    @patch("nakedagent.tools.shutil.which", return_value=r"C:\tools\build.cmd")
    @patch("nakedagent.tools.sys.stdin.isatty", return_value=False)
    def test_shell_blocks_cmd_metachars_for_batch_files_on_windows(
        self, _mock_isatty, _mock_which, mock_run
    ):
        # Windows runs .bat/.cmd through cmd.exe even with shell=False, so
        # metacharacters in arguments would be interpreted there.
        with patch("nakedagent.tools.os.name", "nt"):
            out = tool_shell(
                "", "build.cmd target&whoami", self.workspace,
                allow_shell=True, shell_allowlist=("build.cmd",),
            )
        self.assertIn("metacharacters", out)
        mock_run.assert_not_called()

    def test_split_search_replace_requires_start_marker(self):
        # GLM-5.2 review finding #2, related defect caught while fixing it:
        # the old implementation defaulted the SEARCH start to line 0 when
        # no "<<<<<<<" was present at all, silently treating whatever came
        # first as SEARCH content instead of erroring. Now it's required.
        missing_start = "old\n=======\nnew\n>>>>>>> REPLACE"
        with self.assertRaises(ValueError):
            _split_search_replace(missing_start)

    def test_split_search_replace_sequential_not_independent(self):
        # The actual finding #2 mechanism: each marker is found *after* the
        # previous one, not independently from index 0 -- so a marker-only
        # line that appears before the real block (e.g. leftover content
        # above it) doesn't get mistaken for part of the block.
        text = "=======\n<<<<<<< SEARCH\nold\n=======\nnew\n>>>>>>> REPLACE"
        search, replace = _split_search_replace(text)
        self.assertEqual(search, "old")
        self.assertEqual(replace, "new")

    def test_patch_rejects_conflict_marker_content_ambiguity(self):
        # Case E from the review: patching a file to resolve conflict
        # markers, where the intended SEARCH text itself contains a second
        # <<<<<<< before the real >>>>>>>, must be rejected, not silently
        # miswritten with a "Patched" success message.
        tool_write("f.txt", "x\n", self.workspace)
        block = (
            "<<<<<<< SEARCH\n"
            "<<<<<<< HEAD\n"
            "ours\n"
            "=======\n"
            "theirs\n"
            ">>>>>>> branch\n"
            "=======\n"
            "RESOLVED\n"
            ">>>>>>> REPLACE"
        )
        out = tool_patch("f.txt", block, self.workspace)
        self.assertIn("Error", out)
        self.assertEqual((self.workspace / "f.txt").read_text(), "x\n")


if __name__ == "__main__":
    unittest.main()
