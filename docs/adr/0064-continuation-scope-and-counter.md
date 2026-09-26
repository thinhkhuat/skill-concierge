# ADR-0064 — Continuations are for the same task, and the audit counts them

Status: Accepted (2026-09-26)
Amends: ADR-0063 decision 1 (the continuation paragraph of rule 3) and decision 2 (the audit reader).
Corrects one statement in ADR-0063, which is accepted and therefore left as written.
Evidence: `plans/reports/code-reviewer-260926-1940-v0521-diff.md` (review of 0.52.1: 1 Medium, 10 Low);
owner decisions 2026-09-26 ~20:05 (count and narrow the continuation) and ~20:50 (the two wording fixes).

## Context

The 0.52.1 review found that a continuation could stand in for the search on unrelated new work: the
paragraph asked only that the skill was used earlier this session, and nothing measured continuations. A
session that used one skill at turn 1 could write `USING: <it> (continuing)` for a different task at turn
20, and the audit would count it as normal skill use. The review also found audit-reader defects, one of
them introduced in 0.52.1 on the strength of a wrong review nit (a pre-filter clause called redundant).

## Decision

1. **Scope** (owner-approved wording): the continuation applies when this turn's offer does not list the
   skill **and the new work is the same task**. The re-read names its tool directly — `get_skill`
   (rule 5) — and the harness's skill tool is the fallback when that call is unavailable **or cannot find
   the skill** (a command-file skill is not indexed, ADR-0001). Standing order 682 → 697 words.
2. **The audit counts continuations**: `USING: <name> (continuing)` rulings, how many re-read the skill in
   the same turn (a `get_skill` or Skill call for that name), and how many name a skill with no earlier
   use in the session (Skill, `get_skill` or a `USING:` line — read from the whole session file, before
   the `--since` window too). This gives epoch-watch W28 its numbers.
3. **Audit reader fixes:**
   - the search that backs a skip must come before the ruling in the turn — rule 4's "a search shown in
     this reply" read in order, the same snapshot the authorization already used (0.52.1);
   - `--harvest` keeps the clause of the ruling that was judged (the first), not a later one;
   - the pre-filter clause for enforcer attachments is restored: the June 2026 enforcer head
     ("SKILL-FIRST (standing …") contains neither `USING` nor `SKILL-CHECK:`;
   - a wrapped ruling does not start on a blank line, and a markdown-wrapped skill name reads only after
     a colon ("Using `rg` to …" is prose);
   - bare title-case prose ("Search …", "Skipping …" at a line start) still reads as a ruling in the
     display counts — the old optional-colon forms must keep reading; the verdicts use tool calls.
4. **Correction to ADR-0063:** it said `get_skill("<name>")` appears once "because harness adapters
   rewrite that literal". No adapter rewrites it (the DSH docstring that said so was wrong too). The
   string appears once because the doctrine test and the doctrine selftest pin it.

## Consequences

- Measured 2026-09-26 20:47, 0.52.1 reader vs 0.52.2 reader: last 7 days identical (135 skip turns,
  11 false, 12 search-backed, 112 authorized; enforcer-run 4/128). Since 2026-07-04: 8 skips backed only
  by a later search move from search-backed to false (false 583 → 591, search-backed 80 → 72); other
  counts unchanged. Continuations since 2026-07-04: 28 (most before the rule); since 2026-09-19: 3, all
  re-read, none without an earlier use.
- A new trail epoch starts at the 0.52.2 deploy (the standing order changed).
- `analyze.py` counts every `get_skill` row as a deep pull, so continuation re-reads raise deep-pull and
  external-take counts from the 0.52.1 deploy (2026-09-26 19:41) on; those are not comparable across it.
- Revert: `git revert` of the release commit.
