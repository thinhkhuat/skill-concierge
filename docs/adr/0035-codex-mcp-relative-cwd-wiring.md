# ADR-0035: Codex MCP wiring — relative `cwd`, not `${CLAUDE_PLUGIN_ROOT}`

| | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-08-24 |
| **Supersedes** | none |
| **Amends** | ADR-0033 (corrects its claim that Codex "reads `.mcp.json` the same way") |

## Context

The first Codex-side validation of the dual-harness deploy (v0.25.1) found the retrieval organ
silently dead in every Codex session: 248 tools enumerated, zero `skill-search` matches, while
hooks, the ledger and the shared index all worked. Root cause, reproduced on Codex CLI 0.149.1:

```
$ codex mcp get skill-search
  command: ${CLAUDE_PLUGIN_ROOT}/bin/skill-search-mcp     ← LITERAL, never expanded
```

**Codex expands `${CLAUDE_PLUGIN_ROOT}` in plugin hook commands but leaves it literal in plugin
MCP `command`/`args`** (upstream: openai/codex#35762; the asymmetry is in
`codex-rs/codex-mcp/src/plugin_config.rs`, which roots relative `cwd` values but does not expand
command placeholders). ADR-0033's context claim that Codex "reads `.mcp.json` the same way" was
proven for hooks and disproven for MCP. The server itself was healthy — driven directly over
stdio it completed a full JSON-RPC session — so this was wiring, not engine.

The outage was invisible in ledger metrics: the enforcer offer queries Qdrant over REST and kept
working, so every turn logged normally while the pull tool (`search_skills` / `get_skill`) the
SKILL-FIRST doctrine mandates did not exist. This is the same "healthy index the agent cannot
reach" mode that motivated doctor's `MCP reachable` check on the Claude side (v0.25.0).

## Decision

**Give Codex its own MCP descriptor using Codex's native plugin-root mechanism: a relative
command resolved against `"cwd": "."`.** Per upstream guidance (openai/codex discussion #28145),
a relative `cwd` in a plugin MCP config is resolved against the installed plugin root — the
Codex-native replacement for embedding `${CLAUDE_PLUGIN_ROOT}`, and portable across the
versioned cache dirs a fixed absolute path would break on every release.

- New `.codex-plugin/mcp.json`: `"command": "./bin/skill-search-mcp"`, `"cwd": "."`, env
  mirroring `.mcp.json`. The launcher self-locates via `BASH_SOURCE`, so a relative spawn is
  safe (verified by launching it relatively from the cache root).
- `.codex-plugin/plugin.json` `mcpServers` repointed from `./.mcp.json` to the new file. The
  shared `.mcp.json` stays untouched — Claude Code's wiring is proven and
  `auto_reindex._mcp_env()` reads that file as its env source of truth.
- **`SKILL_SERVER_RECORDS` is deliberately omitted** from the Codex descriptor. `.mcp.json`
  carries it as a `${HOME}` literal that only Claude Code's MCP launcher expands (the 0.21.1
  lesson); under Codex the literal would mint a garbage path, while the engine's own
  `Path.home()` default is correct.
- **Env parity is enforced, not hoped for.** Two descriptors for one engine is a drift risk, so
  `scripts/check_mcp_env_parity.py` (wired into driftcheck's command checks) fails on any shared
  key whose values differ and on any key present only in the Codex file. The Claude file is the
  source of truth; the Codex file may deliberately omit keys, never invent them.

**Migration note — corrected by the retest.** The broken registration was the
**plugin-provided** entry itself, not a hand-registered user-scope one: `codex mcp remove
skill-search` reports no such server while `codex mcp get` still returns it, which is exactly
how Codex surfaces manifest-sourced servers. No user-side cleanup exists or is needed — the
manifest repoint IS the whole migration, applied automatically by the plugin update. Per
Codex's model, plugin-bundled servers are launched from the plugin; user config only toggles
them (`[plugins."skill-concierge@skill-concierge".mcp_servers.skill-search]`).

## Consequences

- Codex sessions get the full retrieval organ: `search_skills` and `get_skill` become real
  tools, matching what the injected SKILL-FIRST doctrine already mandates there.
- The claude/codex descriptor pair is now a maintained surface: engine env changes land in
  `.mcp.json` first and are mirrored to the Codex file, with driftcheck refusing the commit on
  divergence (same guard class as the openwiki version mirror).
- If a future Codex build starts expanding `${CLAUDE_PLUGIN_ROOT}` in MCP commands, nothing
  breaks — the relative-`cwd` form does not use the variable at all.

## Validation

- Upstream behavior grounded in openai/codex#35762 (command/args never expanded; observed live
  on 0.149.1) and discussion #28145 (`"cwd": "."` = plugin root, `plugin_config.rs`).
- Relative spawn proven: `cd <codex cache root> && ./bin/skill-search-mcp` launches the engine
  (launcher self-locates via `BASH_SOURCE`, ADR-0018 self-heal path included).
- `mcp-env-parity` check green: 7 shared keys in lockstep, `SKILL_SERVER_RECORDS` omission
  flagged as deliberate.
- Retest executed same-day against the deployed 0.25.2 Codex cache: `codex mcp get
  skill-search` shows `command: ./bin/skill-search-mcp` with `cwd` **resolved by Codex's own
  loader** to the plugin root (`.../0.25.2/.`) — the literal variable is gone; and the server
  spawned exactly as Codex will spawn it (that resolved cwd, relative command, descriptor env)
  completed a full stdio session: `initialize` → `skill-search 1.29.0`, `tools/list` → all four
  tools, `tools/call search_skills` → ranked results. Sole residue: observing an interactive
  Codex session's own tool surface, which requires the next live Codex session. First Codex
  validation report: `plans/reports/codex-validation-260824-dual-harness-v0251.md`, defect D1.
