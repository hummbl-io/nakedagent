// Differential-test harness (spec/conformance/differential):
//   deno run --allow-read tools/diff-harness.ts cases.jsonl > out.jsonl
import { parseToolCalls } from "../src/toolcall.ts";
import { splitSearchReplace, truncate } from "../src/tools.ts";
import { isAllowedShellCommand } from "../src/shlex.ts";
import { decodeReplace, pyStrip } from "../src/pyutil.ts";

const out: string[] = [];
for (const line of Deno.readTextFileSync(Deno.args[0]).split("\n")) {
  if (!line) continue;
  const c = JSON.parse(line);
  let r: unknown;
  switch (c.op) {
    case "toolcall":
      r = parseToolCalls(c.input).map((x) => [x.tool, x.args, x.content]);
      break;
    case "patch_split":
      try {
        const p = splitSearchReplace(c.input);
        r = [p.search, p.replace];
      } catch (e) {
        r = { error: (e as Error).message };
      }
      break;
    case "allowlist":
      r = isAllowedShellCommand(c.cmd, c.allowlist);
      break;
    case "strip":
      r = pyStrip(c.input);
      break;
    case "decode":
      r = decodeReplace(Uint8Array.from(atob(c.b64), (ch) => ch.charCodeAt(0)));
      break;
    case "trunc":
      r = truncate(c.unit.repeat(c.n));
      break;
    default:
      throw new Error(`unknown op ${c.op}`);
  }
  out.push(JSON.stringify(r));
}
console.log(out.join("\n"));
