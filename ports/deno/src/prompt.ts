import { compareCodePoints } from "./pyutil.ts";
import { DEFAULT_SHELL_TIMEOUT, toolPatch, toolRead, toolShell, toolWrite } from "./tools.ts";
import type { ShellPolicy, ToolFunc } from "./tools.ts";

/** A registry entry: the function plus the fenced-block example shown to the model (empty: listed by name only). */
export interface Tool {
  fn: ToolFunc;
  usage?: string;
}

/**
 * Ordered tool registry. It is the port's plugin seam (spec section 9): an embedding program adds
 * or replaces tools with set() and sends foundation tools back with disable().
 */
export class Registry {
  #tools = new Map<string, Tool>();

  get(name: string): Tool | undefined {
    return this.#tools.get(name);
  }

  /** Adds a tool, or replaces the tool of the same name in place (keeping its position). */
  set(name: string, tool: Tool): this {
    this.#tools.set(name.toLowerCase(), tool);
    return this;
  }

  /** Removes tools by name. Call it after all set() calls so that it wins over them. */
  disable(...names: string[]): this {
    for (const n of names) this.#tools.delete(n.toLowerCase());
    return this;
  }

  entries(): [string, Tool][] {
    return [...this.#tools.entries()];
  }
}

const USAGE = {
  shell: "```shell\nls -la\n```",
  read: "```read README.md\n```",
  write: "```write hello.txt\nHello, world!\n```",
  patch: "```patch hello.txt\n" +
    "<<<<<<< SEARCH\n" +
    "Hello, world!\n" +
    "=======\n" +
    "Goodbye, world!\n" +
    ">>>>>>> REPLACE\n" +
    "```",
};

export function newShellPolicy(): ShellPolicy {
  return { allowShell: false, allowlist: [], timeoutSeconds: DEFAULT_SHELL_TIMEOUT };
}

/** The four foundation tools with the given shell policy applied. */
export function defaultRegistry(policy: ShellPolicy = newShellPolicy()): Registry {
  return new Registry()
    .set("shell", { usage: USAGE.shell, fn: (a, c, w) => toolShell(a, c, w, policy) })
    .set("read", { usage: USAGE.read, fn: toolRead })
    .set("write", { usage: USAGE.write, fn: toolWrite })
    .set("patch", { usage: USAGE.patch, fn: toolPatch });
}

const HEADER = "You are nakedagent, a terminal coding agent. You have these tools, " +
  "invoked as a fenced code block whose language tag is the tool name:";

const RULES = "Rules:\n" +
  "- One tool call at a time is safest; you may emit more than one per message\n" +
  "  if you're confident, but batched calls all run without seeing each other's\n" +
  "  results -- a call that depends on an earlier result must wait for the next\n" +
  "  message.\n" +
  "- Only emit a fenced tool block when you mean to execute it -- every tagged\n" +
  "  fence at column 0 is dispatched, including ones meant as examples.\n" +
  "- `patch`'s SEARCH text must match the file exactly (including whitespace) " +
  "and uniquely -- if it doesn't, you'll get an error back and should read the " +
  "file again before retrying.\n" +
  "- When you have no more tool calls to make, just respond normally -- that " +
  "hands control back to the user.\n";

/** Builds the system prompt from the registry (spec section 7). */
export function buildSystemPrompt(registry: Registry): string {
  const examples: string[] = [];
  const noUsage: string[] = [];
  for (const [name, tool] of registry.entries()) {
    if (tool.usage) examples.push(tool.usage);
    else noUsage.push(name);
  }
  const parts = [HEADER, examples.join("\n\n")];
  if (noUsage.length > 0) {
    noUsage.sort(compareCodePoints);
    parts.push(
      "Additional tools are available (invoked the same way, as a fenced block whose language tag is the tool name): " +
        noUsage.map((n) => `\`${n}\``).join(", ") + ".",
    );
  }
  parts.push(RULES);
  return parts.join("\n\n");
}
