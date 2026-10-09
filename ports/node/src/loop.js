import { chat, DEFAULT_HOST } from './llm.js';
import { parseToolCalls } from './toolcall.js';
import { buildSystemPrompt, defaultRegistry } from './prompt.js';

// The agent loop (spec section 9).

export const MAX_STEPS = 25;

/**
 * options: { model, host, workspace, llm: {api, apiKeyEnv}, shell: {allowShell, allowlist, timeoutSeconds},
 *            registry (default: foundation tools), out: (text) => void (default: stdout) }
 */
function settle(options) {
  const o = { host: DEFAULT_HOST, llm: {}, ...options };
  o.registry ??= defaultRegistry(o.shell);
  o.out ??= (text) => process.stdout.write(text);
  return o;
}

/** One model call plus any tool calls in its reply. Resolves true if a tool ran. */
export async function step(messages, options) {
  const o = settle(options);
  const reply = await chat(messages, o.model, o.host, o.llm);
  messages.push({ role: 'assistant', content: reply });
  o.out(`\n--- assistant ---\n${reply}\n`);

  const calls = parseToolCalls(reply);
  if (calls.length === 0) return false;
  for (const call of calls) {
    const tool = o.registry.get(call.tool.toLowerCase());
    let result;
    if (!tool) {
      result = `Error: unknown tool '${call.tool}'.`;
    } else {
      try {
        result = await tool.fn(call.args, call.content, o.workspace);
      } catch (e) {
        result = `Error: ${e?.name ?? 'Error'}: ${e?.message ?? e}`;
      }
    }
    o.out(`--- ${call.tool} ${call.args} ---\n${result}\n`);
    messages.push({ role: 'user', content: `[${call.tool} output]\n${result}` });
  }
  return true;
}

/** Calls step() while it keeps running tools, capped at MAX_STEPS rounds. */
export async function runUntilDone(messages, options) {
  const o = settle(options);
  for (let i = 0; i < MAX_STEPS; i++) {
    if (!(await step(messages, o))) return;
  }
  o.out(`\n--- stopped after ${MAX_STEPS} tool-call rounds; your turn ---\n`);
}

export function newConversation(options) {
  return [{ role: 'system', content: buildSystemPrompt(settle(options).registry) }];
}

/** One-shot: run prompt to completion and resolve with the transcript. */
export async function run(prompt, options) {
  const o = settle(options);
  const messages = newConversation(o);
  messages.push({ role: 'user', content: prompt });
  await runUntilDone(messages, o);
  return messages;
}
