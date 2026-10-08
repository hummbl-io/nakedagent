import { cpIndex, cpLen, decodeReplace, pyRepr } from "./pyutil.ts";

// Model chat client (spec section 8): Ollama and OpenAI-compatible wire formats, non-streaming.

export const DEFAULT_HOST = "http://localhost:11434";
export const DEFAULT_API_KEY_ENV = "OPENAI_API_KEY";

export interface Message {
  role: string;
  content: string;
}

export interface LLMOptions {
  api?: string;
  apiKeyEnv?: string;
}

export class LLMError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "LLMError";
  }
}

const REDIRECTS = new Set([301, 302, 303]);

function firstChars(text: string, n: number): string {
  return cpLen(text) <= n ? text : text.slice(0, cpIndex(text, n));
}

/**
 * Sends one chat request and returns the assistant reply text.
 * Bearer credentials go to the initial URL only: redirects are followed by hand (301/302/303 become
 * a GET without body or credentials) so that no later request can carry them.
 * Needs --allow-net, and --allow-env for the API key variable.
 */
export async function chat(
  messages: Message[],
  model: string,
  host: string = DEFAULT_HOST,
  { api = "ollama", apiKeyEnv = DEFAULT_API_KEY_ENV }: LLMOptions = {},
): Promise<string> {
  if (api !== "ollama" && api !== "openai") {
    throw new LLMError(`--api must be one of ollama, openai, got: ${pyRepr(api)}`);
  }
  let parsed: URL | null = null;
  try {
    parsed = new URL(host);
  } catch {
    // handled below
  }
  if (!parsed || (parsed.protocol !== "http:" && parsed.protocol !== "https:") || !parsed.host) {
    throw new LLMError(`--host must be an http:// or https:// URL, got: ${pyRepr(host)}`);
  }

  let name: string;
  let url: string;
  let payload: Record<string, unknown>;
  if (api === "ollama") {
    name = "Ollama";
    url = `${host}/api/chat`;
    payload = { model, messages, stream: false, think: false };
  } else {
    name = "OpenAI-compatible API";
    url = `${host.replace(/\/+$/, "")}/chat/completions`;
    payload = { model, messages, stream: false };
  }
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (api === "openai") {
    const key = Deno.env.get(apiKeyEnv) ?? "";
    if (key) headers.Authorization = `Bearer ${key}`;
  }

  let res: Response;
  try {
    let method = "POST";
    let body: string | undefined = JSON.stringify(payload);
    let hdrs: Record<string, string> = headers;
    for (let hops = 0;; hops++) {
      res = await fetch(url, { method, headers: hdrs, body, redirect: "manual", signal: AbortSignal.timeout(300_000) });
      const location = res.headers.get("location");
      if (!REDIRECTS.has(res.status) || !location || hops >= 10) break;
      await res.arrayBuffer();
      url = new URL(location, url).href;
      method = "GET";
      body = undefined;
      hdrs = {};
    }
  } catch (e) {
    const err = e as Error & { cause?: { code?: string; message?: string } };
    const cause = err.cause ? `: ${err.cause.code ?? err.cause.message}` : "";
    const tip = api === "ollama" ? " Is `ollama serve` running?" : "";
    throw new LLMError(`could not reach ${name} at ${host} (${err.message}${cause}).${tip}`);
  }

  const raw = new Uint8Array(await res.arrayBuffer());
  if (res.status < 200 || res.status >= 300) {
    const hint = api === "openai" && (res.status === 401 || res.status === 403)
      ? ` (check the key in $${apiKeyEnv})`
      : "";
    const detail = firstChars(decodeReplace(raw), 200);
    const reason = [String(res.status), res.statusText].filter(Boolean).join(" ");
    throw new LLMError(`${name} at ${host} returned HTTP ${reason}${hint}${detail ? `: ${detail}` : ""}`);
  }

  let data: unknown;
  try {
    data = JSON.parse(decodeReplace(raw));
  } catch (e) {
    throw new LLMError(`${name} at ${host} returned a non-JSON response: ${(e as Error).message}`);
  }
  const shapeError = () => new LLMError(`unexpected ${name} response shape: ${firstChars(decodeReplace(raw), 300)}`);
  const obj = (v: unknown): Record<string, unknown> | null =>
    v !== null && typeof v === "object" && !Array.isArray(v) ? v as Record<string, unknown> : null;

  let message: Record<string, unknown> | null;
  if (api === "ollama") {
    message = obj(obj(data)?.message);
  } else {
    const choices = obj(data)?.choices;
    message = Array.isArray(choices) && choices.length > 0 ? obj(obj(choices[0])?.message) : null;
  }
  if (!message || !("content" in message)) throw shapeError();
  const content = message.content;
  if (content === null) return "";
  if (typeof content !== "string") throw shapeError();
  return content;
}
