---
phase: 3
title: Audit patch
status: completed
effort: S
---

# Phase 3: Audit patch — recognise the AUTHORIZED-SKIP marker

## Overview
Teach the false-SKIPPING detector to recognise a lawful hook-authorized skip, so a `SKIPPING: none` that
follows a Phase-1 `SKILL-CHECK:` line is NOT mis-scored as a false-skip violation. Without this, the new
correct behavior would inflate the "hardest rule" violation rate.

## Requirements
- Functional: a turn whose transcript contains the AUTHORIZED-SKIP marker (`SKILL-CHECK:`, the exact string
  from Phase 1's `AUTHORIZED_SKIP_MARKER`) counts as a **lawful** skip, not a false-skip. Add a distinct
  `authorized_skip` tally for telemetry.
- Non-functional: stdlib-only (matches the script today); no behavior change for turns without the marker.

## Related Code Files
- Modify: `skills/skill-usage-audit/scripts/audit_skill_usage.py` (owns)
- Modify (docs of the metric): `skills/skill-usage-audit/SKILL.md` — note the new marker + tally so the
  metric definition stays honest.

## Architecture / anchors (verified 2026-07-04)
- False-skip logic: `_skip_verdicts` ~`audit_skill_usage.py:101-116` — "`SKIPPING` declared with NO
  `search_skills` in the same turn."
- Search recognition: `_SEARCH_SLUGS` ~`:50`.
- The proposal explicitly flagged this coupling (proposal Idea 1, guardrail: "patch the audit detector in the
  same change").

## Implementation Steps
1. Introduce the marker recognition: if a turn contains `SKILL-CHECK:` (shared constant value from Phase 1),
   treat its `SKIPPING` as authorized — exclude from the false-skip count, add to an `authorized_skip` count.
2. Keep the join robust to the exact marker string; add a module-level constant mirroring Phase 1's value and
   a comment noting the cross-file contract.
3. Update `--selftest` with a case: a synthetic turn `SKILL-CHECK: … / SKIPPING: none` → 0 false-skips, 1
   authorized_skip. Keep the existing self/meta + false-skip cases passing.
4. Update `skills/skill-usage-audit/SKILL.md` to document the marker + the new tally in the metric definition.

## Success Criteria
- [ ] `SKILL-CHECK:`-authorized skips excluded from false-SKIPPING; counted as `authorized_skip`.
- [ ] `python3 skills/skill-usage-audit/scripts/audit_skill_usage.py --selftest` passes (old + new cases).
- [ ] SKILL.md metric definition updated to mention the marker + tally.

## Risk Assessment
- Marker-string drift between enforcer (Phase 1) and auditor. Mitigate: identical literal value + a comment in
  both files naming the contract; lead verifies the two literals match during integration.
