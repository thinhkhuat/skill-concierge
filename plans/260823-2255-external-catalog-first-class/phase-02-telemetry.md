---
phase: 2
title: "Telemetry — external offer to take"
status: completed
priority: P2
effort: "1.5h"
dependencies: [1]
---

# Phase 2: Telemetry — external offer→take

## Overview
Measure whether the external annex earns its place: external offer→take
conversion, kept distinct from installed, epoch-scoped.

## Requirements
- Functional: the ledger `offer` event records which offered names were external
  (annex) vs installed; `analyze.py` reports external annex offers, external takes
  (from the ADR-0031 `get_skill` rows), and the conversion between them.
- Non-functional: no hot-path config reads; fail-open.

## Architecture
- `_append_offer` gains an `ext` field: the list of external annex names offered
  this turn (already computed in Phase 1). Absent/empty when none.
- `analyze.py`: a new rollup — external annex offers (count + distinct skills),
  external takes (existing `get_skill` rows split by catalog alias), and
  `external offer→take` (turns that annexed an external AND then get_skill'd one).
- Epoch note: annex changes offer composition → window from ship; installed
  offer→take is unaffected (installed ranking unchanged) and continues.

## Related Code Files
- Modify: `hooks/scripts/enforcer.py` (`_append_offer` ext field — likely already
  threaded in Phase 1), `scripts/analyze.py` (external rollup extension).

## Implementation Steps
1. Thread `ext=[names]` into the `offer` ledger row for annex turns.
2. `analyze.py`: compute external-annex-offer turns; join to `get_skill` external
   takes by session; print `external annex: N offers / M takes / X% conv`.
3. analyze `--selftest`: synthetic ledger with an annex offer + a matching
   external get_skill → conversion computed; empty-ledger safe.

## Success Criteria
- [x] `analyze.py --selftest` green with the new external-conversion case.
- [x] Live ledger row for a docker annex turn carries `ext:[antigravity:...]`.
- [x] `analyze.py` prints the external annex offer/take/conversion block.

## Risk Assessment
- Double-count if a promoted skill's later use is logged as external: Phase 3
  promotion makes it installed → its takes become `auto`, not `get_skill`, so the
  split stays clean. Signal = external takes for a name that is now installed;
  response = classify by CURRENT scope at analyze time.
