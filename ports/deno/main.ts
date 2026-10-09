// nakedagent for Deno: deno run --allow-read --allow-write --allow-run --allow-net --allow-env main.ts "prompt"
import * as path from "node:path";
import { parseArgs } from "node:util";
import { DEFAULT_API_KEY_ENV, DEFAULT_HOST, DEFAULT_SHELL_TIMEOUT, newConversation, run, runUntilDone } from "./mod.ts";
import type { Options } from "./mod.ts";

const VERSION = "0.1.0-dev";

function fail(message: string, code = 1): number {
  console.error(`error: ${message}`);
  return code;
}

async function main(argv: string[]): Promise<number> {
  let parsed;
  try {
    parsed = parseArgs({
      args: argv,
      allowPositionals: true,
      options: {
        model: { type: "string", short: "m", default: "qwen2.5-coder:7b" },
        workspace: { type: "string", short: "w" },
        host: { type: "string" },
        api: { type: "string", default: "ollama" },
        "api-key-env": { type: "string", default: DEFAULT_API_KEY_ENV },
        "allow-shell": { type: "boolean", default: false },
        "shell-allowlist": { type: "string", multiple: true, default: [] },
        "shell-timeout": { type: "string", default: String(DEFAULT_SHELL_TIMEOUT) },
        version: { type: "boolean", default: false },
      },
    });
  } catch (e) {
    return fail((e as Error).message, 2);
  }
  const { values, positionals } = parsed;
  if (values.version) {
    console.log(VERSION);
    return 0;
  }
  if (positionals.length > 1) return fail("only one prompt argument is allowed", 2);
  const api = values.api as string;
  if (api !== "ollama" && api !== "openai") return fail(`--api must be one of ollama, openai, got: '${api}'`, 2);
  const timeout = Number.parseInt(values["shell-timeout"] as string, 10);
  if (!(timeout > 0)) return fail("--shell-timeout must be greater than 0");
  let host = values.host as string | undefined;
  if (!host) {
    if (api !== "ollama") return fail("--api openai needs --host (e.g. https://api.openai.com/v1)");
    host = DEFAULT_HOST;
  }
  const options: Options = {
    model: values.model as string,
    host,
    workspace: path.resolve((values.workspace as string | undefined) ?? Deno.cwd()),
    llm: { api, apiKeyEnv: values["api-key-env"] as string },
    shell: {
      allowShell: values["allow-shell"] as boolean,
      allowlist: (values["shell-allowlist"] as string[]).map((p) => p.trim()).filter(Boolean),
      timeoutSeconds: timeout,
    },
  };

  try {
    if (positionals.length === 1) {
      await run(positionals[0], options);
      return 0;
    }
    const messages = newConversation(options);
    console.log(`nakedagent -- workspace: ${options.workspace} -- model: ${options.model}\nCtrl-D to exit.\n`);
    for (;;) {
      const line = prompt("> ");
      if (line === null) break; // end of input
      if (!line.trim()) continue;
      messages.push({ role: "user", content: line.trim() });
      await runUntilDone(messages, options);
    }
    console.log();
    return 0;
  } catch (e) {
    return fail((e as Error).message);
  }
}

if (import.meta.main) Deno.exit(await main(Deno.args));
