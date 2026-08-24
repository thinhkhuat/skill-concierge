# ADR-0033: Dual-harness parity — Codex skill discovery

| | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-08-24 |
| **Supersedes** | none |
| **Amends** | ADR-0028 (multi-session index scoping — extends the scope system to a second harness) |

## Context

skill-concierge was built for Claude Code, but Codex is a sibling harness that speaks the same
plugin dialect: it clones the marketplace repo as-is, auto-discovers `hooks/hooks.json`,
expands the same `${CLAUDE_PLUGIN_ROOT}` variable, reads `.mcp.json` the same way, and loads
`skills/*/SKILL.md`. A first Codex install (v0.20.8, July 2026) proved the hooks fired and the
MCP connected — and an abandoned `feat/codex-dual-harness` branch (commit `0f9569e`) built this
exact parity once before stalling on three failing discovery tests. This ADR revives that work
onto current main with the failures fixed.

The defect without it: the **retrieval index is blind to Codex's skill universe**. Discovery only
walked `~/.claude/**`, so Codex's personal skills (`~/.codex/skills/`) and plugin-bundled skills
(`~/.codex/plugins/cache/**`, hundreds of them) were invisible to the semantic retriever. The
enforcer would inject the SKILL-FIRST mandate over half an empty shelf — governing Claude's
catalogue while Codex sessions searched it.

## Decision

**Widen skill discovery to include Codex's directories, alongside the existing Claude Code
paths.** Three new constants in `skills_discovery.py`:

- `CODEX_PERSONAL_ROOT = ~/.codex/skills/`
- `CODEX_PROJECT_ROOT = {cwd}/.codex/skills/`
- `CODEX_PLUGIN_GLOB = ~/.codex/plugins/cache/**/skills/*/SKILL.md`

added to `SKILL_DIRS` (additive) and `_plugin_paths()` (merged with Claude hits).

**Scope isolation.** Each Codex-discovered skill gets a distinct scope — `codex-personal`,
`codex-plugin`, `codex-project:{root}` — so a reindex in one harness can never prune the
other's points, and any session on the machine can prune skills genuinely gone from disk.
`visible_scopes()` includes them unconditionally (when the flag is on). The plugin-side
`enforcer.py` chain-hint sidecar mirror (`_visible_sidecar_names`) reads the same codex scopes,
so `next-skills:` chains fire for Codex-scope skills too.

**Codex plugin cache is unfiltered.** Claude's cache is filtered via
`installed_plugins.json` + `settings.json`; Codex tracks enablement in `config.toml` (TOML),
and `skills_discovery.py` is stdlib-only on a 3.10 floor where `tomllib` doesn't exist. A few
stale/disabled entries beat a blind spot over Codex's whole universe — the same trade the
unreadable-manifest fallback already makes for Claude.

**One-var revert.** `SKILL_CODEX_ROOTS=0` (default on) drops every Codex path + scope,
byte-identical to the pre-dual-harness engine; a reindex prunes the codex points.

**No `hooks` field in `.codex-plugin/plugin.json`.** The Codex plugin validator rejects it;
hooks are auto-discovered from `hooks/hooks.json`, which uses the same format, event names, and
`${CLAUDE_PLUGIN_ROOT}` expansion Codex already honors. The Codex manifest declares
`skills` + `mcpServers` explicitly plus the `interface` block. `.codex/hooks.json` carries
only the repo-development parity gate (openwiki commit guard), mirroring
`.claude/settings.json` for sessions developing THIS repo under Codex.

**Hermetic tests.** The July branch's three failing discovery tests failed because fixtures
patched `SKILL_DIRS`/`PLUGIN_GLOB` but not the new Codex globals, leaking the machine's real
`~/.codex/plugins/cache/**` (312 skills observed) into assertions. Fixed at the conftest level
with an autouse fixture pinning every Codex seam to a temp path — imported only AFTER the env
pinning block, because `skills_discovery` reads its env seams at import time and an early
import would capture the operator's live catalog-roots config (the `antigravity` leak).

## Consequences

- Both harnesses' skills index into ONE shared Qdrant collection; the enforcer, chain hints,
  and search offer across the union.
- The Codex cache being unfiltered means stale plugin versions CAN be indexed until pruned by
  a later version landing; accepted (see above).
- Ledger epoch note: installing skill-concierge into Codex is a config change — start a new
  epoch when reading ledger metrics (`analyze.py --since`).
- The invocation ledger gains Codex session rows (`turn`/`offer` events share the same file);
  `Skill`-tool `auto` capture is Claude-only until Codex exposes a skill-invocation hook event.

## Validation

- `vendor/skill-search` test suite: 73 collected, 72 pass; the one failure
  (`test_end_to_end_build_search_incremental`) is environmental (needs the Qdrant server up).
- `enforcer.py --selftest` + `doctrine.py --selftest` green.
- `driftcheck.py` exit 0 (now mirroring `.codex-plugin/plugin.json`'s version).
