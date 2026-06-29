---
phase: 5
title: "Offer-suppression keep-off map"
status: pending
priority: P2
dependencies: [4]
---
<!-- Updated: Validation Session 1 - hard-drop; take-rate<=5% with min N; auto-regen+auto-apply with clean-window/minN/revert/audit-log guardrails -->

# Phase 5: Offer-suppression keep-off map

## Overview
Ledger-derived suppression of chronic never-take skills from the **offer menu only** (still
catalogue-reachable via `search_skills`). Applies smart-suggest's log-and-prune philosophy to the
offer->take data the enforcer already logs. "Move 1" from the 2026-06-29 smart-suggest study.

## Requirements
- **Functional:** HARD-DROP from the offered set any skill with `offers >= N` and `take-rate <= EPS`
  (defaults N=15, EPS=5%). Never remove from the index.
- **Non-functional:** stdlib-only, load-once, **fail-open** (missing/empty `keep-off.json` -> no
  suppression), within the existing ~300ms per-turn budget, cold-start safe (no suppression below N offers).

## Architecture
- New artifact `config/keep-off.json` - inverse of `config/keep-on.json`; skill names to hard-drop
  from offers, each with the supporting stat (`offered N`, `take-rate`) for auditability.
- Generator reads the **Phase-4 CLEAN-WINDOW ledger**, not the full historical ledger - the current
  ledger spans the pre-enrichment era so its never-taker counts are confounded. Hence `dependencies: [4]`.
- Application: in `hooks/scripts/enforcer.py`, after `_retrieve()` and before `_ranked_mandate()`,
  hard-drop keep-off names. Emit a `keepoff_skip` ledger band so the loop can measure it.
- **Governance = AUTO-regen + auto-apply** (setup.sh / doctor cadence). Guardrails that make
  auto-apply safe (operator chose auto over human-review; these are the mitigations):
  (a) regenerate from the clean-window only; (b) enforce min N so a noisy short window can't suppress;
  (c) keep-off is reversible - a revert path / it is just a config the enforcer reads fail-open;
  (d) log the suppressed set on every regen for audit.

## Related Code Files
- Create: `config/keep-off.json`
- Create: `scripts/build_keep_off.py` (or extend `scripts/apply-overrides.py`) - emits keep-off from the clean-window per-skill offer->take; wired into setup.sh + doctor --fix for auto-regen
- Create: `docs/adr/0011-ledger-derived-offer-suppression.md`
- Modify: `hooks/scripts/enforcer.py` (hard-drop filter + `keepoff_skip` band + `--selftest` cases)
- Modify: `scripts/analyze.py` (windowed per-skill offer->take if not already)

## Implementation Steps
1. Land Phase 4 clean-window first (dependency); take post-enrichment offer->take per skill.
2. Write ADR-0011: policy = hard-drop iff `offers >= N` and `take-rate <= EPS` (N=15, EPS=5%); rank/
   suppress by MEASURED conversion, not cosine (ADR-0009 score!=take lock); auto-apply WITH the four guardrails.
3. `build_keep_off.py` -> `config/keep-off.json` from the windowed ledger; wire auto-regen into setup.sh + doctor --fix.
4. `enforcer.py`: load keep-off once, hard-drop post-`_retrieve`, emit `keepoff_skip` band, fail-open.
5. `--selftest`: keep-off filter drops a listed name; fail-open on missing file.

## Success Criteria
- [ ] ADR-0011 written and accepted (auto-apply + guardrails recorded; no silent threshold drift).
- [ ] `python3 hooks/scripts/enforcer.py --selftest` passes (incl. keep-off + fail-open).
- [ ] `python3 scripts/doctor.py` -> status: OK before and after.
- [ ] `python3 scripts/driftcheck.py driftcheck.json` exit 0 (version bump: plugin.json + marketplace.json + CHANGELOG together).
- [ ] Each auto-regen logs the suppressed set (audit) and is reversible.
- [ ] Re-run `analyze.py` on a fresh window: offered-turn conversion rises / never-take offers fall.

## Risk Assessment
- **Pre-enrichment confound (high):** mitigated by the Phase 4 dependency - never suppress on the old ledger.
- **Score!=take (ADR-0009):** suppress by conversion, not cosine; ADR-0011 states this.
- **Auto-apply over-suppressing (the human-review trade-off the operator accepted):** mitigated by clean-window + min N + reversibility + per-regen audit log; a wrongly-suppressed skill stays search-reachable and earns back on the next window.
