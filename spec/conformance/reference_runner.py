"""Run conformance cases against the Python reference implementation.

The vectors under ``spec/conformance/vectors/`` are language-neutral JSON. This
module is the oracle: ``build_vectors.py`` records expected results with it, and
``tests/test_conformance_vectors.py`` re-checks the committed vectors with it so
the reference and the vectors cannot drift apart.

Value encoding (see spec/SPEC.md, "Vector value encoding"): anywhere a text or
byte value appears it is one of
  * a JSON string,
  * ``{"repeat": [string, count]}``   -- ``string`` repeated ``count`` times,
  * ``{"b64": string}``               -- raw bytes, base64,
  * ``{"concat": [value, ...]}``      -- concatenation of text values.
"""

from __future__ import annotations

import base64
import http.server
import json
import os
import re
import sys
import tempfile
import threading
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nakedagent import llm, loop, tools  # noqa: E402
from nakedagent.toolcall import parse  # noqa: E402


# --------------------------------------------------------------------- values

def decode_text(v) -> str:
    if isinstance(v, str):
        return v
    if "repeat" in v:
        s, n = v["repeat"]
        return s * n
    if "concat" in v:
        return "".join(decode_text(p) for p in v["concat"])
    raise ValueError(f"not a text value: {v!r}")


def decode_bytes(v) -> bytes:
    if isinstance(v, dict) and "b64" in v:
        return base64.b64decode(v["b64"])
    return decode_text(v).encode("utf-8")


def encode_text(s: str):
    """Smallest stable encoding: collapse a long leading run of one character."""
    if not s:
        return s
    c = s[0]
    n = 1
    while n < len(s) and s[n] == c:
        n += 1
    if n >= 100:
        run = {"repeat": [c, n]}
        rest = s[n:]
        return run if not rest else {"concat": [run, encode_text(rest)]}
    # run too short at the front: look for the first long run further in
    i = 1
    while i < len(s):
        j = i
        while j < len(s) and s[j] == s[i]:
            j += 1
        if j - i >= 100:
            head = s[:i]
            return {"concat": [head, encode_text(s[i:])]}
        i = j
    return s


def encode_bytes(b: bytes):
    try:
        return encode_text(b.decode("utf-8"))
    except UnicodeDecodeError:
        return {"b64": base64.b64encode(b).decode("ascii")}


# ------------------------------------------------------------------ workspace

def _write_files(root: Path, files: dict) -> None:
    for rel, val in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(decode_bytes(val))


def _snapshot(root: Path) -> dict:
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file() and not p.is_symlink():
            rel = p.relative_to(root).as_posix()
            if rel.startswith(".nakedagent/"):
                continue  # audit log is not part of the tool contract
            data = p.read_bytes()
            if os.name == "nt":
                # The reference writes text files in text mode, which on Windows turns
                # LF into CRLF (open question in spec/SPEC.md); compare in LF form.
                data = data.replace(b"\r\n", b"\n")
            out[rel] = encode_bytes(data)
    return out


# ------------------------------------------------------------------- suites

def run_toolcall(case: dict):
    return [
        {"tool": c.tool, "args": c.args, "content": c.content}
        for c in parse(decode_text(case["input"]))
    ]


def run_patch_split(case: dict):
    try:
        search, replace = tools._split_search_replace(decode_text(case["input"]))
    except ValueError as e:
        return {"error": str(e)}
    return {"search": encode_text(search), "replace": encode_text(replace)}


_FS_TOOLS = {"read": tools.tool_read, "write": tools.tool_write, "patch": tools.tool_patch}


class SymlinkUnavailable(Exception):
    """Raised when the platform refuses to create a symlink fixture (for example Windows without privilege)."""


def run_fs(case: dict):
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td) / "ws"
        outside = Path(td) / "outside"  # sibling of the workspace, for escape cases
        ws.mkdir()
        _write_files(ws, case.get("files", {}))
        if "outside" in case or "symlinks" in case:
            outside.mkdir()
            _write_files(outside, case.get("outside", {}))
        for link, target in case.get("symlinks", {}).items():
            lp = ws / link
            lp.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.symlink(target, lp, target_is_directory=(lp.parent / target).is_dir())
            except (OSError, NotImplementedError) as e:
                raise SymlinkUnavailable(str(e)) from e
        result = _FS_TOOLS[case["tool"]](
            case.get("args", ""), decode_text(case.get("content", "")), ws
        )
        out = {"result": encode_text(result), "files": _snapshot(ws)}
        if "outside" in case or "symlinks" in case:
            out["outside_files"] = _snapshot(outside)
        return out


def run_allowlist(case: dict):
    return tools._is_allowed_shell_command(case["command"], tuple(case["allowlist"]))


def run_shell(case: dict):
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td)
        with mock.patch.object(sys, "stdin", _NoTty()):
            result = tools.tool_shell(
                case.get("args", ""),
                decode_text(case.get("content", "")),
                ws,
                allow_shell=case.get("allow_shell", False),
                shell_allowlist=tuple(case.get("shell_allowlist", [])),
                shell_timeout=case.get("shell_timeout", 120),
            )
    return encode_text(result)


class _NoTty:
    def isatty(self):
        return False


def run_prompt(case: dict):
    reg = dict(tools.TOOLS)
    for name in case.get("extra_tools_without_usage", []):
        reg[name] = lambda a, c, w: ""
    return encode_text(loop._system_prompt(reg))


# ---------------------------------------------------------------- mock server

class _Server:
    """Scripted HTTP server: replays ``script`` entries in order, records requests."""

    def __init__(self, script: list[dict]):
        self.script = list(script)
        self.requests: list[dict] = []
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):  # silence
                pass

            def _handle(self):
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) if n else b""
                try:
                    body = json.loads(raw) if raw else None
                except ValueError:
                    body = {"__raw__": raw.decode("utf-8", "replace")}
                outer.requests.append({
                    "method": self.command,
                    "path": self.path,
                    "body": body,
                    "auth": self.headers.get("Authorization"),
                })
                step = outer.script.pop(0) if outer.script else {"status": 500, "body": "script exhausted"}
                self.send_response(step.get("status", 200))
                for k, v in step.get("headers", {}).items():
                    self.send_header(k, v)
                payload = step["body"]
                data = payload.encode() if isinstance(payload, str) else json.dumps(payload).encode()
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = _handle

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *a):
        self.httpd.shutdown()
        self.httpd.server_close()


def _unused_port() -> int:
    import socket

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def run_llm(case: dict):
    env = dict(case.get("env", {}))
    api = case.get("api", "ollama")
    kwargs = {"api": api}
    if "api_key_env" in case:
        kwargs["api_key_env"] = case["api_key_env"]
    messages = case["messages"]

    def call(host) -> dict:
        with mock.patch.dict(os.environ, env, clear=False):
            for k in ("OPENAI_API_KEY", "CUSTOM_KEY"):
                if k not in env:
                    os.environ.pop(k, None)
            try:
                return {"reply": llm.chat(messages, case["model"], host, **kwargs)}
            except llm.LLMError as e:
                return {"error": re.sub(r"127\.0\.0\.1:\d+", "HOST:PORT", str(e))}

    out: dict
    if case.get("host") is not None:  # literal host (validation cases)
        out = call(case["host"])
        out["requests"] = []
    elif case.get("unreachable"):
        out = call(f"http://127.0.0.1:{_unused_port()}")
        out["requests"] = []
    else:
        with _Server(case.get("server", [])) as srv:
            out = call(f"http://127.0.0.1:{srv.port}{case.get('host_path', '')}")
        out["requests"] = [
            {
                "method": r["method"],
                "path": r["path"],
                "body": r["body"],
                "authorization": r["auth"],
            }
            for r in srv.requests
        ]
    return out


def run_loop(case: dict):
    script = [{"status": 200, "body": {"message": {"content": r}}} for r in case["replies"]]
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td) / "ws"
        ws.mkdir()
        home = Path(td) / "home"
        home.mkdir()
        _write_files(ws, case.get("files", {}))
        with _Server(script) as srv, mock.patch.object(sys, "stdin", _NoTty()), \
                mock.patch.dict(os.environ, {"HOME": str(home), "USERPROFILE": str(home)}), \
                mock.patch("builtins.print"):
            loop.run(
                case["prompt"],
                "test-model",
                ws,
                f"http://127.0.0.1:{srv.port}",
                allow_shell=case.get("allow_shell", False),
                shell_allowlist=tuple(case.get("shell_allowlist", [])),
            )
        reqs = srv.requests
        last = reqs[-1]["body"]["messages"] if reqs else []
        norm = []
        for m in last:
            content = m["content"]
            if m["role"] == "system":
                content = "$SYSTEM"
            norm.append({"role": m["role"], "content": encode_text(content)})
        return {
            "request_count": len(reqs),
            "last_request_messages": norm,
            "files": _snapshot(ws),
        }


SUITES = {
    "toolcall": run_toolcall,
    "patch_split": run_patch_split,
    "fs_tools": run_fs,
    "shell_allowlist": run_allowlist,
    "shell_policy": run_shell,
    "prompt": run_prompt,
    "llm_wire": run_llm,
    "loop": run_loop,
}
