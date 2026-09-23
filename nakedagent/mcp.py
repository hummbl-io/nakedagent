"""Zero-dependency Model Context Protocol (MCP) client using pure Python standard library.

Provides JSON-RPC 2.0 communication over stdio pipes without third-party packages.
Connects nakedagent to any MCP server (e.g. coordination-bus, cognitive-ledger,
base120, utf, onepassword).
"""
from __future__ import annotations

import json
import queue
import subprocess
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# MCP protocol revision this client speaks (2024-11-05 is the widely
# deployed stdio baseline; servers negotiate down if older).
MCP_PROTOCOL_VERSION = "2024-11-05"


class StdlibMcpClient:
    """Pure stdlib JSON-RPC 2.0 client for MCP servers over stdio."""

    def __init__(self, command: list[str], cwd: Optional[Path] = None):
        self.command = command
        self.cwd = cwd
        self.proc: Optional[subprocess.Popen] = None
        self._request_id = 0
        self._stderr_tail: List[str] = []
        self._stderr_lock = threading.Lock()
        self._stdout_q: queue.Queue[Optional[str]] = queue.Queue()
        self._initialized = False

    def _drain_stderr(self) -> None:
        """Continuously drain stderr so a chatty server can't fill the pipe
        buffer and deadlock the call path. Keeps a small tail for errors."""
        assert self.proc is not None and self.proc.stderr is not None
        for line in self.proc.stderr:
            with self._stderr_lock:
                self._stderr_tail.append(line.rstrip())
                if len(self._stderr_tail) > 50:
                    self._stderr_tail.pop(0)

    def _drain_stdout(self) -> None:
        """Push each stdout line onto the response queue; None on EOF so
        call() can time out instead of blocking on readline forever."""
        assert self.proc is not None and self.proc.stdout is not None
        for line in self.proc.stdout:
            self._stdout_q.put(line)
        self._stdout_q.put(None)

    def start(self) -> None:
        """Start the MCP server subprocess and perform the MCP handshake.

        Per the MCP lifecycle spec the client MUST send `initialize` and
        then the `initialized` notification before any other request; real
        servers may reject `tools/list` issued pre-handshake.
        """
        if self.proc is not None:
            if self.proc.poll() is None:
                return
            self.close()  # dead child — drop stale pipes before respawn
        self.proc = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(self.cwd) if self.cwd else None,
            text=True,
            bufsize=1,
        )
        threading.Thread(target=self._drain_stderr, daemon=True).start()
        threading.Thread(target=self._drain_stdout, daemon=True).start()
        try:
            self.call(
                "initialize",
                {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "nakedagent", "version": "0.1.0"},
                },
            )
            self._notify("notifications/initialized", {})
            self._initialized = True
        except Exception:
            self.close()
            raise

    def _notify(self, method: str, params: Dict[str, Any]) -> None:
        """Send a JSON-RPC notification (no id, no response expected)."""
        assert self.proc is not None and self.proc.stdin is not None
        msg = json.dumps({"jsonrpc": "2.0", "method": method, "params": params})
        self.proc.stdin.write(f"{msg}\n")
        self.proc.stdin.flush()

    def _stderr_text(self) -> str:
        with self._stderr_lock:
            return "".join(self._stderr_tail)

    def close(self) -> None:
        """Terminate the MCP server subprocess."""
        if self.proc is not None:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=2)
            except Exception:
                try:
                    self.proc.kill()
                    self.proc.wait(timeout=2)  # reap — no zombie
                except Exception:
                    pass
            finally:
                self.proc = None
                self._initialized = False
                with self._stderr_lock:
                    self._stderr_tail.clear()

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

        # Consume queued stdout lines until the response whose id matches
        # this request arrives. Servers may emit notifications (no id) or
        # log noise on stdout; the reader thread + queue make timeout_s real
        # (a hung server raises TimeoutError instead of blocking forever).
        skipped = 0
        while True:
            try:
                line = self._stdout_q.get(timeout=timeout_s)
            except queue.Empty:
                raise RuntimeError(
                    f"MCP call {method!r} timed out after {timeout_s}s") from None
            if line is None:
                raise RuntimeError(
                    f"MCP server closed stdout unexpectedly: {self._stderr_text()}")
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                data = None
            if isinstance(data, dict) and data.get("id") == self._request_id:
                break
            skipped += 1
            if skipped > 128:
                raise RuntimeError("MCP server emitted >128 non-matching lines before our response")

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
