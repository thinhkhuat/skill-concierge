# ADR-0042: ZCode quintuple-harness parity — ZCode as the fifth first-class citizen

| | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-08-28 |
| **Supersedes** | none |
| **Amends** | ADR-0033 (discovery mirror), ADR-0034 (offer isolation), ADR-0038/0039 (harness set), ADR-0018 (launcher self-heal direction) |

## Context

Following ADR-0033/0034/0035 (Codex), ADR-0038 (Command Code), and ADR-0039 (OMP),
**ZCode** (`zcode`) is added as the fifth first-class citizen. ZCode is the first harness
in the set with **full native Claude-format plugin parity**: it recognizes `.claude-plugin/`
manifests (also `.zcode-plugin/` and `.codex-plugin/`), fires the plugin `hooks/hooks.json`
on all seven of its hook events with `additionalContext` injection, expands
`${CLAUDE_PLUGIN_ROOT}` in plugin hook commands (and injects `ZCODE_PLUGIN_ROOT` as an env
var), and auto-connects plugin-provided MCP servers from the plugin `.mcp.json` under the
`plugin:<plugin>:<server>` namespace. **No adapter vehicle is needed** — the contrast with
ADR-0038's mod and ADR-0039's extension module is the headline simplification.

The integration was validated from inside a live ZCode session on 2026-08-28 (plugin cache
v0.20.8, installed 2026-08-16 from the `skill-concierge` marketplace → GitHub repo). That
validation found four defects, each reproduced, not inferred:

1. **The MCP retrieval organ was dead in every ZCode session.** ZCode's marketplace cache
   copy shipped `bin/skill-search-mcp` as `-rw-r--r--` (Claude's cache copy of the same
   file: `-rwxr-xr-x`), so every server spawn died with `Permission denied` before the
   stdio handshake — no `search_skills`/`get_skill` tools existed in any session, while
   the doctrine kept instructing the agent to call them. ZCode's own `diagnosing-hooks`
   pitfall 4 names this exact class and the cure: invoke through an interpreter so the
   executable bit is irrelevant.
2. **The plugin cache was 13 versions stale** (0.20.8 vs 0.33.1): the running enforcer
   predated external-annex markers, cross-harness offer isolation (ADR-0034), dynamic
   annex sizing, harness stamps, and multi-intent shaping.
3. **ZCode sessions were mis-detected as `claude`.** `_running_harness()`'s marker set had
   no `.zcode` entry, so the ZCode hook path fell to the `claude` fallback — consulting
   Claude's plugin registry and settings instead of ZCode's
   (`~/.zcode/cli/plugins/installed_plugins.json`, `~/.zcode/cli/config.json`). Live proof:
   the session's offer included `add-harness-to-skill-concierge`, whose Qdrant point is
   scope `omp-managed` — an OMP-managed skill ZCode cannot invoke (absent from its skill
   list). The 0.20.8 enforcer (pre-ADR-0034) didn't even filter foreign scopes.
4. **A latent shared-venv downgrade ping-pong.** The ADR-0018 launcher self-heal resynced
   the venv engine FROM the deployed cache on any version mismatch. With a ZCode cache at
   0.20.8 against a 0.33.x-stamped venv, the first working ZCode MCP spawn would have
   *downgraded* the shared venv engine to 0.20.8 until the next Claude spawn re-upgraded
   it. (It never fired only because defect 1 killed the spawn first.)

**Load-bearing structural fact:** `~/.agents/skills` — ZCode's big skill shelf — is a
**symlink to `~/.claude/skills`** on this machine. ZCode's invocable universe is therefore
the already-indexed `personal` scope (2,551 points) plus ~27 skills in `~/.zcode/skills`
and its plugin cache. This integration is a *correctness* job (identity + isolation + MCP
wiring), not a corpus job.

## Decision

### 1. Harness identity (`enforcer.py`, `ledger.py`; `doctrine.py` needs nothing)

- `_running_harness()` returns `"zcode"`; new `UNDER_ZCODE` module constant. Precedence:
  `SKILL_CONCIERGE_HARNESS=zcode|z-code` → `ZCODE_PLUGIN_ROOT` env (absolute, non-falsy —
  the ADR-0034 falsy-candidate rule) → `.zcode/` path marker on the existing
  `CLAUDE_PLUGIN_ROOT` / `__file__` candidate loop → existing fallbacks. No other harness
  sets `ZCODE_PLUGIN_ROOT` and no Claude/Codex/OMP install path contains `.zcode/`, so the
  new branches cannot fire under them (selftest-pinned).
- `doctrine.py _harness_adapt()` has **no zcode rewrite**: ZCode flattens plugin MCP ids
  exactly like Claude Code (`mcp__plugin_skill-concierge_skill-search__search_skills`,
  verified live) and resolves plugin skills by the same `plugin:skill` alias, so the
  Claude-default rendering is already ZCode-correct. Pinned by a doctrine selftest case.
- `ledger.py` stamps `harness: "zcode"` via a `_zcode_harness()` fallback with the same
  two positive signals (payload/env precedence unchanged for the other harnesses).

### 2. Cross-harness isolation (`enforcer.py`)

- `_foreign_scopes()` under zcode: `("plugin", "codex-plugin", "codex-personal",
  "commandcode-personal", "omp-personal", "omp-managed", "omp-plugin")` — plus
  `"personal"` **only when `~/.agents/skills` does NOT resolve to `~/.claude/skills`**
  (`_zcode_shares_personal_shelf()`). The symlink is positive knowledge the whole
  `personal` scope is ZCode-invocable; on a divergent machine per-row survival moves to
  the twin check. Resolved per session, never baked into the machine-global index
  (the ADR-0028 hazard). `project:` scopes stay shared-by-construction (existing invariant).
- `_invocable_plugin_ids()` under zcode delegates to `_zcode_invocable_plugin_ids()`
  (Claude's registry is never consulted): ids from ZCode's LIST-shaped
  `installed_plugins.json` (installation checked via `installPath` on disk) plus the
  BUILTIN cache plugins (newest version dir present; builtins are enabled-but-unregistered),
  gated by `~/.zcode/cli/config.json` `plugins.enabledPlugins` (absent key = enabled —
  the Claude-mirroring rule) minus `suppressedBuiltins`. None only when nothing is
  readable — UNKNOWN filters nothing.
- `_invocable_twin()` under zcode: the plugin-id twin (namespaced row whose plugin is in
  ZCode's registry) OR a **filesystem twin** — `<name>/SKILL.md` exists under
  `~/.agents/skills` or `~/.zcode/skills` (`_zcode_readable_skill`; OSError = UNKNOWN =
  keep, the drop-only-on-positive-knowledge rule). The foreign annex (`_retrieve_foreign`)
  inherits both rescues through its existing `_invocable_twin` call.
- Foreign annex label: `"claude/codex/omp"` (compound, Command Code precedent).
- The chain-hint scope mirror unions the zcode scopes under the same
  `SKILL_ZCODE_ROOTS` flag (the ADR-0033 codex-mirror pattern).

### 3. Discovery mirror (`skills_discovery.py`)

`SKILL_ZCODE_ROOTS` (default ON, one-var revert — `=0` + reindex drops every zcode path +
scope byte-identically):

| Root | Scope |
|---|---|
| `~/.zcode/skills` | `zcode-personal` |
| `<cwd>/.zcode/skills`, `<cwd>/.agents/skills` | `zcode-project:<abspath>` |
| ZCode plugin cache | `zcode-plugin` |

- **`~/.agents/skills` is NOT a discovery root** — it realpath-dedups into `personal`
  anyway on the shared-shelf layout, and baking a per-machine symlink into the
  machine-global index is the ADR-0028 hazard. Invocability is the session-side twin
  check's job (§2).
- Plugin roots are **registry-enumerated** (`_zcode_plugin_roots()`: registry
  installPaths + newest builtin version dirs, enablement-filtered), never a wholesale
  cache glob — the ZCode cache is append-only exactly like Claude's, and an unfiltered
  glob indexes every stale version (the pollution class fixed for Claude in 0.19.0/0.25.0).
  Unreadable-everything degrades to the whole-cache glob with a warning (the
  blind-spot-beats-stale trade).
- `_scope_for()` checks `.zcode` INSIDE the shared `/plugins/cache/` block **before** the
  generic `plugin` fallthrough — without it, every ZCode plugin skill would silently land
  in Claude's `plugin` scope. The ZCode cache layout mirrors Claude's
  (`cache/<marketplace>/<plugin>/<version>/skills/`), so `_namespaced_name()` needed no
  change (verified live: `zcode-guide:diagnosing-hooks`).
- `visible_scopes()` gains the zcode scopes; `auto_reindex._mcp_env()` forwards
  `SKILL_ZCODE_ROOTS` defensively (not pinned in `.mcp.json` — the standing invariant).

### 4. MCP wiring (fixes defect 1; no per-harness descriptor)

- The shared `.mcp.json` moves to the **interpreter form**:
  `"command": "/bin/bash", "args": ["${CLAUDE_PLUGIN_ROOT}/bin/skill-search-mcp"]` —
  a cache copy without exec bits can no longer kill the server, in EVERY harness that
  imports the descriptor (Claude Code, OMP natively per ADR-0039, ZCode for plugin
  servers). This kills the failure class instead of chmod-ing after each update.
- `SKILL_SERVER_RECORDS` becomes an **absolute path** (was `${HOME}/...`): ZCode expands
  only a whitelist of templates for plugin servers, and config-file scopes expand none —
  the 0.21.1 `SKILL_TRIGGERS` class. Codex keeps its deliberate omission (ADR-0035).
- `adapters/zcode/mcp.json` is a **manual fallback only** (user-scope
  `~/.zcode/cli/config.json` → `mcp.servers`, absolute paths, no templates — config-file
  servers never expand them), with the ADR-0039 duplicate-server caution: do not run it
  alongside a healthy plugin layer. Covered by `check_mcp_env_parity.py`.
- `adapters/zcode/install.sh`: idempotent verifier/repair — chmod +x the cached bins,
  optional `--mcp-fallback` merge (backup first), doctor row, verification checklist.

### 5. Launcher self-heal becomes one-directional (`bin/skill-search-mcp`)

The ADR-0018 resync fires only when the deployed cache version is ≥ the venv stamp
(absent stamp = resync, the first-install case). A stale cache **warns on stderr and
serves the newer engine** — it must never downgrade the shared venv (defect 4). This is
strictly safer for every harness: the upgrade direction (a `/plugin update` shipping new
engine code) behaves exactly as before.

### 6. Ops mirror

- `doctor.py check_zcode()` (WARN-only, fail-open when `~/.zcode` is absent): cache
  presence, version parity vs SSOT, launcher exec bits. Live on the defect machine it
  flags exactly the two observed defects.
- Version manifests bumped in unison (`.claude-plugin/plugin.json`,
  `.claude-plugin/marketplace.json`, `.codex-plugin/plugin.json`, root `package.json`) +
  CHANGELOG + README + `openwiki/quickstart.md` (driftcheck mirrors). The release ritual
  gains: update the ZCode marketplace copy (Settings → Plugin Management) so the cache
  stays version-locked — `check_zcode` makes skipping it loud.
- **Ledger epoch boundary** at ship: enforcer + discovery changed, so pre-0.34.0
  ZCode-session rows are a different epoch and never pool with post-ship rates.

### 7. Accepted caveats (stated, not solved)

- **No budget organ under ZCode.** ZCode injects every discovered skill's full
  description; it has no `skillOverrides` seam (only binary skill disable). The
  enforcement organ (ranked offers) is the only lever. Revisit if ZCode grows a
  description-budget setting.
- **Chain-hint scope mirror asymmetry (pre-existing):** the mirror unions personal/plugin/
  codex/zcode scopes but not the commandcode/omp ones — an ADR-0039-era gap, unchanged
  here (noting it; fixing it is out of this ADR's blast radius).
- **Desktop-managed MCP lists** can override file-based config (ZCode diagnosing-mcp
  pitfall 11); the plugin-layer primary path avoids that surface entirely, and the
  manual fallback documents it.

## Consequences

- ZCode achieves full governance parity: SessionStart doctrine + self-heals, per-turn
  semantic enforcement with harness-correct offer isolation, cross-harness annexing with
  twin rescues, ledger rows stamped `harness: "zcode"`, and live `search_skills`/
  `get_skill` retrieval.
- Claude Code, Codex, Command Code, and OMP behavior is unchanged or strictly safer:
  detection branches cannot fire under their env/paths (selftest-pinned), discovery is
  additive + flag-gated, the launcher guard only removes the downgrade direction, and the
  `.mcp.json` interpreter form is the documented stdio shape in every consumer.
- The venv-downgrade hazard class is closed machine-wide: any harness's stale cache now
  warns instead of rewriting the shared engine.
- Live evidence at ship time: enforcer/doctrine selftests green including the new zcode
  pins; discovery smoke shows 9 registry/builtin plugin roots and correct scopes; the
  defect offer row (`omp-managed` `add-harness-to-skill-concierge`) now resolves
  non-invocable; `check_mcp_env_parity` green across five descriptors.
