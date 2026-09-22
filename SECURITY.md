# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in this project, please report it privately:

1. **Do not open a public GitHub issue.**
2. Go to [Security Advisories](https://github.com/hummbl-io/nakedagent/security/advisories/new) and create a private security advisory.
3. Include a description of the vulnerability, steps to reproduce, and potential impact.

You will receive a response within 48 hours. If the vulnerability is confirmed, a fix will be prioritized and a security advisory will be published after the fix is deployed.

## Trust boundaries

- **Workspace plugins**: `<repo>/.nakedagent/plugins/*.py` files are NOT loaded by default — they are repo-controlled Python executed with the operator's privileges. Only pass `--trust-workspace-plugins` in workspaces you trust. User-global `~/.nakedagent/plugins/` is operator-owned and always loads.
- **Untrusted repos**: run nakedagent in untrusted clones without `--trust-workspace-plugins` (the default). Clone-and-inspect is a primary use case; the plugin seam must not become a `setup.py`-style code-execution vector.
- **Shell tool**: non-interactive shell execution requires `--allow-shell` plus a prefix-based `--shell-allowlist`.

## License

MIT - see [LICENSE](LICENSE).