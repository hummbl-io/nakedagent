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
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

# MCP protocol revision this client speaks (2024-11-05 is the widely
# deployed stdio baseline; servers negotiate down if older).
MCP_PROTOCOL_VERSION = "2024-11-05"


class _Write:
    """One frame; dispatch/cancellation decisions use the connection lock."""

    def __init__(self, frame: str, deadline: float):
        self.frame = frame
        self.deadline = deadline
        self.done = threading.Event()
        self.started = False
        self.cancelled = False
        self.error: Exception | None = None


class _Connection:
    """State owned by exactly one child generation."""

    def __init__(self, proc: subprocess.Popen, stdout_q: queue.Queue[str | None]):
        self.proc = proc
        self.stdout_q = stdout_q
        self.lock = threading.Lock()
        self.write_lock = threading.Lock()
        self.writes: queue.Queue[_Write] = queue.Queue(maxsize=64)
        self.writer: threading.Thread | None = None
        self.dispatcher: threading.Thread | None = None
        self.pending: dict[int, queue.Queue[Any]] = {}
        self.stderr_tail: list[str] = []
        self.stderr_lock = threading.Lock()
        self.threads: list[threading.Thread] = []
        self.closed = False


class StdlibMcpClient:
    """Pure stdlib JSON-RPC 2.0 client for MCP servers over stdio."""

    def __init__(self, command: list[str], cwd: Path | None = None):
        self.command = command
        self.cwd = cwd
        self.proc: subprocess.Popen | None = None
        self._request_id = 0
        self._stderr_tail: list[str] = []
        self._stderr_lock = threading.Lock()
        self._stdout_q: queue.Queue[str | None] = queue.Queue()
        self._initialized = False
        self._lifecycle_lock = threading.RLock()
        self._connection: _Connection | None = None
        self._cleanup_errors: list[str] = []

    def _drain_stderr(self, conn: _Connection) -> None:
        """Continuously drain stderr so a chatty server can't fill the pipe
        buffer and deadlock the call path. Keeps a small tail for errors."""
        assert conn.proc.stderr is not None
        for line in conn.proc.stderr:
            with conn.stderr_lock:
                conn.stderr_tail.append(line.rstrip())
                if len(conn.stderr_tail) > 50:
                    conn.stderr_tail.pop(0)

    def _drain_stdout(self, conn: _Connection) -> None:
        """Push each stdout line onto the response queue; None on EOF so
        call() can time out instead of blocking on readline forever."""
        assert conn.proc.stdout is not None
        try:
            for line in conn.proc.stdout:
                conn.stdout_q.put(line)
        finally:
            conn.stdout_q.put(None)

    @staticmethod
    def _fail_pending(conn: _Connection, error: RuntimeError) -> None:
        with conn.lock:
            conn.closed = True
            pending = list(conn.pending.values())
            conn.pending.clear()
        for response_q in pending:
            response_q.put(error)

    def _dispatch_stdout(self, conn: _Connection) -> None:
        """A single consumer routes each reply to its owning request."""
        unmatched = 0
        while True:
            line = conn.stdout_q.get()
            if line is None:
                with conn.stderr_lock:
                    stderr = "".join(conn.stderr_tail)
                self._fail_pending(conn, RuntimeError(
                    f"MCP server closed stdout unexpectedly: {stderr}"))
                return
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                data = None
            raw_id = data.get("id") if isinstance(data, dict) else None
            request_id = raw_id if isinstance(raw_id, int) and not isinstance(raw_id, bool) else None
            with conn.lock:
                response_q = conn.pending.pop(request_id, None) if request_id is not None else None
            if response_q is not None:
                response_q.put(data)
                unmatched = 0
            else:
                # Notifications and late responses have no active owner.
                unmatched += 1
                if unmatched > 128:
                    self._fail_pending(conn, RuntimeError(
                        "MCP server emitted >128 non-matching lines before our response"))
                    return

    def _start_dispatcher(self, conn: _Connection) -> None:
        with conn.lock:
            if conn.dispatcher is not None:
                return
            if conn.closed:
                raise RuntimeError("MCP connection closed")
            thread = threading.Thread(target=self._dispatch_stdout, args=(conn,), daemon=True)
            conn.dispatcher = thread
            conn.threads.append(thread)
            thread.start()

    def _abort_write(self, conn: _Connection) -> None:
        """Retire this generation after an interrupted or failed pipe write.

        A partially written JSON frame cannot be reused safely. Do not call
        close() here: it acquires lifecycle locks and waits for I/O threads.
        Killing the owned child releases a blocked pipe without making the
        caller wait for cleanup or risking a replacement generation.
        """
        self._fail_pending(conn, RuntimeError(
            "MCP connection closed after interrupted request write; effect outcome unknown"))
        try:
            if conn.proc.poll() is None:
                conn.proc.kill()
        except OSError as exc:
            self._cleanup_errors.append(type(exc).__name__)

    def _write_frames(self, conn: _Connection) -> None:
        """One writer per connection, never one blocking thread per call."""
        while not conn.closed:
            try:
                job = conn.writes.get(timeout=0.05)
            except queue.Empty:
                continue
            locked = conn.write_lock.acquire(timeout=max(0.0, job.deadline - time.monotonic()))
            try:
                with conn.lock:
                    if conn.closed:
                        job.error = RuntimeError("MCP connection closed")
                    elif job.cancelled or not locked or time.monotonic() >= job.deadline:
                        job.error = RuntimeError("MCP request write timed out")
                    else:
                        job.started = True
                if job.error is None:
                    try:
                        assert conn.proc.stdin is not None
                        conn.proc.stdin.write(job.frame)
                        conn.proc.stdin.flush()
                    except Exception as exc:  # noqa: BLE001 -- retire the transport on any writer failure
                        job.error = exc
                        self._abort_write(conn)
            finally:
                # Synchronize with the caller's expiry decision. Once done
                # is set, the caller knows the frame is no longer in flight.
                with conn.lock:
                    job.done.set()
                if locked:
                    conn.write_lock.release()
        # Release queued frames promptly after this generation is retired.
        while True:
            try:
                job = conn.writes.get_nowait()
            except queue.Empty:
                return
            job.error = RuntimeError("MCP connection closed")
            job.done.set()

    def _send(self, conn: _Connection, payload: dict[str, Any], deadline: float,
              timeout_error: RuntimeError) -> None:
        frame = json.dumps(payload) + "\n"
        if time.monotonic() >= deadline:
            raise timeout_error
        job = _Write(frame, deadline)
        with conn.lock:
            if conn.closed:
                raise RuntimeError("MCP connection closed")
            if conn.writer is None:
                thread = threading.Thread(target=self._write_frames, args=(conn,), daemon=True)
                conn.writer = thread
                conn.threads.append(thread)
                thread.start()
        try:
            conn.writes.put(job, timeout=max(0.0, deadline - time.monotonic()))
        except queue.Full:
            raise timeout_error from None
        with conn.lock:
            # Shutdown may have drained the queue between the earlier check
            # and put(). Do not wait on a frame with no remaining writer.
            if conn.closed:
                job.cancelled = True
                raise RuntimeError("MCP connection closed")
        if not job.done.wait(timeout=max(0.0, deadline - time.monotonic())):
            with conn.lock:
                job.cancelled = True
                interrupted = job.started and not job.done.is_set()
            if interrupted:
                self._abort_write(conn)
            raise timeout_error
        if job.error is not None:
            raise job.error

    def start(self, timeout_s: float = 30.0) -> None:
        """Start the MCP server subprocess and perform the MCP handshake.

        Per the MCP lifecycle spec the client MUST send `initialize` and
        then the `initialized` notification before any other request; real
        servers may reject `tools/list` issued pre-handshake.
        """
        deadline = time.monotonic() + timeout_s
        if not self._lifecycle_lock.acquire(timeout=max(0.0, deadline - time.monotonic())):
            raise RuntimeError(f"MCP start timed out after {timeout_s}s")
        try:
            if self.proc is not None:
                if (self.proc.poll() is None and self._initialized
                        and self._connection is not None
                        and not self._connection.closed):
                    return
                self.close()  # detach the dead generation and its old queue
            proc = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(self.cwd) if self.cwd else None,
                text=True,
                encoding="utf-8",
                bufsize=1,
            )
            conn = _Connection(proc, queue.Queue())
            self.proc = proc
            self._connection = conn
            self._stdout_q = conn.stdout_q
            try:
                self._start_dispatcher(conn)
                for target in (self._drain_stderr, self._drain_stdout):
                    thread = threading.Thread(target=target, args=(conn,), daemon=True)
                    conn.threads.append(thread)
                    thread.start()
                self._rpc(
                    conn,
                    "initialize",
                    {
                        "protocolVersion": MCP_PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {"name": "nakedagent", "version": "0.1.0"},
                    },
                    max(0.0, deadline - time.monotonic()),
                )
                self._notify("notifications/initialized", {}, deadline=deadline)
                self._initialized = True
            except Exception:  # Any handshake failure must reap the child.
                self._abort_write(conn)
                self.close()
                raise
        finally:
            self._lifecycle_lock.release()

    def _notify(self, method: str, params: dict[str, Any], *, deadline: float | None = None) -> None:
        """Send a JSON-RPC notification (no id, no response expected)."""
        assert self.proc is not None and self.proc.stdin is not None
        conn = self._connection
        assert conn is not None
        self._send(conn, {"jsonrpc": "2.0", "method": method, "params": params},
                   deadline if deadline is not None else time.monotonic() + 30.0,
                   RuntimeError(f"MCP notification {method!r} timed out"))

    def _stderr_text(self) -> str:
        conn = self._connection
        if conn is None:
            return ""
        with conn.stderr_lock:
            return "".join(conn.stderr_tail)

    def close(self) -> None:
        """Terminate the MCP server subprocess."""
        # Kill the owned child before waiting for lifecycle or request locks.
        # This releases an in-flight pipe write if the child stopped reading.
        preempt_proc = self.proc
        if preempt_proc is not None:
            try:
                if preempt_proc.poll() is None:
                    preempt_proc.terminate()
            except OSError as exc:
                self._cleanup_errors.append(type(exc).__name__)
        with self._lifecycle_lock:
            proc = self.proc
            conn = self._connection
            self.proc = None
            self._connection = None
            self._stdout_q = queue.Queue()
            self._initialized = False
            if proc is None:
                if conn is not None:
                    self._fail_pending(conn, RuntimeError("MCP connection closed"))
                return
            try:
                if proc.poll() is None:
                    proc.terminate()
            except OSError as exc:
                self._cleanup_errors.append(type(exc).__name__)
            if conn is not None:
                self._fail_pending(conn, RuntimeError("MCP connection closed"))
            try:
                proc.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired) as exc:
                self._cleanup_errors.append(type(exc).__name__)
                try:
                    proc.kill()
                    proc.wait(timeout=2)
                except (OSError, subprocess.TimeoutExpired) as kill_exc:
                    self._cleanup_errors.append(type(kill_exc).__name__)
            finally:
                for stream in (proc.stdin, proc.stdout, proc.stderr):
                    if stream is not None:
                        try:
                            stream.close()
                        except (OSError, ValueError) as close_exc:
                            self._cleanup_errors.append(type(close_exc).__name__)
                if conn is not None:
                    conn.stdout_q.put(None)
                    for thread in conn.threads:
                        if thread.ident is not None:
                            thread.join(timeout=1)

    def call(self, method: str, params: dict[str, Any] | None = None, timeout_s: float = 30.0) -> Any:
        """Execute a request with a deadline for locks, sending, and reply.

        Unsent expired frames are cancelled. An interrupted write retires the
        connection; timing out cannot undo remote effects already started.
        """
        if timeout_s < 0:
            raise ValueError("timeout_s must be nonnegative")
        deadline = time.monotonic() + timeout_s
        if time.monotonic() >= deadline:
            raise RuntimeError(f"MCP call {method!r} timed out after {timeout_s}s")
        if not self._lifecycle_lock.acquire(timeout=max(0.0, deadline - time.monotonic())):
            raise RuntimeError(f"MCP call {method!r} timed out after {timeout_s}s")
        try:
            if self.proc is None or self._connection is not None:
                self.start(timeout_s=max(0.0, deadline - time.monotonic()))
            conn = self._connection
            if conn is None:
                # Supports the pre-existing queue-fed unit tests, which inject
                # a fake process directly instead of starting a child.
                assert self.proc is not None
                conn = _Connection(self.proc, self._stdout_q)
                self._connection = conn
        finally:
            self._lifecycle_lock.release()
        return self._rpc(conn, method, params, max(0.0, deadline - time.monotonic()))

    def _rpc(self, conn: _Connection, method: str,
             params: dict[str, Any] | None, timeout_s: float) -> Any:
        deadline = time.monotonic() + timeout_s
        timeout_error = RuntimeError(f"MCP call {method!r} timed out after {timeout_s}s")
        if time.monotonic() >= deadline:
            raise timeout_error
        response_q: queue.Queue[Any] = queue.Queue(maxsize=1)
        with conn.lock:
            if conn.closed:
                raise RuntimeError("MCP connection closed")
            self._request_id += 1
            request_id = self._request_id
            conn.pending[request_id] = response_q
            payload = {"jsonrpc": "2.0", "id": request_id,
                       "method": method, "params": params or {}}
        try:
            self._start_dispatcher(conn)
            self._send(conn, payload, deadline, timeout_error)
        except Exception:
            with conn.lock:
                conn.pending.pop(request_id, None)
            raise
        try:
            data = response_q.get(timeout=max(0.0, deadline - time.monotonic()))
        except queue.Empty:
            with conn.lock:
                conn.pending.pop(request_id, None)
            raise timeout_error from None
        if isinstance(data, Exception):
            raise data
        if "error" in data:
            error = data["error"]
            if isinstance(error, dict):
                raise RuntimeError(f"MCP RPC Error [{error.get('code')}]: {error.get('message')}")
            raise RuntimeError(f"MCP RPC Error: {error}")
        return data.get("result")

    def list_tools(self) -> list[dict[str, Any]]:
        """List tools provided by the MCP server."""
        res = self.call("tools/list")
        if isinstance(res, dict):
            return res.get("tools", [])
        return []

    def invoke_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Invoke an MCP tool by name."""
        return self.call("tools/call", {"name": name, "arguments": arguments})


def mcp_tool_wrapper(client: StdlibMcpClient, tool_name: str) -> Callable[[str, str, Path], str]:
    """Wrap an MCP tool into nakedagent's (args: str, content: str, workspace: Path) signature."""

    def _tool(args: str, content: str, workspace: Path) -> str:
        # If content contains JSON arguments, parse it; otherwise treat content or args as text
        arguments: dict[str, Any] = {}
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
        except Exception as e:  # noqa: BLE001 - preserve the public tool-error boundary
            return f"Error executing MCP tool '{tool_name}': {e}"

    return _tool
