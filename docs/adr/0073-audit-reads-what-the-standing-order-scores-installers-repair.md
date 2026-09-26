# ADR-0073 — The audit scores what the standing order binds; installers repair what doctor flags

Status: Accepted (2026-09-27)
Amends: ADR-0071 (decisions 2 and 3, the miner sample), ADR-0072 (the installers, doctor rows). Both are
accepted and left as written; this ADR records the corrections.
Evidence: `plans/reports/code-reviewer-260927-0045-v0528-diff.md` (post-ship review of 0.52.8: 3 Medium,
5 Low) and `plans/reports/code-reviewer-260927-0115-v0529-diff.md` (post-ship review of 0.52.9: 1 High,
4 Medium, 9 Low).

## Context

**The 0.52.8 review found three Medium problems in the audit and the miner:**
- **M1, later names.** A later name in a continuation had to be a "known" skill. But "known" meant every
  `SKILL.md` on disk: 4,395 names, test fixtures included. So `run`, `update`, `search` and `setup` counted
  as skills, and "USING: study, then run the tests (continuing)" read as `['study', 'run']`.
- **M2, decision 2 applied to lists only.** ADR-0071 decision 2 says a ruling that answers the harness is
  not scored, but only list-form records got that treatment. The review counted 676 of 964 scored skip
  turns opened by string records the reader itself classes as not work.
- **M3, the miner sample.** The balanced corpus took the first rows in file order: 396 actionable rows
  from the first 28 of 50 projects, sorted by name.

**The 0.52.9 review found one High problem:** doctor told users to re-run the Claude Code installer in
two states it could not repair.
- A missing install dir made the script exit 1 with no message: a failing command substitution under
  `set -e`.
- A missing launcher at the current version failed the verify on every run.

**Four Medium problems:**
- **Unreadable git.** A checkout git cannot read went down the plain-copy branch and shipped an untracked
  `.env`.
- **Registry repoint.** It matched on the scope name only, so other projects' records were rewritten.
- **Siblings not fixed.** The fixes were not carried to the sibling installers (Command Code quoting;
  OMP and ZCode registry writes).
- **Codex dead ends.** A Codex listing error read as "not installed", non-JSON output crashed the
  script, and a complete cache that Codex did not list failed on every run.

## Decision

1. **A later continuation part is read only as a real skill name.** A multi-word later part counts when
   its first word is a skill this session already used, or a hyphenated installed skill. The catalogue
   holds installed skills only: `tests/`, `fixtures/` and `marketplaces/` copies are skipped. "then run
   the tests" is prose even where a skill is named `run`.
2. **What the standing order binds is scored.**
   - Rule 4 of the standing order makes a notification's content and a message's content a task. So a
     turn opened by a task notification, a cross-session message or another harness string stays
     scored.
   - A program's prompt opens an unscored turn in either storage form. That is a `system` prompt, or an
     SDK prompt from a program entrypoint, whose text would be work had a person sent it. The harness's
     own notifications in an SDK-launched session carry the same fields and stay scored.
   - The report adds one line: the skip verdicts on turns a work prompt opened, beside the headline.
     The headline is mostly harness-message turns, and must not be read as the work-prompt rate.
   - Wording fix to ADR-0071 decision 2: only the *skip rulings* in an unscored turn are unscored. A
     continuation in it still counts.
3. **A skip ruling a resumed session copied counts once.** The copy in the session's own file wins, the
   same rule continuations already follow.
4. **Negation edges.** Only an adverb (`really`, `actually`, `yet`, `strictly`, `quite`, `longer`) or `be`
   may stand between a negator and "continu…". So "(won't stop continuing)" stays a continuation and
   "(not actually continuing)" does not. "(no need for a new task)", "(not a brand new task)" and
   "(new task? no, …)" negate the new task.
5. **Ranking ties break by name**, so two runs agree whatever the hash seed.
6. **The miner samples by a hash of the prompt text, not by file order.** The sample is the same for
   the same prompts on any machine. It is spread across projects in proportion to their rows, instead
   of taking the first projects by name.
7. **Installers repair what doctor flags, and refuse what they cannot copy safely.**
   - **Claude Code and OMP:**
     - A missing or unreadable manifest falls back to the registry value; the script no longer exits
       silently.
     - A current version with a missing dir or launcher is exported again from the checkout.
     - A lost exec bit is repaired without a CLI call.
     - ZCode has no fast path; it exports on every run, so it cannot report a broken copy as current.
   - **All four exporting installers:**
     - A `.git` checkout that git cannot read is refused before any CLI call or write.
     - The check reads the version at HEAD, so a staged but uncommitted change is refused too.
     - Exports are staged and swapped in with mode 0755, and a failed copy removes its staging dir.
     - The replaced tree moves to a hidden `.<version>.replaced-<time>`, which skill discovery skips.
       Only the newest such copy is kept.
   - **Registry repoint (Claude Code, OMP, ZCode):**
     - It changes only the record the run read: scope and project for Claude Code and OMP. ZCode's
       registry holds one record per plugin id, with no scopes.
     - The backup is written only after the concurrent-change check passes. It sits beside the registry
       path the harness reads, not a symlink's target, and the newest five backups are kept.
     - OMP reads its record with a unit separator.
   - **Codex:**
     - A failed or non-JSON `codex plugin list` is reported with Codex's own message, and nothing is
       changed.
     - The fast path also needs Codex to list the plugin; otherwise the refresh path's `add` registers
       it.
     - An incomplete copy left after `add` is replaced.
     - A record with no `enabled` field counts as enabled everywhere.
     - HEAD's `.codex-plugin/plugin.json` must carry the same version as `.claude-plugin/plugin.json`.
   - **Command Code:** passes paths to Python as arguments.
8. **Doctor.**
   - The Codex row requires `.codex/hooks.json` as the installer does.
   - The Claude Code row reports an unreadable manifest (or no installPath) as a finding. Its `version`
     is then `None`, because the registry's value is a claim, not what is deployed.
   - The selftest covers the Codex MCP and hooks findings and the ZCode missing-launcher finding.
9. **Installer tests are hermetic.** `tests/installer_env.py` builds PATH from the fake CLIs plus links
   to system tools, so no real `claude`, `codex`, `omp`, `zcode` or `docker` can run. It also sets
   `PYTHONDONTWRITEBYTECODE=1`, so no Python writes a cache into the throwaway HOME.

## Consequences

- **Audit, 0.52.9 → this reader, measured side by side at 01:44:57-01:45:34 with `PYTHONHASHSEED=0`.**
  - Since 2026-07-04:
    - skip turns 967 → 944, false 592 → 576, search-backed 73 → 69, hook-authorized 302 → 299;
    - enforcer-run turns 672 → 655;
    - continuations 108 in both; sessions flagged self/meta 129 in both.
  - Attribution, by switching one rule off at a time:
    - the resumed-copy rule removes 19 turns (the review counted 19);
    - the program-prompt rule removes 4.
  - Turns a work prompt opened: 164/277 false. The other 667 skip turns answer a notification, a
    message or another harness record.
  - Since 2026-09-19 the headline is unchanged (27/190), and the work-prompt line is 7/31.
- **Built and discarded before shipping: a wider program rule.** It also counted every string record in
  an SDK-launched session as a program's prompt, and moved 967 → 577. The harness's own messages there
  carry `promptSource: sdk` too, so the rule now also requires prompt-shaped text.
- **Miner (read-only `mine()`, 01:46):** 2,537 rows, balanced 396 + 396. The actionable half now comes
  from 32 projects instead of 28. The corpus is not rebuilt; that stays held until after the Track B
  switch-over.
- **Corrections:**
  - ADR-0071 decision 2 and the 0.52.8 epoch-watch line overstated what was unscored (decision 2 above).
  - ADR-0072 said the Codex copy on this machine was at 0.45.0. The owner's Codex install at 01:02:49
    moved it to 0.52.9.
  - The 0.52.9 CHANGELOG's "15 new installer tests" were 13 new and 2 changed.
- **Still open:**
  - `setup.sh` and `bin/skill-search-mcp` still paste a path into Python source; they are Track B files
    and are fixed there.
  - One `sdk-cli` string record with no `promptSource`, found by the 0.52.8 review, stays scored: its
    fields do not name a program.
  - For OMP and ZCode, the concurrent-change abort and the symlinked-registry mode are not covered by a
    test of their own (the Claude Code tests cover the same code shape).
  - `-y` stays unconditional.
  - `CODEX_HOME` and `CLAUDE_CONFIG_DIR` are still ignored.
- No change to the standing order, the enforcer or the engine, so no new trail epoch. The audit reader
  changed: compare skip-turn counts only within one reader version.
- Revert: `git revert` of the release commit.
