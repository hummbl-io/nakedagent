"""Credential-free CLI smoke test; run from a nakedagent source checkout.

This verifies agent behavior, not the cloud isolation boundary.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


class Fixture(BaseHTTPRequestHandler):
    calls = 0

    def do_POST(self):
        if self.path != "/api/chat":
            self.send_error(404)
            return
        json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).calls += 1
        reply = (
            "```write result.txt\nnakedagent-sandbox-ok\n```"
            if self.calls == 1 else "Fixture task complete."
        )
        payload = json.dumps({"message": {"content": reply}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args):
        pass


def main():
    root = Path(__file__).resolve().parents[3]
    server = HTTPServer(("127.0.0.1", 0), Fixture)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="nakedagent-smoke-") as temp:
            base = Path(temp)
            home = base / "home"
            workspace = base / "workspace"
            home.mkdir()
            workspace.mkdir()
            env = {key: os.environ[key] for key in ("PATH", "SystemRoot", "WINDIR")
                   if key in os.environ}
            env.update(HOME=str(home), USERPROFILE=str(home), TMP=str(base),
                       TEMP=str(base), TMPDIR=str(base), PYTHONNOUSERSITE="1",
                       NO_PROXY="127.0.0.1,localhost")
            proc = subprocess.run(
                [sys.executable, "-m", "nakedagent", "Create result.txt with the fixture marker.",
                 "--workspace", str(workspace), "--host", f"http://127.0.0.1:{server.server_port}",
                 "--model", "deterministic-fixture"],
                cwd=root, env=env, capture_output=True, text=True, timeout=60,
            )
            marker = workspace / "result.txt"
            checks = {
                "cli_exit_zero": proc.returncode == 0,
                "marker_written": marker.exists() and marker.read_text().strip() == "nakedagent-sandbox-ok",
                "two_fixture_calls": Fixture.calls == 2,
                "fresh_home_no_plugins": not (home / ".nakedagent/plugins").exists(),
            }
            print(json.dumps({"checks": checks, "passed": all(checks.values()),
                              "model": "deterministic-local-http-fixture",
                              "isolation_verified": False}, indent=2))
            return 0 if all(checks.values()) else 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == "__main__":
    raise SystemExit(main())
