"""Model chat client. stdlib only: urllib for HTTP, json for the wire format.

Two wire formats, one function:
- "ollama" (default): Ollama's native /api/chat. Local, no key.
- "openai": the OpenAI-compatible /chat/completions shape. One format covers
  hosted APIs (OpenAI, Gemini's OpenAI endpoint, OpenRouter, Groq, ...),
  self-hosted servers (vLLM, LM Studio, llama.cpp) and gateways -- which is
  how nakedagent reaches models too large to run locally. `host` is the base
  URL including its version path, e.g. https://api.openai.com/v1.

The API key is read from a named environment variable, never a CLI value, so
it stays out of shell history and process listings.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_HOST = "http://localhost:11434"
APIS = ("ollama", "openai")
DEFAULT_API_KEY_ENV = "OPENAI_API_KEY"


class LLMError(RuntimeError):
    pass


# Kept so existing imports and plugins keep working; the error now covers
# every backend, not just Ollama.
OllamaError = LLMError


def chat(
    messages: list[dict[str, str]],
    model: str,
    host: str = DEFAULT_HOST,
    *,
    api: str = "ollama",
    api_key_env: str = DEFAULT_API_KEY_ENV,
) -> str:
    """Send a chat request, return the assistant reply text.

    ponytail: stream=False for MVP (one JSON response, no NDJSON chunk
    parsing). Upgrade to streaming when interactive latency actually
    matters to a user, not before.
    """
    if api not in APIS:
        raise LLMError(f"--api must be one of {', '.join(APIS)}, got: {api!r}")
    parsed = urllib.parse.urlparse(host)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        # `urllib` will happily open file:// and other schemes; --host is a
        # user-supplied CLI flag, not model-controlled, but there's no
        # reason to accept anything but a real HTTP(S) server (devin
        # review, P2.7).
        raise LLMError(f"--host must be an http:// or https:// URL, got: {host!r}")

    headers = {"Content-Type": "application/json"}
    if api == "ollama":
        name = "Ollama"
        url = f"{host}/api/chat"
        # think=False: thinking-capable models (qwen3.x) otherwise spend the
        # reply in hidden reasoning and return empty `content` to the loop.
        payload = {"model": model, "messages": messages, "stream": False, "think": False}
    else:
        name = "OpenAI-compatible API"
        url = f"{host.rstrip('/')}/chat/completions"
        payload = {"model": model, "messages": messages, "stream": False}
        # An unset variable means no auth header: local servers (vLLM, LM
        # Studio, Ollama's /v1) need none, and a hosted API that does will
        # answer 401, which is reported below with the variable's name.
        key = os.environ.get(api_key_env, "")
        if key:
            headers["Authorization"] = f"Bearer {key}"

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        # The server was reached but returned a non-2xx (e.g. model not
        # found, 500). HTTPError is a URLError subclass, so without this
        # earlier branch it would be misreported as "could not reach" --
        # misleading, since the server answered. Read the body for a hint.
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:200]
        except Exception:
            pass
        hint = ""
        if api == "openai" and e.code in (401, 403):
            hint = f" (check the key in ${api_key_env})"
        raise LLMError(
            f"{name} at {host} returned HTTP {e.code} {e.reason}{hint}"
            + (f": {detail}" if detail else "")
        ) from e
    except urllib.error.URLError as e:
        tip = " Is `ollama serve` running?" if api == "ollama" else ""
        raise LLMError(f"could not reach {name} at {host} ({e}).{tip}") from e
    except json.JSONDecodeError as e:
        # a 200 with a non-JSON body (proxy error page, truncated response)
        # is not a URLError subclass -- without this it escaped chat() as a
        # raw traceback (same crash class as the tool-exception finding, at
        # the llm layer).
        raise LLMError(f"{name} at {host} returned a non-JSON response: {e}") from e

    try:
        if api == "ollama":
            content = data["message"]["content"]
        else:
            content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise LLMError(f"unexpected {name} response shape: {str(data)[:300]}") from e
    # Some OpenAI-compatible servers send null content for an empty reply;
    # the loop expects a string.
    return content or ""
