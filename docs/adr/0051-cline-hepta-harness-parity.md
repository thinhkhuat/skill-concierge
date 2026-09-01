# ADR-0051: Cline hepta-harness parity — Cline CLI as the seventh first-class citizen

| | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-09-01 |
| **Supersedes** | none |
| **Amends** | ADR-0033 (discovery mirror), ADR-0034 (offer isolation), ADR-0038/0039 (harness set), ADR-0042 (harness set), ADR-0050 (harness set) |

## Context

Following ADR-0033 (Codex), ADR-0038 (Command Code), ADR-0039 (OMP), ADR-0042 (ZCode), and
ADR-0050 (DSH), **Cline** (the Cline CLI / SDK agent runtime, verified against v3.0.60) is
added as the seventh first-class citizen alongside Claude Code, Codex, Command Code, Oh My
Pi, ZCode, and DeepSeek Harness.

Cline's integration surface, verified from the shipped `sdk/packages/core/src/hooks/` source
(`hook-file-config.ts`, `hook-file-hooks.ts`), `sdk/packages/shared/src/hooks/events.ts`,
the live install layout on the reference machine, and `cline --help`:

1. **Cline is a native file-hook harness — the enforcement vehicle needs NO TS adapter.**
   Cline discovers hook scripts from `<cwd>/.cline/hooks/` and the global `~/.cline/hooks`
   (`--hooks-dir` adds more), maps FILE NAMES to events (`UserPromptSubmit.*` →
   `prompt_submit`, `PostToolUse.*` → `tool_result`, `PreToolUse.*` → `tool_call`,
   `TaskStart.*` → `agent_start`, …), spawns them with a serialized JSON payload on stdin,
   and parses a JSON control object from stdout. This is the same shape as Claude Code's
   native settings hooks — the closest sibling of any harness in the set.
2. **Multiple same-event hook files co-fire, with contexts MERGED.**
   `hook-file-hooks.ts` `mergeHookControls()` joins every hook's `context` strings with
   `\n` across all files mapped to one event. So skill-concierge installs SEPARATE
   `UserPromptSubmit.cjs` / `PostToolUse.cjs` files and the operator's pre-existing
   extension-less bridges (`~/.cline/hooks/UserPromptSubmit` etc., which forward to Claude
   hooks) are never touched — no marker-patching of user-owned files, the failure class
   every other installer guards against.
3. **`prompt_submit` is the per-turn enforcement point with a context-injection return.**
   The payload carries `userPromptSubmit: {prompt, attachments}` + `taskId`; the control
   object `{cancel: bool, contextModification?: string}` (Cline 3.0.60 binary contract,
   confirmed by the operator's existing bridges and the upstream `HookControl` contract's
   `context` field) injects the text into the session. `cancel: true` is never used —
   skill-concierge is advisory, and hooks are disabled under `--yolo` anyway (Cline's own
   policy, not ours).
4. **Skills are SKILL.md directories under `~/.cline/data/settings/skills/` (personal) and
   `<cwd>/.cline/skills/` (project)**, invoked by the model via a `use_skill` tool, with
   name/description frontmatter and slash-command aliases. This satisfies the ADR-0001
   criterion (model-invocable SKILL.md skills) — Cline roots belong in discovery.
5. **MCP via `~/.cline/data/settings/cline_mcp_settings.json`** (`mcpServers` map with
   `command`/`args`/`env`/`disabled`). Cline expands NO `${CLAUDE_PLUGIN_ROOT}` templates,
   so the descriptor uses the interpreter form (`/bin/bash` + absolute launcher path) — the

## Decision

### 1. Harness identity (`enforcer.py`, `doctrine.py`, `ledger.py`)

- `_running_harness()` returns `"cline"`. Precedence: `SKILL_CONCIERGE_HARNESS=cline|cline-cli`
  → `.cline` path marker on the hook's install location → existing fallbacks. No other
  harness's env or path contains the marker, so the branch cannot fire elsewhere
  (selftest-pinned). `UNDER_CLINE` module constant added.
- `_foreign_scopes()` under cline: every OTHER harness's scopes — `plugin`, `personal`,
  `codex-*`, `commandcode-personal`, `omp-*`, `zcode-*` — Cline reads only its own two skill
  roots (item 4), the ADR-0050 DSH shape. `foreign` label:
  `claude/codex/omp/zcode/commandcode/dsh`.
- `_invocable_plugin_ids()` returns `None` under cline (item 6); `_invocable_twin()` adds
  the filesystem twin: `<name>/SKILL.md` under `~/.cline/data/settings/skills/` or
  `<cwd>/.cline/skills/` (OSError → keep, fail-to-non-blocking).

### 2. Discovery (`skills_discovery.py`) — `SKILL_CLINE_ROOTS`

- `cline-personal`: `~/.cline/data/settings/skills` · `cline-project:<abspath>`:
  `<cwd>/.cline/skills`. One shared collection, distinct scopes, additive; `=0` + a
  reindex reverts byte-identically. Forwarded by `auto_reindex._mcp_env()` (the
  index-shaping-flag invariant).

### 3. Enforcement vehicle — file-hook bridge (`adapters/cline/`)

- `adapters/cline/skill-concierge.cline-hook.cjs`: a zero-dependency Node bridge. Two modes:
  - `prompt_submit` (from the `UserPromptSubmit.cjs` shim): fires the SessionStart
    doctrine/self-heal chain ONCE per session — doctrine via `hooks/scripts/doctrine.py`,
    detached `auto_reindex`/`auto_overrides`/`auto_flywheel`/`auto_promote`; session state
    is a TTL-swept flag file under the durable home (`~/.claude/skill-concierge/`), because
    file hooks are stateless processes (the DSH adapter held this in memory inside a
    long-lived plugin; file hooks cannot). Then the per-turn leg: a ledger `UserPromptSubmit`
    row (harness `cline`) and `hooks/scripts/enforcer.py` on the prompt, whose
    `hookSpecificOutput.additionalContext` is wrapped in
    `<hook_context source="skill-concierge">` and returned as `contextModification`.
  - `tool_result` (from the `PostToolUse.cjs` shim): ledger capture — `use_skill` maps to
    the ledger's Skill-tool lane (name read from the raw parameters), and the MCP legs
    (`use_mcp_tool` with `tool_name` `…search_skills`/`…get_skill`) map to the
    `search`/`get_skill` lanes. Phase 1 carries the `use_mcp_tool` naming assumption
    (accepted caveat below); the mapping degrades to a no-op row when the shape differs.
  - **Fail-open everywhere**: any throw returns `{cancel:false}` — a dead bridge degrades to
    a plain Cline session.
- `adapters/cline/install.sh`: idempotent installer — generates the two event shims into
  `~/.cline/hooks/` (root-resolved absolute require paths, self-owned names only; NEVER
  touches the operator's extension-less bridge files), merges the skill-search MCP row into
  `cline_mcp_settings.json` (backup first, idempotent, `--no-mcp` opt-out), ensures the
  personal skills root exists, verifies, and prints the doctor row.
- `adapters/cline/mcp.json`: MANUAL FALLBACK descriptor (absolute interpreter form), in
  strict env lockstep with `.mcp.json` (`check_mcp_env_parity.py`). The installer's merged
  global row is the primary wiring; the fallback is for project-scoped `.cline/mcp.json`

### 4. Doctrine rendering (`doctrine.py`)

- `_harness_adapt()` cline branch rewrites the plugin-namespaced tool to Cline's
  `use_mcp_tool(server_name="skill-search", tool_name="search_skills")` form and the
  slash-command hint likewise. **Phase-1 assumption**: Cline 3.0.60's exact MCP tool
  surface was not verifiable from docs (the CLI is the new SDK runtime); the classical
  Cline `use_mcp_tool(server_name, tool_name)` contract is used and must be confirmed in a
  live session — the DSH ADR-0050 §7 caveat class. A wrong rendering degrades to prose the
  model can still resolve from the MCP server description; it cannot break a turn.

### 5. Ops mirror

- `scripts/doctor.py` `check_cline()` (WARN-only, fail-open): hooks dir + own shim files,
  MCP row, personal skills root.
- `scripts/check_mcp_env_parity.py` covers `adapters/cline/mcp.json`; `driftcheck.json`
  `paths_exist` mirrors the cline surface.
- Version manifests bumped in unison (0.43.1 → 0.44.0): `.claude-plugin/plugin.json`,
  `.claude-plugin/marketplace.json`, `.codex-plugin/plugin.json`, root `package.json`,
  CHANGELOG, README, `openwiki/quickstart.md`.
- **Ledger epoch boundary** at ship: enforcer + discovery changed, so pre-0.44.0 Cline rows
  (none exist yet) and post-ship rows are separate epochs per the AGENTS.md pooling rule.

## Consequences

- Cline achieves governance parity on the semantic/enforcement axis: cline-root discovery
  under `cline-*` scopes, harness-correct foreign-scope isolation with a filesystem twin
  rescue, doctrine + per-turn mandate injection through the native `prompt_submit` file
  hook, ledger rows stamped `harness: "cline"`, an interpreter-form MCP row, and a
  `check_cline` doctor row.
- Claude Code, Codex, Command Code, OMP, ZCode, and DSH behavior is unchanged or strictly
  safer: detection branches cannot fire under their env/paths (selftest-pinned), and
  discovery is additive + flag-gated.
- Accepted caveats (stated, not solved): the `use_mcp_tool` doctrine rendering and the
  `use_skill` parameter name await live-session verification; no budget organ under Cline
  (the ZCode/DSH caveat applies); hook-less under `--yolo` is Cline's own policy.

## Live evidence at ship time

- Cline 3.0.60 present on the reference machine; `~/.cline/hooks/` carries the operator's
  three extension-less bridges (contract verified against their headers); global MCP
  settings at `~/.cline/data/settings/cline_mcp_settings.json` with `mcpServers` map.
- Upstream source pinned: `sdk/packages/core/src/hooks/hook-file-config.ts`
  (`HookConfigFileName` map, extension set, search-path layering),
  `sdk/packages/shared/src/hooks/events.ts` (`prompt_submit` ↔ `UserPromptSubmitData`,
  `HookEventPayloadSchema`), `hook-file-hooks.ts` (`mergeHookControls` context join),
  `sdk/examples/hooks/README.md` (multi-hook coexistence, JSON contract).

  use — never both layers for the same server name.

   ADR-0042 failure-class closure (a cache copy without exec bits cannot kill the server).
6. **No skill plugin registry.** Cline plugins (AgentPlugin modules) contribute
   `rules|commands|mcpServers|hooks|tools` — never skills. Skill invocability is purely
   filesystem, so the cross-harness twin test (ADR-0034) has no registry to consult and
   falls back to a filesystem twin on the Cline personal root (the ADR-0042/0050 pattern).
7. **No native env identity signal.** Cline sets no `OMPCODE`-style flag in hook
   subprocesses; the adapter's bridge sets `SKILL_CONCIERGE_HARNESS=cline` explicitly (the
   Command Code/OMP pattern), with a `.cline` install-path marker as the fallback.
