"""Inert regressions for resume identity and active event-log protection."""
import functools
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from nakedagent.driver import run_functional
from nakedagent.eventlog import open_log
from nakedagent.functional import AgentEvent, AgentState, agent_reducer
from nakedagent.loop import _system_prompt
from nakedagent.replay import verify
from nakedagent.tools import tool_patch, tool_read, tool_write


def suspended_log(path, workspace, tools, model="recorded-model"):
    prompt = _system_prompt(tools)
    state = AgentState.initial(prompt, policy={
        "model": model, "workspace": str(workspace), "extra": {},
    })
    writer = open_log(path, system_prompt=prompt, model=model,
                      workspace=str(workspace))
    for event in (AgentEvent("USER_INPUT", "fixture task"),
                  AgentEvent("MODEL_REPLY", "```write result.txt\nfixture\n```"),
                  AgentEvent("ESCALATE", "fixture review")):
        state, _ = agent_reducer(state, event)
        writer.write_event(event, state.current_hash())
    writer.close(state.step_count, state.current_hash(), state.is_terminal,
                 state.terminal_reason, state.suspended)


class ResumeIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name).resolve()
        self.log = self.workspace / "run.jsonl"
        self.tools = {"write": tool_write}

    def test_different_model_refused_before_model_or_log_mutation(self):
        suspended_log(self.log, self.workspace, self.tools)
        before = self.log.read_bytes()
        model = Mock(return_value="done")
        with self.assertRaisesRegex(RuntimeError, "model"):
            run_functional("approve", "other-model", self.workspace,
                           tools=self.tools, llm_fn=model,
                           event_log_path=self.log, resume_from=self.log)
        model.assert_not_called()
        self.assertEqual(self.log.read_bytes(), before)

    def test_different_workspace_refused_before_effect_or_log_mutation(self):
        suspended_log(self.log, self.workspace, self.tools)
        other = self.workspace / "other"
        other.mkdir()
        before = self.log.read_bytes()
        model = Mock(side_effect=["```write result.txt\nfixture\n```", "done"])
        with self.assertRaisesRegex(RuntimeError, "workspace"):
            run_functional("approve", "recorded-model", other,
                           tools=self.tools, llm_fn=model,
                           event_log_path=self.log, resume_from=self.log)
        model.assert_not_called()
        self.assertFalse((other / "result.txt").exists())
        self.assertEqual(self.log.read_bytes(), before)

    def test_equivalent_absolute_workspace_spelling_can_resume(self):
        suspended_log(self.log, self.workspace, self.tools)
        alias = self.workspace / "unused" / ".."
        model = Mock(return_value="done")
        state = run_functional("approve", "recorded-model", alias,
                               tools=self.tools, llm_fn=model,
                               event_log_path=self.log, resume_from=self.log)
        self.assertTrue(state.is_terminal)
        self.assertEqual(state.policy["workspace"], str(self.workspace))
        self.assertTrue(verify(self.log)[0])

    def test_ambiguous_relative_recorded_workspace_cannot_resume(self):
        suspended_log(self.log, Path("relative-workspace"), self.tools)
        before = self.log.read_bytes()
        model = Mock(return_value="done")
        with self.assertRaisesRegex(RuntimeError, "workspace"):
            run_functional("approve", "recorded-model", Path("relative-workspace"),
                           tools=self.tools, llm_fn=model,
                           event_log_path=self.log, resume_from=self.log)
        model.assert_not_called()
        self.assertEqual(self.log.read_bytes(), before)

    def test_mismatch_is_refused_before_loading_plugins(self):
        suspended_log(self.log, self.workspace, self.tools)
        with patch("nakedagent.driver._build_tools") as build, \
                self.assertRaisesRegex(RuntimeError, "model"):
            run_functional("approve", "other-model", self.workspace,
                           llm_fn=Mock(), event_log_path=self.log,
                           resume_from=self.log)
        build.assert_not_called()

    def test_new_run_records_absolute_workspace_from_relative_input(self):
        original_cwd = Path.cwd()
        try:
            os.chdir(self.workspace)
            state = run_functional("fixture", "m", Path("."), tools=self.tools,
                                   llm_fn=Mock(return_value="done"),
                                   event_log_path=self.log)
        finally:
            os.chdir(original_cwd)
        self.assertEqual(state.policy["workspace"], str(self.workspace))
        self.assertTrue(verify(self.log)[0])


class ActiveLogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name).resolve()
        self.log = self.workspace / "run.jsonl"

    def assert_log_protected(self, tool_name, tool, target, content):
        model = Mock(side_effect=[f"```{tool_name} {target}\n{content}\n```", "done"])
        state = run_functional("fixture task", "m", self.workspace,
                               tools={tool_name: tool}, llm_fn=model,
                               event_log_path=self.log)
        ok, detail = verify(self.log)
        self.assertTrue(ok, detail)
        results = [receipt.event.payload for receipt in state.trace
                   if receipt.event.event_type == "TOOL_RESULT"]
        self.assertEqual(len(results), 1)
        self.assertIn("active event log", results[0])

    def test_write_to_active_log_is_refused(self):
        self.assert_log_protected("write", tool_write, "run.jsonl", "replacement")

    def test_patch_to_active_log_is_refused(self):
        block = '<<<<<<< SEARCH\n"kind": "header"\n=======\n"kind": "changed"\n>>>>>>> REPLACE'
        self.assert_log_protected("patch", tool_patch, "run.jsonl", block)

    def test_absolute_log_target_is_refused(self):
        self.assert_log_protected("write", tool_write, str(self.log), "replacement")

    def test_renamed_foundation_tool_is_also_protected(self):
        self.assert_log_protected("edit", tool_write, "run.jsonl", "replacement")

    def test_partial_foundation_tool_is_also_protected(self):
        self.assert_log_protected("edit", functools.partial(tool_write),
                                  "run.jsonl", "replacement")

    def test_hardlink_alias_is_protected(self):
        self.log.touch()
        alias = self.workspace / "alias.jsonl"
        try:
            alias.hardlink_to(self.log)
        except OSError as exc:
            self.skipTest(f"hard links unavailable: {exc}")
        self.assert_log_protected("write", tool_write, alias.name, "replacement")

    def test_symlink_alias_is_protected(self):
        self.log.touch()
        alias = self.workspace / "alias.jsonl"
        try:
            alias.symlink_to(self.log)
        except OSError as exc:
            self.skipTest(f"symlinks unavailable: {exc}")
        self.assert_log_protected("write", tool_write, alias.name, "replacement")

    def test_unrelated_write_and_read_of_log_still_work(self):
        model = Mock(side_effect=["```write output.txt\nfixture\n```",
                                 "```read run.jsonl\n```", "done"])
        run_functional("fixture task", "m", self.workspace,
                       tools={"write": tool_write, "read": tool_read},
                       llm_fn=model, event_log_path=self.log)
        self.assertEqual((self.workspace / "output.txt").read_text(), "fixture")
        self.assertTrue(verify(self.log)[0])

    def test_log_named_file_remains_writable_without_active_recorder(self):
        model = Mock(side_effect=["```write run.jsonl\nordinary file\n```", "done"])
        run_functional("fixture task", "m", self.workspace,
                       tools={"write": tool_write}, llm_fn=model)
        self.assertEqual(self.log.read_text(), "ordinary file")

    def test_resumed_log_is_protected(self):
        tools = {"write": tool_write}
        suspended_log(self.log, self.workspace, tools)
        model = Mock(side_effect=["```write run.jsonl\nreplacement\n```", "done"])
        state = run_functional("approve", "recorded-model", self.workspace,
                               tools=tools, llm_fn=model,
                               event_log_path=self.log, resume_from=self.log)
        self.assertTrue(verify(self.log)[0])
        self.assertTrue(any("active event log" in receipt.event.payload
                            for receipt in state.trace
                            if receipt.event.event_type == "TOOL_RESULT"))


if __name__ == "__main__":
    unittest.main()
