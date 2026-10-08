# 0085 — OpenCode v2 as the eighth harness (octa-harness parity)

- Status: accepted
- Date: 2026-10-08
- Deciders: Thinh
- Supersedes: none (extends ADR-0033/0038/0039/0042/0050/0051 — the per-harness adapter series)

## Context

skill-concierge runs as a first-class governance layer on seven harnesses (Claude Code, Codex,
Command Code, OMP, ZCode, DSH, Cline). OpenCode v2 ships a real plugin system
(`Plugin.define({ id, setup(ctx) })`, loaded from `plugins` in `opencode.json(c)` or
`.opencode/plugins/`) with hook surfaces that map cleanly onto every Claude Code concept the
plugin uses today:

| Claude Code concept | OpenCode v2 surface |
| --- | --- |
| `.mcp.json` + `${CLAUDE_PLUGIN_ROOT}` auto-connect | `ctx.mcp.transform` → `editor.set("skill-search", …)` |
| `UserPromptSubmit` enforcer (additionalContext) | `ctx.session.hook("prompt")` + `ctx.session.hook("context")` system-part push |
| SessionStart doctrine | once-per-session system part via the `context` hook (plugin setup is per-location, not per-session) |
| SessionStart self-heal batch | detached fire at plugin `setup` (scripts are internally throttled) |
| `PreToolUse(Skill)` blocklist deny | `ctx.permission.hook("evaluate")` with `event.action === "skill"` → `effect = "deny"` |
| `PostToolUse` ledger + exclusion echo | `ctx.tool.hook("execute.after")` |

OpenCode v2 skill discovery (documented, verified against opencode.ai/v2/docs/skills): global
`~/.config/opencode/skills`, project `.opencode/skills` (walked to the project root), plus
compatibility reads of `~/.claude/skills`, `~/.agents/skills`, and their project-level twins.
Skills are invoked by the model through the native `skill` tool (`{"id": …}`), gated by the
`skill` permission action.

## Decision

1. **Eighth harness id `opencode`**, following the ADR-0051 (Cline) precedent in every layer:
   engine discovery roots, enforcer scope tuples, ledger classification, doctor row, installer,
   adapter bridge, versioned docs.
2. **Engine roots** (index-shaping, one-var revert): `SKILL_OPENCODE_ROOTS=0` drops both paths +
   scopes. Roots: `~/.config/opencode/skills` → scope `opencode-personal`; `<cwd>/.opencode/skills`
   → `opencode-project:<dir>` (CWD-relative at reindex time, the CLINE_PROJECT_ROOT pattern).
   `SKILL_OPENCODE_ROOTS` joins `ENGINE_ENV_KEYS` (the reindex-forwarding invariant).
3. **`personal` is invocable from OpenCode** (documented compatibility read of `~/.claude/skills`)
   — the OMP/Codex lane, not the shared-shelf-symlink lane. Foreign from OpenCode: `plugin`
   (no plugin-cache read), every other harness's exclusive scopes, and `claude-synced`.
4. **Namespaced plugin rows (`x:y`) are never invocable from OpenCode** (no Claude plugin
   registry): `_plugin_gate_ok` follows the DSH/Cline rule. The plugin's OWN skills reach
   OpenCode the DSH way — the installer re-roots `skills/*/SKILL.md` copies into
   `~/.config/opencode/skills/<name>/` (plain names, `opencode-personal` scope), NOT via
   `ctx.skill.transform` (rejected: a second registration path with precedence interactions
   and nothing the disk copies don't already give; the transform would also register ids the
   index cannot see, splitting provenance).
5. **The adapter** is `adapters/opencode/plugin/` — a zero-build TS plugin
   (`export default { id: "skill-concierge", setup(ctx) }`, the local-plugin shape; no
   `@opencode/plugin` import needed, matching local plugins on this machine) plus
   `adapters/opencode/install.sh` which: registers the plugin package path in the global
   `~/.config/opencode/opencode.json` `plugins` array (safe_write, backup, preserve-all),
   re-roots the plugin skills, fires a reindex, and verifies. Fail-open everywhere: any spawn
   error degrades to no injection, never a blocked turn — the repo doctrine; the two denying
   gates (skill blocklist via the permission hook, which delegates to skill_guard.py) fail OPEN
   on internal error exactly as in Claude Code.
6. **Doctrine + enforcer delivery**: per-session doctrine once, per-turn enforcer block on the
   first agent-loop model call after each admitted prompt (a pending flag set in the prompt
   hook). Mutating `event.prompt.text` is rejected — prompt edits become the canonical persisted
   user input; system parts carry governance text instead.
7. **Tool-name lanes**: OpenCode's native `skill` tool (input key `id`) joins the ledger's
   activation lane (`_NAME_KEYS` += `id`, tool name `skill`); the transform-registered MCP
   server's effective tool ids (`skill-search_search_skills` / `skill-search_get_skill`) join
   `SEARCH_TOOLS`/`GET_TOOLS`.

## Consequences

- OpenCode gains full Claude Code parity: skill-search MCP, SKILL-FIRST doctrine, per-turn
  enforcer offers, blocklist deny, exclusion echo, invocation ledger, self-heal batch, and the
  plugin's own ten governance skills.
- The enforcer runs via `SKILL_CONCIERGE_HARNESS=opencode` set explicitly by the adapter (the
  Command Code/OMP/Cline pattern); `.opencode` path-marker fallback covers re-rooted copies.
- Doctor grows a WARN-only `check_opencode()` row (no `~/.config/opencode` → one "not installed"
  line, never a failure).
- The vendored engine patch (skills_discovery.py, server.py `_ORIGIN_HEADS`) is recorded in
  `vendor/skill-search/VENDORED.md`.
- Ledger metrics for the new harness start a fresh epoch (ADR guardrail: never pool across the
  config change).
