"""Offline, synthetic replay demonstration: python -m examples.replay_demo."""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from nakedagent.eventlog import open_log
from nakedagent.functional import AgentEvent, AgentState, agent_reducer
from nakedagent.replay import verify


def main() -> int:
    system = "Synthetic replay demonstration. No tools or model are executed."
    policy = {"model": "synthetic", "workspace": "demo", "extra": {}}
    state = AgentState.initial(system, policy=policy)
    events = (
        AgentEvent("USER_INPUT", "Say hello."),
        AgentEvent("MODEL_REPLY", "Hello from a synthetic trace."),
        AgentEvent("TERMINATION", "DEMO_COMPLETE"),
    )
    with TemporaryDirectory(prefix="nakedagent-demo-") as directory:
        path = Path(directory) / "demo.jsonl"
        writer = open_log(path, system_prompt=system, **policy)
        try:
            for event in events:
                state, _ = agent_reducer(state, event)
                writer.write_event(event, state.current_hash())
        finally:
            writer.close(state.step_count, state.current_hash(),
                         state.is_terminal, state.terminal_reason)
        valid, detail = verify(path)
        print(f"Original trace: {detail}")
        if not valid:
            return 1

        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        records[2]["payload"] = "Changed after recording."
        path.write_text("".join(json.dumps(record) + "\n" for record in records),
                        encoding="utf-8")
        valid, detail = verify(path)
        print(f"Changed trace: {'UNEXPECTED ACCEPTANCE' if valid else 'rejected'} ({detail})")
        print("Replay checks consistency; it does not authenticate the author or external effects.")
        return int(valid)


if __name__ == "__main__":
    raise SystemExit(main())
