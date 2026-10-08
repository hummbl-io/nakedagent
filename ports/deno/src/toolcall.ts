import { pyRstrip, pyStrip } from "./pyutil.ts";

// Fenced tool-call parser (spec section 4).

export interface ToolCall {
  tool: string;
  args: string;
  content: string;
}

const OPEN_RE = /^```([A-Za-z0-9_]+)(?: ([^\n`]*))?$/;

/** Length of a column-0 all-backtick line (trailing whitespace allowed), else 0. */
function bareTicks(line: string): number {
  const s = pyRstrip(line);
  if (s === "") return 0;
  for (let i = 0; i < s.length; i++) if (s[i] !== "`") return 0;
  return s.length;
}

/** Length of the opening backtick run of a column-0 fence marker (>= 3), else 0. */
function fenceTicks(line: string): number {
  let n = 0;
  while (n < line.length && line[n] === "`") n++;
  return n >= 3 ? n : 0;
}

export function parseToolCalls(text: string): ToolCall[] {
  const lines = text.replaceAll("\r\n", "\n").split("\n");
  const calls: ToolCall[] = [];
  let i = 0;
  const n = lines.length;
  while (i < n) {
    const m = OPEN_RE.exec(lines[i]);
    if (!m) {
      i++;
      continue;
    }
    const tool = m[1];
    const args = pyStrip(m[2] ?? "");
    const body: string[] = [];
    const stack = [3];
    i++;
    let closed = false;
    while (i < n) {
      const line = lines[i];
      const bare = bareTicks(line);
      if (bare > 0) {
        if (bare === stack[stack.length - 1]) {
          stack.pop();
          i++;
          if (stack.length === 0) {
            closed = true;
            break;
          }
          body.push(line);
          continue;
        }
        body.push(line);
        i++;
        continue;
      }
      const ticks = fenceTicks(line);
      if (ticks > 0) stack.push(ticks);
      body.push(line);
      i++;
    }
    if (closed) {
      calls.push({ tool, args, content: body.join("\n") });
    } else {
      calls.push({ tool: "__refused__", args: tool, content: `unclosed fence for '${tool}'; call refused` });
    }
  }
  return calls;
}
