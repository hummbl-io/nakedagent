"""Local synthetic child regressions for REC-045; no external MCP server."""
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from nakedagent.mcp import StdlibMcpClient

SERVER = '''import json, sys
pending = []
late = None
for line in sys.stdin:
    req = json.loads(line)
    method = req.get("method")
    if method == "initialize" and "--hang-init" in sys.argv:
        continue
    if method == "notifications/initialized":
        continue
    if method == "pair":
        pending.append(req)
        if len(pending) == 2:
            for item in reversed(pending):
                print(json.dumps({"jsonrpc":"2.0","id":item["id"],
                    "result":item["params"]["name"]}), flush=True)
            pending.clear()
        continue
    if method == "late":
        late = req
        continue
    if late is not None:
        print(json.dumps({"jsonrpc":"2.0","id":late["id"],
            "result":"stale"}), flush=True)
        late = None
    print(json.dumps({"jsonrpc":"2.0","id":req["id"],
        "result":method}), flush=True)
    if method == "exit_after_reply":
        break
'''


class TestMcpRepair(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        path = Path(self.tmp.name) / "server.py"
        path.write_text(SERVER, encoding="utf-8")
        self.client = StdlibMcpClient([sys.executable, str(path)])

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()

    def test_clean_exit_can_respawn_without_old_eof(self):
        self.assertEqual(self.client.call("exit_after_reply", timeout_s=5), "exit_after_reply")
        assert self.client.proc is not None
        self.client.proc.wait(timeout=5)
        self.client.start()
        self.assertEqual(self.client.call("ping", timeout_s=5), "ping")

    def test_call_after_dead_child_restarts_before_write(self):
        self.assertEqual(self.client.call("exit_after_reply", timeout_s=5), "exit_after_reply")
        assert self.client.proc is not None
        self.client.proc.wait(timeout=5)
        self.assertEqual(self.client.call("ping", timeout_s=5), "ping")

    def test_concurrent_reversed_replies_are_routed_to_owners(self):
        self.client.start()
        out = {}

        def request(name):
            try:
                out[name] = self.client.call("pair", {"name": name}, timeout_s=1.5)
            except RuntimeError as exc:
                out[name] = type(exc).__name__ + ": " + str(exc)

        threads = [threading.Thread(target=request, args=(name,)) for name in ("one", "two")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2)
        self.assertFalse(any(t.is_alive() for t in threads))
        self.assertEqual(out, {"one": "one", "two": "two"})

    def test_late_reply_after_timeout_is_not_next_result(self):
        self.client.start()  # spawn outside the tight per-call timeout
        with self.assertRaisesRegex(RuntimeError, "timed out"):
            self.client.call("late", timeout_s=0.1)
        self.assertEqual(self.client.call("ping", timeout_s=5), "ping")

    def test_cold_handshake_honors_call_timeout(self):
        self.client.command.append("--hang-init")
        began = time.monotonic()
        with self.assertRaisesRegex(RuntimeError, "timed out"):
            self.client.call("ping", timeout_s=0.2)
        self.assertLess(time.monotonic() - began, 1.5)
        self.assertIsNone(self.client.proc)

    def test_close_reaps_and_closes_owned_streams(self):
        self.client.start()
        conn = self.client._connection
        assert conn is not None
        proc = conn.proc
        self.client.close()
        self.assertIsNotNone(proc.poll())
        self.assertTrue(all(stream.closed for stream in (proc.stdin, proc.stdout, proc.stderr)))
        self.assertTrue(all(not thread.is_alive() for thread in conn.threads))

    def test_close_wakes_pending_caller(self):
        self.client.start()
        out = []

        def request():
            try:
                out.append(self.client.call("late", timeout_s=5))
            except RuntimeError as exc:
                out.append(type(exc).__name__ + ": " + str(exc))

        thread = threading.Thread(target=request)
        thread.start()
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            conn = self.client._connection
            assert conn is not None
            with conn.lock:
                if conn.pending:
                    break
            time.sleep(0.01)
        self.client.close()
        thread.join(timeout=1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(out, ["RuntimeError: MCP connection closed"])

    def test_partial_reader_start_failure_reaps_child_and_close_is_idempotent(self):
        original_start = threading.Thread.start
        starts = 0
        captured = []

        def fail_second_start(thread):
            nonlocal starts
            starts += 1
            if starts == 2:
                captured.append(self.client.proc)
                raise RuntimeError("injected reader startup failure")
            original_start(thread)

        with (
            patch.object(threading.Thread, "start", fail_second_start),
            self.assertRaisesRegex(RuntimeError, "injected reader startup failure"),
        ):
            self.client.start(timeout_s=0.5)
        self.assertEqual(starts, 2)
        self.assertIsNone(self.client.proc)
        self.assertEqual(len(captured), 1)
        self.assertIsNotNone(captured[0].poll())
        self.client.close()
        self.client.close()

    def test_close_cancels_blocked_write_without_writer_lock(self):
        server = Path(self.tmp.name) / "blocked_server.py"
        server.write_text('''import json, sys, time
for line in sys.stdin:
    req = json.loads(line)
    if req.get("method") == "initialize":
        print(json.dumps({"jsonrpc":"2.0","id":req["id"],"result":{}}), flush=True)
    elif req.get("method") == "notifications/initialized":
        time.sleep(10)
''', encoding="utf-8")
        self.client.command = [sys.executable, str(server)]
        self.client.start(timeout_s=5)
        proc = self.client.proc
        assert proc is not None
        outcome = []

        def request():
            try:
                self.client.call("large", {"data": "x" * (4 * 1024 * 1024)}, timeout_s=0.1)
                outcome.append("returned")
            except (OSError, RuntimeError) as exc:
                outcome.append(type(exc).__name__)

        caller = threading.Thread(target=request, daemon=True)
        caller.start()
        time.sleep(0.2)
        self.assertTrue(caller.is_alive(), "fixture did not block the pipe write")
        closer = threading.Thread(target=self.client.close, daemon=True)
        closer.start()
        closer.join(timeout=1.5)
        if closer.is_alive() and proc.poll() is None:
            proc.kill()  # only the owned fake child; ensure bounded test cleanup
        caller.join(timeout=1.5)
        closer.join(timeout=1.5)
        self.assertFalse(closer.is_alive(), "close waited for the blocked writer")
        self.assertFalse(caller.is_alive())
        self.assertIsNotNone(proc.poll())
        self.assertTrue(outcome)


if __name__ == "__main__":
    unittest.main()
