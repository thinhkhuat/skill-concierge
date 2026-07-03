---
phase: 2
title: Doctrine
status: completed
effort: S
---

# Phase 2: Doctrine — the library doctrine + find-skills escalation

## Overview
Encode the "library doctrine" into the SessionStart SKILL-FIRST doctrine so the in-session agent classifies
intent with reasoning (trivial errand vs. real work; unambiguous vs. ambiguous), treats a lazy "nothing
fits" on real work as top-severity, and escalates ambiguous/no-fit turns to `find-skills` instead of
self-serving. This is the human-side complement to Phase 1's hook-side AUTHORIZED-SKIP.

## Requirements
- Functional: doctrine text states — skip is a reasoning-based intent classification; error costs are
  asymmetric (needless search = cheap; lazy skip on real work = highest-severity slop); burden of proof is on
  SKIP; a bare "nothing cleared the floor" on real/ambiguous work escalates to `find-skills`, never a
  self-declared skip.
- Non-functional: concise; consistent with the existing `USING/SEARCH/SKIPPING` token protocol; must not
  contradict Phase 1's AUTHORIZED-SKIP semantics.

## Related Code Files
- Modify: `hooks/doctrine/skill-first.md` (ONLY file this phase owns)
- Read-only reference: `hooks/scripts/doctrine.py` (confirm whether it emits `skill-first.md` verbatim or
  transforms it — do not edit unless the doctrine text must live there; if so, flag to lead, do not overreach).

## Implementation Steps
1. Add a concise **"Library doctrine"** block to `skill-first.md`: the asymmetric-cost framing + burden-of-proof
   on SKIP + `find-skills` escalation for ambiguous/non-trivial + no-fit.
2. Tie it to the new hook tier: when the hook emits a `SKILL-CHECK:` AUTHORIZED-SKIP line, the agent may honor
   it for a genuinely trivial/conversational turn, but for real/ambiguous work still escalates to `find-skills`.
3. Keep the existing token rules intact; do not bloat — target a short, high-signal addition.

## Success Criteria
- [ ] `skill-first.md` contains the library doctrine (asymmetric cost, burden-on-SKIP, find-skills escalation).
- [ ] Text is consistent with Phase 1's AUTHORIZED-SKIP (`SKILL-CHECK:`) semantics.
- [ ] No contradiction with existing USING/SEARCH/SKIPPING protocol; SessionStart still emits cleanly
      (spot-check the hook doesn't error).

## Risk Assessment
- Doctrine bloat / mixed signals. Mitigate: concise addition, cross-checked against Phase 1 wording by lead
  during integration.
