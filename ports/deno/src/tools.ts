import * as path from "node:path";
import { compareCodePoints, cpIndex, cpLen, decodeReplace, decodeStrict, pySplitLines, pyStrip } from "./pyutil.ts";
import { isAllowedShellCommand, shlexSplit } from "./shlex.ts";

/**
 * A tool is (args, content, workspace) => text. Tool-level failures are returned as text
 * (spec section 5); a thrown error is an unexpected failure the loop reports.
 */
export type ToolFunc = (args: string, content: string, workspace: string) => string | Promise<string>;

export const MAX_OUTPUT = 8000;
export const DEFAULT_SHELL_TIMEOUT = 120;
const IS_WIN = Deno.build.os === "windows";

export function truncate(s: string): string {
  const n = cpLen(s);
  if (n <= MAX_OUTPUT) return s;
  return `${s.slice(0, cpIndex(s, MAX_OUTPUT))}\n...[truncated, ${n - MAX_OUTPUT} more chars]`;
}

// ---------------------------------------------------------------- path guard

function splitComponents(p: string): string[] {
  return p.split(IS_WIN ? /[\\/]/ : /\//).filter((c) => c !== "" && c !== ".");
}

function lstatOrNull(p: string): Deno.FileInfo | null {
  try {
    return Deno.lstatSync(p);
  } catch {
    return null;
  }
}

/**
 * Like Python's Path.resolve() (non-strict): symlinks are followed, ".." is applied after the
 * component before it is resolved, and components that do not exist are kept as written.
 */
export function realpathNonStrict(p: string): string {
  const root = path.parse(p).root;
  let cur = root;
  let comps = splitComponents(p.slice(root.length));
  let links = 0;
  while (comps.length > 0) {
    const c = comps.shift()!;
    if (c === "..") {
      if (cur !== root) cur = path.dirname(cur);
      continue;
    }
    const next = path.join(cur, c);
    const st = lstatOrNull(next);
    if (st && st.isSymlink) {
      links++;
      let target: string;
      try {
        target = Deno.readLinkSync(next);
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

function resolveTarget(workspace: string, rel: string): { target: string; ws: string } {
  const ws = realpathNonStrict(path.resolve(workspace));
  const joined = path.isAbsolute(rel) ? rel : ws + path.sep + rel;
  return { target: realpathNonStrict(joined), ws };
}

function isInside(target: string, ws: string): boolean {
  const rel = path.relative(ws, target);
  return rel === "" || (rel !== ".." && !rel.startsWith(".." + path.sep) && !path.isAbsolute(rel));
}

const PROTECTED = new Set([".git", ".nakedagent"]);

function protectedTarget(target: string, ws: string): string | null {
  let first = path.relative(ws, target).split(path.sep)[0];
  if (IS_WIN) first = first.toLowerCase();
  return PROTECTED.has(first) ? first : null;
}

const missingPath = (tool: string) => `Error: ${tool} tool needs a path, e.g. \`\`\`${tool} path/to/file.py\`\`\``;

function isNotFound(e: unknown): boolean {
  return e instanceof Deno.errors.NotFound || e instanceof Deno.errors.NotADirectory;
}

// ---------------------------------------------------------------- read / write / patch

export function toolRead(args: string, _content: string, workspace: string): string {
  const p = pyStrip(args);
  if (p === "") return missingPath("read");
  const { target, ws } = resolveTarget(workspace, p);
  if (!isInside(target, ws)) return `Error: ${p} is outside the workspace.`;
  let st: Deno.FileInfo;
  try {
    st = Deno.statSync(target);
  } catch (e) {
    if (isNotFound(e)) return `Error: ${p} does not exist.`;
    throw e;
  }
  if (st.isDirectory) {
    const names = [...Deno.readDirSync(target)].map((e) => e.name).sort(compareCodePoints);
    return `${p} is a directory:\n${names.join("\n")}`;
  }
  return truncate(decodeReplace(Deno.readFileSync(target)));
}

export function toolWrite(args: string, content: string, workspace: string): string {
  const p = pyStrip(args);
  if (p === "") return missingPath("write");
  const { target, ws } = resolveTarget(workspace, p);
  if (!isInside(target, ws)) return `Error: ${p} is outside the workspace.`;
  const bad = protectedTarget(target, ws);
  if (bad) return `Error: ${p} is in protected directory '${bad}'.`;
  Deno.mkdirSync(path.dirname(target), { recursive: true });
  Deno.writeTextFileSync(target, content);
  return `Wrote ${cpLen(content)} chars to ${p}.`;
}

/** Splits a <<<<<<< SEARCH / ======= / >>>>>>> REPLACE block (spec 5.2). Throws Error if malformed. */
export function splitSearchReplace(block: string): { search: string; replace: string } {
  const lines = pySplitLines(block);
  const find = (from: number, text: string): number => {
    for (let i = from; i < lines.length; i++) if (pyStrip(lines[i]) === text) return i;
    return -1;
  };
  const start = find(0, "<<<<<<< SEARCH");
  const sep = start >= 0 ? find(start + 1, "=======") : -1;
  const end = sep >= 0 ? find(sep + 1, ">>>>>>> REPLACE") : -1;
  if (end < 0) throw new Error("expected <<<<<<< SEARCH / ======= / >>>>>>> REPLACE markers, in that order");
  for (let i = start + 1; i < end; i++) {
    if (pyStrip(lines[i]).startsWith("<<<<<<<")) {
      throw new Error("a second <<<<<<< marker appears before the matching >>>>>>>");
    }
  }
  if (lines.slice(end + 1).some((l) => pyStrip(l) !== "")) {
    throw new Error("unexpected content after >>>>>>> REPLACE; use one patch block per call");
  }
  return { search: lines.slice(start + 1, sep).join("\n"), replace: lines.slice(sep + 1, end).join("\n") };
}

/** Non-overlapping occurrences; an empty needle matches len+1 times, like Python's str.count. */
function countOccurrences(hay: string, needle: string): number {
  if (needle === "") return cpLen(hay) + 1;
  let n = 0;
  for (let i = hay.indexOf(needle); i !== -1; i = hay.indexOf(needle, i + needle.length)) n++;
  return n;
}

export function toolPatch(args: string, content: string, workspace: string): string {
  const p = pyStrip(args);
  if (p === "") return missingPath("patch");
  const { target, ws } = resolveTarget(workspace, p);
  if (!isInside(target, ws)) return `Error: ${p} is outside the workspace.`;
  const bad = protectedTarget(target, ws);
  if (bad) return `Error: ${p} is in protected directory '${bad}'.`;
  try {
    Deno.statSync(target);
  } catch (e) {
    if (isNotFound(e)) return `Error: ${p} does not exist. Use write to create it.`;
    throw e;
  }
  let parts: { search: string; replace: string };
  try {
    parts = splitSearchReplace(content);
  } catch (e) {
    return `Error: malformed patch block (${(e as Error).message}).`;
  }
  const original = decodeStrict(Deno.readFileSync(target));
  if (original === null) return `Error: ${p} is not valid UTF-8; patch refused without changing the file.`;
  const count = countOccurrences(original, parts.search);
  if (count === 0) return `Error: SEARCH text not found in ${p}. It must match exactly, including whitespace.`;
  if (count > 1) return `Error: SEARCH text matches ${count} locations in ${p}; make it more specific.`;
  const at = parts.search === "" ? 0 : original.indexOf(parts.search);
  Deno.writeTextFileSync(target, original.slice(0, at) + parts.replace + original.slice(at + parts.search.length));
  return `Patched ${p}.`;
}

// ---------------------------------------------------------------- shell

export interface ShellPolicy {
  allowShell: boolean;
  allowlist: string[];
  timeoutSeconds: number;
}

function isExecutable(file: string): boolean {
  try {
    const st = Deno.statSync(file);
    if (!st.isFile) return false;
    return IS_WIN || ((st.mode ?? 0o111) & 0o111) !== 0;
  } catch {
    return false;
  }
}

/** shutil.which: a name with a directory part is checked directly, otherwise PATH is searched. */
function which(name: string): string | null {
  if (!name) return null;
  const exts = IS_WIN ? (Deno.env.get("PATHEXT") || ".COM;.EXE;.BAT;.CMD").split(";") : [""];
  const direct = name.includes("/") || (IS_WIN && name.includes("\\"));
  const dirs = direct ? [""] : (Deno.env.get("PATH") || "").split(path.delimiter);
  for (const dir of dirs) {
    const base = direct ? name : path.join(dir || ".", name);
    const candidates = IS_WIN && exts.some((e) => base.toLowerCase().endsWith(e.toLowerCase()))
      ? [base]
      : exts.map((e) => base + e);
    for (const c of candidates) if (isExecutable(c)) return c;
  }
  return null;
}

export async function toolShell(
  args: string,
  content: string,
  workspace: string,
  policy: ShellPolicy,
): Promise<string> {
  let cmd = pyStrip(content);
  if (cmd === "") cmd = pyStrip(args);
  if (cmd === "") return "Error: shell tool got no command.";
  const timeout = policy.timeoutSeconds;
  if (!(timeout > 0)) return "Error: --shell-timeout must be a positive integer.";
  if (!policy.allowShell) {
    return "Error: shell execution blocked (non-interactive shell execution requires --allow-shell).";
  }
  if (!isAllowedShellCommand(cmd, policy.allowlist)) {
    return "Error: shell execution blocked (non-interactive command is not in --shell-allowlist).";
  }
  let argv: string[];
  try {
    argv = shlexSplit(cmd);
  } catch (e) {
    return `Error: malformed command (${(e as Error).message}).`;
  }
  const name = argv[0] ?? "";
  const exe = which(name);
  if (exe === null) {
    return `Error: '${name}' is not an executable on PATH. ` +
      "Non-interactive mode runs programs directly without a shell, so " +
      "shell built-ins (e.g. cmd's echo/dir) and operators (|, &&, ;) " +
      "are not available.";
  }
  if (IS_WIN && /\.(bat|cmd)$/i.test(exe) && argv.slice(1).some((a) => /[&|<>^%!"]/.test(a))) {
    return "Error: shell execution blocked (cmd.exe metacharacters in arguments to a batch file); " +
      "Windows runs .bat/.cmd files through cmd.exe, which would interpret them.";
  }
  // The AbortSignal option of Deno.Command does not reliably stop a running child (observed on Windows),
  // so the timeout kills the child by hand.
  let timedOut = false;
  let out: Deno.CommandOutput;
  let timer: number | undefined;
  try {
    const child = new Deno.Command(exe, {
      args: argv.slice(1),
      cwd: workspace,
      stdin: "null",
      stdout: "piped",
      stderr: "piped",
    }).spawn();
    timer = setTimeout(() => {
      timedOut = true;
      try {
        child.kill("SIGKILL");
      } catch {
        // already exited
      }
    }, timeout * 1000);
    out = await child.output();
  } catch (e) {
    if (timedOut) return `Error: command timed out after ${timeout}s.`;
    return `Error: command execution failed: ${(e as Error).name}: ${(e as Error).message}`;
  } finally {
    if (timer !== undefined) clearTimeout(timer);
  }
  if (timedOut) return `Error: command timed out after ${timeout}s.`;
  const parts = [`(exit ${out.code})`];
  if (out.stdout.length > 0) parts.push(decodeReplace(out.stdout));
  if (out.stderr.length > 0) parts.push(`--- stderr ---\n${decodeReplace(out.stderr)}`);
  return truncate(parts.join("\n"));
}
