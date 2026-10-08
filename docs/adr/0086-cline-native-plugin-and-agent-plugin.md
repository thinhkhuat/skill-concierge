# 0086 — Cline: native code plugin + Agent Plugin (Claude Code parity on Cline 3.0.69+)

- Status: accepted
- Date: 2026-10-08
- Deciders: Thinh
- Supersedes: ADR-0051's file-hook vehicle (the fallback is removed; ADR-0051's decisions on skill
  roots, MCP naming and the enforcer lane stand except where this record says otherwise)

## Context

ADR-0051 integrated Cline through its file hooks: `UserPromptSubmit.cjs` delivered the enforcer
menu and the doctrine, `PostToolUse.cjs` the ledger and the exclusion echo. Reading the installed
Cline 3.0.69 runtime (`@cline/core` and `@cline/agents` dist, re-checked on 3.0.70 the same day)
showed four things that change the design:

1. **The file hooks that inject context are muted.** `prompt_submit` runs from `onEvent` with
   `detached: e.detachAsyncHooks ?? true` and its result is never read; `agent_start` runs
   detached unless `blockingRunStartHooks` is set, and the CLI never sets it. Neither the menu nor
   the doctrine reached the model through file hooks on this version. A `PreToolUse` file hook
   does block, but Cline maps its `cancel: true` to `stop`, which ends the whole run.
2. **Code plugins can do the job.** Cline loads TypeScript plugin modules (`AgentPlugin`:
   `manifest`, `setup(api, ctx)`, `hooks`). `api.registerRule` puts text in the system prompt;
   `beforeTool` returning `{ skip, reason }` refuses one call and the run continues; `afterTool`
   and `beforeTool` accept `appendContext`, which Cline adds as a `<hook_context>` message.
3. **Two traps in that API.** `beforeModel`'s `messages` *replaces* the request's message list
   (`n = { ...n, messages: W(s.messages) }`), so a hook that returns only its own message wipes
   the conversation — the defect that kept the first attempt (branch `cline/0a565`) from merging.
   And `beforeRun` runs *before* the run's input message is added, so it cannot see the prompt.
4. **Plugins run in a sandbox with a 3-second hook limit** (`Fc(e.hookTimeoutMs, 3000)`, no env
   override). The full enforcer takes 2–4 s live, because Command Code — the owner's first Jev
   rung, with a 5.5 s span (ADR-0079/0080) — answers in 0.8 s at p50 and 1.6 s at p90 per call
   and the router makes two calls.

Cline 3.0.69 also loads **Agent Plugins** (agent-plugins.org): a folder in `~/.agents/plugins/`
with `plugin.json`, `mcp.json` and `skills/`, whose skills Cline lists as `<plugin>:<skill>` and
whose MCP servers it starts itself. Its loader accepts only six SKILL.md frontmatter keys (`name`,
`description`, `license`, `compatibility`, `metadata`, `allowed-tools`) and rejects any skill with
another; the plugin's own skills carry Claude Code's `user-invocable`, `argument-hint` and
`next-skills`.

## Decision

The owner chose (2026-10-08): refuse only the blocked call, ship both plugin forms, rework now.

1. **The code plugin is the primary Cline vehicle** (`adapters/cline/skill-concierge.cline-plugin.ts`).
   The installer writes the one-line loader `~/.cline/plugins/skill-concierge.ts`, which re-exports
   the module from this checkout, so there is no installed copy to go stale (Cline skips symlinks in
   that folder, hence a generated file).
   - `setup`: the SKILL-FIRST doctrine as a system-prompt rule (`doctrine.py`'s Cline rendering, read live,
     which names the Agent Plugin's tool `skill-concierge_skill-search__search_skills_<suffix>`) and the detached self-heal batch, which also re-syncs the Agent Plugin.
   - `beforeModel`: reads the run's prompt from the request (stripping Cline's `<user_input>` wrapper,
     skipping hook context and runtime reminders), writes one `UserPromptSubmit` ledger row per run,
     and inserts the menu right after the prompt, **returning the full message list**. Each run starts
     two enforcer passes: the full one (Jev, Command Code first, untouched) and a fast preview
     (`ENFORCER_JEV_ROUTER=0`, about 0.3 s, `ENFORCER_LEDGER=0` so the turn keeps one offer row). The
     first model call carries the full menu when it lands within 2 s and the preview otherwise; later
     calls in the run carry the full menu once it lands.
   - `beforeTool`: `skill_guard.py` decides; a deny returns `{ skip, reason }` — that one call is
     refused and the turn continues, as in Claude Code.
   - `afterTool`: the ledger row and the "not for" echo via `appendContext`; the tool's output is never
     rewritten; a refused or failed call writes no row. MCP tool names match with Cline's hash suffix
     (`skill-concierge_skill-search__get_skill_d998a651`).
   - Subagents (`snapshot.parentAgentId`) get no menu and write no turn row (ADR-0020).
   - Every hook answers within 2 s and fails open. Cline's 3 s clock starts when it sends the call,
     so the conversation's trip into and out of the sandbox counts too; an overrun fails the turn.
2. **The Agent Plugin ships the skills and the MCP server.** `adapters/cline/agent_plugin.py` builds
   `~/.agents/plugins/skill-concierge/` from the checkout: `plugin.json` (`adapters/cline/agent-plugin.json`
   plus the SSOT version), `mcp.json` (the `skill-search` server generated from `.mcp.json` in Cline's
   schema: `bash <checkout>/bin/skill-search-mcp` and the same env, so it cannot drift), and `skills/` as
   generated copies that drop the frontmatter keys Cline rejects (Claude Code reads them; Cline does
   not) and resolve `${CLAUDE_PLUGIN_ROOT}` to the checkout path. It writes only changed files, prunes
   files it added, refuses a symlinked destination (it would write into the link's target), and its
   `check` mode reports drift. Copies are the price of Cline's frontmatter rule; the re-sync at
   each Cline session start and doctor's drift check keep them honest.
3. **The enforcer offers Agent Plugin skills to Cline.** Under Cline a `plugin:skill` row passes the
   plugin gate and the twin test when `~/.agents/plugins/<plugin>/` holds `plugin.json` and
   `skills/<skill>/SKILL.md` (`_cline_agent_plugin_skill`). Plain rows keep ADR-0051's roots.
4. **`ENFORCER_LEDGER`** (default ON) — `=0` makes an enforcer run write no offer row. Set only by
   the plugin's preview pass.
5. **Cline's system prompt joins the harness-message lane.** On its `claude-code` provider Cline runs
   Claude Code underneath, and that inner session's `UserPromptSubmit` carries Cline's entire system
   prompt ("You are Cline, an AI coding agent…"); it now skips before any embed or Jev I/O
   (`_HARNESS_MSG_RE`, mirrored in `build_keep_off.py`).
6. **File hooks are retired.** The owner decided to delete the fallback outright: the bridge
   (`skill-concierge.cline-hook.cjs`), the shim templates (`adapters/cline/hooks/`), the manual
   `adapters/cline/mcp.json`, `tests/test_cline_bridge_modes.py` and `install.sh --file-hooks` are
   gone. On Cline 3.0.69+ the fallback delivered no menu and no doctrine (Context, point 1), and
   its blocklist deny (`cancel`) ended the whole turn, where the owner chose to refuse only the one
   tool call, which the plugin's `beforeTool` `{ skip, reason }` does. `install.sh` takes no options
   (any option exits 1 with a usage line) and retires leftovers of the old installer: the four
   shims in `~/.cline/hooks/` that carry its "GENERATED by adapters/cline/install.sh" marker (an
   operator's own hook file is left alone) and its skill-search row in
   `~/.cline/data/settings/cline_mcp_settings.json` (backed up first; a row not pointing at
   `bin/skill-search-mcp` is left alone; `adapters/cline/mcp_row.py` does the removal). doctor's
   Cline row checks the plugin loader and the Agent Plugin only, and warns while an old shim or the
   old MCP row remains, because a turn would be governed twice. The plugin now sets
   `SKILL_CONCIERGE_HARNESS=cline` when it runs the hook scripts, which the bridge used to do.

## Consequences

- Verified live on Cline 3.0.70, `openai-codex` provider, local runtime host: the model sees the
  prompt, the menu (first call; the full Jev menu landed in 2.0–2.3 s in three runs) and the doctrine
  rule; all ten `skill-concierge:*` skills and the hashed MCP tools are listed; a blocklisted skill is
  refused with the blocklist's own reason and the run completes; a `get_skill` result arrives whole and
  the exclusion echo follows as hook context; a four-call turn writes one turn row and one offer row.
- **Hub host limit.** When the CLI attaches to a running hub — here the VS Code extension's sidecar —
  the hub builds the session with `configExtensionCount: 0`, so no plugin runs, and that sidecar also
  fails to start its plugin sandbox (`Cannot find module 'jiti'`). `CLINE_SESSION_BACKEND_MODE=local`
  makes the CLI run the session itself. Whether a standalone hub loads plugins is unverified.
- **Remaining gaps against Claude Code.** The first model call usually carries the embedding
  preview, not the whole-shelf ranking (the full menu landed in 2.0–2.3 s live, past the 2 s wait),
  while the ledger's offer row records the full menu; the menu is not stored in the transcript, so a
  provider's prompt cache misses on the previous turn's tail (inference, not measured); a plugin
  sandbox restart forgets the run, so that turn can log a second turn row; doctrine and rule text
  reach subagents too (a rule has no per-agent scope); no budget organ (the ZCode/DSH caveat); the
  Agent Plugin's skills are copies until the next Cline session re-syncs them; doctor warns while
  `CLINE_SESSION_BACKEND_MODE` is not `local`.
- **Epoch boundary.** Cline turns now carry real menus and one offer row per turn, and claude-code-
  provider inner turns fall into `harness_skip`: Cline ledger metrics before and after 0.63.0 are
  different epochs and must not be pooled.
