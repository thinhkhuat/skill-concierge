---
phase: 5
title: Deploy wiring
status: completed
effort: S
---

# Phase 5: Deploy wiring — engine re-copy + reindex so vendor changes actually deploy

## Overview
The vendored engine is COPIED into a stable venv (ADR-0013 freshness check). Editing
`vendor/skill-search/` source does NOT take effect until the engine is re-copied and the index rebuilt.
This phase makes the Phase-4 change live locally and proves freshness.

## Requirements
- Functional: deployed engine == edited vendor source (freshness OK); index rebuilt with body-trigger points.
- Non-functional: idempotent; `doctor.py` reports green; no dim/model mismatch.

## Related Code Files
- Modify (only if a flag/step must be surfaced): `setup.sh`
- Run (no source edit): `skill-search --reindex`, `scripts/doctor.py`

## Implementation Steps
1. Re-copy the vendored engine into the stable venv the way `setup.sh` / `doctor.py --fix` does (do not
   hand-hack paths — use the existing mechanism). Confirm the ADR-0013 engine-freshness check passes.
2. Reindex: `skill-search --reindex` (or the setup step) so body-trigger points are built. Capture the index
   point counts before/after (base / trigger) as evidence for Phase 7.
3. Run `python3 scripts/doctor.py` → expect `status: OK` (enrichment check stays OK/0 under multi-vector).
4. If `setup.sh` needs a comment or the new flags surfaced for reproducibility, add minimal notes there.

## Success Criteria
- [ ] Engine-freshness check OK (deployed == source).
- [ ] Reindex succeeds; trigger point-count rises vs the description-only baseline (record the delta).
- [ ] `doctor.py` → `status: OK`.

## Risk Assessment
- Reindex failure / dim mismatch. Mitigate: doctor freshness + health checks catch it; kill-switch reverts to
  description-only then reindex.
