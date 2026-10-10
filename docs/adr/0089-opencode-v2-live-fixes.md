# 0089 — OpenCode v2 live fixes: one plugin entry, an owned skills folder, native MCP tools, subagent scoping

- Status: accepted
- Date: 2026-10-09
- Deciders: Thinh ("resolve the issue with opencode v2 and make sure it works end to end, feature-parity with
  claude code", 2026-10-09 ~10:26)
- Amends: ADR-0085 (OpenCode v2 adapter). Its plugin-entry, skills-root and MCP-registration choices are replaced as
  described below; the rest stands.

## Context

Thinh's OpenCode TUI listed two `skill-concierge` server plugins, one of them `failed`. Live sessions on OpenCode
2.0.24 then showed five more defects. Every one was reproduced in a real OpenCode session before the fix:

1. **Duplicate plugin entry.** `~/.config/opencode/opencode.json` `plugins` held this checkout's plugin and a second
   copy from a versioned Claude Code cache (`…/plugins/cache/skill-concierge/skill-concierge/0.64.0/…`). Both copies
   declare the plugin id `skill-concierge`; OpenCode loads the first and fails the second. The installer
   de-duplicated by exact path only, so running it from any other copy appended a second entry. The cache-copy run
   was manual (an agent at 01:19, `logs/opencode-install-261009-0119.log`); no code calls the installer that way.
2. **Skills written into Claude Code's shelf.** On this machine `~/.config/opencode/skills` is a symlink to
   `~/.claude/skills` (and `~/.agents/skills` points there too). The installer copied the plugin's 10 skills into it,
   so Claude Code listed plain `doctor`, `setup`, `blocklist`, … beside `skill-concierge:doctor`. No skill of Thinh's
   was overwritten: none of the 10 names existed there before the first OpenCode install (Claude Code's skill list at
   16:07 on 2026-10-08), and every copy was byte-identical to the repo. The index never held an `opencode-personal`
   row for them: discovery keeps one row per name and resolves real paths, so the copies counted as `personal`.
3. **MCP tools hidden in Code Mode.** OpenCode v2 exposes MCP tools through Code Mode by default
   (opencode.ai/v2/docs/mcp-servers: "Code Mode is the default. Set `codemode` to false when a server's tools must
   stay on the provider's native tool list"). The doctrine and the ledger name the native tool
   `skill-search_search_skills`, which did not exist; a live model went looking for skill-search inside `execute`.
4. **Subagent sessions governed as top-level turns.** A subagent runs in a child session that fires the same
   `prompt` hook. It received the doctrine and the per-turn menu, and the ledger counted its prompt as a main-session
   turn. Claude Code fires no UserPromptSubmit inside a subagent (ADR-0020).
5. **A refused skill call logged as a use.** A blocklist-denied `skill` call still reached `execute.after` and wrote
   an `auto` ledger row.
6. **Another plugin's text ranked as the prompt.** Thinh's `context-injector` plugin prepends a
   `<system-context>…</system-context>` block to the first prompt of each session, before this plugin reads it. The
   enforcer ranked skills on that block plus the prompt, and the ledger stored the block as `q`.

## Decision

1. **One plugin entry.** A `plugins` entry is a copy of this plugin when its path, resolved the way OpenCode
   resolves it (`file://`, `~`, relative to the config file), ends in `adapters/opencode/plugin` and that folder's
   `package.json` is named `skill-concierge-opencode`, or the folder is gone and its path names `skill-concierge`.
   The installer keeps exactly one copy, pointing at the copy it runs from, in the position (and with the `options`)
   of the first, and leaves every other entry alone. Run from a plugin-cache copy, it refuses to take over from a
   checkout OpenCode already runs: the cache copy is deleted on the next update. Doctor warns when more than one copy
   is listed. The rule lives in `adapters/opencode/oc_config.py`, which the installer and doctor share.
2. **An owned skills folder.** The installer copies the plugin's skills into
   `~/.config/opencode/skill-concierge-skills/`, a folder only it writes, and registers that folder once in
   `opencode.json` `skills` (opencode.ai/v2/docs/skills: "Add more local directories … with the `skills` array"). It
   never writes into `~/.config/opencode/skills`. Copies an older installer left there are removed only when the
   folder holds nothing but a `SKILL.md` equal to the repo's current file or one of its committed versions; any
   other copy stays, with a message naming it. The engine indexes the new folder as `opencode-personal` (`OPENCODE_CONCIERGE_ROOT`, recorded in
   `vendor/skill-search/VENDORED.md`), the enforcer's OpenCode twin check reads it, and doctor checks the folder, the
   `skills` entry and that no old copies remain.
3. **Native MCP tools.** The plugin registers the skill-search server with `codemode: false`, so
   `skill-search_search_skills` and `skill-search_get_skill` are native tools, as in Claude Code.
4. **Subagent scoping.** At admission the plugin starts a non-blocking `ctx.session.get({sessionID})`; a child
   session carries `parentID`. Awaiting that call inside a session hook deadlocked the session in three of three live
   attempts, so the lookup is never awaited: its answer lands before the first model call. The turn is handled at that
   first model call (`context` hook): a child session gets no menu and no turn row, its doctrine call carries
   `agent_id` so doctrine.py's ADR-0020 rule (and its `SKILL_SUBAGENT_STOP` switch) applies, and its tool rows carry
   `agent_id` so ledger.py stamps them `sub`. A session whose lookup has not landed is governed as top level.
5. **Only completed calls are uses.** `execute.after` writes nothing for a call that is not `completed` or carries
   an error. Every prompt admitted before a model call gets its own turn row; the menu answers the latest.
6. **The user's words only.** A leading `<system-context>…</system-context>` block is removed before the enforcer
   and the ledger see the prompt. The prompt OpenCode stores is never edited.

## Consequences

- Live on OpenCode 2.0.24 (a private `opencode serve`, Thinh's global config, 2026-10-09): one plugin loaded; the
  model called `skill-search_search_skills` natively; `skill-search_get_skill` returned the skill with its
  `SKILL-EXCLUDES` line; `whereami` (blocklisted) was refused while the turn went on; the explore subagent saw neither
  the doctrine nor the menu while the main agent saw both; the ledger held `offer`, `turn`, `search` and `get_skill`
  rows for the main session, none for the child session, and no `auto` row for the refused call.
- `tests/test_opencode_plugin.py` drives the plugin through `tests/opencode_plugin_harness.mjs` (a fake OpenCode
  context, stub hook scripts); four of its five tests fail on the 0.65.0 plugin. `tests/test_opencode_install_dedupe.py`
  runs the real installer against throwaway configs.
- The 10 copies removed from `~/.claude/skills` on this machine are archived in
  `~/_ARCHIVE/skill-concierge-opencode-legacy-skills-20261009/`.
- The menu is now built at the first model call instead of at admission. The work is the same; it happens a moment
  later in the same turn.
- A running OpenCode service keeps the old plugin until `opencode service restart`.
- Known limits. A child session whose parent lookup has not landed by its first model call is governed as top
  level; in every live session observed the in-process lookup landed first, and no counter measures the fallback.
  A prompt aborted before any model call writes no turn row. Duplicate copies in a project config, a global
  `opencode.jsonc` or `~/.config/opencode/plugins/` are not checked. The plugin's per-session maps grow for the life
  of the service (about 100 bytes a session).
- Unchanged and noted: discovery still indexes one row per skill name, so under OpenCode the concierge skills arrive
  as `dsh-personal` rows (DSH's copies come first) and pass through the enforcer's filesystem twin check.

## Revert

`git revert` the 0.65.1 commit and re-run `adapters/opencode/install.sh` from that tree. That restores the 0.65.0
installer, which writes into `~/.config/opencode/skills` again.
