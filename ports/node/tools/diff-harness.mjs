// Differential-test harness (spec/conformance/differential): node tools/diff-harness.mjs cases.jsonl > out.jsonl
import fs from 'node:fs';
import { parseToolCalls } from '../src/toolcall.js';
import { splitSearchReplace, truncate } from '../src/tools.js';
import { isAllowedShellCommand } from '../src/shlex.js';
import { pyStrip, decodeReplace } from '../src/pyutil.js';

const out = [];
for (const line of fs.readFileSync(process.argv[2], 'utf8').split('\n')) {
  if (!line) continue;
  const c = JSON.parse(line);
  let r;
  switch (c.op) {
    case 'toolcall':
      r = parseToolCalls(c.input).map((x) => [x.tool, x.args, x.content]);
      break;
    case 'patch_split':
      try {
        const p = splitSearchReplace(c.input);
        r = [p.search, p.replace];
      } catch (e) {
        r = { error: e.message };
      }
      break;
    case 'allowlist':
      r = isAllowedShellCommand(c.cmd, c.allowlist);
      break;
    case 'strip':
      r = pyStrip(c.input);
      break;
    case 'decode':
      r = decodeReplace(Buffer.from(c.b64, 'base64'));
      break;
    case 'trunc':
      r = truncate(c.unit.repeat(c.n));
      break;
    default:
      throw new Error(`unknown op ${c.op}`);
  }
  out.push(JSON.stringify(r));
}
process.stdout.write(out.join('\n') + '\n');
