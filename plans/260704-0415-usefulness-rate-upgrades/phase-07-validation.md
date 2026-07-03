---
phase: 7
title: Validation
status: completed
effort: M
---

# Phase 7: Validation — opus-validate adversarial review + my final gate

## Overview
Dual validation before go-live: (a) automated self-checks + a shadow-A/B smoke, then (b) an Opus adversarial
review of the whole diff against the plan + guardrails, then (c) my own final reconciliation gate. Fix
blockers, re-verify.

## Requirements
- No source edits in this phase except blocker fixes surfaced by validation.

## Implementation Steps
1. **Self-checks (must all pass):**
   - `python3 hooks/scripts/enforcer.py --selftest`
   - `python3 skills/skill-usage-audit/scripts/audit_skill_usage.py --selftest`
   - vendor tests (`vendor/skill-search/tests/`)
   - `python3 scripts/doctor.py` → `status: OK`
   - Flag round-trip: confirm `ENFORCER_AUTHORIZED_SKIP=0` and `SKILL_BODY_TRIGGERS=0` restore prior behavior.
2. **Shadow A/B smoke** (proposal-required, run even though feature ships on): use
   `scripts/multivector_experiment.py` (or the repo's A/B harness) to compare description-only vs.
   +body-triggers retrieval on the available eval set. Record separation/rank-1 delta (regression or gain) in
   the journal + decisions-audit — this is the evidence the all-ON override deferred.
3. **Opus-validate** (`opus-validate` skill): pre-flight context, then spawn `agent-validator` (model: opus)
   to adversarially verify the implementation vs. the plan, the guardrails (fail-silent hook, VENDORED.md,
   SSOT), and the docs vs. the diff. Save its report to `plans/reports/`.
4. **Final gate (me):** reconcile the opus report; fix any blocker in-place; re-run the affected self-checks;
   confirm zero blockers remain.

## Success Criteria
- [ ] All self-checks + vendor tests + doctor green; flag round-trip verified.
- [ ] A/B smoke run and its result recorded (gain / neutral / regression — stated honestly).
- [ ] opus-validate PASS, or every blocking issue fixed and re-verified.
- [ ] My final gate: zero unresolved blockers.

## Risk Assessment
- A/B shows regression while feature ships ON (user override). Mitigate: record loudly; kill-switch documented;
  prereq #4 re-measurement flagged as the follow-up that would decide a later default-off.
