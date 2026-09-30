"""Bounded local-child regressions for request write deadlines (no live MCP)."""
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from nakedagent.mcp import StdlibMcpClient

SERVER = '''import json, pathlib, sys, time
record = pathlib.Path(sys.argv[1])
for line in sys.stdin:
    req = json.loads(line)
    method = req.get("method")
    if method == "notifications/initialized":
        print("P1_READY", file=sys.stderr, flush=True)
        if "--stall" in sys.argv:
            time.sleep(15)
        continue
    if method != "initialize":
        with record.open("a", encoding="utf-8") as output:
            output.write(json.dumps(method) + "\\n")
    print(json.dumps({"jsonrpc":"2.0", "id":req["id"], "result":method}), flush=True)
'''


class TestMcpWriteDeadline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.record = root / "requests.jsonl"
        server = root / "server.py"
        server.write_text(SERVER, encoding="utf-8")
        self.client = StdlibMcpClient([sys.executable, "-I", "-S", str(server), str(self.record)])
        self.callers = []
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        # Watchdog cleanup also bounds the known-broken baseline: do not wait
        # for its blocked call before killing this fixture's owned child.
        proc = self.client.proc
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.wait(timeout=3)
        for caller in self.callers:
            caller.join(timeout=3)
        self.client.close()

    def _start(self, stall=False):
        if stall:
            self.client.command.append("--stall")
        self.client.start(timeout_s=5)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if "P1_READY" in self.client._stderr_text():
                return
            time.sleep(0.01)
        self.fail("local fixture never became ready")

    def _request(self, method, params=None, timeout_s=0.1):
        outcomes = []

        def request():
            try:
                outcomes.append(self.client.call(method, params, timeout_s=timeout_s))
            except Exception as exc:  # noqa: BLE001 -- assert worker failures on the test thread
                outcomes.append(exc)

        caller = threading.Thread(target=request, daemon=True)
        self.callers.append(caller)
        caller.start()
        return caller, outcomes

    def _recorded(self):
        if not self.record.exists():
            return []
        return [json.loads(line) for line in self.record.read_text(encoding="utf-8").splitlines()]

    def test_blocked_pipe_times_out_without_external_close(self):
        self._start(stall=True)
        proc = self.client.proc
        started = time.monotonic()
        caller, outcomes = self._request("large", {"data": "x" * (4 * 1024 * 1024)})
        caller.join(timeout=1)
        self.assertFalse(caller.is_alive(), "request deadline did not bound the pipe write")
        self.assertLess(time.monotonic() - started, 1)
        self.assertIsInstance(outcomes[0], RuntimeError)
        self.assertIn("timed out", str(outcomes[0]))
        # An interrupted frame cannot safely share a connection with later
        # requests. The timed-out writer must retire this child itself.
        self.assertTrue(self.client._connection.closed)
        proc.wait(timeout=2)
        self.assertEqual(self._recorded(), [])

    def test_writer_lock_wait_expires_without_late_dispatch(self):
        self._start()
        conn = self.client._connection
        proc = self.client.proc
        conn.write_lock.acquire()
        try:
            caller, outcomes = self._request("expired")
            caller.join(timeout=0.7)
            finished_on_time = not caller.is_alive()
        finally:
            conn.write_lock.release()
        caller.join(timeout=2)
        self.assertTrue(finished_on_time, "request deadline did not bound the writer lock")
        self.assertIsInstance(outcomes[0], RuntimeError)
        self.assertIn("timed out", str(outcomes[0]))
        self.assertEqual(self.client.call("ping", timeout_s=2), "ping")
        self.assertIs(self.client.proc, proc, "an unsent expiry need not retire a healthy peer")
        self.assertEqual(self._recorded(), ["ping"])

    def test_expired_budget_does_not_send_a_request(self):
        self._start()
        with self.assertRaisesRegex(RuntimeError, "timed out"):
            self.client.call("expired", timeout_s=0)
        self.assertEqual(self.client.call("ping", timeout_s=2), "ping")
        self.assertEqual(self._recorded(), ["ping"])

    def test_queued_expiry_preserves_writer_then_retired_generation_restarts(self):
        self._start(stall=True)
        old_conn = self.client._connection
        old_proc = self.client.proc
        first, first_outcomes = self._request(
            "large", {"data": "x" * (4 * 1024 * 1024)}, timeout_s=1.5)
        deadline = time.monotonic() + 0.7
        while time.monotonic() < deadline and not old_conn.write_lock.locked():
            time.sleep(0.01)
        self.assertTrue(old_conn.write_lock.locked(), "fixture writer did not reach its pipe")
        second, second_outcomes = self._request("expired")
        second.join(timeout=0.7)
        self.assertFalse(second.is_alive(), "queued request ignored its own shorter deadline")
        self.assertIsInstance(second_outcomes[0], RuntimeError)
        self.assertIn("timed out", str(second_outcomes[0]))
        self.assertTrue(first.is_alive(), "unsent expiry cancelled another request")
        self.assertIsNone(old_proc.poll())
        first.join(timeout=2)
        self.assertFalse(first.is_alive(), "in-flight write did not expire")
        self.assertIsInstance(first_outcomes[0], RuntimeError)
        self.assertIn("timed out", str(first_outcomes[0]))
        self.client.command.remove("--stall")
        self.assertEqual(self.client.call("ping", timeout_s=5), "ping")
        self.assertIsNot(self.client._connection, old_conn)
        self.assertIsNotNone(old_proc.poll())
        self.assertTrue(all(not thread.is_alive() for thread in old_conn.threads))
        self.assertEqual(self._recorded(), ["ping"])

    def test_many_requests_share_one_writer_and_close_joins_it(self):
        self._start()
        conn = self.client._connection
        writer = conn.writer
        initial_threads = tuple(conn.threads)
        for number in range(12):
            method = f"request_{number}"
            self.assertEqual(self.client.call(method, timeout_s=2), method)
            self.assertIs(conn.writer, writer)
            self.assertEqual(tuple(conn.threads), initial_threads)
        self.assertEqual(len(initial_threads), 4)
        self.client.close()
        self.assertTrue(all(not thread.is_alive() for thread in initial_threads))

    def test_close_between_validation_and_enqueue_wakes_caller(self):
        self._start()
        conn = self.client._connection
        put = conn.writes.put

        def enqueue_after_shutdown(job, **kwargs):
            # Deterministic peer-review interleaving: close has joined the
            # writer and drained the empty queue before the frame is queued.
            self.client.close()
            put(job, **kwargs)

        with patch.object(conn.writes, "put", side_effect=enqueue_after_shutdown):
            caller, outcomes = self._request("late", timeout_s=2)
            caller.join(timeout=0.7)
        self.assertFalse(caller.is_alive(), "closed connection left a frame without a writer")
        self.assertIsInstance(outcomes[0], RuntimeError)
        self.assertEqual(str(outcomes[0]), "MCP connection closed")
        self.assertEqual(self._recorded(), [])
