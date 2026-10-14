# 0091 — The installed Command Code mod carries its checkout path; no shipped file names one machine

- Status: accepted
- Date: 2026-10-14
- Deciders: Thinh ordered "please work on the github issue: https://github.com/thinhkhuat/skill-concierge/issues/1" and,
  through AskUserQuestion, chose to ship it as 0.68.4 and to fix the `.mcp.json` home paths next (0.68.5). This record
  was written after his PR #2 decision prompt went unanswered, under his standing never-block rule. Awaiting his review.
- Relates to: ADR-0038 (Command Code adapter), amends its plugin-root resolution. Implementation: `5e62cde` (0.68.4) and
  `5f7b0ef` (0.68.5). Root-cause analysis: [`docs/issues/issue-1.md`](../issues/issue-1.md).

## Context

`adapters/commandcode/install.sh` copies `skill-concierge.mod.ts` to `~/.commandcode/mods/skill-concierge.ts`. In that
copy, `__dirname/../..` is `$HOME`. The mod's last fallback was one maintainer's checkout path, so on every other machine
it spawned no enforcer, ledger or exclusion echo. Its handlers fail open, so it said nothing, and install verify and
doctor compared bytes and passed. Issue #1 reported it with a live smoke: FAIL without `SKILL_CONCIERGE_ROOT`, PASS with
it. The reporter also showed that a symlinked mod is loaded under its link path, and that a `settings.json` `env` block
does not reach mods.

The same personal path was in the DSH, OMP and OpenCode adapters (unused there, because they load in place), in the
installer's project-folder slug, and in `SKILL_TRIGGERS` and `SKILL_SERVER_RECORDS` in every shipped MCP descriptor.

## Decision

1. **The copy carries its checkout path.** The installer writes the path into the copy's `INSTALLED_ROOT` line through
   `adapters/commandcode/mod_root.py`. Doctor reads and compares through the same module, so the two cannot disagree on
   what a correct copy is.
2. **Lookup order: `SKILL_CONCIERGE_ROOT`, the written-in root, the file's own location.** A candidate counts only when
   it holds `hooks/scripts/enforcer.py`, so a useless env value falls through. When none does, every script path is
   empty and the mod posts one `cmd.ui.notify` notice.
3. **The broken case fails loudly before and after install.** The installer refuses a root without the hook scripts
   before writing anything. Verify, and doctor's Command Code row (FAIL), reject an installed copy whose root cannot
   reach them, including a pre-fix copy with no `SKILL_CONCIERGE_ROOT`.
4. **No shipped file names one machine.** The sibling fallbacks are deleted. The project folder is named by
   `project_slug.py`, a port of Command Code's own `@sindresorhus/slugify` defaults, tested against its bundled copy.
   The MCP descriptors pin `${HOME}/…`, which the engine, `build_triggers.py` and doctor expand. The pin stays, so the
   records folder the server writes and the one doctor reads remain the same (caveats §17).
   `tests/test_no_personal_paths.py` scans shipped code and these JSON files.

## Alternatives rejected

- **A pointer file, `~/.commandcode/skill-concierge-root`** (PR #2, anhdtran22). It keeps the copy byte-identical to the
  repo file, which is its real advantage. It adds a second piece of install state that an uninstall leaves behind, and
  the copy and the pointer can disagree. Doctor's shared renderer already gives the byte comparison its meaning back.
  The PR arrived after 0.68.4 was written; it is correct on its own base.
- **A symlinked mod** so `../..` resolves: verified live by the reporter, no effect.
- **A `settings.json` `env` block:** verified live by the reporter, not passed to mods.
- **Reading the root from `~/.commandcode/mcp.json`:** couples the mod to the MCP entry, which a user may disable.
- **Dropping the descriptor pins and relying on engine defaults:** reopens the writer/reader split on
  `SKILL_SERVER_RECORDS` that caveats §17 forbids.

## Consequences

- A fresh clone, `./setup.sh` and `adapters/commandcode/install.sh` give a working Command Code install with no
  environment variable. Moving the clone needs a reinstall; doctor reports the moved case as FAIL.
- On machines where the adapter was inert, Command Code turns start writing `turn` and offer rows. Treat that as a break
  when comparing Command Code ledger windows there. The maintainer's machine is unaffected: its mod already worked.
- A checkout path with non-ASCII letters may get a different project-folder name than Command Code computes; the
  installer then skips that clone's project-local MCP override, and the user-scope entry still works.
