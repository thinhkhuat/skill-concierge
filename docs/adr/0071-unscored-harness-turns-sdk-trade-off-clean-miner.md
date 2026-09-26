# ADR-0071 — Harness records open unscored turns; the SDK trade-off; a clean miner corpus; installers install HEAD's version

Status: Accepted (2026-09-27)
Amends: ADR-0068 decisions 1, 2, 3 and 5 (field rules, verdict turns, negation, the miner), and the
installers of ADR-0069 and ADR-0039/0042. Corrects ADR-0068, which is accepted and left as written.
(ADR-0070 is reserved for Track B.)
Evidence:
- `plans/reports/code-reviewer-260926-2340-v0526-diff.md` (review of 0.52.6: 3 Medium, 4 Low);
- the release gate on v0.52.7, which caught the installer version defect;
- runs of the 0.52.7 and 0.52.8 readers, launched together at 2026-09-27 00:27:10.

## Context

The review of 0.52.6 found four problems:
- **A false claim.** ADR-0068 said all 1,083 SDK prompts with an `sdk-…` entrypoint come from programs. The
  review found at least 25 typed by a person through an SDK-based desktop app, in 10 sessions. No record
  field tells them apart from that app's templates.
- **Team relays re-scored, not removed.** ADR-0068 said team relays were "out of the verdict turns", but
  a list-form relay no longer opened a turn, so its skip ruling merged into the turn before it, usually a
  `<local-command-stdout>` record, and was scored there.
- **Negation gaps.** The negation rule missed "(no longer continuing x)" and "(instead of a continuation)",
  and rejected "(not really a new task; continuing)".
- **Miner corpus.** Its rows depended on the directory listing (listing order and sorted order shared no
  balanced rows). 27 % of them were prompts subagents wrote. A bot framework's scheduler messages, which
  the harness records as typed by a person, made up 26 of its 440 conversational rows.

Separately, the v0.52.7 release gate showed that the installers read the version to install from the
working tree but export `git archive HEAD`. An uncommitted version change put HEAD's content in a cache
dir named for the new version.

## Decision

1. **The SDK rule stays, as a recorded trade-off.** An SDK prompt from a program entrypoint (`sdk-…`)
   is not work and not a miner prompt, even when a person typed it through an SDK app. The loss, as the
   0.52.6 review measured it: 8 prompts in the audit window, 15 of about 3,500 miner rows. The owner was
   asked and did not answer; the choice keeps any new template that app adds out of the gate's corpus,
   and it is reversible.
2. **A harness record in list form opens an unscored turn.** A non-`isMeta` user record whose content is
   a list of text or image blocks, but which hands over no work (a team relay, a program's prompt, an
   interrupt), starts a turn whose rulings are never scored. Its ruling answers the harness, so it is
   neither scored nor merged into the turn before.
3. **The continuation note is read by meaning.** A note is a fresh ruling when:
   - the continuation word itself is negated ("not / no / never / no longer / …n't continuing",
     "instead of / rather than / without a continuation"); or
   - the note names a new task or new work that is not itself negated ("not a new task", "isn't really
     new work" still read).

   After a comma, a later multi-word part names a skill only when its first word is a known skill: the
   installed catalogue or a skill this session used ("+ ak-git for the commit"). Otherwise "then re-run
   the tests" would read `re-run`.
4. **Bot scheduler messages are not work.** The four openings of that bot framework's scheduler
   ("Meanwhile, Heartbeat check", "…reply to your human partner", "…System health check", "…Component
   upgrades available") are neither work in the audit nor prompts in the miner. They end a miner turn.
5. **The miner skips subagent transcripts and reads files in sorted order.** Its selftest checks that
   both file orders give the same rows.
6. **Every exporting installer installs HEAD's version.** In a git checkout, the Codex, Claude Code, OMP
   and ZCode installers refuse, before any CLI call or write, when the working tree's
   `.claude-plugin/plugin.json` version differs from HEAD's.

## Consequences

- Audit, same minute (0.52.7 → 0.52.8), since 2026-07-04:
  - skip-ruling turns 976 → 963, false 603 → 591, search-backed 74 → 73, hook-authorized 299 → 299;
  - enforcer-run turns 309 of 679 → 300 of 669;
  - continuations 104: re-read 9, no earlier use 10 → 9, stale 2; organic 73: 2 / 8 / 1 → 2 / 7 / 1. One unit
    (`42a91b8d`) moved from "no earlier use" to gap 0, because a list-form SDK record now opens a turn
    between the fresh ruling and the continuation;
  - since 2026-09-19 the readers agree. The whole change comes from decision 2: the 0.52.8 reader with
    that rule removed gives 0.52.7's figures exactly.
- Miner (read-only `mine()`): 3,514 → 2,534 labelled rows (−980). The subagent skip removes 945 (927
  actionable, 18 conversational) and the bot openings 35 (9 actionable, 26 conversational). Balanced, the
  corpus is 396 + 396 and no longer depends on the directory listing. The live `prompt_intent`
  collection is still not rebuilt (held until after the Track B switch-over).
- Installer tests run each installer against the real checkout, so they now fail while a version
  change is uncommitted: commit first, then run the suite.
- **Corrections to ADR-0068:**
  - Its Context and decision 1: of the 1,083 `sdk-…` SDK prompts, at least 25 were typed by a person.
  - Its "Amends" line should also list ADR-0067 decision 2, since ADR-0068 decision 2 changed it.
  - Its "229 … 66 … 31 … 1" counts are prompt records the miner skipped, not the 257 rows removed. As rows
    (the 0.52.6 review's count): 177 SDK, 50 team, 29 notice, 1 auto-continuation.
  - The epoch-watch line "team relays … out of the verdict turns" was false until this release.
- Not read: the newer record field `turnOrigin` (`scheduled`, `peer`, `sdk`, …). Scheduled tasks are
  already caught by their `[Scheduled Task` opening.
- No standing-order change, so no new trail epoch.
- Revert: `git revert` of the release commit.
