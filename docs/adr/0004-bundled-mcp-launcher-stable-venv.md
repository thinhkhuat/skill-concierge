# ADR-0004: Bundled MCP via launcher + stable venv (survive cache wipes)

**Status:** Accepted
**Date:** 2026-06-26
**Deciders:** owner (thinhkhuat)

## Context

The plugin ships the vendored skill-search engine and registers it as an MCP server in
`.mcp.json`. The first design pointed the MCP `command` at a venv **inside the plugin tree**
(`${CLAUDE_PLUGIN_ROOT}/vendor/.venv`). That path lives under the plugin **cache**
(`~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/`), which Claude Code **wipes and
re-creates on every plugin update/reinstall**. Result: the venv was never built where the
MCP looked → `ENOENT` → MCP fails to start (`-32000`).

## Decision

Two pieces:

1. **A launcher** — `bin/skill-search-mcp`. `.mcp.json` points at the launcher, not a
   Python path. The launcher `exec`s a **stable** venv:
   `VENV="${SKILL_CONCIERGE_VENV:-$HOME/.local/share/skill-concierge/venv}"`. If
   `$VENV/bin/skill-search` isn't executable, it exits `127` with a clear "run setup.sh"
   message instead of a cryptic ENOENT.
2. **A stable venv** outside the cache — `~/.local/share/skill-concierge/venv` — built by
   `setup.sh` with a **non-editable** install of the vendored engine, so it survives plugin
   cache wipes. `setup.sh` is idempotent: picks Python 3.10–3.12, reads model/URL from
   `.mcp.json`, builds the venv, ensures the Qdrant container, runs `--reindex` + `--health`,
   then applies overrides (ADR-0005).

## Consequences

### Positive
- The MCP survives `/plugin marketplace update` and reinstalls — the engine lives at a
  stable path the cache can't touch.
- Failure mode is legible (`exit 127`, "run setup.sh") instead of `-32000`/ENOENT.

### Negative / caveats
- **Bootstrap dependency:** a fresh machine must run `setup.sh` once before the MCP connects.
  The plugin is not "zero-setup".
- **Python-picker is naive:** it takes the first `python3.12` on `PATH`. On this machine the
  first one (`~/.local/bin/python3.12`) has a **broken `ensurepip`** → venv creation fails;
  the working build used `/opt/homebrew/bin/python3.12`. Hardening the picker to test
  `venv`+`pip` per candidate is **deferred** (portability-only; see `../caveats.md` §4).
- **Version-is-the-update-signal:** bumping the engine/config requires bumping *both*
  `plugin.json` and `marketplace.json` versions, or a downstream `/plugin marketplace update`
  is a silent no-op (`../caveats.md` §7).

## Related

- ADR-0003 (the venv holds fastembed + mpnet).
- ADR-0005 (`setup.sh`'s final step applies overrides).
- `../caveats.md` §4 (broken-ensurepip picker), §7 (version-bump signal).
