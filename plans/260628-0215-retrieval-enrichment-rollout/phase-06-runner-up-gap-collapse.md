---
phase: 6
title: "Runner-up-gap menu collapse"
status: pending
priority: P3
dependencies: []
---
<!-- Updated: Validation Session 1 - %-share DOMINANCE replaced by top-vs-2nd gap ratio (share never reaches a threshold; max 0.285 over 186 offers) -->

# Phase 6: Runner-up-gap menu collapse

## Overview
When the top candidate is clearly ahead of the runner-up, the competing menu is noise. Collapse the
offer to the single top skill. "Move 2" from the 2026-06-29 smart-suggest study, REDESIGNED after
validation - the original %-share threshold was unworkable.

## Validation finding (why gap, not share)
Over 186 real multi-candidate offers the top candidate's %-share maxes at 0.285 (median 0.215): in
mpnet's compressed cosine band, split across ~5 candidates, no skill ever "dominates" by share, so a
%-share threshold (0.60/0.40/0.30) fires 0% of the time. The workable signal is the GAP between the
top and the runner-up, which is scale-free.

## Requirements
- **Functional:** collapse `shown` to `[top]` when `top_score / second_score >= RATIO`
  (env `ENFORCER_DOMINANCE_RATIO`, default ~1.25). Divide-by-zero guarded.
- **Non-functional:** reuse the scores already in hand in `_ranked_mandate`; no new I/O; fail-open
  (any error -> show full menu).

## Architecture
- In `hooks/scripts/enforcer.py:_ranked_mandate()` (~:206-233) the candidates carry raw scores.
  Compute `ratio = top_score / max(second_score, eps)`; if `multi and ratio >= RATIO`, set
  `shown=[top]` and drop the "Multiple candidates" note.
- Decide on RAW scores (the gap), NOT the displayed %-share. Built on the semantic scores, NOT a
  lexical name-match (`enforcer.py:5-10` warns token-overlap matching fails).

## Related Code Files
- Modify: `hooks/scripts/enforcer.py` (`_ranked_mandate` gap-collapse + `--selftest` case)

## Implementation Steps
1. Add `ENFORCER_DOMINANCE_RATIO` (default ~1.25, divide-by-zero guarded).
2. Compute top/2nd ratio in `_ranked_mandate`; collapse `shown=[top]` + suppress the note when >= RATIO.
3. Calibrate RATIO against the ledger's top/2nd ratio distribution before locking the default.
4. `--selftest`: a 2-candidate set above RATIO renders one line + no note; below -> full menu.

## Success Criteria
- [ ] `python3 hooks/scripts/enforcer.py --selftest` passes (collapse + non-collapse).
- [ ] `python3 scripts/doctor.py` -> status: OK.
- [ ] RATIO default calibrated from the ledger top/2nd distribution (documented).
- [ ] Measured on a fresh window (uses Phase 4): collapsed turns do not reduce offer->take.

## Risk Assessment
- **Collapsing a wrong top pick:** low blast - additive context; agent reads the real prompt and can still `search_skills`. Tune RATIO up if it over-collapses.
- **May still rarely fire if the band is flat even at the top:** acceptable - a rare correct collapse beats a 0%-firing share rule. If it never fires after calibration, DROP Phase 6 rather than keep dead code.
- **Display-only:** no retrieval/index impact; independent of Phase 5.
