"""Suspended-log resume: replay-verified continuation of a v0.4 chain."""
import json
import tempfile
import unittest
from pathlib import Path

from nakedagent.driver import run_functional
from nakedagent.eventlog import EventLogError, open_log, read_log, require_resumable
from nakedagent.functional import AgentEvent, AgentState, agent_reducer
from nakedagent.loop import _system_prompt
from nakedagent.replay import verify


def _scripted_llm(replies):
    it = iter(replies)

    def _chat(messages, model, host):
        try:
            return next(it)
        except StopIteration:
            return "scripted llm exhausted"

    return _chat


def _echo_tool(args, content, workspace):
    return f"echo:{args}:{content}"


def _write_suspended_log(path, workspace, tools, model="m", max_steps=25):
    """Emit a real suspended log: drive the reducer, seal every event.

    Ends suspended after USER_INPUT -> MODEL_REPLY -> ESCALATE.
    """
    system_prompt = _system_prompt(tools)
    state = AgentState.initial(
        system_prompt, max_steps=max_steps,
        policy={"model": model, "workspace": str(workspace), "extra": {}},
    )
    log = open_log(path, system_prompt=system_prompt, model=model,
                   workspace=str(workspace), max_steps=max_steps)
    for ev in (
        AgentEvent("USER_INPUT", "clean up the scratch dir"),
        AgentEvent("MODEL_REPLY", "```shell rm -rf ./scratch\n```"),
        AgentEvent("ESCALATE", "gate abstain: p_risk=0.53 conf=0.02"),
    ):
        state, _ = agent_reducer(state, ev)
        log.write_event(ev, state.current_hash())
    log.close(state.step_count, state.current_hash(), state.is_terminal,
              state.terminal_reason, state.suspended)
    return state


class TestResume(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.workspace = Path(self.td.name)
        self.tools = {"echo": _echo_tool}
        self.log_path = self.workspace / "run.jsonl"

    def tearDown(self):
        self.td.cleanup()

    def test_resume_continues_chain_and_verifies(self):
        _write_suspended_log(self.log_path, self.workspace, self.tools)
        state = run_functional(
            "verdict: proceed", "m", self.workspace, "h",
            tools=self.tools, llm_fn=_scripted_llm(["all done, no calls"]),
            event_log_path=self.log_path, resume_from=self.log_path,
        )
        self.assertTrue(state.is_terminal)
        self.assertFalse(state.suspended)
        # 3 prefix events + USER_INPUT verdict + MODEL_REPLY + TERMINATION
        self.assertEqual(state.step_count, 6)
        # The whole file — prefix + continuation — replays clean.
        ok, msg = verify(self.log_path)
        self.assertTrue(ok, msg)
        parsed = read_log(self.log_path)
        self.assertEqual([e.event_type for e in parsed.events],
                         ["USER_INPUT", "MODEL_REPLY", "ESCALATE",
                          "USER_INPUT", "MODEL_REPLY", "TERMINATION"])
        self.assertEqual(parsed.events[3].payload, "verdict: proceed")
        self.assertFalse(parsed.trailer["suspended"])
        self.assertTrue(parsed.trailer["is_terminal"])

    def test_resume_verdict_lifts_suspension_in_history(self):
        _write_suspended_log(self.log_path, self.workspace, self.tools)
        state = run_functional(
            "verdict: approved", "m", self.workspace, "h",
            tools=self.tools, llm_fn=_scripted_llm(["ok"]),
            event_log_path=self.log_path, resume_from=self.log_path,
        )
        verdict_msgs = [m for m in state.history
                        if m["role"] == "user" and "verdict:" in m["content"]]
        self.assertEqual(len(verdict_msgs), 1)

    def test_refuse_terminal_log(self):
        run_functional(
            "hi", "m", self.workspace, "h",
            tools=self.tools, llm_fn=_scripted_llm(["done"]),
            event_log_path=self.log_path,
        )
        with self.assertRaises(EventLogError):
            require_resumable(read_log(self.log_path), self.log_path)
        with self.assertRaises(RuntimeError):
            run_functional(
                "verdict: proceed", "m", self.workspace, "h",
                tools=self.tools, llm_fn=_scripted_llm(["x"]),
                event_log_path=self.log_path, resume_from=self.log_path,
            )

    def test_refuse_tampered_prefix_and_leave_file_intact(self):
        _write_suspended_log(self.log_path, self.workspace, self.tools)
        lines = self.log_path.read_text(encoding="utf-8").splitlines(keepends=True)
        rec = json.loads(lines[2])  # second event record (header, USER_INPUT, then this)
        rec["payload"] = "forged user input"
        lines[2] = json.dumps(rec) + "\n"
        self.log_path.write_text("".join(lines), encoding="utf-8")
        with self.assertRaises(RuntimeError) as ctx:
            run_functional(
                "verdict: proceed", "m", self.workspace, "h",
                tools=self.tools, llm_fn=_scripted_llm(["x"]),
                event_log_path=self.log_path, resume_from=self.log_path,
            )
        self.assertIn("chain", str(ctx.exception))
        # The refusal happens before the trailer strip: a second attempt
        # sees the same failure, not a mutated file.
        with self.assertRaises(RuntimeError):
            run_functional(
                "v", "m", self.workspace, "h",
                tools=self.tools, llm_fn=_scripted_llm(["x"]),
                event_log_path=self.log_path, resume_from=self.log_path,
            )

    def test_refuse_mismatched_registry_prompt(self):
        _write_suspended_log(self.log_path, self.workspace, self.tools)

        def _other_tool(args, content, workspace):
            return "other"

        with self.assertRaises(RuntimeError) as ctx:
            run_functional(
                "verdict: proceed", "m", self.workspace, "h",
                tools={"echo": _echo_tool, "extra": _other_tool},
                llm_fn=_scripted_llm(["x"]),
                event_log_path=self.log_path, resume_from=self.log_path,
            )
        self.assertIn("prompt", str(ctx.exception))

    def test_refuse_eventlog_path_mismatch(self):
        _write_suspended_log(self.log_path, self.workspace, self.tools)
        with self.assertRaises(ValueError):
            run_functional(
                "verdict: proceed", "m", self.workspace, "h",
                tools=self.tools, llm_fn=_scripted_llm(["x"]),
                event_log_path=self.workspace / "other.jsonl",
                resume_from=self.log_path,
            )

    def test_second_resume_of_completed_log_refuses(self):
        _write_suspended_log(self.log_path, self.workspace, self.tools)
        run_functional(
            "verdict: proceed", "m", self.workspace, "h",
            tools=self.tools, llm_fn=_scripted_llm(["done"]),
            event_log_path=self.log_path, resume_from=self.log_path,
        )
        with self.assertRaises(EventLogError):
            run_functional(
                "verdict: again", "m", self.workspace, "h",
                tools=self.tools, llm_fn=_scripted_llm(["x"]),
                event_log_path=self.log_path, resume_from=self.log_path,
            )

    def test_missing_log_refuses(self):
        with self.assertRaises((EventLogError, OSError)):
            run_functional(
                "verdict: proceed", "m", self.workspace, "h",
                tools=self.tools, llm_fn=_scripted_llm(["x"]),
                event_log_path=self.log_path, resume_from=self.log_path,
            )


if __name__ == "__main__":
    unittest.main()
