// Runs the language-neutral vectors in spec/conformance/vectors (spec/conformance/README.md).
import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import {
  parseToolCalls, toolRead, toolWrite, toolPatch, toolShell, buildSystemPrompt, defaultRegistry,
  newShellPolicy, chat, run, DEFAULT_SHELL_TIMEOUT,
} from '../src/index.js';
import { splitSearchReplace } from '../src/tools.js';
import { isAllowedShellCommand } from '../src/shlex.js';

const VECTORS = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..', '..', 'spec', 'conformance', 'vectors');
const IS_WIN = process.platform === 'win32';

function loadSuite(name) {
  const doc = JSON.parse(fs.readFileSync(path.join(VECTORS, `${name}.json`), 'utf8'));
  assert.equal(doc.suite, name);
  assert.ok(doc.cases.length > 0);
  return doc.cases;
}

// Vector value encoding (spec section 3).
function decodeText(v) {
  if (v === null || v === undefined) return '';
  if (typeof v === 'string') return v;
  if ('repeat' in v) return v.repeat[0].repeat(v.repeat[1]);
  if ('concat' in v) return v.concat.map(decodeText).join('');
  if ('b64' in v) return Buffer.from(v.b64, 'base64').toString('utf8');
  throw new Error('not a text value');
}
function decodeBytes(v) {
  if (v && typeof v === 'object' && 'b64' in v) return Buffer.from(v.b64, 'base64');
  return Buffer.from(decodeText(v), 'utf8');
}

function newWorkspace(files = {}) {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'ng-node-')));
  const ws = path.join(root, 'ws');
  fs.mkdirSync(ws);
  for (const [rel, v] of Object.entries(files)) {
    const p = path.join(ws, ...rel.split('/'));
    fs.mkdirSync(path.dirname(p), { recursive: true });
    fs.writeFileSync(p, decodeBytes(v));
  }
  return ws;
}

function snapshot(ws) {
  const out = {};
  const walk = (dir) => {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      const p = path.join(dir, e.name);
      if (e.isDirectory()) walk(p);
      else {
        const rel = path.relative(ws, p).split(path.sep).join('/');
        if (!rel.startsWith('.nakedagent/')) out[rel] = fs.readFileSync(p);
      }
    }
  };
  walk(ws);
  return out;
}

function expectFiles(ws, expected) {
  const want = {};
  for (const [rel, v] of Object.entries(expected)) want[rel] = decodeBytes(v);
  assert.deepEqual(snapshot(ws), want);
}

const skipPosix = (c) => IS_WIN && c.requires === 'posix';

for (const c of loadSuite('toolcall')) {
  test(`toolcall: ${c.name}`, () => {
    assert.deepEqual(parseToolCalls(decodeText(c.input)), c.expect.map((e) => ({
      tool: decodeText(e.tool), args: decodeText(e.args), content: decodeText(e.content),
    })));
  });
}

for (const c of loadSuite('patch_split')) {
  test(`patch_split: ${c.name}`, () => {
    let got;
    try {
      got = splitSearchReplace(decodeText(c.input));
    } catch (e) {
      assert.ok('error' in c.expect, `unexpected error ${e.message}`);
      assert.equal(e.message, c.expect.error);
      return;
    }
    assert.ok(!('error' in c.expect), 'expected an error');
    assert.deepEqual(got, { search: decodeText(c.expect.search), replace: decodeText(c.expect.replace) });
  });
}

const FS_TOOLS = { read: toolRead, write: toolWrite, patch: toolPatch };
for (const c of loadSuite('fs_tools')) {
  test(`fs_tools: ${c.name}`, () => {
    const ws = newWorkspace(c.files);
    const got = FS_TOOLS[c.tool](c.args ?? '', decodeText(c.content), ws);
    assert.equal(got, decodeText(c.expect.result));
    expectFiles(ws, c.expect.files);
  });
}

for (const c of loadSuite('shell_allowlist')) {
  test(`shell_allowlist: ${c.name}`, () => {
    assert.equal(isAllowedShellCommand(c.command, c.allowlist), c.expect);
  });
}

for (const c of loadSuite('shell_policy')) {
  test(`shell_policy: ${c.name}`, { skip: skipPosix(c) }, () => {
    const policy = {
      allowShell: c.allow_shell ?? false,
      allowlist: c.shell_allowlist ?? [],
      timeoutSeconds: c.shell_timeout ?? DEFAULT_SHELL_TIMEOUT,
    };
    const ws = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'ng-node-')));
    assert.equal(toolShell(c.args ?? '', decodeText(c.content), ws, policy), decodeText(c.expect));
  });
}

for (const c of loadSuite('prompt')) {
  test(`prompt: ${c.name}`, () => {
    const reg = defaultRegistry(newShellPolicy());
    for (const n of c.extra_tools_without_usage ?? []) reg.set(n, { fn: () => '' });
    assert.equal(buildSystemPrompt(reg), decodeText(c.expect));
  });
}

// ---------------------------------------------------------------- llm_wire and loop

// Scripted HTTP server: replays `script` in order and records every request.
async function scripted(script) {
  const reqs = [];
  const pending = [...script];
  const server = http.createServer((req, res) => {
    const chunks = [];
    req.on('data', (d) => chunks.push(d));
    req.on('end', () => {
      const raw = Buffer.concat(chunks).toString('utf8');
      let body = null;
      if (raw) {
        try {
          body = JSON.parse(raw);
        } catch {
          body = { __raw__: raw };
        }
      }
      reqs.push({ method: req.method, path: req.url, body, authorization: req.headers.authorization ?? null });
      const step = pending.shift() ?? { status: 500, body: 'script exhausted' };
      res.statusCode = step.status ?? 200;
      for (const [k, v] of Object.entries(step.headers ?? {})) res.setHeader(k, v);
      res.end(typeof step.body === 'string' ? step.body : JSON.stringify(step.body));
    });
  });
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const addr = `127.0.0.1:${server.address().port}`;
  return { reqs, addr, url: `http://${addr}`, close: () => new Promise((r) => server.close(r)) };
}

async function closedAddress() {
  const s = http.createServer();
  await new Promise((r) => s.listen(0, '127.0.0.1', r));
  const addr = `127.0.0.1:${s.address().port}`;
  await new Promise((r) => s.close(r));
  return addr;
}

async function withEnv(env, fn) {
  const names = ['OPENAI_API_KEY', 'CUSTOM_KEY', ...Object.keys(env)];
  const saved = Object.fromEntries(names.map((n) => [n, process.env[n]]));
  for (const n of ['OPENAI_API_KEY', 'CUSTOM_KEY']) delete process.env[n];
  Object.assign(process.env, env);
  try {
    return await fn();
  } finally {
    for (const [n, v] of Object.entries(saved)) {
      if (v === undefined) delete process.env[n];
      else process.env[n] = v;
    }
  }
}

function checkRequest(got, want) {
  assert.equal(got.method, want.method);
  assert.equal(got.path, want.path);
  assert.deepEqual(got.body, want.body);
  assert.equal(got.authorization, want.authorization);
}

for (const c of loadSuite('llm_wire')) {
  test(`llm_wire: ${c.name}`, async () => {
    await withEnv(c.env ?? {}, async () => {
      const opts = { api: c.api };
      if (c.api_key_env) opts.apiKeyEnv = c.api_key_env;
      let reply;
      let error;
      let reqs = [];
      let addr = '';
      let srv = null;
      try {
        let host;
        if (c.host !== undefined) {
          host = c.host;
        } else if (c.unreachable) {
          addr = await closedAddress();
          host = `http://${addr}`;
        } else {
          srv = await scripted(c.server ?? []);
          addr = srv.addr;
          host = srv.url + (c.host_path ?? '');
        }
        try {
          reply = await chat(c.messages, c.model, host, opts);
        } catch (e) {
          error = e;
        }
        reqs = srv ? srv.reqs : [];
      } finally {
        if (srv) await srv.close();
      }

      if (c.lenient_requests) {
        checkRequest(reqs[0], c.expect.first_request);
        for (const later of reqs.slice(1)) assert.equal(later.authorization, null, `credentials forwarded to ${later.path}`);
        return;
      }
      assert.equal(reqs.length, c.expect.requests.length);
      reqs.forEach((r, i) => checkRequest(r, c.expect.requests[i]));
      if ('reply' in c.expect) {
        assert.ifError(error);
        assert.equal(reply, c.expect.reply);
        return;
      }
      assert.ok(error, `expected an error, got reply ${JSON.stringify(reply)}`);
      const msg = addr ? error.message.replaceAll(addr, 'HOST:PORT') : error.message;
      for (const sub of c.expect.error_contains) assert.ok(msg.includes(sub), `${JSON.stringify(msg)} lacks ${JSON.stringify(sub)}`);
      for (const sub of c.expect.error_absent ?? []) assert.ok(!msg.includes(sub), `${JSON.stringify(msg)} contains ${JSON.stringify(sub)}`);
    });
  });
}

for (const c of loadSuite('loop')) {
  test(`loop: ${c.name}`, async () => {
    const script = c.replies.map((r) => ({ status: 200, body: { message: { content: r } } }));
    const ws = newWorkspace(c.files);
    const srv = await scripted(script);
    try {
      await run(c.prompt, {
        model: 'test-model',
        host: srv.url,
        workspace: ws,
        out: () => {},
        shell: { allowShell: c.allow_shell ?? false, allowlist: c.shell_allowlist ?? [], timeoutSeconds: DEFAULT_SHELL_TIMEOUT },
      });
      assert.equal(srv.reqs.length, c.expect.request_count);
      const last = srv.reqs.at(-1).body.messages.map((m) => ({
        role: m.role, content: m.role === 'system' ? '$SYSTEM' : m.content,
      }));
      assert.deepEqual(last, c.expect.last_request_messages.map((m) => ({ role: m.role, content: decodeText(m.content) })));
      expectFiles(ws, c.expect.files);
    } finally {
      await srv.close();
    }
  });
}
