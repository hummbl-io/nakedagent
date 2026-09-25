import unittest
from pathlib import Path
from unittest.mock import patch

from nakedagent import cli
from nakedagent.llm import OllamaError


class TestCliExitCodes(unittest.TestCase):
    """cli.main() is the only untested module (GLM-5.2 review finding #6).
    The exit-code mapping is the non-trivial part: OllamaError -> 1,
    KeyboardInterrupt -> 130, clean run -> 0. Argparse --version exits 0
    via SystemExit."""

    def test_version_exits_zero(self):
        with self.assertRaises(SystemExit) as ctx:
            cli.main(["--version"])
        self.assertEqual(ctx.exception.code, 0)

    @patch("nakedagent.cli.run")
    def test_clean_oneshot_returns_zero(self, mock_run):
        self.assertEqual(cli.main(["-w", ".", "do something"]), 0)
        mock_run.assert_called_once()

    @patch("nakedagent.cli.run")
    def test_oneshot_passes_shell_flags(self, mock_run):
        self.assertEqual(
            cli.main([
                "--allow-shell",
                "--shell-allowlist",
                "echo",
                "--shell-timeout",
                "3",
                "do something",
            ]),
            0,
        )
        mock_run.assert_called_once_with(
            "do something",
            "qwen2.5-coder:7b",
            Path(".").resolve(),
            "http://localhost:11434",
            allow_shell=True,
            shell_allowlist=("echo",),
            shell_timeout=3,
            trust_plugins=False,
            llm_options={},
        )

    @patch("nakedagent.cli.run")
    def test_oneshot_passes_trust_plugins_flag(self, mock_run):
        self.assertEqual(cli.main(["--trust-plugins", "do something"]), 0)
        mock_run.assert_called_once_with(
            "do something",
            "qwen2.5-coder:7b",
            Path(".").resolve(),
            "http://localhost:11434",
            allow_shell=False,
            shell_allowlist=(),
            shell_timeout=120,
            trust_plugins=True,
            llm_options={},
        )

    @patch("nakedagent.cli.run")
    def test_openai_api_passes_backend_options(self, mock_run):
        self.assertEqual(
            cli.main([
                "--api", "openai",
                "--host", "https://api.example.com/v1",
                "--api-key-env", "MY_KEY",
                "-m", "big-model",
                "do something",
            ]),
            0,
        )
        args, kwargs = mock_run.call_args
        self.assertEqual(args[3], "https://api.example.com/v1")
        self.assertEqual(kwargs["llm_options"], {"api": "openai", "api_key_env": "MY_KEY"})

    @patch("nakedagent.cli.run")
    def test_openai_api_requires_host(self, mock_run):
        self.assertEqual(cli.main(["--api", "openai", "do something"]), 1)
        mock_run.assert_not_called()

    @patch("nakedagent.cli.run")
    def test_oneshot_rejects_non_positive_shell_timeout(self, mock_run):
        self.assertEqual(
            cli.main(["--allow-shell", "--shell-timeout", "0", "do something"]),
            1,
        )
        mock_run.assert_not_called()

    @patch("nakedagent.cli.run", side_effect=OllamaError("boom"))
    def test_ollama_error_exits_one(self, _mock_run):
        self.assertEqual(cli.main(["-w", ".", "do something"]), 1)

    @patch("nakedagent.cli.run", side_effect=KeyboardInterrupt)
    def test_keyboard_interrupt_exits_130(self, _mock_run):
        self.assertEqual(cli.main(["-w", ".", "do something"]), 130)

    def test_event_log_requires_oneshot_prompt(self):
        self.assertEqual(cli.main(["--event-log", "run.jsonl"]), 1)

    @patch("nakedagent.driver.run_functional")
    def test_event_log_routes_to_functional_driver(self, mock_fn):
        self.assertEqual(
            cli.main(["-w", ".", "--event-log", "run.jsonl", "do something"]),
            0,
        )
        self.assertEqual(mock_fn.call_count, 1)
        self.assertEqual(mock_fn.call_args.kwargs["event_log_path"], Path("run.jsonl"))


if __name__ == "__main__":
    unittest.main()
