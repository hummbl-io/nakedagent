"""Zero-dependency Model Context Protocol (MCP) client using pure Python standard library.

Provides JSON-RPC 2.0 communication over stdio pipes without third-party packages.
Connects nakedagent to any MCP server (e.g. coordination-bus, cognitive-ledger,
base120, utf, onepassword).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


class StdlibMcpClient:
    """Pure stdlib JSON-RPC 2.0 client for MCP servers over stdio."""

    def __init__(self, command: list[str], cwd: Optional[Path] = None):
        self.command = command
        self.cwd = cwd
        self.proc: Optional[subprocess.Popen] = None
        self._request_id = 0

    def start(self) -> None:
        """Start the MCP server subprocess."""
        if self.proc is not None:
            return
        self.proc = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(self.cwd) if self.cwd else None,
            text=True,
            bufsize=1,
        )

    def close(self) -> None:
        """Terminate the MCP server subprocess."""
        if self.proc is not None:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=2)
            except Exception:
                self.proc.kill()
            finally:
                self.proc = None

    def call(self, method: str, params: Optional[Dict[str, Any]] = None, timeout_s: float = 30.0) -> Any:
        """Execute a JSON-RPC 2.0 request and return the result."""
        if self.proc is None:
            self.start()
        assert self.proc is not None
        assert self.proc.stdin is not None
        assert self.proc.stdout is not None

        self._request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params or {},
        }
        msg = json.dumps(payload)
        self.proc.stdin.write(f"{msg}\n")
        self.proc.stdin.flush()

        line = self.proc.stdout.readline()
        if not line:
            stderr_out = ""
            if self.proc.stderr:
                stderr_out = self.proc.stderr.read()
            raise RuntimeError(f"MCP server closed stdout unexpectedly: {stderr_out}")

        data = json.loads(line)
        if "error" in data:
            raise RuntimeError(f"MCP RPC Error [{data['error'].get('code')}]: {data['error'].get('message')}")
        return data.get("result")

    def list_tools(self) -> List[Dict[str, Any]]:
        """List tools provided by the MCP server."""
        res = self.call("tools/list")
        if isinstance(res, dict):
            return res.get("tools", [])
        return []

    def invoke_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        """Invoke an MCP tool by name."""
        return self.call("tools/call", {"name": name, "arguments": arguments})


def mcp_tool_wrapper(client: StdlibMcpClient, tool_name: str) -> Callable[[str, str, Path], str]:
    """Wrap an MCP tool into nakedagent's (args: str, content: str, workspace: Path) signature."""

    def _tool(args: str, content: str, workspace: Path) -> str:
        # If content contains JSON arguments, parse it; otherwise treat content or args as text
        arguments: Dict[str, Any] = {}
        text_input = content.strip() or args.strip()
        if text_input:
            try:
                parsed = json.loads(text_input)
                if isinstance(parsed, dict):
                    arguments = parsed
                else:
                    arguments = {"input": parsed}
            except json.JSONDecodeError:
                arguments = {"input": text_input}

        try:
            result = client.invoke_tool(tool_name, arguments)
            if isinstance(result, (dict, list)):
                return json.dumps(result, indent=2)
            return str(result)
        except Exception as e:
            return f"Error executing MCP tool '{tool_name}': {e}"

    return _tool
