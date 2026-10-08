import { pyStrip } from "./pyutil.ts";

/**
 * POSIX word splitting as Python's shlex.split defaults (spec section 6).
 * Throws Error on an unterminated quote or a trailing backslash.
 */
export function shlexSplit(s: string): string[] {
  const tokens: string[] = [];
  let cur = "";
  let inTok = false;
  const rs = Array.from(s);
  for (let i = 0; i < rs.length; i++) {
    const c = rs[i];
    if (c === " " || c === "\t" || c === "\r" || c === "\n") {
      if (inTok) {
        tokens.push(cur);
        cur = "";
        inTok = false;
      }
    } else if (c === "\\") {
      if (i + 1 >= rs.length) throw new Error("No escaped character");
      cur += rs[++i];
      inTok = true;
    } else if (c === "'") {
      inTok = true;
      let j = i + 1;
      while (j < rs.length && rs[j] !== "'") cur += rs[j++];
      if (j >= rs.length) throw new Error("No closing quotation");
      i = j;
    } else if (c === '"') {
      inTok = true;
      let j = i + 1;
      for (;;) {
        if (j >= rs.length) throw new Error("No closing quotation");
        const d = rs[j];
        if (d === '"') break;
        if (d === "\\") {
          if (j + 1 >= rs.length) throw new Error("No escaped character");
          const nx = rs[j + 1];
          cur += nx === '"' || nx === "\\" ? nx : "\\" + nx;
          j += 2;
          continue;
        }
        cur += d;
        j++;
      }
      i = j;
    } else {
      cur += c;
      inTok = true;
    }
  }
  if (inTok) tokens.push(cur);
  return tokens;
}

/** Token-prefix match against the allowlist; anything that fails to split never matches. */
export function isAllowedShellCommand(cmd: string, allowlist: string[] | undefined): boolean {
  if (!allowlist || allowlist.length === 0) return false;
  let argv: string[];
  try {
    argv = shlexSplit(pyStrip(cmd));
  } catch {
    return false;
  }
  if (argv.length === 0) return false;
  for (const pattern of allowlist) {
    const item = pyStrip(pattern);
    if (item === "") continue;
    let pat: string[];
    try {
      pat = shlexSplit(item);
    } catch {
      continue;
    }
    if (pat.length === 0 || argv.length < pat.length) continue;
    if (pat.every((tok, k) => argv[k] === tok)) return true;
  }
  return false;
}
