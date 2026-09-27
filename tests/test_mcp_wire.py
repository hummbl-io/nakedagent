"""End-to-end wire tests for StdlibMcpClient.

The MCP mount path had zero coverage — a wrong method name survived as a
silent error-string (R22) and response-id matching was never exercised
(R19). These tests drive a real subprocess speaking newline JSON-RPC so
the wire contract, not a mock, is what gets verified.
"""
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from nakedagent.mcp import StdlibMcpClient

SERVER_SRC = textwrap.dedent(
    """
    import json, sys
    initialized = False
    for line in sys.stdin:
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        method = req.get("method")
        if method == "notifications/initialized":
            initialized = True
            continue  # notification: no response
        if method == "die":
            sys.exit(3)
        if method == "hang":
            continue  # never respond — client must time out, not block
        # Lifecycle enforcement: reject any request before initialize.
        if method != "initialize" and not initialized:
            resp = {"jsonrpc": "2.0", "id": req.get("id"),
                    "error": {"code": -32002, "message": "server not initialized"}}
            sys.stdout.write(json.dumps(resp) + "\\n")
            sys.stdout.flush()
            continue
        if method == "initialize":
            resp = {"jsonrpc": "2.0", "id": req["id"],
                    "result": {"protocolVersion": req["params"].get("protocolVersion"),
                               "capabilities": {"tools": {}},
                               "serverInfo": {"name": "fake", "version": "0"}}}
        elif method == "tools/list":
            resp = {"jsonrpc": "2.0", "id": req["id"],
                    "result": {"tools": [{"name": "echo", "description": "echoes args"}]}}
        elif method == "tools/call":
            args = req["params"].get("arguments", {})
            # Server may emit a notification BEFORE the response; a client
            # that reads the next line blindly returns the notification
            # as if it were the result.
            if args.get("_emit_notice"):
                sys.stdout.write(json.dumps(
                    {"jsonrpc": "2.0", "method": "notifications/message",
                     "params": {"note": "interleaved"}}) + "\\n")
                sys.stdout.flush()
            if args.get("_chatty"):
                # >128KiB stderr: deadlocks any client that pipes stderr
                # but never drains it (pipe buffer fills, server blocks).
                sys.stderr.write("noise\\n" * 24000)
                sys.stderr.flush()
            resp = {"jsonrpc": "2.0", "id": req["id"],
                    "result": {"content": [{"type": "text", "text": json.dumps(args)}]}}
        elif method == "fail":
            resp = {"jsonrpc": "2.0", "id": req["id"],
                    "error": {"code": -32000, "message": "boom"}}
        else:
            resp = {"jsonrpc": "2.0", "id": req["id"], "result": None}
        sys.stdout.write(json.dumps(resp) + "\\n")
        sys.stdout.flush()
    """
)


class McpFixture(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.server = self.dir / "fake_server.py"
        self.server.write_text(SERVER_SRC, encoding="utf-8")
        self.client = StdlibMcpClient([sys.executable, str(self.server)])

    def tearDown(self):
        self.client.close()


class TestWireRoundtrip(McpFixture):
    def test_list_and_call_over_real_stdio(self):
        tools = self.client.list_tools()
        self.assertEqual([t["name"] for t in tools], ["echo"])
        res = self.client.invoke_tool("echo", {"x": 1})
        self.assertIn("content", res)
        self.assertIn('"x": 1', res["content"][0]["text"])

    def test_error_response_raises(self):
        with self.assertRaises(RuntimeError):
            self.client.call("fail")

    def test_dead_child_detected(self):
        with self.assertRaises(RuntimeError):
            self.client.call("die")


class TestNotificationInterleave(McpFixture):
    """R19: the client takes the NEXT stdout line as the response. A server
    that emits a notification first causes the notification to be returned
    as the call result — silently wrong, no error."""

    def test_notification_is_not_mistaken_for_result(self):
        res = self.client.invoke_tool("echo", {"_emit_notice": True, "x": 1})
        self.assertIsNotNone(res, "notification swallowed the response")
        self.assertIn("content", res,
                      f"got notification or garbage instead of result: {res}")


class TestStderrDrain(McpFixture):
    """A server that writes >128KiB to stderr mid-request deadlocks a client
    whose stderr pipe is never drained (the server blocks on write and never
    sends the response)."""

    def test_chatty_server_does_not_deadlock(self):
        res = self.client.invoke_tool("echo", {"_chatty": True})
        self.assertIn("content", res)


class TestCallTimeout(McpFixture):
    """R6: timeout_s must be real — a hung server raises, not wedges."""

    def test_hung_server_times_out(self):
        with self.assertRaises(RuntimeError) as ctx:
            self.client.call("hang", timeout_s=0.5)
        self.assertIn("timed out", str(ctx.exception))

    def test_client_recovers_after_timeout(self):
        with self.assertRaises(RuntimeError):
            self.client.call("hang", timeout_s=0.3)
        res = self.client.invoke_tool("echo", {"x": 2})
        self.assertIn("content", res)


class TestLifecycleHandshake(McpFixture):
    """The fixture rejects requests issued before initialize/initialized —
    so a passing round-trip proves the client performs the handshake."""

    def test_handshake_performed_on_start(self):
        # setUp attached; list_tools only succeeds if initialize ran.
        tools = self.client.list_tools()
        self.assertEqual([t["name"] for t in tools], ["echo"])
        self.assertTrue(self.client._initialized)


if __name__ == "__main__":
    unittest.main()
