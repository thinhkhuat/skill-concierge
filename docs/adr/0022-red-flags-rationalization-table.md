# ADR-0022 — Red Flags rationalization table (H2)

Status: Accepted (2026-07-06)
Relates to: ADR-0015 (library doctrine / AUTHORIZED-SKIP — the doctrine this reformats lives beside it),
ADR-0019 (over-fire lane — its row-7 mirror routes here). Plan:
`plans/260706-1315-superpowers-anti-dodge-integration/` (Phase 4). Design arc:
`docs/anti-dodge-integration-v0.14.md`. Reference (adapted, not copied): superpowers v6.1.1 Red Flags
table (`using-superpowers/SKILL.md:34-50`) — MIT.

## Context
`hooks/doctrine/skill-first.md` stated its anti-dodge rationalizations as prose bullets (rule 4 dodges,
rule 6 dodges). Prose read once at session-start blurs by mid-conversation. Superpowers' insight: a
**symptom-indexed table** pattern-matches at the moment of temptation — the agent's own excuse is the
key that retrieves its counter. This is doctrine-craft only; the injected surface is the same file.

## Decision
- **Reformat, not rewrite.** The three rule-4 "feel-exempt" dodges (`skill-first.md:53-55`) and the three
  rule-6 confidence dodges (`:61-63`) become one markdown `| Symptom | Refutation |` table under rule 6.
  Rule 4 now points forward to the table (its first three rows); the rule-4 lawful-no-task class bullets
  are untouched.
- **Rule numbers are FIXED.** The library doctrine and rule bodies cross-reference "rule 2 / 3 / 4" by
  number (`:56,:69,:89-92`). The table replaces bullet CONTENT only, never the rule structure — all
  cross-refs still resolve.
- **v1 rows (7).** 3 rule-4 + 3 rule-6 existing excuses + 1 genuinely-new row from this session's live
  dogfood: the over-fire mirror *"this is just me explaining my own prior output — surely no skill."* Its
  refutation routes to the ADR-0019 enforcer lane (authorized by the `SKILL-CHECK:` line), NOT a
  self-declared skip — and explicitly re-arms SEARCH if the turn carries any task tail.
- **No double-count [Red-Team M2].** *"I already searched last turn / earlier."* already existed verbatim
  at `:54`; it is MOVED into the table, not added — it appears exactly once after the edit.
- **Anchor-collision guard (HARD, cross-file with ADR-0019).** The literal phrase
  `self-referential recap lane` (the H5 audit signature) does NOT appear anywhere in the doctrine text —
  row 7 uses "the enforcer's OVER-fire lane" instead. A collision would make the audit miscount real
  false-skips as authorized.
- **No code change.** `doctrine.py:_body()` injects everything between the `DOCTRINE-START/END` markers
  verbatim; markdown tables pass through untouched.

## Evidence
- `rg "self-referential recap lane" hooks/doctrine/skill-first.md` → **ABSENT** (HARD constraint held).
- `doctrine.py` SessionStart injection over the edited file: injected body contains the Red Flags table
  (`Red Flags` + `Symptom` present), the rule-4 forward-pointer is intact, and the forbidden phrase is
  absent from the injected body.
- Consistency with the enforcer per-turn re-assert (`enforcer.py:256-262`, the compressed
  `"Few don't fit" / "I'm confident" / "you named a tool" are NOT skips`): the table's rows 2/3/5 carry
  the same three refutations — the two surfaces do not drift.

## Consequences
- The dodge-refutation doctrine is now symptom-indexed: an agent forming an excuse can match its exact
  wording to the counter, instead of recalling prose read at session-start.
- The doctrine surface stays a single injected file; no code, no new flag.

## Open / to measure
- **v2 rows (deferred to Phase 3 / H1).** The highest-frequency verbatim excuses from the harvested
  corpus should replace/extend the v1 rows once a clean epoch window exists. Per the accepted caveat
  (`anti-dodge-integration-v0.14.md` §5), that re-measure window may be "insufficient data" this epoch —
  do NOT author v2 from an unclean or too-small window.
