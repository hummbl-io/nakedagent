"""Property-style invariant checks for the functional lane.

Stdlib only (random/unittest) per DOCTRINE.md — no hypothesis. Each test
encodes one of the invariants functional.py's docstring claims. Seeded RNG;
failures print the seed + event stream so they replay deterministically.

Expected state at 24727f8: HASH_INJECTIVITY and GENESIS_DISTINCTNESS FAIL
(peer-review R4/R5 — that's the point: the suite exists because review
missed them). MONOTONICITY / TERMINATION / REPLAY-DETERMINISM should pass.

Post-fix state: all green. R4/R5/R9/R14/R8 fixes landed in working tree;
the suite's remaining role is regression coverage.
"""

import random
import string
import unittest

from nakedagent.functional import (
    AgentEvent,
    AgentState,
    agent_reducer,
    compute_step_hash,
    replay_trace,
)

EVENT_TYPES = ["USER_INPUT", "MODEL_REPLY", "TOOL_RESULT", "TERMINATION", "ALARM", "ESCALATE"]
NONTERMINAL_TYPES = ["USER_INPUT", "MODEL_REPLY", "TOOL_RESULT"]
SEED = 20260923
N_STREAMS = 200
STREAM_LEN = 40


def _rand_text(rng, n=24):
    return "".join(rng.choice(string.ascii_letters + " ;```") for _ in range(n))


def _gen_stream(rng, length=STREAM_LEN, types=EVENT_TYPES):
    return [
        AgentEvent(event_type=rng.choice(types), payload=_rand_text(rng))
        for _ in range(length)
    ]


class TestHashInjectivity(unittest.TestCase):
    """R4: compute_step_hash must distinguish field boundaries."""

    def test_action_field_boundary_collision(self):
        # Direct reproduction of the framing bug: ('a','bc') vs ('ab','c')
        from nakedagent.functional import ToolAction
        h_a = compute_step_hash(
            "0" * 64, 1, AgentEvent("MODEL_REPLY", "x"),
            (ToolAction("shell", "a", "bc"),),
        )
        h_b = compute_step_hash(
            "0" * 64, 1, AgentEvent("MODEL_REPLY", "x"),
            (ToolAction("shell", "ab", "c"),),
        )
        self.assertNotEqual(
            h_a, h_b,
            "R4: distinct ToolActions produce identical hashes — unframed concat",
        )

    def test_sampled_space_injective(self):
        rng = random.Random(SEED)
        seen = {}
        for i in range(10_000):
            ev = AgentEvent(rng.choice(EVENT_TYPES), _rand_text(rng, 12))
            h = compute_step_hash("f" * 64, i, ev, ())
            if h in seen:
                self.fail(f"hash collision between samples {seen[h]} and {i}")
            seen[h] = i


class TestGenesisDistinctness(unittest.TestCase):
    """R5: genesis hash must bind system_prompt and max_steps."""

    def test_distinct_prompts_distinct_genesis(self):
        a = AgentState.initial("prompt A").current_hash()
        b = AgentState.initial("prompt B").current_hash()
        self.assertNotEqual(a, b, "R5: genesis hash ignores system_prompt")

    def test_distinct_max_steps_distinct_genesis(self):
        a = AgentState.initial("p", max_steps=1).current_hash()
        b = AgentState.initial("p", max_steps=100).current_hash()
        self.assertNotEqual(a, b, "R5: genesis hash ignores max_steps")


class TestMonotonicity(unittest.TestCase):
    """Trace is strictly append-only; step_index strictly +1; prev_hash chains."""

    def test_random_streams(self):
        rng = random.Random(SEED)
        for s in range(N_STREAMS):
            state = AgentState.initial("sp")
            prev_len, prev_idx, prev_hash = 0, 0, state.current_hash()
            for ev in _gen_stream(rng):
                state, _ = agent_reducer(state, ev)
                tr = state.trace
                self.assertGreaterEqual(len(tr), prev_len, f"stream {s}: trace shrank")
                if len(tr) > prev_len:
                    rec = tr[-1]
                    self.assertEqual(rec.step_index, prev_idx + 1)
                    self.assertEqual(rec.prev_hash, prev_hash)
                    prev_idx, prev_hash = rec.step_index, rec.state_hash
                prev_len = len(tr)


class TestDeterminismAndReplay(unittest.TestCase):
    """Same (initial, events) -> identical hashes; replay recomputes chain."""

    def test_deterministic(self):
        rng = random.Random(SEED)
        events = _gen_stream(rng)
        a = AgentState.initial("sp")
        b = AgentState.initial("sp")
        for ev in events:
            a, _ = agent_reducer(a, ev)
            b, _ = agent_reducer(b, ev)
        self.assertEqual(
            [r.state_hash for r in a.trace], [r.state_hash for r in b.trace]
        )

    def test_replay_trace_ok_flag_is_vacuous(self):
        """R14: replay_trace's is_valid flag cannot be False for a
        deterministic reducer — it generates the chain from the given
        events, then 'verifies' by recomputing hashes of those SAME events
        (self-consistent, binds to nothing external). The real mutation
        binding lives in replay.py's recorded-hash comparison. This test
        pins the vacuity so it's a documented choice, not a false sense."""
        rng = random.Random(SEED)
        events = _gen_stream(rng, 15, types=NONTERMINAL_TYPES)
        state, ok = replay_trace("sp", events)
        self.assertTrue(ok, "clean replay should verify")
        evil = list(events)
        evil[3] = AgentEvent(evil[3].event_type, evil[3].payload + "X")
        _, ok2 = replay_trace("sp", evil)
        self.assertTrue(
            ok2,
            "R14 semantics changed — replay_trace now detects mutation "
            "(it would need recorded hashes as input to do so)",
        )

    def test_recorded_hash_binding_detects_mutation(self):
        """The real verification path (what replay.py does): record
        per-step hashes during generation, mutate an event, recompute —
        the recorded-vs-recomputed comparison MUST catch it."""
        rng = random.Random(SEED)
        events = _gen_stream(rng, 15, types=NONTERMINAL_TYPES)
        # generation pass: record the hash chain as an external anchor
        state = AgentState.initial("sp")
        for ev in events:
            state, _ = agent_reducer(state, ev)
        recorded = [r.state_hash for r in state.trace]
        # replay pass over a mutated stream, checked against the anchor
        evil = list(events)
        evil[3] = AgentEvent(evil[3].event_type, evil[3].payload + "X")
        state2 = AgentState.initial("sp")
        for ev in evil:
            state2, _ = agent_reducer(state2, ev)
        recomputed = [r.state_hash for r in state2.trace]
        self.assertNotEqual(recorded, recomputed)
        # and the divergence must be at-or-before the mutated index
        divergent = [i for i, (a, b) in enumerate(zip(recorded, recomputed)) if a != b]
        self.assertTrue(divergent and divergent[0] <= 3)

    def test_postterminal_events_rejected_by_replay(self):
        """v0.4 refuses a tail beyond a terminal event."""
        rng = random.Random(SEED)
        events = _gen_stream(rng, 10, types=NONTERMINAL_TYPES)
        events.insert(5, AgentEvent("TERMINATION", "done"))
        tail_mutated = list(events)
        tail_mutated[8] = AgentEvent("USER_INPUT", "MUTATED-TAIL")
        _, ok_clean = replay_trace("sp", events)
        _, ok_mut = replay_trace("sp", tail_mutated)
        self.assertFalse(ok_clean)
        self.assertFalse(ok_mut)


class TestBoundedTermination(unittest.TestCase):
    def test_terminal_at_max_steps(self):
        rng = random.Random(SEED)
        state = AgentState.initial("sp", max_steps=5)
        for ev in _gen_stream(rng, 30, types=NONTERMINAL_TYPES):
            state, _ = agent_reducer(state, ev)
        self.assertTrue(state.is_terminal)
        self.assertEqual(state.terminal_reason, "BOUNDED_MAX_STEPS_REACHED")
        # events after terminal produce no new trace entries
        n = len(state.trace)
        state, _ = agent_reducer(state, AgentEvent("USER_INPUT", "more"))
        self.assertEqual(len(state.trace), n)


class TestPostTerminalDispatch(unittest.TestCase):
    """R8: once a TOOL_RESULT makes the state terminal, remaining sibling
    actions must NOT dispatch — their effects would execute while the
    reducer drops their results (off-ledger effects)."""

    def test_sibling_actions_not_dispatched_after_terminal(self):
        import tempfile
        from pathlib import Path
        from nakedagent.sidekick import SidekickHarness, CallableProvider

        ws = Path(tempfile.mkdtemp())
        dispatched = []

        # Registry-level spy: wrap read so we see every dispatch.
        h = SidekickHarness(
            workspace=ws,
            provider=CallableProvider(
                lambda msgs: "```read a.txt\n```\n```read b.txt\n```"
            ),
            max_steps=3,  # USER_INPUT=1, MODEL_REPLY=2; first TOOL_RESULT -> 3 = bound spent
        )
        real_read = h.tools["read"]

        def spy(args, content, w):
            dispatched.append(args)
            return real_read(args, content, w)

        h.tools["read"] = spy
        (ws / "a.txt").write_text("a")
        (ws / "b.txt").write_text("b")
        h.run_turn("go")
        self.assertEqual(
            dispatched, ["a.txt"],
            "post-terminal sibling dispatched — off-ledger effect",
        )


class TestMcpMountDispatch(unittest.TestCase):
    """Mounted MCP tools must dispatch via client.invoke_tool — a wrong
    method name (call_tool) turns every call into an AttributeError caught
    by the runner and returned as an error *string*, which lands in the
    ledger looking like a real tool result (silent off-facts)."""

    def test_mounted_tool_dispatches_via_invoke_tool(self):
        import tempfile
        from pathlib import Path
        from nakedagent.sidekick import SidekickHarness, CallableProvider

        ws = Path(tempfile.mkdtemp())
        calls = []

        class FakeMcp:
            def start(self):
                pass

            def list_tools(self):
                return [{"name": "mcp_echo"}]

            def invoke_tool(self, name, params):
                calls.append((name, params))
                return {"echo": params}

            def stop(self):
                pass

        h = SidekickHarness(
            workspace=ws,
            provider=CallableProvider(lambda msgs: "done"),
        )
        registered = h.attach_mcp_client(FakeMcp())
        self.assertEqual(registered, ["mcp_echo"])
        out = h.tools["mcp_echo"](args="", content='{"x": 1}', ws=ws)
        self.assertEqual(calls, [("mcp_echo", {"x": 1})])
        self.assertIn('"echo"', out)
        self.assertNotIn("Error executing", out)


class TestReplayMaxStepsFidelity(unittest.TestCase):
    """R9: replay_trace must honour the original run's max_steps."""

    def test_long_run_replays_fully(self):
        # non-terminal stream so only max_steps bounds it: a run configured
        # for 50 steps must replay all 30 when given its recorded budget
        rng = random.Random(SEED)
        events = _gen_stream(rng, 30, types=NONTERMINAL_TYPES)
        # wrong budget still truncates — caller must supply it
        state_default, _ = replay_trace("sp", events)
        self.assertEqual(len(state_default.trace), 25)
        # recorded budget replays fully
        state, ok = replay_trace("sp", events, max_steps=50)
        self.assertTrue(ok)
        self.assertEqual(
            len(state.trace), 30,
            "replay with recorded max_steps must not truncate",
        )


if __name__ == "__main__":
    unittest.main()
