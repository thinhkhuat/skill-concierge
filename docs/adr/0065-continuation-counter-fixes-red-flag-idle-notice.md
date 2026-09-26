# ADR-0065 — The continuation counter reads every form; a red flag for stale continuations; idle notices are harness messages

Status: Accepted (2026-09-26)
Amends: ADR-0064 decision 2 (the continuation counter) and the red-flags table of ADR-0062 (rule 6);
ADR-0054's harness-message lane gains one prompt head.
Evidence: `plans/reports/code-reviewer-260926-2055-v0522-diff.md` (review of 0.52.2: 3 Medium, 9 Low);
owner decision 2026-09-26 ~21:12 (add the red-flags row); ledger replay of cross-session idle notices.

## Context

The 0.52.2 counter read only the exact `(continuing)` suffix, while agents also write
`(continuing the earlier work)`, `(continued …)`, `(continuation …)` and several names on one line — it
saw about a third of the continuations. It also credited a load earlier in the same turn as "earlier
use", and did not count a load before the ruling line as the re-read. "The new work is the same task"
cannot be measured directly, and the red-flags table had no row for the excuse that skips it.

Separately, `[Cross-session idle notice]` prompts reached the enforcer as user tasks: 3 in the ledger
since 2026-09-25, 2 given a full offer and 1 an intent skip, none the harness lane.

## Decision

1. **The counter reads every continuation form** (`(continu(ing|ed|ation) …)`, names joined by `+`, `,`,
   `&`, `and`). Per continued skill per turn it records whether the turn loads it (the Skill tool or
   skill-search's own `get_skill`, before or after the line), whether the session used it before this
   turn (snapshot at turn open; a load, a `USING:` line or the user's slash command, before the
   `--since` window too), and how many turns ago it was last used — more than 5 (`STALE_TURNS`) is
   counted as likelier new work, the proxy for "not the same task". Counts are reported for all
   sessions and for organic ones; `--continuations` lists each one (session id prefix, time, skill) for
   hand review. Name forms of one skill (`plugin:name`, `name`) match; only skill-search's own
   `get_skill`/`search_skills` count (another server's `search_skills` no longer backs a skip).
2. **Red-flags row** (owner-approved): "I'm still in <skill> — continuing." → "Only for the same task;
   new work: SEARCH (3)." Standing order 697 → 715 words.
3. **Harness-message lane**: a prompt opening `[Cross-session idle notice]` is harness-generated (the
   enforcer's `_HARNESS_MSG_RE` and its twin in `scripts/build_keep_off.py`, pinned byte-equal).
4. **Text fixes:** `doctrine.py` no longer claims any harness rewrites `get_skill("<name>")`; the
   standing-order header says the test pins its count and the selftest its presence; the usage-audit
   SKILL.md puts the authorized-skip sentence back beside its subject and documents the pre-filter's
   case sensitivity and the queued-prompt split.

## Consequences

- Measured 2026-09-26 21:15, 0.52.2 reader vs 0.52.3 reader: skip verdicts unchanged in both windows.
  Continuations since 2026-07-04: 29 → 92 (organic 69; re-read in the turn 8; no earlier use 9; last
  used more than 5 turns ago 12). Since 2026-09-19: 4 → 14 (organic 5; re-read 4; no earlier use 0;
  stale 4). The ADR-0064 baselines (28 and 3) were form-limited.
- ADR-0064's "other counts unchanged" left out the enforcer-run line, which moved with the same 8 turns
  (302/644 → 309/644). 0.52.2 was installed on Claude Code at 2026-09-26 20:51:46.
- A new trail epoch starts at the 0.52.3 deploy (the standing order changed).
- Revert: `git revert` of the release commit.
