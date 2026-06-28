---
phase: 4
title: "Compliance measurement"
status: pending
effort: ""
priority: P2
dependencies: [1]
effort: "1h + collection wait"
---

# Phase 4: Clean-window compliance measurement (the referee)

## Overview
The instrument exists (C1: `analyze.py` offered-turn conversion). What's missing is
CLEAN data: today's ledger is contaminated by this and prior meta-sessions (about
skill-concierge itself), reading ~92% dodge. This phase collects a clean workload window
of real task sessions on the enriched index and measures whether the dodge actually
falls. It is the referee for every compliance claim (Phase 1's real-world payoff, Phase 2,
Phase 3 activation). Wait-and-collect, not a build.

## Requirements
- Functional: a before/after offered-turn conversion read across a clean window, attributable to enrichment.
- Non-functional: no contamination from meta-discussion sessions; honest N and confounds noted.

## Architecture
Mark T0 = the commit/time enrichment goes live (Phase 1 `--live`). Accumulate real,
non-meta task sessions. Then `analyze.py --since T0` for the "after"; an equivalent clean
pre-enrichment window (if recoverable) or a fresh held-out baseline for the "before".
Compare `offered-turn dodge` and `hit@k`.

## Related Code Files
- Reuse: `scripts/analyze.py` (`--since`/`--until` already shipped; offered-turn conversion from C1)
- No new code expected (analysis only).

## Implementation Steps
1. Stamp T0 at Phase 1 `--live`.
2. Use the system normally on real tasks (NOT meta-sessions about skill-concierge) to bank a clean window.
3. `analyze.py --since T0`; report offered-turn dodge, hit@k, per-skill offer→take.
4. Compare against the contaminated baseline AND a clean pre-enrichment reference; state N + confounds explicitly.
5. Decide: did enrichment move compliance? If retrieval is fixed but dodge persists → the residual IS a compliance problem → Phase 2 (doctrine re-injection) is the lever.

**Red-team M7 — the referee can barely referee; design for it:** (a) PRE-REGISTER the minimum N of real task turns and the meta-session exclusion rule before collecting (this workbench's dominant workload IS skill-concierge meta-work — the contamination that already poisoned the baseline). (b) STAGGER T0 for Phase 1 (enrichment) and Phase 2 (doctrine re-injection) by a measurable window — if both ship near T0, any delta confounds retrieval with a doctrine change and is unattributable. (c) Accept the honest near-term output is DIRECTIONAL until enough clean turns accrue; do not over-claim.

## Success Criteria
- [ ] A measurement on a window with NO meta-session contamination (≥ some agreed N of real task turns).
- [ ] Offered-turn dodge before-vs-after enrichment reported with honest N/confounds.
- [ ] A grounded verdict: retrieval-fix sufficient, or compliance (Phase 2) still needed.

## Risk Assessment
- **Contamination** (the prior killer) → exclude meta-sessions explicitly; this is the whole point.
- **Low N / slow accrual** → directional-only until enough turns; do not over-claim on a thin window.
- **Confounds** (model changes, doctrine edits) → annotate the window boundaries with what else changed.
