# ADR-0099 — The MCP launcher reads the machine-local engine file, not just the parent env

**Status:** Accepted
**Date:** 2026-11-07

## Context

ADR-0098 stamped every index point with the identity of the embedder that built it, and
represented in v0.76.1 by `scripts/engine_env.py` reading
`~/.claude/skill-concierge/engine-env.json`. That fixed every path that goes through
`engine_env.py`: the SessionStart `auto_reindex`, `auto_flywheel`, `doctor`, `setup.sh`.

It did not fix the **query server**. `bin/skill-search-mcp` takes its engine settings from
`.mcp.json` plus whatever the parent process exported, and `.mcp.json` cannot carry
`SKILL_OLLAMA_URL` or `SKILL_EMBED_TOKEN` (ADR-0097 forbids the token there). The parent is
a Claude session, whose own environment depends on how it was launched.

Measured on 2026-11-07, three freshly restarted sessions, same plugin, same machine:

| MCP server | `SKILL_OLLAMA_URL` | token |
|---|---|---|
| pid 2230 | *(unset)* | no |
| pid 99572 | *(unset)* | no |
| pid 5783 | `https://rtx.thinhkhuat.com` | yes |

Two of three fell back to `http://localhost:11434` with no token. They could still retrieve
— the index is uniform and the local Ollama was running — but they were not querying
through the configured embedder, and nothing said so.

## Decision

The launcher loads the same machine-local file `engine_env.py` reads, before `exec`-ing the
engine. Precedence matches exactly: an explicitly exported variable wins; the file fills
what is missing. The engine reads its settings at import time, so the loader must run in the
launcher, before the exec — not inside the engine.

Fail-open on every input: an absent, unreadable or malformed file leaves the engine on the
values it already had and never blocks MCP startup. The parse runs in an isolated Python
(`-I`) with an inline program, so a config file is never `eval`ed by the shell and no temp
file is written on the startup path. Keys are restricted to uppercase identifiers with
non-empty string values, so a stray key cannot become a shell injection.

## Why not the alternatives

- **Put the URL and token in `.mcp.json`.** Rejected: ADR-0097 already decided the token
  never belongs in the descriptor, which is committed and shipped.
- **Have the engine read the file itself.** Rejected: the engine computes its constants at
  import, before any of its own code could run, so the settings would arrive too late.
- **Launch the MCP from a wrapper that sources `harness-env.sh`.** Rejected: it couples the
  plugin to one shell file on one machine and would not travel.

## Consequences

All three paths — query server, background reindex, doctor — now resolve one embedder from
one file. The failure mode this closes was invisible: retrieval kept working, so a session on
the wrong embedder looked identical to a correct one.

Verified by driving the real launcher over stdio in an empty environment and reading the
`health` tool's own report: `provenance.current` is the GPU-host identity,
`stale_points 0`, `status ok`.

## Watch out

The launcher can only add settings; it cannot correct an explicitly exported wrong value.
That precedence is deliberate (an operator's decision outranks a file), but it means a stale
export still wins. Recheck with the clean-environment probe rather than a shell that has
already sourced something.
