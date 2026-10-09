import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import os from 'node:os';
import {
  pyStrip, pySplitLines, cpLen, cpIndex, decodeReplace, decodeStrict,
} from './pyutil.js';
import { shlexSplit, isAllowedShellCommand } from './shlex.js';

// A tool is (args, content, workspace) => string. Tool-level failures are returned as text
// (spec section 5); a thrown error is an unexpected failure the loop reports.

export const MAX_OUTPUT = 8000;
export const DEFAULT_SHELL_TIMEOUT = 120;
const IS_WIN = process.platform === 'win32';

export function truncate(s) {
  const n = cpLen(s);
  if (n <= MAX_OUTPUT) return s;
  return `${s.slice(0, cpIndex(s, MAX_OUTPUT))}\n...[truncated, ${n - MAX_OUTPUT} more chars]`;
}

// ---------------------------------------------------------------- path guard

function splitComponents(p) {
  return p.split(IS_WIN ? /[\\/]/ : /\//).filter((c) => c !== '' && c !== '.');
}

// Like Python's Path.resolve() (non-strict): symlinks are followed, ".." is applied after the
// component before it is resolved, and components that do not exist are kept as written.
export function realpathNonStrict(p) {
  const root = path.parse(p).root;
  let cur = root;
  let comps = splitComponents(p.slice(root.length));
  let links = 0;
  while (comps.length > 0) {
    const c = comps.shift();
    if (c === '..') {
      if (cur !== root) cur = path.dirname(cur);
      continue;
    }
    const next = path.join(cur, c);
    let st = null;
    try {
      st = fs.lstatSync(next);
    } catch {
      /* does not exist */
    }
    if (st && st.isSymbolicLink()) {
      links++;
      let target;
      try {
        target = fs.readlinkSync(next);
      } catch {
        cur = next;
        continue;
      }
      if (links > 255) {
        cur = next;
        continue;
      }
      if (path.isAbsolute(target)) {
        const troot = path.parse(target).root;
        cur = /^[\\/]$/.test(troot) ? path.parse(cur).root : troot;
        comps = [...splitComponents(target.slice(troot.length)), ...comps];
      } else {
        comps = [...splitComponents(target), ...comps];
      }
      continue;
    }
    cur = next;
  }
  return cur;
}

function resolveTarget(workspace, rel) {
  const ws = realpathNonStrict(path.resolve(workspace));
  const joined = path.isAbsolute(rel) ? rel : ws + path.sep + rel;
  return { target: realpathNonStrict(joined), ws };
}

function isInside(target, ws) {
  const rel = path.relative(ws, target);
  return rel === '' || (rel !== '..' && !rel.startsWith('..' + path.sep) && !path.isAbsolute(rel));
}

const PROTECTED = new Set(['.git', '.nakedagent']);

function protectedTarget(target, ws) {
  let first = path.relative(ws, target).split(path.sep)[0];
  if (IS_WIN) first = first.toLowerCase();
  return PROTECTED.has(first) ? first : null;
}

const missingPath = (tool) => `Error: ${tool} tool needs a path, e.g. \`\`\`${tool} path/to/file.py\`\`\``;

// ---------------------------------------------------------------- read / write / patch

export function toolRead(args, _content, workspace) {
  const p = pyStrip(args);
  if (p === '') return missingPath('read');
  const { target, ws } = resolveTarget(workspace, p);
  if (!isInside(target, ws)) return `Error: ${p} is outside the workspace.`;
  let st;
  try {
    st = fs.statSync(target);
  } catch (e) {
    if (e.code === 'ENOENT' || e.code === 'ENOTDIR') return `Error: ${p} does not exist.`;
    throw e;
  }
  if (st.isDirectory()) {
    const names = fs.readdirSync(target).sort((a, b) => Buffer.compare(Buffer.from(a), Buffer.from(b)));
    return `${p} is a directory:\n${names.join('\n')}`;
  }
  return truncate(decodeReplace(fs.readFileSync(target)));
}

export function toolWrite(args, content, workspace) {
  const p = pyStrip(args);
  if (p === '') return missingPath('write');
  const { target, ws } = resolveTarget(workspace, p);
  if (!isInside(target, ws)) return `Error: ${p} is outside the workspace.`;
  const bad = protectedTarget(target, ws);
  if (bad) return `Error: ${p} is in protected directory '${bad}'.`;
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.writeFileSync(target, content, 'utf8');
  return `Wrote ${cpLen(content)} chars to ${p}.`;
}

// Splits a <<<<<<< SEARCH / ======= / >>>>>>> REPLACE block (spec 5.2). Throws Error on a malformed block.
export function splitSearchReplace(block) {
  const lines = pySplitLines(block);
  const find = (from, text) => {
    for (let i = from; i < lines.length; i++) if (pyStrip(lines[i]) === text) return i;
    return -1;
  };
  const start = find(0, '<<<<<<< SEARCH');
  const sep = start >= 0 ? find(start + 1, '=======') : -1;
  const end = sep >= 0 ? find(sep + 1, '>>>>>>> REPLACE') : -1;
  if (end < 0) throw new Error('expected <<<<<<< SEARCH / ======= / >>>>>>> REPLACE markers, in that order');
  for (let i = start + 1; i < end; i++) {
    if (pyStrip(lines[i]).startsWith('<<<<<<<')) {
      throw new Error('a second <<<<<<< marker appears before the matching >>>>>>>');
    }
  }
  if (lines.slice(end + 1).some((l) => pyStrip(l) !== '')) {
    throw new Error('unexpected content after >>>>>>> REPLACE; use one patch block per call');
  }
  return { search: lines.slice(start + 1, sep).join('\n'), replace: lines.slice(sep + 1, end).join('\n') };
}

// Non-overlapping occurrences; an empty needle matches len+1 times, like Python's str.count.
function countOccurrences(hay, needle) {
  if (needle === '') return cpLen(hay) + 1;
  let n = 0;
  for (let i = hay.indexOf(needle); i !== -1; i = hay.indexOf(needle, i + needle.length)) n++;
  return n;
}

export function toolPatch(args, content, workspace) {
  const p = pyStrip(args);
  if (p === '') return missingPath('patch');
  const { target, ws } = resolveTarget(workspace, p);
  if (!isInside(target, ws)) return `Error: ${p} is outside the workspace.`;
  const bad = protectedTarget(target, ws);
  if (bad) return `Error: ${p} is in protected directory '${bad}'.`;
  if (!fs.existsSync(target)) return `Error: ${p} does not exist. Use write to create it.`;
  let parts;
  try {
    parts = splitSearchReplace(content);
  } catch (e) {
    return `Error: malformed patch block (${e.message}).`;
  }
  const original = decodeStrict(fs.readFileSync(target));
  if (original === null) return `Error: ${p} is not valid UTF-8; patch refused without changing the file.`;
  const count = countOccurrences(original, parts.search);
  if (count === 0) return `Error: SEARCH text not found in ${p}. It must match exactly, including whitespace.`;
  if (count > 1) return `Error: SEARCH text matches ${count} locations in ${p}; make it more specific.`;
  const at = parts.search === '' ? 0 : original.indexOf(parts.search);
  fs.writeFileSync(target, original.slice(0, at) + parts.replace + original.slice(at + parts.search.length), 'utf8');
  return `Patched ${p}.`;
}

// ---------------------------------------------------------------- shell

function isExecutable(file) {
  try {
    if (!fs.statSync(file).isFile()) return false;
    if (!IS_WIN) fs.accessSync(file, fs.constants.X_OK);
    return true;
  } catch {
    return false;
  }
}

// shutil.which: a name with a directory part is checked directly, otherwise PATH is searched.
function which(name) {
  if (!name) return null;
  const exts = IS_WIN ? (process.env.PATHEXT || '.COM;.EXE;.BAT;.CMD').split(';') : [''];
  const direct = name.includes('/') || (IS_WIN && name.includes('\\'));
  const dirs = direct ? [''] : (process.env.PATH || '').split(path.delimiter);
  for (const dir of dirs) {
    const base = direct ? name : path.join(dir || '.', name);
    const candidates = IS_WIN && exts.some((e) => base.toLowerCase().endsWith(e.toLowerCase()))
      ? [base]
      : exts.map((e) => base + e);
    for (const c of candidates) if (isExecutable(c)) return c;
  }
  return null;
}

/** policy: { allowShell: boolean, allowlist: string[], timeoutSeconds: number } */
export function toolShell(args, content, workspace, policy) {
  let cmd = pyStrip(content);
  if (cmd === '') cmd = pyStrip(args);
  if (cmd === '') return 'Error: shell tool got no command.';
  const timeout = policy.timeoutSeconds;
  if (!(timeout > 0)) return 'Error: --shell-timeout must be a positive integer.';
  if (!policy.allowShell) {
    return 'Error: shell execution blocked (non-interactive shell execution requires --allow-shell).';
  }
  if (!isAllowedShellCommand(cmd, policy.allowlist)) {
    return 'Error: shell execution blocked (non-interactive command is not in --shell-allowlist).';
  }
  let argv;
  try {
    argv = shlexSplit(cmd);
  } catch (e) {
    return `Error: malformed command (${e.message}).`;
  }
  const name = argv[0] ?? '';
  const exe = which(name);
  if (exe === null) {
    return (
      `Error: '${name}' is not an executable on PATH. ` +
      'Non-interactive mode runs programs directly without a shell, so ' +
      "shell built-ins (e.g. cmd's echo/dir) and operators (|, &&, ;) " +
      'are not available.'
    );
  }
  if (IS_WIN && /\.(bat|cmd)$/i.test(exe) && argv.slice(1).some((a) => /[&|<>^%!"]/.test(a))) {
    return (
      'Error: shell execution blocked (cmd.exe metacharacters in arguments to a batch file); ' +
      'Windows runs .bat/.cmd files through cmd.exe, which would interpret them.'
    );
  }
  const r = spawnSync(exe, argv.slice(1), {
    cwd: workspace,
    stdio: ['ignore', 'pipe', 'pipe'],
    timeout: timeout * 1000,
    maxBuffer: 256 * 1024 * 1024,
    windowsHide: true,
  });
  if (r.error && r.error.code === 'ETIMEDOUT') return `Error: command timed out after ${timeout}s.`;
  if (r.error) return `Error: command execution failed: ${r.error.name}: ${r.error.message}`;
  const code = r.status ?? -(os.constants.signals[r.signal] ?? 1);
  const parts = [`(exit ${code})`];
  if (r.stdout && r.stdout.length > 0) parts.push(decodeReplace(r.stdout));
  if (r.stderr && r.stderr.length > 0) parts.push(`--- stderr ---\n${decodeReplace(r.stderr)}`);
  return truncate(parts.join('\n'));
}
