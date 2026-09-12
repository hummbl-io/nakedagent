# Doctrine

nakedagent is an **omakase** coding agent. The word means *chef's choice*:
the chef picks the courses, but you are always free to send anything back.
We pick the tools and tune the details so a first run needs no decisions,
and we ship a clean seam so you can change everything without forking the
foundation.

This is the same principle Rails was built on and that Omarchy carries into
the OS: curated defaults over a paradox of choice, with substitutions
welcome *through a designed seam*, not by rewriting the kitchen.

## Defaults over decisions

A first `python -m nakedagent` makes zero decisions. There is a default
model, a default host, a default workspace, a default tool set. Every one
of them is considered. You run it and it works.

Great defaults are also a benchmark: when you do want to substitute, you
weigh it against a known good, not against a blank page. "Is this actually
better?" is a question the default lets you ask.

## The foundation stays naked

The foundation is four tools (`shell`, `read`, `write`, `patch`), one model
backend (Ollama), and the standard library. Nothing else. This is not
minimalism for its own sake — it is the load-bearing constraint that gives
the project its reason to exist: no supply chain, because there is no
supply. `urllib` + `json` + `subprocess` + `re` are enough to drive a local
model through a working tool-use loop.

Capability that does not serve *every* user does not belong in the
foundation. It belongs in a plugin (below). The foundation's job is to be
correct, small, and complete enough that the seam is the only extension
path anyone needs.

## The seam is the substitution mechanism

The omakase promise — "you're free to change everything" — is only real if
there is a designed place to make a change. That place is the plugin seam
(`nakedagent/plugins.py`):

- Drop a `.py` file in `.nakedagent/plugins/` (repo-local) or
  `~/.nakedagent/plugins/` (user-global).
- It defines a module-level `TOOLS: dict[str, ToolFunc]` and/or
  `DISABLE: list[str]`.
- At startup the loader imports each, merges `TOOLS` into the runtime
  registry, applies `DISABLE`, and the model can call the surviving tools by
  name.
- No registration, no metadata, no framework. A plugin is just a Python
  file that defines `TOOLS` and/or `DISABLE`.

User-global overrides repo-local; later files override earlier; tool names
are case-insensitive (matching the foundation's dispatch). A plugin that
fails to load is skipped with a warning — one bad plugin cannot brick the
agent, same fail-soft posture as a tool that raises.

### Two ways to substitute

**Override** — a plugin that reuses a foundation tool's name replaces its
function. The chef's opinion lives on the tool, not in a static string the
seam can't reach: each tool carries a `.usage` attribute (the fenced-block
example shown to the model), and a plugin that replaces a tool should set
`.usage` on its replacement too, so the model sees the new syntax instead of
the foundation's. The system prompt is built from the merged registry, so
this happens automatically — no separate prompt-editing step.

**Disable** — a plugin that lists a tool name in `DISABLE` removes it from
the registry entirely. "Send it back" rather than swap. A user who wants a
read-only agent disables `shell` and `write`; the model never sees them in
the prompt, so it never tries to call them. `DISABLE` is applied after all
`TOOLS` merges, so it wins over any substitution — including a plugin that
both defines and disables a name.

This is where `difflib` diffs on `patch`, `read` pagination, cloud
providers, shell sandboxing, context compaction, and every other
"would be nice" live: as substitutions a user makes, not as foundation
surface we maintain. DHH removed a "bare mode" from Omarchy for violating
this principle; the lesson is, don't offer a stripped choice, offer a good
default plus a clean way to deviate.

## Better is better, not newer

We ship what works. The standard library has been load-bearing for decades;
that is an argument *for* it, not against. A new library is not a reason to
add a dependency. A new pattern is not a reason to add an abstraction. The
foundation earns its keep by being boring and staying put.

## Unapologetically itself

nakedagent is not trying to be aider, gptme, or OpenHands. It is a minimal,
stdlib-only, local-first agent that proves a 7B model and four tools are
enough to do real work. Comparisons to the larger tools name what is
*deliberately not here* and why, not what is missing by accident.

## What this means for contributors

- A bug in the foundation (wrong error message, crash path, parser defect)
  is foundation work. Fix it in the foundation, with a regression test.
- A new capability (a fifth tool, a second model backend, a richer edit
  format) is almost always a plugin, not a foundation addition. Ask first
  whether the foundation is the right home before adding to it.
- The seam itself is foundation work and stays minimal. If the loader grows
  metadata, versioning, or a registry protocol, that is the moment to stop
  and ask whether we are building a plugin framework — which is a different
  project.
