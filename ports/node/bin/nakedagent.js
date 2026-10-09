#!/usr/bin/env node
import path from 'node:path';
import readline from 'node:readline/promises';
import { parseArgs } from 'node:util';
import {
  run, runUntilDone, newConversation, DEFAULT_HOST, DEFAULT_API_KEY_ENV, DEFAULT_SHELL_TIMEOUT,
} from '../src/index.js';

const VERSION = '0.1.0-dev';

function fail(message, code = 1) {
  process.stderr.write(`error: ${message}\n`);
  return code;
}

async function main(argv) {
  let parsed;
  try {
    parsed = parseArgs({
      args: argv,
      allowPositionals: true,
      options: {
        model: { type: 'string', short: 'm', default: 'qwen2.5-coder:7b' },
        workspace: { type: 'string', short: 'w' },
        host: { type: 'string' },
        api: { type: 'string', default: 'ollama' },
        'api-key-env': { type: 'string', default: DEFAULT_API_KEY_ENV },
        'allow-shell': { type: 'boolean', default: false },
        'shell-allowlist': { type: 'string', multiple: true, default: [] },
        'shell-timeout': { type: 'string', default: String(DEFAULT_SHELL_TIMEOUT) },
        version: { type: 'boolean', default: false },
      },
    });
  } catch (e) {
    return fail(e.message, 2);
  }
  const { values, positionals } = parsed;
  if (values.version) {
    console.log(VERSION);
    return 0;
  }
  if (positionals.length > 1) return fail('only one prompt argument is allowed', 2);
  if (values.api !== 'ollama' && values.api !== 'openai') {
    return fail(`--api must be one of ollama, openai, got: '${values.api}'`, 2);
  }
  const timeout = Number.parseInt(values['shell-timeout'], 10);
  if (!(timeout > 0)) return fail('--shell-timeout must be greater than 0');
  let host = values.host;
  if (!host) {
    if (values.api !== 'ollama') return fail('--api openai needs --host (e.g. https://api.openai.com/v1)');
    host = DEFAULT_HOST;
  }
  const options = {
    model: values.model,
    host,
    workspace: path.resolve(values.workspace ?? process.cwd()),
    llm: { api: values.api, apiKeyEnv: values['api-key-env'] },
    shell: {
      allowShell: values['allow-shell'],
      allowlist: values['shell-allowlist'].map((p) => p.trim()).filter(Boolean),
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
    const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
    try {
      for (;;) {
        let line;
        try {
          line = await rl.question('> ');
        } catch {
          break; // input closed
        }
        if (!line.trim()) continue;
        messages.push({ role: 'user', content: line.trim() });
        await runUntilDone(messages, options);
      }
    } finally {
      rl.close();
    }
    console.log();
    return 0;
  } catch (e) {
    return fail(e.message);
  }
}

process.exitCode = await main(process.argv.slice(2));
