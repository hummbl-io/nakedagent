"""Bounded network probes; failures need controller policy-log corroboration."""
import hashlib
import json
import os
from pathlib import Path
import socket
import urllib.request

root = Path(__file__).resolve().parents[3]
manifest = json.loads((root / "manifest.json").read_text())
integrity = all(hashlib.sha256((root / name).read_bytes()).hexdigest() == digest
                for name, digest in manifest["files"].items())
checks = []
for url in ("https://example.com", "https://api.github.com"):
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            result = {"connected": True, "status": response.status}
    except Exception as exc:
        result = {"connected": False, "error": type(exc).__name__, "detail": str(exc)[:300]}
    checks.append({"kind": "https", "target": url, **result})
try:
    with socket.create_connection(("1.1.1.1", 443), timeout=5):
        direct = {"connected": True}
except Exception as exc:
    direct = {"connected": False, "error": type(exc).__name__, "detail": str(exc)[:300]}
checks.append({"kind": "direct_tcp", "target": "1.1.1.1:443", **direct})
print(json.dumps({"source_hashes_match": integrity, "uid": os.getuid(),
                  "network_probes": checks,
                  "interpretation": "Connection failures alone do not prove enforcement."}, indent=2))
