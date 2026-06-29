# ADR-0011 — Ledger-derived offer suppression (keep-off map)

Status: Accepted (2026-06-29)
Relates to: ADR-0009 (operator gate thresholds; score≠take), ADR-0006 (compounding ledger).

## Context
The invocation ledger shows ~93% offered-turn dodge: of turns where the enforcer surfaced ≥1
skill, the agent used none (189/204). A cohort of skills is offered 20–30× and taken 0×:
`review-docs` 0/29, `skill-search` 0/22, `caveman-stats` 0/21, `agentmemory:recap` 0/21,
`zoom-out` 0/20, `ck:journal` 0/18. The cosine ranker keeps re-surfacing them; ADR-0009 already
found the score is a weak (anti-correlated) usefulness signal. Per-skill MEASURED conversion is
the better signal — the same log-and-prune idea behind UserPromptSubmit "smart-suggest" coaches.

## Decision
Hard-drop chronic never-take skills from the OFFER MENU only (still catalogue-reachable via
`search_skills`), driven by ledger conversion, not cosine:

- **Policy:** drop a skill iff `offered ≥ N` (default 15) AND `take-rate ≤ EPS` (default 5%).
- **Window:** computed over a POST-ENRICHMENT clean window. v0.5.0 enrichment (2026-06-28) changed
  which skill ranks where, so pre-enrichment per-skill counts are confounded. Default boundary
  `2026-06-28 16:05:00` (CHANGELOG + ship-log handoff); refine to the exact ship commit time when
  git is accessible. Env: `KEEPOFF_SINCE`.
- **Data-sufficiency guard:** if the window has `< MIN_WINDOW_OFFERED_TURNS` (default 40), emit an
  EMPTY keep-off (suppress nothing). Never suppress on a thin/noisy window.
- **Mechanism:** `scripts/build_keep_off.py` writes `config/keep-off.json` (names + audit stats),
  reusing `analyze._offer_conversion` so keep-off and the analyzer can never report a divergent
  metric. `enforcer.py` loads it once and hard-drops post-`_retrieve`, fail-OPEN (missing/empty/bad
  file → no suppression).
- **Governance:** AUTO-regen + auto-apply is the INTENDED end-state (operator choice over
  human-review). Guardrails: clean-window-only, min-N, min-window, reversible (delete/empty the
  file), per-regen audit stats. The auto-regen TRIGGER (wiring into `doctor --fix` / `setup.sh`) is
  DEFERRED until one real post-enrichment run is eyeballed; the generator runs manually until then.
  Auto-apply at runtime is live (the hook reads the file) but inert while the file is empty.

## Consequences
- Reclaims menu slots from 0%-converting skills; should reduce offered-turn dodge (to be measured).
- A wrongly-suppressed skill stays search-reachable; it re-enters NOT via menu-conversion (it is
  dropped pre-offer, logged under `dropped` not `offered`) but when its historical `offered` count
  rolls out of the window below N. No catalogue removal, no index change.
- Inert until a sufficient post-enrichment window accrues — shipped, not necessarily yet suppressing.

## Review (2026-06-29, independent code-reviewer) — SHIP-WITH-FIXES, applied
Merge-safe (inert: `keep_off: []`, P6 default-off). Fixes applied this session:
- **Denominator counts only `band=="offer"` (SHOWN menus).** getaway / intent_skip log candidates the
  agent never saw; counting them inflated `offered` and risked over-suppression (finding #1). On the
  full ledger this drops the flagged set 7->6 (`zoom-out` fell below the 15-offer floor once
  never-shown impressions were excluded). build_keep_off uses this corrected metric.
- P6 collapse decided in `_apply_dominance` so the ledger logs the POST-collapse menu (#2).
- `build_keep_off --full` refuses to overwrite the live config (#3).
- Malformed `ENFORCER_DOMINANCE_RATIO` fails silent to `None` (#4).
- `intent_skip` path threads `dropped=` for telemetry symmetry (#6).

## Open (operator decision, deferred — not changed here)
`analyze.py`'s "offered-turn dodge" headline (~93%) is computed ALL-BANDS (includes never-shown
getaway / intent_skip turns), so it likely OVERSTATES the shown-menu dodge. build_keep_off now uses
the corrected `band=="offer"` denominator, so the two intentionally differ. Whether `analyze.py`
adopts the same filter — changing the published compliance number and the evidence framing behind
ADR-0009 — is an operator call, deliberately NOT made here (don't silently move an operator metric).
