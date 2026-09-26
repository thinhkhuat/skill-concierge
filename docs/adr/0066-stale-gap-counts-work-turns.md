# ADR-0066 — The stale-continuation gap counts work turns

Status: Accepted (2026-09-26)
Amends: ADR-0065 decision 1 (the stale proxy and continuation parsing). Corrects ADR-0065's stale
figures, which is accepted and therefore left as written.
Evidence: `plans/reports/code-reviewer-260926-2120-v0523-diff.md` (review of 0.52.3: 1 Medium, 7 Low).

## Context

ADR-0065 flagged a continuation as likelier new work when its skill was last used more than 5 turns
earlier. The audit opens a turn on every text-only user record — Stop-hook feedback, slash-command
records, notifications, cross-session messages, compaction summaries — about 11,000 of them against roughly
3,400 typed prompts. So the 5-turn gap often spanned one or two real prompts, and 15 of the 16 flagged
continuations were same-task continuations split by hook records.

## Decision

1. The stale gap counts **work turns**: a user record whose content is a string, not `isMeta`, not a
   compaction summary, and not opening with a harness, local-command, bash-output, notification or
   Stop-hook head. The verdict turn (a reply boundary) is unchanged — rule 3's "in this reply" is
   judged per reply.
2. Continuation parsing needs the colon, skips filler words and the quoted `<name>` placeholder, and
   reads a continuation word anywhere in the parentheses ("(phase 2, continuing)").
3. A slash command counts as earlier use only from the user's own prompt record, not from a tool result
   that quotes a transcript. A duplicated record line counts once. The listing shows local time, sorted,
   with self/meta sessions marked.
4. `scripts/build_prompt_intent.py` skips the harness-message heads the enforcer's lane skips, and
   `isMeta` records (the class sweep ADR-0065 missed).

## Consequences

- Measured 2026-09-26 21:50: since 2026-07-04 the stale count is 1 (0.52.3 reported 12); since
  2026-09-19 it is 0 (0.52.3 reported 4). Continuations since 2026-07-04: 98 (organic 74; re-read 8;
  no earlier use 11); since 2026-09-19: 15 (organic 5; re-read 4; no earlier use 0). The rise from 92 is
  the "(phase …, continuing)" and multi-name forms plus new live turns.
- Loose name matching can join two different skills whose names nest; all real matches today are
  correct (documented in the audit SKILL.md, not fixed).
- No standing-order change, so no new trail epoch for the rulings.
- Revert: `git revert` of the release commit.
