"""Offline benchmark regressions: fake services and temporary Git fixtures only."""

from __future__ import annotations

import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class Rows(list):
    def select(self, indices):
        return Rows(self[i] for i in indices)


def load_bench(filename):
    """Import without installing or importing datasets/SWE-bench dependencies."""
    modules = {name: types.ModuleType(name) for name in (
        "datasets", "swebench", "swebench.harness", "swebench.harness.grading",
        "swebench.harness.utils",
    )}
    modules["datasets"].load_dataset = lambda *a, **kw: Rows()
    modules["swebench.harness.grading"].get_eval_report = lambda *a, **kw: {}
    modules["swebench.harness.utils"].make_test_spec = lambda row: None
    spec = importlib.util.spec_from_file_location(filename, ROOT / "bench" / f"{filename}.py")
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, modules):
        spec.loader.exec_module(module)
    return module


class RunnerIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.out = self.root / "out"
        self.runner = load_bench("run_nakedagent_swebench")
        self.iid = "fixture__repo-1"
        self.baseline = "a" * 40
        self.calls = []

    def command(self, cmd, timeout=600):
        self.calls.append((cmd, timeout))
        if "git" in cmd:
            args = cmd[cmd.index("git") + 1:]
            if args[:1] == ["rev-parse"]:
                return subprocess.CompletedProcess(cmd, 0, self.baseline + "\n", "")
            if args[:1] == ["ls-files"]:
                return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def invoke(self, *, command=None, model=None, mode="bash"):
        from nakedagent import loop
        datasets = types.ModuleType("datasets")
        datasets.load_dataset = lambda *a, **kw: Rows([
            {"instance_id": self.iid, "problem_statement": "inert fixture"},
        ])

        def default_model(messages, *args, **kwargs):
            messages.append({"role": "assistant", "content": "fixture done"})

        argv = ["runner", "--naked-src", str(ROOT), "--out", str(self.out),
                "--slice", "0:1", "--mode", mode]
        with patch.dict(sys.modules, {"datasets": datasets}), \
                patch.object(sys, "argv", argv), patch.object(sys, "path", list(sys.path)), \
                patch.object(loop, "MAX_STEPS", loop.MAX_STEPS), \
                patch.object(loop, "_run_until_done", side_effect=model or default_model) as call, \
                patch.object(self.runner, "sh", side_effect=command or self.command), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(self.runner.main(), 0)
        return call.call_count

    def predictions(self):
        path = self.out / "preds.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def trajectory(self):
        return json.loads((self.out / f"{self.iid}.traj.json").read_text(encoding="utf-8"))

    @unittest.skipUnless(shutil.which("git"), "Git is required for the temporary index fixture")
    def test_staged_unstaged_untracked_and_binary_changes_preserve_index(self):
        repo = self.root / "repo"
        repo.mkdir()

        def git(args, cwd=repo):
            return subprocess.run(["git", "-c", "core.autocrlf=false", *args], cwd=cwd,
                                  capture_output=True, text=True, encoding="utf-8", timeout=10, check=False)

        self.assertEqual(git(["init", "-q"]).returncode, 0)
        (repo / "tracked.txt").write_bytes(b"old\n")
        (repo / "deleted.txt").write_bytes(b"remove me\n")
        self.assertEqual(git(["add", "tracked.txt", "deleted.txt"]).returncode, 0)
        tree = git(["write-tree"])
        self.assertEqual(tree.returncode, 0)
        self.baseline = tree.stdout.strip()
        index_after_model = []

        def model(messages, *args, **kwargs):
            (repo / "tracked.txt").write_bytes(b"staged\n")
            self.assertEqual(git(["add", "tracked.txt"]).returncode, 0)
            (repo / "tracked.txt").write_bytes(b"staged\nunstaged\n")
            (repo / "deleted.txt").unlink()
            (repo / "staged new.txt").write_bytes(b"staged addition\n")
            self.assertEqual(git(["add", "staged new.txt"]).returncode, 0)
            (repo / "new file.txt").write_bytes(b"new content\n")
            (repo / "new.bin").write_bytes(b"\0\1\2\xff")
            (repo / "empty.txt").write_bytes(b"")
            index_after_model.append(git(["ls-files", "--stage", "-z"]).stdout)

        def command(cmd, timeout=600):
            if "git" in cmd and "rev-parse" not in cmd:
                args = cmd[cmd.index("git") + 1:]
                return git(args)
            return self.command(cmd, timeout)

        self.invoke(command=command, model=model)
        result = self.predictions()[self.iid]["model_patch"]
        self.assertIn("-old\n+staged\n+unstaged", result)
        self.assertIn("new file.txt", result)
        self.assertIn("+new content", result)
        self.assertIn("new.bin", result)
        self.assertIn("GIT binary patch", result)
        self.assertIn("empty.txt", result)
        self.assertEqual(git(["ls-files", "--stage", "-z"]).stdout, index_after_model[0])
        # Apply to a separate temporary baseline checkout: concatenated patches
        # must recreate the actual final files, including binary/new/empty files.
        applied_repo = self.root / "applied"
        applied_repo.mkdir()
        self.assertEqual(git(["init", "-q"], applied_repo).returncode, 0)
        (applied_repo / "tracked.txt").write_bytes(b"old\n")
        (applied_repo / "deleted.txt").write_bytes(b"remove me\n")
        self.assertEqual(git(["add", "."], applied_repo).returncode, 0)
        applied = subprocess.run(["git", "-c", "core.autocrlf=false", "apply", "--binary", "-"],
                                 cwd=applied_repo, input=result.encode("utf-8"), capture_output=True,
                                 timeout=10, check=False)
        self.assertEqual(applied.returncode, 0, applied.stderr)
        for filename in ("tracked.txt", "staged new.txt", "new file.txt", "new.bin", "empty.txt"):
            self.assertEqual((applied_repo / filename).read_bytes(), (repo / filename).read_bytes())
        self.assertFalse((applied_repo / "deleted.txt").exists())

    def test_baseline_is_captured_before_model_changes_head(self):
        initial = self.baseline

        def model(*args, **kwargs):
            self.baseline = "b" * 40  # stand-in for a commit made by the model

        def command(cmd, timeout=600):
            if "diff" in cmd:
                return subprocess.CompletedProcess(cmd, 0, "fixture patch" if initial in cmd else "", "")
            return self.command(cmd, timeout)

        self.invoke(command=command, model=model)
        self.assertEqual(self.predictions()[self.iid]["model_patch"], "fixture patch")
        self.assertEqual(self.trajectory()["baseline"], initial)

    def test_system_verifier_sees_changes_against_baseline(self):
        def command(cmd, timeout=600):
            if "diff" in cmd:
                return subprocess.CompletedProcess(cmd, 0, "staged patch" if self.baseline in cmd else "", "")
            return self.command(cmd, timeout)

        self.assertEqual(self.invoke(command=command, mode="system"), 1)

    def test_failed_collection_is_retryable_and_records_trajectory(self):
        def failed(cmd, timeout=600):
            if "diff" in cmd:
                return subprocess.CompletedProcess(cmd, 128, "misleading partial output", "fixture diff failed")
            return self.command(cmd, timeout)

        self.invoke(command=failed)
        self.assertNotIn(self.iid, self.predictions())
        self.assertIn("collection_error", self.trajectory()["status"])
        self.assertIn("fixture diff failed", self.trajectory()["status"])
        self.assertEqual(self.invoke(), 1)
        self.assertIn(self.iid, self.predictions())

    def test_untracked_listing_failure_is_not_completed(self):
        def command(cmd, timeout=600):
            if "ls-files" in cmd:
                return subprocess.CompletedProcess(cmd, 128, "", "fixture listing failed")
            return self.command(cmd, timeout)

        self.invoke(command=command)
        self.assertNotIn(self.iid, self.predictions())
        self.assertIn("fixture listing failed", self.trajectory()["status"])

    def test_untracked_diff_error_is_not_completed(self):
        def command(cmd, timeout=600):
            if "ls-files" in cmd:
                return subprocess.CompletedProcess(cmd, 0, "new.txt\0", "")
            if "--no-index" in cmd:
                return subprocess.CompletedProcess(cmd, 2, "partial", "fixture new file failed")
            return self.command(cmd, timeout)

        self.invoke(command=command)
        self.assertNotIn(self.iid, self.predictions())
        self.assertIn("fixture new file failed", self.trajectory()["status"])

    def test_baseline_failure_skips_model_and_is_retryable(self):
        def command(cmd, timeout=600):
            if "rev-parse" in cmd:
                return subprocess.CompletedProcess(cmd, 128, "", "fixture no HEAD")
            return self.command(cmd, timeout)

        self.assertEqual(self.invoke(command=command), 0)
        self.assertNotIn(self.iid, self.predictions())
        self.assertIn("fixture no HEAD", self.trajectory()["status"])

    def test_model_error_retains_successfully_collected_partial_patch(self):
        def model(*args, **kwargs):
            raise RuntimeError("fixture model failed after edit")

        def command(cmd, timeout=600):
            if "diff" in cmd:
                return subprocess.CompletedProcess(cmd, 0, "valid partial patch", "")
            return self.command(cmd, timeout)

        self.invoke(command=command, model=model)
        self.assertEqual(self.predictions()[self.iid]["model_patch"], "valid partial patch")
        self.assertIn("fixture model failed", self.trajectory()["status"])

    def test_runner_cleanup_timeout_does_not_lose_prediction(self):
        def command(cmd, timeout=600):
            if cmd[1] == "rm":
                self.assertLessEqual(timeout, 60)
                raise subprocess.TimeoutExpired(cmd, timeout)
            return self.command(cmd, timeout)

        self.invoke(command=command)
        self.assertIn(self.iid, self.predictions())


class ScorerIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.out = self.root / "out"
        self.scorer = load_bench("score_preds")
        self.ids = ["fixture__repo-1", "fixture__repo-2", "fixture__repo-3"]
        self.checkpoints = []
        self.cleanups = []
        self.current = None

    def summary(self):
        path = self.out / "score_summary.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def command(self, cmd, data=None, timeout=1800):
        if cmd[1] == "run":
            self.current = next(iid for iid in self.ids if iid.replace("__", "-") in cmd[4])
            self.checkpoints.append(self.summary())
        if cmd[1] == "rm":
            self.cleanups.append(cmd[-1])
        return subprocess.CompletedProcess(cmd, 0, b"fixture output", b"")

    def invoke(self, command=None, patches=None):
        preds = {iid: {"instance_id": iid, "model_patch": (patches or {}).get(iid, "fixture patch")}
                 for iid in self.ids}
        path = self.root / "preds.json"
        path.write_text(json.dumps(preds), encoding="utf-8")
        argv = ["scorer", str(path), str(self.out)]
        with patch.object(sys, "argv", argv), \
                patch.object(self.scorer, "load_dataset", return_value=[{"instance_id": i} for i in self.ids]), \
                patch.object(self.scorer, "make_test_spec", return_value=types.SimpleNamespace(eval_script="true")), \
                patch.object(self.scorer, "get_eval_report", side_effect=lambda spec, pred, *a, **kw: {
                    pred["instance_id"]: {"resolved": True, "tests_status": {}},
                }), patch.object(self.scorer, "run", side_effect=command or self.command), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(self.scorer.main(), 0)

    def test_evaluation_timeout_checkpoints_and_continues_with_partial_output(self):
        def command(cmd, data=None, timeout=1800):
            result = self.command(cmd, data, timeout)
            if cmd[-1] == "/eval.sh" and self.current == self.ids[1]:
                raise subprocess.TimeoutExpired(cmd, timeout, output=b"partial stdout", stderr=b"partial stderr")
            return result

        self.invoke(command)
        summary = self.summary()
        self.assertEqual(summary[self.ids[1]]["status"], "timeout")
        self.assertTrue(summary[self.ids[0]]["resolved"])
        self.assertTrue(summary[self.ids[2]]["resolved"])
        self.assertIn(self.ids[0], self.checkpoints[1])
        self.assertIn(self.ids[1], self.checkpoints[2])
        output = (self.out / f"{self.ids[1]}.test_output.txt").read_bytes()
        self.assertIn(b"partial stdout", output)
        self.assertIn(b"partial stderr", output)

    def test_startup_timeout_is_per_instance(self):
        def command(cmd, data=None, timeout=1800):
            result = self.command(cmd, data, timeout)
            if cmd[1] == "run" and self.current == self.ids[0]:
                raise subprocess.TimeoutExpired(cmd, timeout)
            return result

        self.invoke(command)
        self.assertEqual(self.summary()[self.ids[0]]["status"], "timeout")
        self.assertIn(self.ids[0], self.checkpoints[1])
        self.assertTrue(self.summary()[self.ids[2]]["resolved"])

    def test_cleanup_timeout_is_bounded_and_does_not_abort_batch(self):
        def command(cmd, data=None, timeout=1800):
            if cmd[1] == "rm":
                self.assertLessEqual(timeout, 60)
                raise subprocess.TimeoutExpired(cmd, timeout)
            return self.command(cmd, data, timeout)

        self.invoke(command)
        self.assertEqual(len(self.summary()), 3)
        self.assertTrue(all(row["resolved"] for row in self.summary().values()))

    def test_empty_and_failed_instances_checkpoint_before_next_start(self):
        def command(cmd, data=None, timeout=1800):
            result = self.command(cmd, data, timeout)
            if cmd[1] == "run" and self.current == self.ids[1]:
                return subprocess.CompletedProcess(cmd, 1, b"", b"fixture start failed")
            return result

        self.invoke(command, patches={self.ids[0]: ""})
        self.assertIn(self.ids[0], self.checkpoints[0])
        self.assertIn(self.ids[1], self.checkpoints[1])
        self.assertEqual(self.summary()[self.ids[1]]["status"], "container_failed")
        self.assertFalse(any(self.ids[1].replace("__", "-") in name for name in self.cleanups),
                         "An explicit failed start must not remove a possibly pre-existing container")

    def test_apply_failure_checkpoints_before_next_start(self):
        def command(cmd, data=None, timeout=1800):
            result = self.command(cmd, data, timeout)
            if " /tmp/patch.diff" in cmd[-1] and self.current == self.ids[0]:
                return subprocess.CompletedProcess(cmd, 1, b"", b"fixture apply failed")
            return result

        self.invoke(command)
        self.assertIn(self.ids[0], self.checkpoints[1])
        self.assertEqual(self.summary()[self.ids[0]]["status"], "patch_apply_failed")


if __name__ == "__main__":
    unittest.main()
