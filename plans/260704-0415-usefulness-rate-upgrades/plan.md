---
title: >-
  Usefulness-rate upgrades: body-trigger retrieval + AUTHORIZED-SKIP gating +
  library doctrine
description: >-
  Implement the validated 260704-0244 proposal end-to-end. EVERYTHING default-ON
  (user override), env kill-switches default-ON. Local go-live (hold push).
status: pending
priority: P1
branch: feat/usefulness-rate-upgrades-0.12.0
tags:
  - retrieval
  - enforcer
  - gating
  - docs
blockedBy: []
blocks: []
created: '2026-07-04'
createdBy: 'ck:plan'
source: skill
---

# Usefulness-rate upgrades: body-trigger retrieval + AUTHORIZED-SKIP gating + library doctrine

## Overview

Implement the Opus-validated proposal `plans/reports/proposal-260704-0244-retrieval-body-signal-and-protocol-gating-report.md` end-to-end. Three moves + supports:

1. **Gating** — AUTHORIZED-SKIP enforcer tier (both legs) replaces today's silent getaway/intent_skip verdicts; + `get_skill` nudge.
2. **Library doctrine** — skip = reasoning-based intent classification; asymmetric cost; burden-of-proof on SKIP; ambiguous/no-fit → escalate to `find-skills`.
3. **Body-trigger retrieval (Option 4)** — feed each skill body's "when to use"/"Triggers:" sections into the proven MAX-pool trigger layer (today description-only); + char→token awareness.
   Supports: **audit-detector patch** (recognise the new marker), **deploy wiring** (engine re-copy + reindex), **maximal docs**, **local go-live**.

**USER OVERRIDE (recorded):** everything ships **DEFAULT-ON**, including the pieces the proposal cautioned to gate (getaway-floor leg, body-trigger retrieval). Each feature gets an env kill-switch **defaulting ON** so "on by default" holds exactly while a one-variable rollback exists. Rationale, risk, and the override itself are in `decisions-audit-log.md`.

## Execution model

- **Sequential** sonnet-5 sub-agent implementers (NO worktree — user directive). One phase owns its files, runs to green, then the next starts. No two implementers touch the same file concurrently.
- File-ownership is disjoint per phase (see each phase). `enforcer.py` (P1) and `skill-first.md` (P2) are separate files.
- Lead (me) integrates, runs the deploy/reindex, drives validation + go-live.

## Phases

| Phase | Name | Status | Owns (files) |
|-------|------|--------|--------------|
| 1 | [Gating core](./phase-01-gating-core.md) | Pending | Completed |
| 2 | [Doctrine](./phase-02-doctrine.md) | Pending | Completed |
| 3 | [Audit patch](./phase-03-audit-patch.md) | Pending | Completed |
| 4 | [Body triggers](./phase-04-body-triggers.md) | Pending | Completed |
| 5 | [Deploy wiring](./phase-05-deploy-wiring.md) | Pending | Completed |
| 6 | [Documentation](./phase-06-documentation.md) | Pending | Completed |
| 7 | [Validation](./phase-07-validation.md) | Pending | Completed |
| 8 | [Go-live](./phase-08-go-live.md) | Pending | Completed |

## Acceptance criteria (whole plan)

- [ ] All 3 moves + audit patch + find-skills escalation + char→token fix implemented, EVERYTHING default-ON with ON-default env kill-switches.
- [ ] `enforcer.py --selftest`, `audit_skill_usage.py --selftest`, vendor tests, `doctor.py` all green.
- [ ] Reindex builds body-trigger points; index point-count rises vs description-only baseline.
- [ ] Docs complete: ADR-0015 + ADR-0016, README/AGENTS/CLAUDE/CHANGELOG updated, VENDORED.md records the vendor change, handoff + journal + decisions-audit written.
- [ ] Opus-validate PASS (or all blockers fixed) + my final gate clean.
- [ ] Version 0.12.0 in plugin.json + marketplace.json; CHANGELOG finalized; merged to `main` locally; **NOT pushed**; user handed the exact `git push` + `/plugin update` commands.

## Risks

- **Under-gating regression** (getaway leg + body triggers ON without the proposal's gating/A-B). Mitigation: doctrine escalation text embedded in the getaway message, ON-default kill-switches, audit metric watches it, A/B smoke in P7. User-directed; recorded.
- **Vendored divergence** — vendor edits must be in VENDORED.md; engine must be re-copied + reindexed to deploy (ADR-0013).
- **Hook fail-silent guardrail** — enforcer changes stay additive, never block a turn.

## Dependencies

Follows: validated proposal `proposal-260704-0244-...`, Opus validation `opus-validation-260704-0320-...`. No cross-plan blockers (the only other unfinished-plan artifacts are historical).
