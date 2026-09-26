# ADR-0063 — Continuing a skill re-reads it; audit reader fixes after the v0.52.0 review

Status: Accepted (2026-09-26)
Amends: ADR-0058's off-list route (a skill already invoked this session may be continued without the
search) and the standing-order text of ADR-0062 (rule 3 gains one paragraph). Corrects three statements
in ADR-0062, which is accepted and therefore left as written.
Evidence: `plans/reports/smoke-260926-1922-v0520-live-session.md` (live session after the 0.52.0
restart), `plans/reports/code-reviewer-260926-1910-v0520-fixes.md` (second review, 9 Low findings),
`plans/reports/tester-260926-1910-v0520-blind.md`.

## Context

The first live session on 0.52.0 continued the skill it had used since turn 1 after a restart. The
router's whole-shelf offer for that short "continue" turn did not list the skill, so the literal
off-list route (search → load → quote → `USING:`) applied, and the agent — sensibly — skipped it. The
rule had no line for continuing a skill already in use, and the agent carried the skill from memory
after the restart instead of from its body.

The second code review of 0.52.0 found no Critical, High or Medium defect and nine Low ones in the audit
reader and the release text.

## Decision

1. **Continuing a skill** (rule 3, owner-approved wording, 2026-09-26 19:32): to keep following a skill
   invoked earlier this session when this turn's offer does not list it, line 1 is
   `USING: <name> (continuing)`, then the agent re-reads the skill's body in the same reply with the
   rule-5 call (`get_skill`), using the harness's own skill tool only when that call is unavailable,
   before other work. The re-read stands in for the search; a body that excludes the new work is
   re-ruled as usual. `get_skill` is preferred because it is logged as a read (`ev: get_skill`), not
   as a new invocation (`ev: auto`), so adoption counts and mined chains are not inflated; it runs no
   skill setup; it works the same in every harness; and the skill-exclusion echo fires on it. The
   standing order grows 614 → 682 words (853 at v0.51.x). The string `get_skill("<name>")` still appears
   once, in rule 5, because harness adapters rewrite that literal.
2. **Audit reader fixes** (`skills/skill-usage-audit/scripts/audit_skill_usage.py`):
   - a turn's verdict uses the authorization and enforcer state as it stood when the agent first ruled,
     so a `SKILL-CHECK:` line that arrives later in the turn (a queued notification) cannot authorize a
     skip already written;
   - rulings wrapped in markdown need their colon (`**SEARCH:** q`, `` `USING: x` ``, `> NO SKILL: z`),
     so a bold prose heading such as "**Search results**" is not read as a ruling; the bold-colon form
     now reads; the re-rule pattern gets the same lead, so a wrapped re-rule retracts the old skill;
   - the report splits skip rulings into `NO SKILL:` and the old `SKIPPING` (epoch-watch W27);
   - the "enforcer-run" line is described as "turns where the enforcer injected", not "the doctrine's
     own population": short and slash prompts get no offer either, yet the doctrine binds them.
3. **Corrections to ADR-0062's text:**
   - It said the new readers also read "lower-case" rulings: none exist in the store; the extra rulings
     were all markdown-wrapped.
   - Its reader-change figures were incomplete. Measured 2026-09-26 19:35, 0.51.1 reader vs the 0.52.1
     reader, since 2026-07-04: USING 1,843 → 1,916; SEARCH 498 → 516; skip turns 899 → 925; false
     557 → 583; search-backed 71 → 80; hook-authorized 271 → 262; organic `USING` 1,036 → 1,066;
     organic Skill-tool 419 → 419. Last 7 days: identical except the first live `NO SKILL:` ruling
     (skip turns 131 → 132, hook-authorized 108 → 109). Changes in these counts across the reader
     change are the reader, not uptake.
   - "Every skill you can use judged" excludes, besides keep-off and blocklisted skills, the external
     and other-harness annex rows appended under the ranking: the router never judged those. Rule 1's
     duty to search when no row fits still applies, so no skip opens.

## Consequences

- A new trail epoch starts at the 0.52.1 deploy (the standing order changed); the 0.52.0 epoch lasted
  minutes and is not compared on its own.
- A continued skill leaves a visible trail: a `USING: <name> (continuing)` line followed by a
  `get_skill` ledger row. A continuation without the re-read is the new failure to watch
  (`docs/epoch-watch.md` W28).
- The two readers still differ on a handful of line-1 forms (the label extractor reads wrapped
  rulings without a colon); the audit is the stricter one by design.
- Revert: `git revert` of the release commit.
