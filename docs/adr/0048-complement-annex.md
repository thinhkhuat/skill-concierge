# ADR-0048 — Complement annex: gap-gated, usage-ranked externals

Status: Accepted + implemented (2026-08-29).
Amends: [ADR-0047](0047-revert-tier-parity-restore-annex.md) (the annex SHAPE survives
untouched — additive block, zero displacement, get_skill consumption; only the gate and
the order change) and [ADR-0036](0036-dynamic-annex-sizing.md) (the competitive-margin
rule no longer governs the EXTERNAL annex; it keeps governing the foreign annex).
Source: owner order in session, 2026-08-29 — "make the external catalogs, while staying
as annex, far more helpful and serve as a valuable mechanism along with the builtin";
design fork resolved by owner pick (gap-gate + usage ranking; thin-intent bar reuses
`GETAWAY_FLOOR`).

## Context

Ledger evidence gathered before design (live log, 2026-08-29): 2,656 offers, 410 (~15%)
carried externals — **6 external pulls ever**. The ADR-0047 margin rule admitted echoes
of well-served intents (externals trailing the installed top by 0.08) that nobody
consumed, while the 6 externals that WERE pulled all matched genuine builtin gaps
(multi-source-search, apple-container, pdf-conversion-router, active-directory-attacks).
The annex spoke when it shouldn't and ranked by raw score when it did.

## Decision

The annex becomes the builtin's **complement**, not its echo.

1. **Gap/beat gate** (`_retrieve_external`, default ON): when the installed top ≥
   `GETAWAY_FLOOR` (0.45 — the owner-tuned "the builtin answers this intent" bar, reused
   by owner pick), an external earns a slot only by BEATING that top by
   `ENFORCER_ANNEX_BEAT` (default 0.04). When the top is below it (thin inventory — the
   case externals exist for), the plain `EXTERNAL_FLOOR` (0.32) applies and the annex
   widens to its cap. Well-served intents go annex-silent; the noise class dies.
2. **Usage ranking**: `auto_promote.py` (which already counts external `get_skill` pulls
   per distinct session over the ledger tail for promotion) dumps
   `~/.claude/skill-concierge/external-takes.json` (`{name: count}`, atomic write,
   advisory). The enforcer reads it live (blocklist pattern — tiny file, fail-open):
   taken-before externals float first (takes desc, score desc) and render `used N×`.
   Provenness reorders and marks; it never admits a row below the gate. The external
   query over-fetches (`EXTERNAL_SLOTS * 3`) so beat-gating rejections and reordering
   never shrink the real annex.
3. **Kill-switch**: `ENFORCER_ANNEX_COMPLEMENT=0` restores the ADR-0047 margin-rule floor
   and score-only ordering; the mode-independent `EXTERNAL_SLOTS × 3` over-fetch and
   post-filter slice remain (strictly better than 0.40.0: a legacy-mode annex now fills
   its slots even when floor/blocklist filtering drops top groups, where 0.40.0 would
   have returned short). EPOCH v0.41.0 (offer composition changes).

## What stays

- Zero displacement; separate `must tier=external` query; annex block rendering +
  get_skill footer; blocklist filtering of annex rows; `ENFORCER_EXTERNAL_ANNEX=0` →
  search-only tier. The promotion valve (`PROMOTE_MIN_TAKES=3` distinct sessions)
  unchanged — ranking is the layer BELOW promotion.
- The foreign annex (ADR-0034) untouched: same `_annex_floor` margin rule as ADR-0047.

## Consequences

- The annex fires far less often — by design. Expect the external offer→take rate
  (epoch v0.41.0) to rise while raw annex volume collapses; that is the metric this ADR
  optimizes. If beat-gating starves legitimate complements (cosine-band compression),
  lower `ENFORCER_ANNEX_BEAT` or flip the kill-switch — env-only, no re-release.
- A first-take external still competes blind on score (cold start); it earns ranking
  only after someone pulls it once. Promotion remains the graduation path at 3 sessions.
- `auto_promote` cadence (throttled SessionStart) bounds digest freshness to ~one
  session; the ledger tail window (1 MB) bounds it to recent usage — recent-usage
  ranking is a feature, not a limitation, here.

## Evidence

Implemented + verified 2026-08-29: enforcer selftest case (11c) pins the beat gate, the
thin-intent widening, proven-first ordering, the `used N×` marker, and the kill-switch
(legacy margin floor + query order preserved); auto_promote selftest green (digest write
is additive); live probes in `plans/260829-1517-annex-complement/`.
