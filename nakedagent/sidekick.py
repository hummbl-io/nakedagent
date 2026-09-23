"""NakedAgent Sidekick: Ultra-lightweight, functional, governed coding agent harness.

Combines:
1. Provable Mealy state machine & Merkle execution stream (functional.py).
2. Pluggable model providers (Ollama, OpenRouter/Jev, CLI headless SWE-2 Max, mock/callable).
3. Zero-dependency Model Context Protocol (MCP) tool bridge (mcp.py).
4. Pre-execution Noul micro-adjudication and safety tripwires.
5. Deterministic replay and cryptographic auditability.

All implemented using pure Python standard library (zero third-party dependencies).
"""
from __future__ import annotations

import json
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol, Tuple, Union

from .functional import (
    AgentEvent,
    AgentState,
    FunctionalMachine,
    ToolAction,
    TransitionReceipt,
    reduce_agent_step,
)
from .loop import _system_prompt
from .mcp import StdlibMcpClient
from .toolcall import parse
from .tools import TOOLS, ToolFunc


class ModelProvider(Protocol):
    """Protocol for pluggable model inference providers."""

    def complete(self, messages: List[Dict[str, str]]) -> str:
        """Generate response text from message history."""
        ...


class CallableProvider:
    """Wraps any Python callable (messages) -> str into a ModelProvider."""

    def __init__(self, fn: Callable[[List[Dict[str, str]]], str]):
        self._fn = fn

    def complete(self, messages: List[Dict[str, str]]) -> str:
        return self._fn(messages)


class OllamaProvider:
    """Local inference via Ollama HTTP API (stdlib urllib)."""

    def __init__(self, model: str = "qwen2.5-coder:7b", host: str = "http://localhost:11434"):
        self.model = model
        self.host = host.rstrip("/")

    def complete(self, messages: List[Dict[str, str]]) -> str:
        body = json.dumps({"model": self.model, "messages": messages, "stream": False}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.host}/api/chat",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data["message"]["content"]
        except Exception as e:
            raise RuntimeError(f"OllamaProvider error ({self.host}, {self.model}): {e}") from e


class DevinCliProvider:
    """Headless invocation of SWE-2 Max via Devin CLI executable."""

    def __init__(
        self,
        executable_path: str = "devin",
        model: str = "swe-2-max",
        permission_mode: str = "dangerous",
    ):
        self.executable_path = executable_path
        self.model = model
        self.permission_mode = permission_mode

    def complete(self, messages: List[Dict[str, str]]) -> str:
        # Extract the last user message or synthesize conversation prompt
        last_msg = messages[-1]["content"] if messages else ""
        cmd = [
            self.executable_path,
            "-p",
            last_msg,
            "--model",
            self.model,
            "--permission-mode",
            self.permission_mode,
            "--respect-workspace-trust",
            "false",
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return res.stdout.strip()
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"DevinCliProvider failed (exit {e.returncode}): {e.stderr}") from e


class NoulGateEvaluator(Protocol):
    """Protocol for pre-execution micro-adjudication over actions."""

    def evaluate_action(self, action: ToolAction, workspace: Path) -> Tuple[bool, float, str]:
        """Returns (is_alarm, p_risk, reason)."""
        ...


class DefaultSafeNoulGate:
    """Heuristic / rule-based Noul gate with asymmetric loss tripwires."""

    def __init__(self, risk_threshold: float = 0.40):
        self.risk_threshold = risk_threshold

    def evaluate_action(self, action: ToolAction, workspace: Path) -> Tuple[bool, float, str]:
        tool = action.tool_name.lower()

        # Adjudicated surface: `args` is always in scope (every tool's
        # dispatch reads it); `content` is in scope for shell, which
        # executes `content or args`. Checking content alone leaves args
        # as an uninspected execution channel.
        surface = action.args.lower()
        if tool == "shell":
            surface += "\n" + action.content.lower()

        destructive_patterns = [
            "rm -rf /",
            "rmdir /s /q c:\\",
            "format ",
            ":(){ :|:& };:",
            "git push -f origin main",
            "git reset --hard",
        ]
        for pat in destructive_patterns:
            if pat in surface:
                return True, 0.99, f"Critical tripwire matched destructive pattern: '{pat}'"

        # Safe read-only or bounded operations
        return False, 0.05, "Action validated within safe bounds"


class SidekickHarness:
    """Autonomous Sidekick harness coordinating functional state, MCP tools, and model providers."""

    def __init__(
        self,
        workspace: Path,
        provider: ModelProvider,
        max_steps: int = 25,
        system_prompt: Optional[str] = None,
        noul_gate: Optional[NoulGateEvaluator] = None,
    ):
        self.workspace = Path(workspace)
        self.provider = provider
        self.max_steps = max_steps
        self.noul_gate = noul_gate or DefaultSafeNoulGate()

        # Tool registry: starts with built-in tools
        self.tools: Dict[str, ToolFunc] = dict(TOOLS)
        self._mcp_clients: List[StdlibMcpClient] = []

        # System prompt
        self.system_prompt = system_prompt or _system_prompt(self.tools)

        # Initialize functional state
        self.state = AgentState.initial(self.system_prompt, max_steps=self.max_steps)

    def attach_mcp_client(self, client: StdlibMcpClient) -> List[str]:
        """Mount all tools exposed by an MCP client into the Sidekick tool registry."""
        client.start()
        self._mcp_clients.append(client)
        mcp_tools = client.list_tools()
        registered = []

        for t in mcp_tools:
            rpc_name = t.get("name")
            if not isinstance(rpc_name, str) or not rpc_name:
                continue
            # Registry/dispatch normalize lowercase (parsed tool names are
            # lowercased at action construction); the RPC keeps the server's
            # real name so CamelCase tools stay reachable.
            tool_name = rpc_name.lower()
            if tool_name == "__refused__":
                # Reserved: the parser emits refusals under this name; a
                # mounted tool claiming it would execute every refused call.
                print("[sidekick] refusing MCP tool '__refused__' (reserved)", file=sys.stderr)
                continue
            if tool_name in self.tools:
                # A mounted MCP tool must never silently replace a builtin:
                # the gate threat-model and dispatch table would diverge.
                print(
                    f"[sidekick] refusing MCP tool shadow: '{tool_name}' already registered",
                    file=sys.stderr,
                )
                continue

            def _make_mcp_runner(name: str) -> ToolFunc:
                def _runner(args: str, content: str, ws: Path) -> str:
                    try:
                        # Parse JSON content or interpret as arguments
                        params = {}
                        if content.strip():
                            try:
                                params = json.loads(content)
                            except json.JSONDecodeError:
                                params = {"input": content}
                        elif args.strip():
                            params = {"args": args.strip()}
                        res = client.invoke_tool(name, params)
                        return json.dumps(res, indent=2) if isinstance(res, (dict, list)) else str(res)
                    except Exception as e:
                        return f"Error executing MCP tool '{name}': {e}"

                return _runner

            runner = _make_mcp_runner(rpc_name)
            runner.usage = f"```{tool_name}\n{{...parameters...}}\n```"
            self.tools[tool_name] = runner
            registered.append(tool_name)

        # Refresh system prompt with new tools
        self.system_prompt = _system_prompt(self.tools)
        return registered

    def close(self) -> None:
        """Clean up connected MCP processes."""
        for client in self._mcp_clients:
            try:
                client.close()
            except Exception:
                pass
        self._mcp_clients.clear()

    def run_turn(self, user_prompt: str) -> AgentState:
        """Execute a full turn (user prompt -> model -> tool loops -> final text)."""
        # Event 1: User prompt
        user_event = AgentEvent(event_type="USER_INPUT", payload=user_prompt)
        self.state, actions = FunctionalMachine.step(self.state, user_event)

        # Loop until terminal or no further actions
        while not self.state.is_terminal:
            # Model completion
            messages = list(self.state.history)
            model_reply = self.provider.complete(messages)

            # Event 2: Model reply
            model_event = AgentEvent(event_type="MODEL_REPLY", payload=model_reply)
            self.state, actions = FunctionalMachine.step(self.state, model_event)

            if not actions:
                # Model produced no tool calls -> turn complete, hand control back to human
                break

            # Execute emitted actions — but never dispatch an effect whose
            # result can't be ledgered: once the state is terminal or the
            # step budget is spent, the reducer would drop the TOOL_RESULT
            # and the effect would execute off-ledger.
            for action in actions:
                if self.state.is_terminal or self.state.step_count >= self.state.max_steps:
                    break
                # Noul Pre-Execution Gate
                is_alarm, p_risk, reason = self.noul_gate.evaluate_action(action, self.workspace)
                if is_alarm:
                    alarm_event = AgentEvent(
                        event_type="ALARM",
                        payload=f"Action blocked by Noul Gate (risk={p_risk:.2f}): {reason}",
                    )
                    self.state, _ = FunctionalMachine.step(self.state, alarm_event)
                    break

                # Execute tool
                tool_fn = self.tools.get(action.tool_name)
                if tool_fn is None:
                    tool_output = f"Unknown tool: '{action.tool_name}'"
                else:
                    try:
                        tool_output = tool_fn(action.args, action.content, self.workspace)
                    except Exception as e:
                        tool_output = f"Error in tool '{action.tool_name}': {e}"

                # Feed tool result back into functional machine
                tool_event = AgentEvent(
                    event_type="TOOL_RESULT",
                    payload=tool_output,
                    metadata={"tool": action.tool_name},
                )
                self.state, _ = FunctionalMachine.step(self.state, tool_event)

                # Stop dispatching siblings once terminal — post-terminal
                # effects would execute but their results are dropped by
                # the reducer, leaving effects with no ledger record.
                if self.state.is_terminal:
                    break

        return self.state

    def export_merkle_trace(self) -> List[Dict[str, Any]]:
        """Export the verified cryptographic Merkle trace of this session."""
        return [
            {
                "step_index": r.step_index,
                "prev_hash": r.prev_hash,
                "event_type": r.event.event_type,
                "payload_preview": r.event.payload[:120],
                "actions_count": len(r.actions),
                "state_hash": r.state_hash,
            }
            for r in self.state.trace
        ]
