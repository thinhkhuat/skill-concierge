# ADR-0038: Command Code triple-harness parity — Command Code as a first-class citizen

| | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-08-24 |
| **Supersedes** | none |
| **Amends** | ADR-0033 (discovery mirror), ADR-0034 (offer isolation), ADR-0035 (MCP wiring) |

## Context

Following ADR-0033 (dual-harness discovery parity) and ADR-0034/0035 (Codex offer isolation & MCP wiring),
**Command Code** (`cmd`, v1.32.1) is added as the third first-class citizen alongside Claude Code and Codex.

Command Code has distinct harness characteristics:
1. **No plugin manifest system:** Command Code's extension units are skills directories, settings hooks
   (supporting `PreToolUse`, `PostToolUse`, `Stop`, `SessionStart`, with matchers limited to built-in tools
   `SHELL`, `READ`, `WRITE`, `EDIT`), MCP servers, and **mods** (TypeScript lifecycle plugins).
2. **No `UserPromptSubmit` hook event:** The per-turn gate and prompt-level telemetry cannot run via
   `settings.json` hooks. However, Command Code **mods** expose `transformInput` (firing on every typed
   user prompt), which is the exact native replacement for in-generation enforcement.
3. **Dedicated skills roots:** Command Code stores personal skills at `~/.commandcode/skills/` and
   project skills at `.commandcode/skills/`.
4. **Isolated MCP configuration:** Command Code stores user-scope servers in `~/.commandcode/mcp.json`
   and project overrides in `~/.commandcode/projects/<slug>/mcp.json`. It does not expand `${CLAUDE_PLUGIN_ROOT}`
   literals (the ADR-0035 failure class).

Prior to this ADR, Command Code relied on an out-of-repo monkey-patch script and a stale 0.20.8 cache
pinning, with the per-turn enforcer completely dead.

## Decision

### 1. Three-way harness identity (`enforcer.py` + `doctrine.py`)
- `hooks/scripts/enforcer.py` introduces `_running_harness()` returning `"commandcode"`, `"codex"`, or `"claude"`.
- Precedence: `SKILL_CONCIERGE_HARNESS` environment variable (set by the Command Code mod adapter),
  followed by path marker probes (`.codex`, `.claude`), falling back to `"claude"`.
- `_foreign_scopes()` for Command Code: `("plugin", "codex-plugin", "codex-personal", "personal")`.
  Command Code loads its own personal/project roots plus extra settings locations; foreign harness roots
  are post-filtered out of the installed offer and surfaced in the foreign annex under `[claude/codex]`.
- `doctrine.py` natively adapts tool names per harness (`mcp__skill-search__search_skills` and `/skill-search`
  under Command Code), retiring the out-of-repo monkey-patch.

### 2. Discovery mirror (`skills_discovery.py`)
- `vendor/skill-search/skill_search/skills_discovery.py` adds `SKILL_COMMANDCODE_ROOTS` (default ON).
- Discovers `~/.commandcode/skills/` as `commandcode-personal` and `.commandcode/skills/` as
  `commandcode-project:<path>` scopes.
- `auto_reindex._mcp_env()` forwards `SKILL_COMMANDCODE_ROOTS` to detached reindexes (preserving the
  invariant that every engine-side flag readable from `.mcp.json` is forwarded).

### 3. Command Code Mod adapter (`adapters/commandcode/`)
- `adapters/commandcode/skill-concierge.mod.ts` exports a default mod factory for Command Code:
  - `cmd.hooks({ transformInput })`: invokes `enforcer.py` (with `SKILL_CONCIERGE_HARNESS=commandcode`),
    appends the `<hook_context source="skill-concierge">` mandate and ranked preview to the prompt text,
    and logs turn boundaries to `ledger.py`.
  - Event observers: subscribes to `cmd.on('skill_loaded')` and `cmd.on('tool_completed')` to capture
    `activate_skill`, `search_skills`, and `get_skill` calls into the shared ledger.
  - Fail-open: all mod handlers catch errors and fall through silently.
- `adapters/commandcode/install.sh`: idempotent installer wiring the mod to `~/.commandcode/mods/skill-concierge.ts`,
  configuring `SessionStart` hooks in `~/.commandcode/settings.json`, and configuring `~/.commandcode/mcp.json`.

### 4. Parity and drift enforcement
- `scripts/check_mcp_env_parity.py` validates `adapters/commandcode/mcp.json` in lockstep with `.mcp.json`.
- All version manifests (`.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `.codex-plugin/plugin.json`)
  are bumped in unison.

## Consequences

- Command Code achieves full parity: SessionStart doctrine, per-turn semantic enforcement, foreign-harness
  annexing, tool-usage ledger logging, and background self-healing index/overrides.
- Stale 0.20.8 cache paths and out-of-repo doctrine monkey-patches are eliminated.
- Claude Code and Codex behavior remains byte-identical.
