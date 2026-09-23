"""Tests for pure Python stdlib MCP client and tool wrapper."""
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from nakedagent.mcp import StdlibMcpClient, mcp_tool_wrapper


class TestStdlibMcpClient(unittest.TestCase):
    def test_mcp_call_formatting_and_response(self):
        client = StdlibMcpClient(["dummy_server"])
        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()
        client.proc = mock_proc

        # Simulate JSON-RPC 2.0 response arriving on the stdout queue
        resp_data = {"jsonrpc": "2.0", "id": 1, "result": {"status": "ok", "value": 42}}
        client._stdout_q.put(json.dumps(resp_data) + "\n")

        result = client.call("test_method", {"param": "val"})
        self.assertEqual(result, {"status": "ok", "value": 42})

        # Verify JSON-RPC message sent to stdin
        sent_line = mock_proc.stdin.write.call_args[0][0]
        sent_json = json.loads(sent_line)
        self.assertEqual(sent_json["jsonrpc"], "2.0")
        self.assertEqual(sent_json["method"], "test_method")
        self.assertEqual(sent_json["params"], {"param": "val"})

    def test_mcp_error_handling(self):
        client = StdlibMcpClient(["dummy_server"])
        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()
        client.proc = mock_proc

        error_resp = {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32601, "message": "Method not found"},
        }
        client._stdout_q.put(json.dumps(error_resp) + "\n")

        with self.assertRaises(RuntimeError) as ctx:
            client.call("nonexistent")
        self.assertIn("Method not found", str(ctx.exception))

    def test_mcp_tool_wrapper_dispatch(self):
        client = MagicMock(spec=StdlibMcpClient)
        client.invoke_tool.return_value = {"record_id": "rec-123", "verified": True}

        wrapped = mcp_tool_wrapper(client, "ledger_post")
        workspace = Path(".")
        output = wrapped("", '{"title": "Note", "content": "Proof"}', workspace)

        client.invoke_tool.assert_called_once_with("ledger_post", {"title": "Note", "content": "Proof"})
        self.assertIn("rec-123", output)


class TestMcpShadowRefusal(unittest.TestCase):
    """R1: a mounted MCP tool must not silently replace a builtin — the
    gate threat-model and dispatch table would diverge."""

    def test_builtin_shadow_refused(self):
        from nakedagent.sidekick import SidekickHarness as _Sk

        sk = _Sk.__new__(_Sk)
        sk.tools = {"read": MagicMock(name="builtin_read")}
        sk._mcp_clients = []
        sk.system_prompt = ""

        client = MagicMock(spec=StdlibMcpClient)
        client.list_tools.return_value = [{"name": "read"}, {"name": "mcp_ok"}]

        with patch("nakedagent.sidekick._system_prompt", return_value=""):
            registered = sk.attach_mcp_client(client)

        self.assertNotIn("read", registered)
        self.assertIn("mcp_ok", registered)
        self.assertIsNotNone(sk.tools["read"].name)  # builtin untouched

    def test_malformed_tool_descriptor_skipped(self):
        from nakedagent.sidekick import SidekickHarness as _Sk

        sk = _Sk.__new__(_Sk)
        sk.tools = {}
        sk._mcp_clients = []
        sk.system_prompt = ""

        client = MagicMock(spec=StdlibMcpClient)
        client.list_tools.return_value = [{"name": 42}, {"name": ""}, {}]

        with patch("nakedagent.sidekick._system_prompt", return_value=""):
            registered = sk.attach_mcp_client(client)

        self.assertEqual(registered, [])


if __name__ == "__main__":
    unittest.main()
