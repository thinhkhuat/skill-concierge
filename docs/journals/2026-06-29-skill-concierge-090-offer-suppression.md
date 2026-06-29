# 2026-06-29 — skill-concierge v0.9.0: ledger-driven offer-suppression, shipped inert

## Context
Started from studying an external UserPromptSubmit "smart-suggest" hook and asking how to apply its
log-and-prune philosophy to skill-concierge's enforcer. The enforcer already does a superior semantic
version of most of smart-suggest; the one missing primitive was closing the offer->take loop.

## What changed
- ADR-0011 + scripts/build_keep_off.py + config/keep-off.json + enforcer.py P5/P6. Bumped 0.8.0 -> 0.9.0.
- P5 hard-drops chronic never-take skills from the offer menu (fail-open); P6 collapses on a
  runner-up gap (default-off). Both inert on ship.

## What the data taught us
- The raw ledger showed ~93% offered-turn dodge and skills offered 20-30x, taken 0x — tempting to suppress.
- But the never-takers were a PRE-ENRICHMENT artifact: on the post-enrichment clean window (band=="offer"
  shown menus, 71 turns) ZERO skills qualify. The v0.5.0 enrichment already cured the problem P5 targets;
  the clean-window dependency prevented a wrong 6-7 skill suppression.
- P6's original %-share design was dead-on-arrival (top-share maxes ~0.285); redesigned to a raw gap
  ratio that fires ~5%. No evidence it helps -> shipped default-off.

## Process notes / lessons
- Independent code review (SHIP-WITH-FIXES) caught a real metric bug: the suppression denominator
  counted never-shown getaway/intent_skip candidates as "offered". Fixed to band=="offer" only.
- Validated the deployed CACHE copy (not the source) via two independent verifiers -> GO.
- LESSON: cook's MANDATORY finalize steps (journal + project-management sync) were skipped and only
  done after the user caught it (/come-clean). Finalize is not optional even when the user takes over
  the commit/deploy.
- LESSON: enrichment state matters — doctor currently reports "not enriched", worth reconciling against
  the plan's "enrichment shipped live" premise that underpins the clean-window argument.

## Open
- analyze.py headline denominator (band=offer?), auto-regen wiring, reindex, enrichment-overlay anomaly.
