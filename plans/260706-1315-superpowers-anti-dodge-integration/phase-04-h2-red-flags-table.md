---
phase: 4
title: "H2 Red Flags Table"
status: pending
effort: "S"
---

# Phase 4: H2 Red Flags Table

## Overview

Convert the prose rationalizations in `skill-first.md` into a symptom→refutation **table** that fires at the moment of temptation (the agent's own excuse is the key that retrieves the counter). Mirrors superpowers' Red Flags table (`using-superpowers/SKILL.md:34-50`). v1 ships immediately from known excuses; v2 is refreshed from Phase-3's harvested corpus. Depends on: Phase 1 (v1 can ship), Phase 3 (v2 content).

## Requirements

- Functional: rule-6 (`skill-first.md:60-63`) + the rule-4 bullets (`:52-55`) become a markdown `| symptom | refutation |` table; the enforcer's per-turn re-assert (`enforcer.py:256-262`) stays consistent with it.
- Non-functional: **doctrine-text only, no code**; preserve rule numbering (rule-4 text and the library doctrine at `:56,:69,:89-92` refer to "rule 2" by number).

## Architecture

- `doctrine.py:_body()` (`:39-46`) injects everything between the `<!-- DOCTRINE-START -->…<!-- DOCTRINE-END -->` markers verbatim; markdown tables pass through untouched → no code change.
- Drop the table under the rule-6 header at `:60`, replacing the three bullets at `:61-63` (each is already a clean `*"quote"* — refutation` pair). Fold the rule-4 bullets (`:52-55`) into the same table.
- **v1 rows** (ship now): the 3 existing rule-6 excuses + the 3 rule-4 excuses + one genuinely-new row from this session's live dogfood — the over-fire mirror ("this is me explaining my own prior output, surely no skill" — which routes to H5's lane, NOT a skip). NB [Red-Team M2]: "I already searched last turn" already exists verbatim at `skill-first.md:54` — it is a *reformat into the table*, not a new addition; do not double-count it.
- **v2 rows** (after Phase 3): replace/extend with the highest-frequency verbatim excuses from the harvested corpus.
- Keep the compressed re-assert at `enforcer.py:256-262` (`"Few don't fit" / "I'm confident" / "you named a tool" are NOT skips`) consistent with the table so the two don't drift.

## Related Code Files

- Modify: `hooks/doctrine/skill-first.md` (rule 6 + rule 4 → table)
- Create: `docs/adr/0022-red-flags-rationalization-table.md` (light — doctrine-craft record)

## Implementation Steps

1. Author the v1 symptom→refutation table under rule 6; fold rule-4 bullets in; preserve rule numbers.
2. Cross-check the enforcer per-turn re-assert (`:256-262`) stays consistent.
3. (After Phase 3) refresh rows from the harvested corpus → v2.
4. Finalize ADR-0022.

## Success Criteria

- [ ] Rule-6 (+ rule-4) rationalizations render as a symptom→refutation table.
- [ ] Rule-number cross-references (`:56,:69,:89-92`) still resolve.
- [ ] enforcer per-turn re-assert consistent with the table.
- [ ] v2 rows sourced from the Phase-3 harvest.

## Risk Assessment

- **Renumbering desyncs cross-refs** → mitigation: keep the rule numbers fixed; the table replaces bullet CONTENT only, not the rule structure.
- **v1/v2 drift** from the enforcer re-assert → step 2 gate.
