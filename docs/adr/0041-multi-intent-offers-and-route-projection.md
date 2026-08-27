# ADR-0041: Multi-Intent Offer Shaping + Route Projection

- **Status**: Accepted
- **Date**: 2026-08-28
- **Plan**: `plans/260828-0004-skill-chain-intelligence/plan.md` (Phases 2–3 of 4; Phase 1 = ADR-0040)

## Context

The offer rendered at turn zero had two blind spots, both measured:

1. **Single-intent assumption.** The whole prompt is embedded once and the top-8
   candidates compete for slots of ONE blended intent. A "research it, build it,
   ship it" prompt starves its secondary intents — their candidates mix into one
   list with no signal that they answer *different parts* of the task.
2. **Chains only after the fact.** ADR-0029/0040 chain knowledge fired only via the
   reactive CHAIN-HINT (after a skill was already used). At the moment of choice —
   the offer — the agent saw no route.

## Decision

Both upgrades are **context-only rendering changes** in `_ranked_mandate`: the
candidate set, its scores, every gate, floor, and the locked header/footer literals
are untouched. Single-intent turns with no route render byte-identically to pre-0041.

### Multi-intent shaping (`ENFORCER_MULTI_INTENT`, default ON)

- `_intent_clusters(cands)` — greedy lexical clustering, best-score-first, over
  name+description tokens with a domain-generic stoplist (skill/code/task/agent…
  dropped so overlap tracks *intent vocabulary*, not boilerplate) and naive
  singularization (report/reports, suite/suites).
- Merge rule: Jaccard ≥ `ENFORCER_INTENT_MERGE_J` (0.24) against the cluster's
  token union. Deterministic, pure, zero-network, O(n·k) on ≤ TOP_K rows.
- Split gate: `_multi_intent_gate` — ≥ 2 clusters AND the second lead scores
  ≥ `ENFORCER_INTENT2_RATIO` (0.75) of the first lead. A lexically odd but weak
  sibling cannot split a single-intent turn.
- Render: **leads-first** — rows 1..N are the N primaries (one per intent), the
  supporting rows follow grouped behind their lead; the note states the intent
  count and the one-USING-per-intent-at-its-moment discipline.

### Route projection (`ENFORCER_CHAIN_PROJECTION`, default ON)

- `_route_of(seed)` — bounded walk of the merged chain map (ADR-0030 overrides >
  ADR-0029 declared > ADR-0040 mined, via the same `_visible_sidecar_names()`):
  strongest successor per hop, cycle-safe (visited set), capped at 4 nodes,
  successors must be live map keys.
- Rendered as one advisory line for the TOP candidate only:
  `ROUTE: if X fits, the catalogue's typical continuation is X -> a -> b -> c
  (projection, fit still required).` Wording avoids the audit's locked literals
  (parity rule shared with CHAIN-HINT).
- Default ON (owner direction, 2026-08-28): same blast-radius class as the
  already-ON CHAIN-HINT — one context line, no gate authority. The plan's original
  default-OFF-until-measured caution is superseded; the L4 continuation-rate
  metric below is the check.

### Telemetry (L4 seed)

`_append_offer` gains additive keys `n_intents` (when > 1) and `route` (when
projected), computed by the same pure helpers the renderer used — ledger row and
injected text cannot disagree. Analyzers extend `analyze.py` later
(continuation-rate: did a routed/hinted successor fire within N turns?).

## Consequences

- A blended multi-part prompt now shows N primaries up top instead of one blurred
  list, and the strongest single pick shows its whole typical route before
  anything is invoked.
- Failure modes bounded: lexical clustering can over/under-split at the margins —
  the strength gate and the 0.24 merge threshold were tuned on real catalogue
  descriptions (siblings ≈ 0.27–0.4 overlap merge; disjoint intents ≈ 0 stay
  split); worst case is a cosmetic note, never a lost or displaced candidate.
- Per-turn cost: clustering is trivial (≤8 rows); `_route_of` reads the same three
  small JSON files CHAIN-HINT already reads (sidecar, overrides, mined map) —
  one extra bounded read per offer-bearing turn, no network.
- Epoch note: `n_intents`/`route` keys date this change in the ledger; any
  offer-composition comparison across the 0.32.0 boundary is epoch-scoped.

## Amendment (0.32.1, 2026-08-28)

The 0.32.0 live smoke exposed an over-split: same-family skills share no surface tokens
(synonymy), so a single-intent prompt announced 7 fake intents. Three deterministic fixes,
selftest-pinned against the live prompt shapes: synonym folding (8 conservative domain
families) before clustering; the merge test switched from Jaccard to the overlap
coefficient (Jaccard punishes the long skill-specific token tails siblings carry —
inter=3 over |a|=11,|b|=8 is 0.19 split vs 0.38 merge), with the threshold moved
0.24 → 0.30 accordingly; and `ENFORCER_MAX_INTENTS` (default 3) — beyond the cap,
extra clusters fold back as supporting rows, never announced intents, and the
telemetry cap matches. Known bounded residual: a lexically disjoint near-tied candidate
can appear as a low-value third intent; advisory only, Phase-4's continuation metric
is the arbiter.

## Amendment (0.32.2, 2026-08-28)

Second smoke pass: the cap bounded but did not silence thin false intents — a single stray
lexically-disjoint near-tied row still announced itself. Precision rule added: a second
announced intent must bring ≥2 candidates (`_qualifying_intents`; the top's own cluster
always qualifies; renderer and telemetry share the filter). Deliberate recall cost: a thin
TRUE third intent may go unannounced — advisory annotations must not cry wolf.

## Amendment (0.33.0, 2026-08-28) — the loop closes

L4 shipped: offer events log the fired CHAIN-HINT as an additive `hint` key
(`_chain_hint_data`, shared with the renderer so ledger and injection cannot
disagree), and `analyze.py --continuation` reports route-follow / hint-follow /
multi-intent uptake vs a single-intent control — epoch-scoped, sub-lane excluded,
sub-floor samples print "insufficient data" and never a pooled rate.
