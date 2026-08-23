---
phase: 3
title: "Usage-promotion (fast-follow)"
status: completed
priority: P2
effort: "2h"
dependencies: [1, 2]
---

# Phase 3: Usage-promotion

## Overview
An external skill the agent actually USES repeatedly graduates to a real installed
skill — organic curation by demonstrated usage, resident set grows only by earning.

## Requirements
- Functional: a SessionStart hook reads the ledger's external `get_skill` takes;
  any `catalog:<alias>` skill used in ≥ `PROMOTE_MIN_TAKES` (3) DISTINCT sessions
  auto-promotes via `catalogs.py` promote (symlink into `~/.claude/skills`).
  Idempotent (already-promoted → skip), collision-safe (refuse, log), kill-switch
  `PROMOTE_ENABLED=0`.
- Non-functional: detached/throttled like `auto_reindex`; fail-open; never blocks
  session start; forwards `SKILL_CONCIERGE_CATALOG_ROOTS`.

## Architecture
- New `hooks/scripts/auto_promote.py` (SessionStart), mirrors `auto_flywheel.py`
  shape: throttle stamp, kill-switch, reads ledger tail, counts distinct-session
  external takes per name, calls `catalogs.py` promote for those over threshold.
- Promotion reuses `catalogs.py cmd_promote` logic (symlink, collision refusal).
- After promotion, the ADR-0031 realpath dedup in `discover_skills` suppresses the
  catalog twin at the next reindex → no double-listing; the promoted copy is a
  normal name-only installed skill (auto_overrides gives it its budget entry).
- Wire into `hooks/hooks.json` SessionStart; `.mcp.json` needs nothing new.

## Related Code Files
- Create: `hooks/scripts/auto_promote.py`.
- Modify: `hooks/hooks.json` (SessionStart entry), `scripts/catalogs.py` (expose a
  reusable promote function if needed), doctor `check` (optional: report recent
  promotions).

## Implementation Steps
1. `auto_promote.py`: throttle + kill-switch + ledger distinct-session tally +
   promote-over-threshold, logged, `--selftest`.
2. Reuse catalogs promote (import or subprocess); collision → log + skip.
3. hooks.json SessionStart wiring (timeout 10, detached pattern).
4. Selftest: synthetic ledger with 3-session external takes → promotes; 2-session
   → does not; already-symlinked → idempotent skip.

## Success Criteria
- [x] `auto_promote.py --selftest` green.
- [x] Manual: seed 3-session takes for one antigravity skill → run → symlink
  created in a temp promote dir; re-run → idempotent.
- [x] After promote + reindex, the skill appears once (installed), twin suppressed.

## Risk Assessment
- Promoting junk: conservative threshold (3 distinct sessions of REAL use) + the
  skill was already vetted enough to be used. Signal = unwanted promotions;
  response = raise `PROMOTE_MIN_TAKES` or `PROMOTE_ENABLED=0`, `rm` the symlink.
- Distinct-session counting wrong: use `sid` uniqueness in the ledger, exclude
  `sub` (subagent) rows.
