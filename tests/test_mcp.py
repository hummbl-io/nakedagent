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
        mock_proc.stdout = MagicMock()

        # Simulate JSON-RPC 2.0 response
        resp_data = {"jsonrpc": "2.0", "id": 1, "result": {"status": "ok", "value": 42}}
        mock_proc.stdout.readline.return_value = json.dumps(resp_data) + "\n"
        client.proc = mock_proc

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
        mock_proc.stdout = MagicMock()

        error_resp = {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32601, "message": "Method not found"},
        }
        mock_proc.stdout.readline.return_value = json.dumps(error_resp) + "\n"
        client.proc = mock_proc

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


if __name__ == "__main__":
    unittest.main()
