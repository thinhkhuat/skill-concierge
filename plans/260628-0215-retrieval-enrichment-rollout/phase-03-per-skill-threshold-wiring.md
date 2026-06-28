---
phase: 3
title: "Per-skill threshold wiring"
status: pending
effort: ""
priority: P3
dependencies: [1, 4]
effort: "3h"
---

# Phase 3: Per-skill threshold wiring (marginal; do AFTER Phase 1 re-calibration)

## Overview
Let the enforcer use a per-skill calibrated floor (τ) instead of the single global
`GETAWAY_FLOOR=0.20`, for skills whose calibration status is `ok`. Deliberately
deprioritized: only 5/14 skills currently qualify, and **Phase 1 enrichment will change
the cosine distribution**, so calibration must be RE-RUN after enrichment and the
`ok`-set re-derived before wiring.

## Requirements
- Functional: a candidate skill with an `ok` τ is gated by that τ; others fall back to the global floor.
- Non-functional: additive, fail-silent, stdlib-only; load thresholds once per turn.

## Architecture
`enforcer.py` loads `eval/thresholds.json` at hook start; in the candidate filter use
`floor = thresholds.get(name, GETAWAY_FLOOR)` (and only honor it when `status == "ok"`).
Re-run `calibrate_thresholds.py` AFTER Phase 1 goes live so τ reflects the enriched index. NOTE (red-team M3): the GLOBAL `GETAWAY_FLOOR`/`ITEM_FLOOR` re-tuning now lives in **Phase 1** (enrichment shifts the absolute cosine scale that the global floor gates on); Phase 3 only adds the per-skill `ok` overrides on top of the already-re-tuned global floor.

## Related Code Files
- Modify: `hooks/scripts/enforcer.py` (per-candidate floor lookup; extend `--selftest`)
- Reuse: `scripts/calibrate_thresholds.py` (regenerate `eval/thresholds.json` post-enrichment), `eval/thresholds.json`
- Optional: `scripts/doctor.py` (calibration freshness check)

## Implementation Steps
1. After Phase 1 live: re-run `calibrate_thresholds.py`; note the new `ok`-set (enrichment should grow it past 5).
2. `enforcer.py`: load thresholds.json (fail-silent if absent); apply per-skill τ only for `ok` skills.
3. Extend `enforcer --selftest` to cover the per-skill-floor branch.
4. Hold activation behind Phase 4's clean-window measurement (don't claim improvement unproven).

## Success Criteria
- [ ] `ok`-set re-derived against the ENRICHED index (not the pre-enrichment one).
- [ ] Per-skill τ applied for `ok` skills; global floor fallback for the rest; selftest green.
- [ ] No regression in offered candidates for non-`ok` skills.

## Risk Assessment
- **Building on a pre-enrichment calibration** → mandatory re-run after Phase 1 (encoded in step 1).
- **Marginal value** → keep it small; do not let it expand beyond a per-skill floor lookup.
- **Premature activation** → gated on Phase 4.
