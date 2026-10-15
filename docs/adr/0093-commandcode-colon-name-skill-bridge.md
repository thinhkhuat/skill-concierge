# 0093 — The Command Code colon-name skill bridge (a normalized shelf + `addSkillsPath`)

- Status: accepted
- Date: 2026-10-15
- Deciders: Thinh: "cmd does not support skills with `:` in frontmatter `name` … many of my skills, large number
  actually, are done that way … I want to build the support to address such painpoint of mine, and many others I
  believe, as a cmd mod, inside my concierge, via the mod api supported by commandcode, similar with the concierge
  mod we did earlier." Scoping answers: a **generic** prefix bridge (any `prefix:slug`), a **generated shelf** of
  copies, **rewrite frontmatter and bodies**, shipped as a **separate mod file**.
- Relates to: ADR-0038 (Command Code adapter), ADR-0091 (the drop-in copy carries its checkout root), ADR-0092 (the
  package manifest). Implementation: `scripts/cmd_skill_bridge.py` (builder + verify + clean),
  `adapters/commandcode/skill-bridge.mod.ts` (the registering mod), `hooks/scripts/auto_bridge.py` (SessionStart
  refresh), the `commandcode.mods` manifest in `package.json`, and `tests/test_commandcode_bridge.py`.

## Context

Command Code validates a skill's frontmatter `name` strictly: lowercase letters, numbers and single hyphens, at
most 64 characters, and the skill's **own directory must carry that same name**. A skill that breaks a rule is
SKIPPED at discovery — it is not in `/skills`, not in the `/` menu, not in the model's skill catalogue, and
`/skill-name` cannot reach it. Claude Code has no such rule and resolves `ak:fix` to the `ak-fix` directory the
skill already lives in, so the agentkit corpus (`ak:fix`, `ak:plan`, …), plus personal skills like
`ck:copywriting` and `ckm:competitor`, loads there and never loads in Command Code.

Three facts found while scoping shaped the design, and each contradicts a plausible assumption:

1. **Every other layer already uses the DIRECTORY name.** `skills_discovery.py` sets a skill's name from
   `path.parent.name` (its `_namespaced_name` only prefixes plugin and catalog sources), so the concierge's index,
   its menu, the ledger and the reputation digests all say `ak-fix` while only the frontmatter says `ak:fix`.
   Nothing needed renaming to match the menu; the menu was already right, and Command Code was the only consumer
   reading the field that breaks.
2. **`~/.commandcode/skills` is a symlink to `~/.claude/skills` on a shared-shelf machine** (verified here), and
   `_commandcode_shares_personal_shelf()` makes `personal`-scoped rows invocable in Command Code because of it. So
   an in-place edit of a source would rewrite the Claude Code originals, and — separately — no enforcer change is
   needed to keep the menu honest, because a bridged skill's row is not foreign.
3. **The ModApi cannot inject a skill.** There is no `addSkill` verb. `cmd.addSkillsPath(path)` (an extra discovery
   location, collected at factory time) is the only seam that puts a skill into Command Code's own catalogue.

## Decision

1. **Materialize a shelf; never edit a source.** `scripts/cmd_skill_bridge.py build` copies every skill Command Code
   cannot load as it stands — an illegal `name`, or a legal name naming a different directory — into
   `~/.commandcode/skill-concierge-bridge/<normalized>/`, rewriting only the copy: the top-level frontmatter `name`
   becomes the normalized name, so the declared name and the directory agree. `verify` re-checks every copy against
   the rule and every SOURCE against a hash recorded at build time, which is what proves the originals are untouched.
2. **The shelf lives outside every skill root, deliberately.** `~/.commandcode/skill-concierge-bridge` is not
   `~/.commandcode/skills` (a symlink to the Claude shelf — writing there would overwrite originals), and it is not
   under `~/.claude/` either. Because both Claude Code and the concierge engine discover skills as
   `<root>/*/SKILL.md` under their own roots, the shelf is invisible to both: no duplicate index rows, no second
   menu entry, one corpus.
3. **A separate mod registers it.** `skill-bridge.mod.ts` calls `cmd.addSkillsPath(shelf)` once at factory time and
   registers nothing else — no hooks, so no per-turn cost and no interaction with the governance mod's
   `transformContext` ordering. It carries no baked checkout path (unlike the governance mod, which needs
   `INSTALLED_ROOT` to find its hook scripts): the shelf comes from `SKILL_CONCIERGE_BRIDGE_SHELF` or the same
   default the builder uses, so a copy is a true copy and `cmd --mod ./skill-bridge.mod.ts` works from a checkout.
   A missing shelf is one notice, never a failed session.
4. **Bodies are rewritten consistently, restricted to real prefixes.** In the copy, `<prefix>:<slug>` becomes
   `<prefix>-<slug>` — the slash-invocation form (`/ak:cook`) included — but only for prefixes seen in frontmatter
   that actually contain a colon, and never inside a URL, at a clock time, mid-word, or in a `name: ak:<slug>`
   template placeholder (the slug would start with `<`). Relative references to a sibling skill are re-resolved
   against the shelf, so a skill nested one level deeper (`ak-document-skills/ak-pptx`) loses exactly one `../`
   when it is flattened, and a container's own links to its children keep working because the children are copied
   along inside it (Command Code never scans a skill's own subfolders, so nothing there is mistaken for a skill).
5. **A collision is reported, never silent.** Two sources normalizing to one name keep the first (by sorted path)
   and log the loser — the same rule Command Code itself applies to duplicate names.
6. **The SessionStart hook refreshes the shelf, INLINE and throttled.** `auto_bridge.py` runs
   `cmd_skill_bridge.py build` at session start (the builder's own fingerprint check makes a no-change run a no-op,
   ~0.3 s; a full rebuild of ~120 skills is ~1.5 s), throttled through a stamp that `scripts/smoke.py` seeds like
   every sibling self-heal hook's, so a smoke run never churns live state. It is deliberately **not** detached —
   unlike `auto_reindex.py`: the shelf is what Command Code reads at startup, so a detached writer could rewrite a
   copy mid-discovery while gaining nothing.
7. **The package manifest ships both mods.** `package.json` `commandcode.mods` lists the bridge mod beside the
   governance mod, so `cmd mods add -g thinhkhuat/skill-concierge` installs both — the shelf itself still needs
   `install.sh` (or one `build`) to exist.

## Alternatives rejected

- **Rename the originals in place** (`name: ak:fix` → `ak-fix`). Smallest diff, and destructive twice over: the
  sources belong to their authors, and on this machine the path that looks like Command Code's is a symlink to the
  Claude shelf, so the edit would land in `~/.claude/skills`. Copying also keeps the bridge reversible with one
  `clean`.
- **Rewrite `ak:` at runtime in `transformInput`/`transformContext`.** A second mod rewriting the governance mod's
  input depends on registration order for its effect, slash commands never reach `transformInput` at all, and the
  model would still see a name Command Code cannot resolve. Fixing the artifact beats patching every turn.
- **Register one `addCommand` per bridged skill.** ~117 commands, no auto-invocation, no model catalogue entry, and
  a prompt-returning handler cannot start a skill the way a real skill load does.
- **Expose the shelf as a `settings.json` `skills` entry instead of the mod.** The ask was a mod, and
  `addSkillsPath` is the documented seam for exactly this job; the settings route would also mean two registrations
  of one directory for one purpose.
- **Edit the enforcer to advertise dash names.** Unnecessary: the engine names rows by directory, and Command Code
  treats `personal` as invocable via its shared-shelf check. An edit there would have been a change to the
  governance hot path bought for no behavior.
- **Rewrite references that escape the skills root to absolute paths.** It bakes one machine's layout into copied
  skill content. Such a reference is reported instead (see Consequences).

## Consequences

- On this machine, 117 skills become loadable in Command Code: 107 colon names (the agentkit corpus plus `ck:`/`ckm:`),
  3 space/uppercase names, 1 underscore name, 2 name/directory mismatches, and the 4 children of the
  `ak-document-skills` family. `/ak-fix` and `/skill:ak-fix` resolve, and the model's Command Code catalogue carries
  the same names the concierge menu has always shown.
- Verified pyflakes-clean and covered by `tests/test_commandcode_bridge.py` (25 tests; each key assertion was
  mutation-checked to fail when the behavior it guards is removed) plus the installer and sibling-installer suites.
- **One reported reference regression in the real corpus**: `ak-agentkit/references/task-taxonomy.md` points at
  `../../../rules/primary-workflow.md`, which resolves from `~/.claude/skills/...` and cannot from the shelf (a
  relative path from a shelf under `~/.commandcode` cannot reach `~/.claude/rules`). The builder reports it as a
  warning, and reports every copy whose reference resolved in the source but not in the copy — the pre-existing
  broken references in this corpus are not reported, because they were never this bridge's fault. Moving the shelf
  under `~/.claude/` would fix that one class at the cost of putting Command Code's derived data in Claude Code's
  config directory; the warning is the honest trade.
- The shelf is derived data and never hand-edited: `_bridge.json` names every copy, `clean` deletes only those, and
  `verify` fails if a manifest entry points outside the shelf or a source changed since the build.
- A skill added mid-session is bridged at the NEXT session start (the builder runs before Command Code discovers
  skills in the same start, and whether the hook lands before discovery is not asserted); `cmd_skill_bridge.py build`
  is the immediate path, and `install.sh` builds before it writes any config.
- The shelf is invisible to Claude Code and to the concierge engine by construction, so the bridge adds no duplicate
  skills anywhere; only Command Code, through the mod, sees it.
