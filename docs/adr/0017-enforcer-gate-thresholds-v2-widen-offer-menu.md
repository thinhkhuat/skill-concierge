# ADR-0017: Operator-set enforcer gate thresholds v2 — retain score floor 0.45, widen offer-menu TOP_K 5→8

**Status:** Accepted — **supersedes [ADR-0009](0009-operator-set-gate-thresholds.md)**, which it consolidates. The word floor remains as set by [ADR-0010](0010-word-floor-5-to-3.md) (3) and is referenced, not re-decided. Explicitly reversible (see "Consequences & revert").
**Date:** 2026-07-05
**Deciders:** owner (thinhkhuat)

## Context

Two levers control how visible the enforcer's automatic skill offer is on a given turn (`hooks/scripts/enforcer.py`):

- `GETAWAY_FLOOR` — an offer fires only when the top retrieval cosine ≥ this value. ADR-0009 set it to **0.45** (operator order, over a data-backed recommendation of 0.40).
- `ENFORCER_TOP_K` — how many candidates a fired offer menu lists (each still subject to `ITEM_FLOOR`). Not previously governed by an ADR; default **5**.

Separately, a live diagnosis of retrieval recall (2026-07-05) showed that a conversational, single-phrasing query surfaces generic skills and buries the precise one below the shown cut — e.g. "explain to me how a project codebase works" returned generic analyzers while `codebase-onboarding` fell outside the top hits. The primary fix landed on the engine (query fanout / MAX-pool fusion — see *Related*); on the enforcer side, the owner chose to widen the offer menu so more genuinely-relevant candidates survive to be shown.

## Decision

This ADR is now the single record of the operator-set enforcer gate thresholds and supersedes ADR-0009:

1. **Retain `GETAWAY_FLOOR = 0.45`** (unchanged from ADR-0009). The data-backed 0.40 alternative remains available via `ENFORCER_GETAWAY_FLOOR=0.40`.
2. **Retain the word floor at 3** as set by ADR-0010 (referenced, not re-decided here).
3. **Widen `ENFORCER_TOP_K` default 5 → 8.** A fired offer menu may now list up to 8 candidates (those clearing `ITEM_FLOOR`), so a genuinely-relevant skill that a 5-item cut hid is more likely to surface.

## The tension (recorded, per ADR-0009's own discipline)

ADR-0009's thesis was *noise reduction* — the operator perceived too much offer-noise (~94% of fired offers dodged) and tightened the fire gate. Widening `ENFORCER_TOP_K` pushes the opposite way: it adds lower-ranked candidates to each fired offer, i.e. more push-noise per offer. `TOP_K` is **not** the fire gate (the floor is), so it does not change *how often* an offer fires — only *how many* items a fired offer lists. Accepted on the owner's explicit order because: (a) the owner owns the recall/precision trade-off and is acting to lift genuine-but-buried skills into view; (b) blast radius is bounded — the enforcer is an additive, fail-open hook, so extra menu items never block work; (c) the knob is environment-overridable and the revert is one line.

## Consequences & revert

- To restore the prior menu breadth: set `ENFORCER_TOP_K` default back to `5` in `hooks/scripts/enforcer.py`, or export `ENFORCER_TOP_K=5` (no code edit).
- Score-floor revert is unchanged from ADR-0009: default `0.40` / env `ENFORCER_GETAWAY_FLOOR=0.40`.
- Re-check after any future change: `analyze.py` offered-turn conversion — confirm widening did not drop the take-rate of surviving offers (window to the current epoch per the AGENTS.md telemetry rule).

## Verification

- `python3 scripts/driftcheck.py driftcheck.json` — version IN SYNC at 0.13.0.
- `python3 hooks/scripts/enforcer.py --selftest` — refusal guard + ranked-mandate + imperative-veto pass (this change touches no tested contract).
- Companion engine change verified by `vendor/skill-search/tests/test_fusion.py` + a live e2e (fusion surfaces `codebase-onboarding` that a single phrasing buried).
- Shipped as **0.13.0** (MINOR — additive: new `search_skills(extra_queries=…)` param + wider default).

## Related

- **Supersedes** [ADR-0009](0009-operator-set-gate-thresholds.md) (operator-set gate thresholds; its score-floor decision is retained above).
- [ADR-0010](0010-word-floor-5-to-3.md) — word floor 3 (still in force).
- [ADR-0002](0002-fusion-which-plus-whether.md), [ADR-0012](0012-multi-vector-max-pool-retrieval.md) — the retrieval fusion this release extends.
- **Companion engine change (same release, 0.13.0):** `search_skills` query fanout — the caller passes 2–3 phrasings via `extra_queries`, the server embeds each and MAX-pools the union per skill (`vendor/skill-search/skill_search/server.py`), plus `SKILL_TOP_K=10` deployed in `.mcp.json` for the pull tool. A candidate for its own ADR if the fusion design evolves.
