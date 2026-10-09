import { chat, DEFAULT_HOST } from "./llm.ts";
import type { LLMOptions, Message } from "./llm.ts";
import { parseToolCalls } from "./toolcall.ts";
import { buildSystemPrompt, defaultRegistry } from "./prompt.ts";
import type { Registry } from "./prompt.ts";
import type { ShellPolicy } from "./tools.ts";

// The agent loop (spec section 9).

export const MAX_STEPS = 25;

export interface Options {
  model: string;
  host?: string;
  workspace: string;
  llm?: LLMOptions;
  shell?: ShellPolicy;
  /** Defaults to the foundation tools with `shell` applied. */
  registry?: Registry;
  /** Where progress text goes; defaults to stdout. */
  out?: (text: string) => void;
}

interface Settled extends Required<Pick<Options, "model" | "host" | "workspace" | "llm" | "registry" | "out">> {}

const encoder = new TextEncoder();

function settle(o: Options): Settled {
  return {
    model: o.model,
    host: o.host ?? DEFAULT_HOST,
    workspace: o.workspace,
    llm: o.llm ?? {},
    registry: o.registry ?? defaultRegistry(o.shell),
    out: o.out ?? ((text: string) => void Deno.stdout.writeSync(encoder.encode(text))),
  };
}

/** One model call plus any tool calls in its reply. Resolves true if a tool ran. */
export async function step(messages: Message[], options: Options): Promise<boolean> {
  const o = settle(options);
  const reply = await chat(messages, o.model, o.host, o.llm);
  messages.push({ role: "assistant", content: reply });
  o.out(`\n--- assistant ---\n${reply}\n`);

  const calls = parseToolCalls(reply);
  if (calls.length === 0) return false;
  for (const call of calls) {
    const tool = o.registry.get(call.tool.toLowerCase());
    let result: string;
    if (!tool) {
      result = `Error: unknown tool '${call.tool}'.`;
    } else {
      try {
        result = await tool.fn(call.args, call.content, o.workspace);
      } catch (e) {
        const err = e as Error;
        result = `Error: ${err?.name ?? "Error"}: ${err?.message ?? e}`;
      }
    }
    o.out(`--- ${call.tool} ${call.args} ---\n${result}\n`);
    messages.push({ role: "user", content: `[${call.tool} output]\n${result}` });
  }
  return true;
}

/** Calls step() while it keeps running tools, capped at MAX_STEPS rounds. */
export async function runUntilDone(messages: Message[], options: Options): Promise<void> {
  const o = { ...options, registry: options.registry ?? defaultRegistry(options.shell) };
  const out = settle(o).out;
  for (let i = 0; i < MAX_STEPS; i++) {
    if (!(await step(messages, o))) return;
  }
  out(`\n--- stopped after ${MAX_STEPS} tool-call rounds; your turn ---\n`);
}

export function newConversation(options: Options): Message[] {
  return [{ role: "system", content: buildSystemPrompt(options.registry ?? defaultRegistry(options.shell)) }];
}

/** One-shot: run prompt to completion and resolve with the transcript. */
export async function run(prompt: string, options: Options): Promise<Message[]> {
  const o = { ...options, registry: options.registry ?? defaultRegistry(options.shell) };
  const messages = newConversation(o);
  messages.push({ role: "user", content: prompt });
  await runUntilDone(messages, o);
  return messages;
}
