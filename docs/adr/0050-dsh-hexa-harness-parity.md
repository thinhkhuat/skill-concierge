# ADR-0050: DSH hexa-harness parity — DeepSeek Harness as the sixth first-class citizen

| | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-09-01 |
| **Supersedes** | none |
| **Amends** | ADR-0033 (discovery mirror), ADR-0034 (offer isolation), ADR-0038/0039 (harness set), ADR-0042 (harness set) |

## Context

Following ADR-0033 (Codex), ADR-0038 (Command Code), ADR-0039 (OMP), and ADR-0042 (ZCode),
**DeepSeek Harness** (`dsh`, including the Oh-DSH Desktop Electron distribution) is added as the
sixth first-class citizen alongside Claude Code, Codex, Command Code, Oh My Pi, and ZCode.

DSH has a fundamentally different extension surface from every prior harness in the set:

1. **No Claude-format plugin manifest.** DSH does not read `.claude-plugin/` or `.codex-plugin/`
   manifests, and it does not fire the Claude-format `hooks/hooks.json` command hooks. Its
   extension unit is the **Cordis plugin** — YAML composition rows (`agent.cordis.yml`, or the
   user `cordis.patch.yml` patch layer) that mount npm packages providing tools, skills, and
   services.
2. **MCP via a bridge plugin.** DSH does not auto-connect a plugin `.mcp.json`. Instead the
   `@deepseek-ai/dsh-mcp-client` Cordis plugin connects stdio MCP servers and registers their
   tools on `ctx.tools` under `mcp__<serverName>__<rawName>` (verified in the shipped
   `dsh-mcp-client` source: `publicToolName(serverName, rawName)` = `mcp__skill-search__search_skills`).
   So the skill-search MCP server needs a Cordis row, not a per-harness `.mcp.json` merge — the
   contrast with ADR-0035's Codex `cwd` rewrite and ADR-0039's OMP native expansion.
3. **Per-turn enforcement via `agent/pre-step`.** DSH has no `UserPromptSubmit`/`PreToolUse`
   settings-hook surface (it is not a Claude-format harness), but its Cordis plugins receive the
   `agent/pre-step` event on every agent step — the same event the stock `tool-skill` plugin uses
   to inject skill instructions (verified in the shipped `dsh-tool-skill` source). That is the
   native replacement for in-generation enforcement: the same role `transformInput` plays for
   Command Code (ADR-0038) and `before_agent_start` for OMP (ADR-0039).
4. **Skill roots live under DSH_HOME.** DSH's filesystem skill provider
   (`dsh-skill-filesystem`) scans `DSH_HOME/skills` (personal) and `<cwd>/.dsh/skills` (project).
   DSH_HOME resolves to `~/.ohdsh` under Oh-DSH Desktop and `~/.dsh` under the legacy dsh CLI.
   The `.agents/skills` convention dir is scanned by DSH but is deliberately NOT a discovery
   root here — the hard-won ADR-0042 rule (realpath-dedup into `personal` on the shared-shelf
   machine; baking a per-machine symlink into the machine-global index is the ADR-0028 hazard).
5. **No skill plugin registry.** DSH loads skills from filesystem directories only — there is no
   `installed_plugins.json`-style manifest with per-plugin enablement. So the cross-harness twin
   test (ADR-0034) cannot consult a registry; it falls back to a filesystem twin on the DSH
   personal root, matching the ZCode filesystem-twin rescue (ADR-0042).

## Decision

### 1. Harness identity (`enforcer.py`, `ledger.py`; `doctrine.py`)

- `_running_harness()` returns `"dsh"`; new `UNDER_DSH` module constant. Precedence:
  `SKILL_CONCIERGE_HARNESS=dsh|deepseek-harness|oh-dsh|ohdsh` → `DSH_SHELL=1` env flag (set by
  DSH in agent subprocesses) → `.dsh/` or `.ohdsh/` path marker on the hook's install location
  (`CLAUDE_PLUGIN_ROOT` / `__file__` candidate loop) → existing fallbacks. No other harness sets
  `DSH_SHELL` and no Claude/Codex/OMP/ZCode install path contains `.dsh/` or `.ohdsh/`, so the
  new branches cannot fire under them.
- `doctrine.py _harness_adapt()` rewrites the Claude-default tool names for DSH: the MCP bridge
  names tools `mcp__skill-search__search_skills` (server name without the plugin namespace — the
  Command Code shape), and DSH has no slash-commands, so the `/skill-concierge:skill-search`
  hint is rewritten to the MCP search tool form.
- `ledger.py` stamps `harness: "dsh"` via a `_dsh_harness()` fallback with the same positive
  signals (payload/env precedence unchanged for the other harnesses).

### 2. Cross-harness isolation (`enforcer.py`)

- `_foreign_scopes()` under dsh: every other harness's scopes —
  `("plugin", "personal", "codex-personal", "codex-plugin", "commandcode-personal",
  "omp-personal", "omp-managed", "omp-plugin", "zcode-personal", "zcode-plugin")`. DSH reads only
  its own roots plus the shared `~/.agents/skills` convention; `personal` remains foreign because
  DSH does not read `~/.claude/skills`. `project:` scopes stay shared-by-construction (the
  existing invariant).
- `_invocable_plugin_ids()` under dsh returns `None` — there is no plugin registry manifest to
  consult; UNKNOWN filters nothing (the ADR-0033 union fallback).
- `_invocable_twin()` under dsh: a **filesystem twin** — `<name>/SKILL.md` exists under the
  resolved DSH home `skills/` directory. OSError = UNKNOWN = keep (the drop-only-on-positive-
  knowledge rule). The foreign annex (`_retrieve_foreign`) inherits the same rescue.
- Foreign annex label: `"claude/codex/omp/zcode/commandcode"` (compound, ZCode precedent).
- Installed offer: DSH roots index only the `dsh-personal` / `dsh-project:<path>` scopes, so
  cross-harness isolation is structural, exactly like ADR-0034's derivation.

### 3. Discovery mirror (`skills_discovery.py`)

`SKILL_DSH_ROOTS` (default ON, one-var revert — `=0` + reindex drops every dsh path + scope
byte-identically):

| Root | Scope |
|---|---|
| `DSH_HOME/skills` (`~/.ohdsh` preferred, `~/.dsh` fallback; `SKILL_DSH_HOME`/`DSH_HOME` env override) | `dsh-personal` |
| `<cwd>/.dsh/skills` | `dsh-project:<abspath>` |

- Home resolution mirrors `dsh-skill-filesystem`: explicit override → live `DSH_HOME` env →
  `~/.ohdsh` if it exists (the reference-machine shape) → `~/.dsh` legacy default.
- **`~/.agents/skills` is NOT a discovery root** (ADR-0042 rule reused; invocability is the
  session-side twin check's job).
- `_scope_for()` gains `dsh-personal` / `dsh-project:` branches (checked after zcode, before the
  generic `project:` fallthrough).
- `visible_scopes()` gains the dsh scopes; `auto_reindex._mcp_env()` forwards `SKILL_DSH_ROOTS`
  defensively (it joins the standing invariant tuple; not pinned in `.mcp.json` today).

### 4. MCP wiring (`adapters/dsh/`)

- `adapters/dsh/mcp.json` is the **reference descriptor** for the DSH installer — DSH does not
  read `.mcp.json`, but the descriptor documents the canonical env block in lockstep with
  `.mcp.json` for the parity checker, and the installer renders a **Cordis row** from it:
  `name: '@deepseek-ai/dsh-mcp-client'` with `serverName: skill-search`, `transport: stdio`,
  `command/args` pointing at the interpreter-form launcher (exec-bit-proof, ADR-0042 reason),
  and the env block including `SKILL_CONCIERGE_HARNESS: dsh` + `SKILL_DSH_ROOTS: 1`.
- `scripts/check_mcp_env_parity.py` covers `adapters/dsh/mcp.json` in lockstep.
- The interpreter form `/bin/bash` + absolute launcher path means a cache copy without exec bits
  cannot kill the server (the ADR-0042 failure class, closed the same way).

### 5. Enforcement vehicle — DSH Cordis plugin (`adapters/dsh/`)

- `adapters/dsh/skill-concierge.dsh.ts`: a Cordis plugin (phase-1 implementation) that
  - subscribes `agent/pre-step` (the verified stock-tool-skill event),
  - injects the doctrine once per session by returning `{ kind: "enter", messages: [...extra] }`
    with the doctrine as a user message,
  - runs `hooks/scripts/enforcer.py` on the latest user prompt and injects the
    `<hook_context source="skill-concierge">` mandate + ranked preview the same way,
  - fires the detached `auto_reindex`/`auto_overrides`/`auto_flywheel`/`auto_promote` self-heal
    batch at session start (throttled internally),
  - **fails open everywhere**: any handler throw degrades to a plain DSH session.
- `adapters/dsh/install.sh`: idempotent installer that writes the skill-search MCP row into each
  active DSH profile's `cordis.patch.yml` (desktop + tui, marker-managed, re-run safe), ensures
  launcher exec bits, and verifies the wiring.
- The plugin requires the Cordis loader to resolve a TS/JS module — production installs publish
  it as a DSH bundle; the installer documents the dev wiring.

### 6. Ops mirror

- `scripts/doctor.py check_dsh()` (WARN-only, fail-open when `DSH_HOME` is absent): profile
  presence, cordis.patch.yml skill-search entry (per active profile), launcher exec bit,
  enforcer presence.
- Version manifests bumped in unison (`.claude-plugin/plugin.json`,
  `.claude-plugin/marketplace.json`), keywords gain `dsh` / `deepseek-harness`, README harness
  list extended.
- **Ledger epoch boundary** at ship: enforcer + discovery changed, so pre-0.44.0 DSH-session
  rows are a different epoch and never pool with post-ship rates.

### 7. Accepted caveats (stated, not solved)

- **Ledger tool telemetry is Phase 2.** The DSH Cordis tool-call observation surface (the
  equivalent of OMP's `tool_result`) is not yet pinned from a live session; turn-boundary
  (`UserPromptSubmit`-equivalent) rows are captured, but `auto`/`search`/`get_skill` rows under
  dsh await the verified event surface.
- **Doctrine injection via `agent/pre-step` is phase-1 shape.** It rides the verified stock
  event and return shape, but the exact baseline-merging behavior (whether DSH's
  `dsh-agent-instructions` hard-backs the added message) needs a live-session validation.
- **No budget organ under DSH.** DSH has no `skillOverrides` seam; enforcement is the ranked
  offer + doctrine alone (the ZCode caveat, ADR-0042 §7, applies unchanged).

## Consequences

- DSH achieves governance parity on the semantic/enforcement axis: DSH-root discovery under
  `dsh-*` scopes, harness-correct foreign-scope isolation with a filesystem twin rescue,
  doctrine + per-turn mandate injection through the native `agent/pre-step` event, ledger rows
  stamped `harness: "dsh"`, an interpreter-form MCP row for the skill-search server, and a
  `check_dsh` doctor row.
- Claude Code, Codex, Command Code, OMP, and ZCode behavior is unchanged or strictly safer:
  detection branches cannot fire under their env/paths (selftest-pinned), and discovery is
  additive + flag-gated.
- Live evidence at ship time: enforcer/doctrine/ledger selftests green including the new dsh
  pins; `check_mcp_env_parity` green across six descriptors; installer idempotency verified on
  a sandboxed profile (desktop + tui patches).