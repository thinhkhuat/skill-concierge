---
title: Fixing the environment seam for background jobs left the query server on its own separate one
author: Thinh
date: 2026-11-07
branch: main
id: l-3db60292
scope: repo
status: active
src: agent
touches:
  - scripts/engine_env.py
  - docs/adr/0099-mcp-launcher-reads-machine-local-engine-env.md
  - docs/caveats.md
---

## Decided
Fixing the environment resolution in `scripts/engine_env.py` fixed the background
reindex, the flywheel, doctor and setup — and left the QUERY SERVER wrong. Two
different code paths build the engine environment, and only one was fixed.

`engine_env.py` is the hook/script path. The query server is launched by
`bin/skill-search-mcp`, which gets its settings from `.mcp.json` plus whatever the
PARENT process exported, and `.mcp.json` cannot carry `SKILL_OLLAMA_URL` or
`SKILL_EMBED_TOKEN` (the token is forbidden there by ADR-0097).

Consequence, measured after three sessions were restarted on the same plugin and
machine: two MCP servers launched with neither variable and fell back to
`http://localhost:11434` with an empty token; the third had both from its parent.
Same install, same code, three different embedders — and retrieval worked on all
three, so nothing looked broken.

Fix: the launcher now loads the same machine-local file before `exec`, with
precedence matching `engine_env.py` exactly (explicit export wins, file fills).
It must run in the LAUNCHER, not the engine: the engine reads its constants at
import time, so its own code cannot apply a setting to itself.

## Tried and ruled out
- **Assuming one env seam covers every consumer.** The reindex path was verifiably
  fixed and reported green while the query path stayed wrong. Long-lived servers
  start from a different entry point than short-lived scripts.
- **Putting the URL and token in `.mcp.json`.** ADR-0097 already decided the token
  never ships in the descriptor.
- **Wrapping the MCP launch in a script that sources the user's shell file.**
  Couples the plugin to one machine's shell layout.
- **`eval`-ing the JSON in bash.** Parse in an isolated Python (`-I`) with an
  inline program, emit shell-quoted exports, and restrict keys to
  uppercase identifiers with non-empty string values.

## Watch out
- **Verify a per-process setting at the PROCESS, not at the shared library.** The
  probe that settles it: spawn the real launcher in `env -i` and read what the
  server itself reports. A shell that already sourced something proves nothing.
- **"Restarted the session" does not mean "restarted with the right environment".**
  A child inherits its parent; three restarts from three contexts gave three
  answers.
- **The launcher can only fill gaps.** An explicitly exported stale value still
  wins by design, so a shell carrying an old setting can still pin the wrong
  endpoint.
- **Live MCP servers hold the old launcher in memory.** The fix applies at spawn,
  so it lands on the next restart, not at install time.

In the code:
- `bin/skill-search-mcp` — the engine-env block before `exec "$BIN"`
- `scripts/engine_env.py` — `engine_env()`, `local_engine_env()`, `LOCAL_ENV_PATH`
- machine file: `~/.claude/skill-concierge/engine-env.json`, chmod 600
- `docs/adr/0099-mcp-launcher-reads-machine-local-engine-env.md`,
  `docs/caveats.md` §34
- probe: `env -i HOME=$HOME PATH=/usr/bin:/bin /bin/bash bin/skill-search-mcp`,
  then call `health` over stdio; expected `provenance.current` = the GPU-host
  identity, `stale_points 0`
