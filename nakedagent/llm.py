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
from collections.abc import Callable

DEFAULT_HOST = "http://localhost:11434"
APIS = ("ollama", "openai")
DEFAULT_API_KEY_ENV = "OPENAI_API_KEY"


class LLMError(RuntimeError):
    pass


# Kept so existing imports and plugins keep working; the error now covers
# every backend, not just Ollama.
OllamaError = LLMError


def _read_stream(
    resp,
    *,
    api: str,
    on_chunk: Callable[[str], None] | None,
    name: str,
    host: str,
) -> str:
    """Join a streamed reply, handing each delta to `on_chunk` as it lands.

    Two line formats, one reader. Ollama answers NDJSON: one JSON object per
    line, the delta at `message.content`. The OpenAI-compatible shape answers
    SSE: `data: {...}` lines with the delta at `choices[0].delta.content`,
    closed by `data: [DONE]`.

    A malformed line is skipped rather than fatal. A stream is a partial
    result by nature, and discarding text already received because a later
    line was unparseable would turn a cosmetic transport hiccup into a lost
    reply -- the opposite of what streaming is for. The joined text is what
    the caller gets, so a dropped line shows up as missing text, not as a
    crash. A reply that is empty for *every* line still returns "", which the
    loop already handles.
    """
    pieces: list[str] = []
    for raw in resp:
        line = raw.decode("utf-8", "replace").strip() if isinstance(raw, bytes) else raw.strip()
        if not line:
            continue
        if api == "openai":
            if not line.startswith("data:"):
                continue
            line = line[len("data:") :].strip()
            if line == "[DONE]":
                break
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if api == "ollama":
            delta = (obj.get("message") or {}).get("content") or ""
        else:
            choices = obj.get("choices") or [{}]
            delta = (choices[0].get("delta") or {}).get("content") or ""
        if delta:
            pieces.append(delta)
            if on_chunk is not None:
                on_chunk(delta)
        if obj.get("done") is True:
            break
    return "".join(pieces)


def chat(
    messages: list[dict[str, str]],
    model: str,
    host: str = DEFAULT_HOST,
    *,
    api: str = "ollama",
    api_key_env: str = DEFAULT_API_KEY_ENV,
    stream: bool = False,
    on_chunk: Callable[[str], None] | None = None,
) -> str:
    """Send a chat request, return the assistant reply text.

    The reply comes back whole either way, so existing callers are
    unaffected. With `stream=True` the transport reads it incrementally and
    hands each delta to `on_chunk` as it arrives; the return value is still
    the complete text.

    The note this replaces said to add streaming "when interactive latency
    actually matters to a user, not before". It does now: a branded
    interactive session is what an operator judges the runtime by, and
    waiting in silence for a whole reply is the largest felt difference
    between this and the runtimes beside it.

    Streaming belongs in the foundation rather than behind the seam because
    the model call *is* the foundation (DOCTRINE.md: four tools, one model
    call, two wire formats, the standard library). Delivering that one call
    a piece at a time is a property of the call, not a substitution of it,
    and it stays stdlib-only -- NDJSON for Ollama, SSE for the
    OpenAI-compatible shape, both parsed by iterating the response.

    Bearer credentials are sent only to the initial URL. Redirects, including
    same-origin redirects, omit them; configure the final API endpoint when
    authentication is required.
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
        payload = {"model": model, "messages": messages, "stream": stream, "think": False}
    else:
        name = "OpenAI-compatible API"
        url = f"{host.rstrip('/')}/chat/completions"
        payload = {"model": model, "messages": messages, "stream": stream}

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    if api == "openai":
        # An unset variable means no auth header for local servers. Keep a
        # supplied key on the initial request only: urllib copies ordinary
        # headers across redirects, including to another host or HTTP.
        key = os.environ.get(api_key_env, "")
        if key:
            req.add_unredirected_header("Authorization", f"Bearer {key}")
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            if stream:
                # Returns the joined text; the error branches below still
                # apply, because a streamed call fails the same ways.
                return _read_stream(resp, api=api, on_chunk=on_chunk, name=name, host=host)
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
