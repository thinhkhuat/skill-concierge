# ADR-0039: OMP quadruple-harness parity — Oh My Pi as the fourth first-class citizen

| | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-08-25 |
| **Supersedes** | none |
| **Amends** | ADR-0033 (discovery mirror), ADR-0034 (offer isolation), ADR-0038 (harness set) |

## Context

Following ADR-0033/0034/0035 (Codex dual-harness) and ADR-0038 (Command Code triple-harness),
**Oh My Pi** (`omp`, "OMP") is added as the fourth first-class citizen alongside Claude Code,
Codex, and Command Code.

OMP is the one harness in the set that shares the most DNA with Claude Code — it reads the
`CLAUDE_PLUGIN_ROOT` variable, expands it natively inside plugin MCP command strings, consumes
skills via `read` on `skill://<name>`, and honors Claude-format plugin `.mcp.json` descriptors.
But it diverges sharply on the plugin-hook surface, and that divergence forces a dedicated
enforcement vehicle:

1. **OMP IGNORES Claude-format hooks.** Neither `hooks/hooks.json` command hooks nor the
   plugin's Claude-format lifecycle hooks execute under OMP: command hooks never fire at all,
   and the JS hook surface is not run as lifecycle hooks. The plugin-hook surface OMP does
   load is **TypeScript extension modules**, declared via the root `package.json`
   `{ "omp": { "extensions": [...] } }` field. So enforcement cannot ride
   `hooks/hooks.json` (the ADR-0034 cross-harness path); it rides an extension module —
   `adapters/omp/skill-concierge.ext.ts`, a factory export loaded by OMP from
   `package.json`'s `omp.extensions` list.
2. **`before_agent_start` is the per-turn enforcement point.** OMP has no `UserPromptSubmit`
   hook event (that is a settings-hook event, which OMP ignores). The extension meanwhile
   exposes `before_agent_start`, which fires after a prompt is submitted, carries the prompt,
   and can return an injectable persisted `{ message: { customType, content, display } }`.
   This is the exact native replacement for in-generation enforcement under OMP — the same
   role `transformInput` plays for Command Code (ADR-0038).
3. **OMP expands `${CLAUDE_PLUGIN_ROOT}` natively.** Unlike Codex (ADR-0035,
   openai/codex#35762), OMP resolves the variable inside plugin `.mcp.json` command/args on
   its own. The existing plugin `.mcp.json` needs **no per-harness descriptor**; the MCP wired
   to `skill://` retrieval and the skill-search tools carries over verbatim. A manual
   `adapters/omp/mcp.json` exists only as a fallback (installed outside the normal plugin
   marketplace path, e.g. a dev/extension-only wiring) and is a duplicate-server hazard if
   both it and the plugin-imported `.mcp.json` point at the same server name — installed via
   the marketplace path must not write it.
4. **`codex-plugin` scopes are FOREIGN under omp.** OMP's codex provider scans only
   `~/.codex/skills` and `<cwd>/.codex/skills` — it reads **no plugin cache**
   (`pi-coding-agent` `src/discovery/codex.ts:237-259`). So a `codex-plugin`-scoped skill has
   no invocable twin under omp and must be annexed, not offered. The foreign-scope set under
   omp is `("codex-plugin", "commandcode-personal")`; the foreign annex label is
   `"commandcode"` (commandcode roots OMP cannot load at all).
5. **Identity detection differs from every prior harness.** OMP sets BOTH `OMPCODE=1` and
   `CLAUDE-CODE`-style flags in its child environment. `CLAUDE-CODE` alone is therefore **not**
   Claude proof — a harness must see `OMPCODE=1`. The adapter sets
   `SKILL_CONCIERGE_HARNESS=omp` (or `oh-my-pi`), so `_running_harness()` in
   `hooks/scripts/enforcer.py` keys on that first, falls back to the `OMPCODE=1` env flag, then
   the `".omp/"` path marker, then the pre-dual-harness fallback. A new `UNDER_OMP` constant
   shadows the same decision for module-level reads.
6. **Cross-harness twin resolution follows OMP's own registries.** OMP's claude-plugins
   provider unions the claude + OMP registries, gating entries on `entry.enabled === false`
   (`pi-coding-agent` `src/index/helpers.ts:1000/1061/1102`). So `_invocable_plugin_ids()`
   under omp unions `~/.omp/plugins/installed_plugins.json`, and `_invocable_twin()` is active
   under `claude` OR `omp`.

## Decision

### 1. Harness identity (`enforcer.py` + `doctrine.py`)
- `hooks/scripts/enforcer.py` `_running_harness()` returns `"omp"` for Oh My Pi, alongside
  `"claude"`, `"codex"`, and `"commandcode"`. A new `UNDER_OMP` module constant is set by the
  same detection for non-function call sites.
- Detection precedence: `SKILL_CONCIERGE_HARNESS` env (`omp` | `oh-my-pi`, set by the OMP
  extension adapter) → `OMPCODE=1` env flag → `".omp/"` path marker → existing fallback.
  `OMPCODE=1` is the proof check: OMP sets both `OMPCODE=1` and `CLAUDE-CODE`, so a
  `CLAUDE-CODE`-only check is never treated as Claude identity.
- `_foreign_scopes()` under omp: `("codex-plugin", "commandcode-personal")`. OMP cannot invoke
  codex plugin-cache skills (codex provider reads no plugin cache) or Command Code personal
  roots. Foreign annex label under omp: `"commandcode"`.

### 2. Discovery mirror (`skills_discovery.py`)
- `vendor/skill-search/skill_search/skills_discovery.py` adds `SKILL_OMP_ROOTS` (default ON).
  With it on, discovery adds `~/.omp/agent/skills` (`omp-personal`),
  `<cwd>/.omp/skills` (`omp-project:<abspath>`), `~/.omp/agent/managed-skills`
  (`omp-managed`), and `~/.omp/plugins/cache/plugins/**` (`omp-plugin`, the node_modules
  symlink farm excluded).
- `auto_reindex._mcp_env()` forwards `SKILL_OMP_ROOTS` to detached reindexes, preserving the
  invariant that every engine-side flag readable from `.mcp.json` is forwarded.
- **One-var revert:** `SKILL_OMP_ROOTS=0` drops every omp path + scope, byte-identical to the
  pre-omp engine; a reindex prunes the omp points.

### 3. MCP wiring (nothing to duplicate)
- OMP expands `${CLAUDE_PLUGIN_ROOT}` natively inside plugin `.mcp.json` command/args, so the
  existing plugin `.mcp.json` carries the MCP into OMP sessions with **no per-harness
  descriptor** — the contrast with ADR-0035's Codex `cwd` rewrite, which OMP does not need.
- `adapters/omp/mcp.json` is a **manual fallback only** (extensions-only / non-marketplace
  installs, where the plugin `.mcp.json` is not imported). Where the marketplace path is live,
  the installer must NOT write it: a second file wiring the same server name would create a
  duplicate-server hazard (OMP imports the plugin `.mcp.json` and expands the variable
  natively, so a manual copy is both redundant and conflict-prone).
- `scripts/check_mcp_env_parity.py` covers `adapters/omp/mcp.json` in lockstep with `.mcp.json`;
  `driftcheck.json` `paths_exist` mirrors the omp surface.

### 4. Enforcement vehicle — OMP extension module (`adapters/omp/`)
- `adapters/omp/skill-concierge.ext.ts` (factory export, loaded via root `package.json`
  `{ "omp": { "extensions": [...] } }`):
  - `session_start`: dispatches the SessionStart doctrine/self-heal chain — detached
    `auto_reindex` / `auto_overrides` / `auto_flywheel` / `auto_promote` — mirroring the
    Claude/Codex/Command Code session-start behavior.
  - `before_agent_start` (the UserPromptSubmit equivalent): carries the prompt; feeds it to
    `hooks/scripts/enforcer.py` via stdin `{ prompt, session_id }` and returns an injectable,
    persisted `{ message: { customType: "skill-concierge", content, display: false } }` — the
    OMP-native form of the enforcer's mandate + ranked preview.
  - `tool_result`: forwards PostToolUse-equivalent payloads to `hooks/scripts/ledger.py` —
    `read` + `skill://` activation, `skill-search/search_skills`, `skill-search/get_skill` —
    so the invocation ledger stays populated under OMP.
  - OMP tool names take the `skill-concierge:skill-search/search_skills` shape
    (`plugin:server/tool`); OMP consumes skills via `read` on `skill://<name>`.
  - **Fail-open everywhere:** any extension handler that throws falls through silently; a dead
    OMP extension degrades to a plain OMP session, never a hard failure.
- `adapters/omp/install.sh`: marketplace path (plugin marketplace update + upgrade) when
  installed as a plugin; dev path appends to `~/.omp/agent/config.yml` `extensions`. Never
  writes `~/.omp/agent/mcp.json` (the duplicate-server hazard above).

### 5. Ops mirror
- `scripts/doctor.py` `check_omp()` validates the OMP installation: install version vs SSOT,
  catalog staleness, extension presence in the plugin cache, fail-open if the surface is absent.
- Version manifests (`.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`,
  `.codex-plugin/plugin.json`) and root `package.json` are bumped in unison.

## Consequences

- OMP achieves full parity: SessionStart doctrine + self-heal, per-turn semantic enforcement
  via `before_agent_start`, foreign-harness annexing (codex-plugin / commandcode-personal),
  tool-usage ledger logging, and background reindex/overrides/flywheel/promote.
- OMP's enforcement rides an extension module, not Claude-format hooks — a hook written in
  `hooks/hooks.json` would be silent under OMP, so the extension adapter is the only vehicle
  that fires.
- The plugin `.mcp.json` needs no OMP descriptor; `adapters/omp/mcp.json` remains manual-only
  with an explicit duplicate-server caution.
- Claude Code, Codex, and Command Code behavior remains byte-identical (selftests +
  ADR-0038 evidence). Live probe on 2026-08-25 (headless `omp -p` with the working-tree
  extension) produced ledger rows showing an offer + a turn under `harness: "omp"`.