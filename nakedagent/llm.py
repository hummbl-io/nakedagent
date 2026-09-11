"""Ollama chat client. stdlib only: urllib for HTTP, json for the wire format."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_HOST = "http://localhost:11434"


class OllamaError(RuntimeError):
    pass


def chat(messages: list[dict[str, str]], model: str, host: str = DEFAULT_HOST) -> str:
    """Send a chat request, return the assistant reply text.

    ponytail: stream=False for MVP (one JSON response, no NDJSON chunk
    parsing). Upgrade to streaming when interactive latency actually
    matters to a user, not before.
    """
    parsed = urllib.parse.urlparse(host)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        # `urllib` will happily open file:// and other schemes; --host is a
        # user-supplied CLI flag, not model-controlled, but there's no
        # reason to accept anything but a real HTTP(S) server (devin
        # review, P2.7).
        raise OllamaError(f"--host must be an http:// or https:// URL, got: {host!r}")

    body = json.dumps(
        {"model": model, "messages": messages, "stream": False}
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{host}/api/chat",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        # Ollama was reached but returned a non-2xx (e.g. model not found,
        # 500). HTTPError is a URLError subclass, so without this earlier
        # branch it would be misreported as "could not reach Ollama" --
        # misleading, since the server answered. Read the body for a hint.
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:200]
        except Exception:
            pass
        raise OllamaError(
            f"Ollama at {host} returned HTTP {e.code} {e.reason}"
            + (f": {detail}" if detail else "")
        ) from e
    except urllib.error.URLError as e:
        raise OllamaError(
            f"could not reach Ollama at {host} ({e}). Is `ollama serve` running?"
        ) from e
    except json.JSONDecodeError as e:
        # a 200 with a non-JSON body (proxy error page, truncated response)
        # is not a URLError subclass -- without this it escaped chat() as a
        # raw traceback (same crash class as the tool-exception finding, at
        # the llm layer).
        raise OllamaError(f"Ollama at {host} returned a non-JSON response: {e}") from e

    try:
        return data["message"]["content"]
    except (KeyError, TypeError) as e:
        raise OllamaError(f"unexpected Ollama response shape: {data}") from e
