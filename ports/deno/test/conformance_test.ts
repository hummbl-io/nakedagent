// Runs the language-neutral vectors in spec/conformance/vectors (spec/conformance/README.md).
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import { assert, assertDeepEqual, assertEquals, assertFalse } from "./assert.ts";
import {
  buildSystemPrompt,
  chat,
  DEFAULT_SHELL_TIMEOUT,
  defaultRegistry,
  newShellPolicy,
  parseToolCalls,
  run,
  toolPatch,
  toolRead,
  toolShell,
  toolWrite,
} from "../mod.ts";
import type { ToolFunc } from "../mod.ts";
import { splitSearchReplace } from "../src/tools.ts";
import { isAllowedShellCommand } from "../src/shlex.ts";

const VECTORS = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
  "..",
  "..",
  "spec",
  "conformance",
  "vectors",
);
const IS_WIN = Deno.build.os === "windows";

// deno-lint-ignore no-explicit-any
type Json = any;

function loadSuite(name: string): Json[] {
  const doc = JSON.parse(Deno.readTextFileSync(path.join(VECTORS, `${name}.json`)));
  assertEquals(doc.suite, name);
  assert(doc.cases.length > 0, `${name}: no cases`);
  return doc.cases;
}

// Vector value encoding (spec section 3).
function decodeText(v: Json): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "string") return v;
  if ("repeat" in v) return v.repeat[0].repeat(v.repeat[1]);
  if ("concat" in v) return v.concat.map(decodeText).join("");
  if ("b64" in v) return new TextDecoder().decode(decodeBytes(v));
  throw new Error("not a text value");
}

function decodeBytes(v: Json): Uint8Array {
  if (v && typeof v === "object" && "b64" in v) return Uint8Array.from(atob(v.b64), (c) => c.charCodeAt(0));
  return new TextEncoder().encode(decodeText(v));
}

function writeFiles(dir: string, files: Record<string, Json> = {}) {
  for (const [rel, v] of Object.entries(files)) {
    const p = path.join(dir, ...rel.split("/"));
    Deno.mkdirSync(path.dirname(p), { recursive: true });
    Deno.writeFileSync(p, decodeBytes(v));
  }
}

function newWorkspace(files: Record<string, Json> = {}): string {
  const root = Deno.realPathSync(Deno.makeTempDirSync({ prefix: "ng-deno-" }));
  const ws = path.join(root, "ws");
  Deno.mkdirSync(ws);
  writeFiles(ws, files);
  return ws;
}

// Workspace plus, for cases with `outside` or `symlinks`, the sibling `outside` directory and the symlink
// fixtures. `skip` is set if symlinks cannot be created here.
function newCaseRoot(c: Json): { ws: string; outside: string | null; skip: boolean } {
  const ws = newWorkspace(c.files);
  if (!("outside" in c) && !("symlinks" in c)) return { ws, outside: null, skip: false };
  const outside = path.join(path.dirname(ws), "outside");
  Deno.mkdirSync(outside);
  writeFiles(outside, c.outside);
  for (const [rel, target] of Object.entries<string>(c.symlinks ?? {})) {
    const lp = path.join(ws, ...rel.split("/"));
    Deno.mkdirSync(path.dirname(lp), { recursive: true });
    try {
      let isDir = false;
      try {
        isDir = Deno.statSync(path.resolve(path.dirname(lp), target)).isDirectory;
      } catch {
        // dangling target
      }
      Deno.symlinkSync(target.split("/").join(path.sep), lp, { type: isDir ? "dir" : "file" });
    } catch {
      return { ws, outside, skip: true };
    }
  }
  return { ws, outside, skip: false };
}

function snapshot(root: string): Record<string, Uint8Array> {
  const out: Record<string, Uint8Array> = {};
  const walk = (dir: string) => {
    for (const e of Deno.readDirSync(dir)) {
      const p = path.join(dir, e.name);
      if (e.isSymlink) continue; // fixtures, not tool output
      if (e.isDirectory) walk(p);
      else {
        const rel = path.relative(root, p).split(path.sep).join("/");
        if (!rel.startsWith(".nakedagent/")) out[rel] = Deno.readFileSync(p);
      }
    }
  };
  walk(root);
  return out;
}

function expectFiles(dir: string, expected: Record<string, Json>) {
  const want: Record<string, Uint8Array> = {};
  for (const [rel, v] of Object.entries(expected)) want[rel] = decodeBytes(v);
  assertDeepEqual(snapshot(dir), want);
}

// NAKEDAGENT_FORCE_POSIX_VECTORS=1 runs the POSIX-only vectors on Windows too (useful with Git Bash tools on PATH).
const FORCE_POSIX = Deno.env.get("NAKEDAGENT_FORCE_POSIX_VECTORS") === "1";
const skipPosix = (c: Json) => IS_WIN && !FORCE_POSIX && c.requires === "posix";

function define(suite: string, c: Json, fn: () => void | Promise<void>, extraIgnore = false) {
  Deno.test({ name: `${suite}: ${c.name}`, ignore: skipPosix(c) || extraIgnore, fn });
}

for (const c of loadSuite("toolcall")) {
  define("toolcall", c, () => {
    assertDeepEqual(
      parseToolCalls(decodeText(c.input)),
      c.expect.map((e: Json) => ({
        tool: decodeText(e.tool),
        args: decodeText(e.args),
        content: decodeText(e.content),
      })),
    );
  });
}

for (const c of loadSuite("patch_split")) {
  define("patch_split", c, () => {
    let got;
    try {
      got = splitSearchReplace(decodeText(c.input));
    } catch (e) {
      assert("error" in c.expect, `unexpected error ${(e as Error).message}`);
      assertEquals((e as Error).message, c.expect.error);
      return;
    }
    assertFalse("error" in c.expect, "expected an error");
    assertDeepEqual(got, { search: decodeText(c.expect.search), replace: decodeText(c.expect.replace) });
  });
}

const FS_TOOLS: Record<string, ToolFunc> = { read: toolRead, write: toolWrite, patch: toolPatch };
for (const c of loadSuite("fs_tools")) {
  define("fs_tools", c, async () => {
    const { ws, outside, skip } = newCaseRoot(c);
    if (skip) {
      console.warn(`skipped (cannot create symlinks here): ${c.name}`);
      return;
    }
    const got = await FS_TOOLS[c.tool](c.args ?? "", decodeText(c.content), ws);
    assertEquals(got, decodeText(c.expect.result));
    expectFiles(ws, c.expect.files);
    if (outside) expectFiles(outside, c.expect.outside_files);
  });
}

for (const c of loadSuite("shell_allowlist")) {
  define("shell_allowlist", c, () => {
    assertEquals(isAllowedShellCommand(c.command, c.allowlist), c.expect);
  });
}

for (const c of loadSuite("shell_policy")) {
  define("shell_policy", c, async () => {
    const policy = {
      allowShell: c.allow_shell ?? false,
      allowlist: c.shell_allowlist ?? [],
      timeoutSeconds: c.shell_timeout ?? DEFAULT_SHELL_TIMEOUT,
    };
    const ws = Deno.realPathSync(Deno.makeTempDirSync({ prefix: "ng-deno-" }));
    assertEquals(await toolShell(c.args ?? "", decodeText(c.content), ws, policy), decodeText(c.expect));
  });
}

for (const c of loadSuite("prompt")) {
  define("prompt", c, () => {
    const reg = defaultRegistry(newShellPolicy());
    for (const n of c.extra_tools_without_usage ?? []) reg.set(n, { fn: () => "" });
    assertEquals(buildSystemPrompt(reg), decodeText(c.expect));
  });
}

// ---------------------------------------------------------------- llm_wire and loop

interface Recorded {
  method: string;
  path: string;
  body: unknown;
  authorization: string | null;
}

// Scripted HTTP server: replays `script` in order and records every request.
function scripted(script: Json[]) {
  const reqs: Recorded[] = [];
  const pending = [...script];
  const server = Deno.serve({ hostname: "127.0.0.1", port: 0, onListen() {} }, async (req) => {
    const raw = await req.text();
    let body: unknown = null;
    if (raw) {
      try {
        body = JSON.parse(raw);
      } catch {
        body = { __raw__: raw };
      }
    }
    const u = new URL(req.url);
    reqs.push({
      method: req.method,
      path: u.pathname + u.search,
      body,
      authorization: req.headers.get("authorization"),
    });
    const step = pending.shift() ?? { status: 500, body: "script exhausted" };
    return new Response(typeof step.body === "string" ? step.body : JSON.stringify(step.body), {
      status: step.status ?? 200,
      headers: step.headers ?? {},
    });
  });
  const addr = `127.0.0.1:${server.addr.port}`;
  return { reqs, addr, url: `http://${addr}`, close: () => server.shutdown() };
}

function closedAddress(): string {
  const l = Deno.listen({ hostname: "127.0.0.1", port: 0 });
  const addr = `127.0.0.1:${(l.addr as Deno.NetAddr).port}`;
  l.close();
  return addr;
}

async function withEnv<T>(env: Record<string, string>, fn: () => Promise<T>): Promise<T> {
  const names = ["OPENAI_API_KEY", "CUSTOM_KEY", ...Object.keys(env)];
  const saved = Object.fromEntries(names.map((n) => [n, Deno.env.get(n)]));
  for (const n of ["OPENAI_API_KEY", "CUSTOM_KEY"]) Deno.env.delete(n);
  for (const [k, v] of Object.entries(env)) Deno.env.set(k, v);
  try {
    return await fn();
  } finally {
    for (const [n, v] of Object.entries(saved)) {
      if (v === undefined) Deno.env.delete(n);
      else Deno.env.set(n, v);
    }
  }
}

function checkRequest(got: Recorded, want: Json) {
  assertEquals(got.method, want.method);
  assertEquals(got.path, want.path);
  assertDeepEqual(got.body, want.body);
  assertEquals(got.authorization, want.authorization);
}

for (const c of loadSuite("llm_wire")) {
  define("llm_wire", c, () =>
    withEnv(c.env ?? {}, async () => {
      const opts: { api: string; apiKeyEnv?: string } = { api: c.api };
      if (c.api_key_env) opts.apiKeyEnv = c.api_key_env;
      let reply: string | undefined;
      let error: Error | undefined;
      let reqs: Recorded[] = [];
      let addr = "";
      let srv: Awaited<ReturnType<typeof scripted>> | null = null;
      try {
        let host: string;
        if (c.host !== undefined) {
          host = c.host;
        } else if (c.unreachable) {
          addr = closedAddress();
          host = `http://${addr}`;
        } else {
          srv = await scripted(c.server ?? []);
          addr = srv.addr;
          host = srv.url + (c.host_path ?? "");
        }
        try {
          reply = await chat(c.messages, c.model, host, opts);
        } catch (e) {
          error = e as Error;
        }
        reqs = srv ? srv.reqs : [];
      } finally {
        if (srv) await srv.close();
      }

      if (c.lenient_requests) {
        checkRequest(reqs[0], c.expect.first_request);
        for (const later of reqs.slice(1)) {
          assertEquals(later.authorization, null, `credentials forwarded to ${later.path}`);
        }
        return;
      }
      assertEquals(reqs.length, c.expect.requests.length);
      reqs.forEach((r, i) => checkRequest(r, c.expect.requests[i]));
      if ("reply" in c.expect) {
        if (error) throw error;
        assertEquals(reply, c.expect.reply);
        return;
      }
      assert(error !== undefined, `expected an error, got reply ${JSON.stringify(reply)}`);
      const msg = addr ? error.message.replaceAll(addr, "HOST:PORT") : error.message;
      for (const sub of c.expect.error_contains) {
        assert(msg.includes(sub), `${JSON.stringify(msg)} lacks ${JSON.stringify(sub)}`);
      }
      for (const sub of c.expect.error_absent ?? []) {
        assertFalse(msg.includes(sub), `${JSON.stringify(msg)} contains ${JSON.stringify(sub)}`);
      }
    }));
}

for (const c of loadSuite("loop")) {
  define("loop", c, async () => {
    const script = c.replies.map((r: string) => ({ status: 200, body: { message: { content: r } } }));
    const ws = newWorkspace(c.files);
    const srv = await scripted(script);
    try {
      await run(c.prompt, {
        model: "test-model",
        host: srv.url,
        workspace: ws,
        out: () => {},
        shell: {
          allowShell: c.allow_shell ?? false,
          allowlist: c.shell_allowlist ?? [],
          timeoutSeconds: DEFAULT_SHELL_TIMEOUT,
        },
      });
      assertEquals(srv.reqs.length, c.expect.request_count);
      // deno-lint-ignore no-explicit-any
      const last = (srv.reqs.at(-1)!.body as any).messages.map((m: Json) => ({
        role: m.role,
        content: m.role === "system" ? "$SYSTEM" : m.content,
      }));
      assertDeepEqual(
        last,
        c.expect.last_request_messages.map((m: Json) => ({ role: m.role, content: decodeText(m.content) })),
      );
      expectFiles(ws, c.expect.files);
    } finally {
      await srv.close();
    }
  });
}
