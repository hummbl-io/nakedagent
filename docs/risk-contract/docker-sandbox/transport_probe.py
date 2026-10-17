"""Distinguish proxy TCP acceptance from successful external HTTP exchange."""
import json
import socket
import ssl

results = []
for sni in ("one.one.one.one", None):
    row = {"target": "1.1.1.1:443", "sni": sni, "tcp": False, "tls": False,
           "response_received": False}
    try:
        with socket.create_connection(("1.1.1.1", 443), timeout=5) as raw:
            row["tcp"] = True
            context = ssl.create_default_context()
            if sni is None:
                context.check_hostname = False
            with context.wrap_socket(raw, server_hostname=sni) as secured:
                row["tls"] = True
                secured.sendall(b"HEAD / HTTP/1.1\r\nHost: one.one.one.one\r\nConnection: close\r\n\r\n")
                reply = secured.recv(256)
                row["response_received"] = bool(reply)
                row["status_line"] = reply.split(b"\r\n", 1)[0].decode("ascii", "replace")
    except Exception as exc:
        row["error"] = type(exc).__name__
        row["detail"] = str(exc)[:300]
    results.append(row)
print(json.dumps(results, indent=2))
