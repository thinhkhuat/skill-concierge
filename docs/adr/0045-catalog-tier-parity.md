# ADR-0045 — Catalog tier parity: one offer, one floor

Status: Accepted + implemented (2026-08-28).
Supersedes: [ADR-0032](0032-external-catalogs-first-class-annex.md) (the additive-annex
shape and its zero-displacement invariant; the get_skill consumption lane and
usage-promotion survive) and [ADR-0043](0043-catalog-flywheel-generation-and-bounded-parallel-workers.md)
Decision "default coverage stays installed-only".
Amends: [ADR-0031](0031-external-catalog-roots.md) (the substrate — catalog-roots config,
`catalog:<alias>` scope, `tier: external`, promotion — is unchanged and load-bearing) and
[ADR-0036](0036-dynamic-annex-sizing.md) (the competitive-margin rule survives for the
foreign annex only).
Source: owner decision in session, 2026-08-28 — "no favor, none of the unfairness between
the 2", following the parity audit of the same day (five asymmetries, listed below).

## Context

The audit found the built-in shelf and the external catalogs at parity in the SUBSTRATE
(same embedder, same collection, same flywheel pipeline, `search_skills` fused, `get_skill`
equal) but not in the per-turn OFFER, where five asymmetries all favored installed skills:

1. The ADR-0032 annex was silent on installed-getaway turns — the turns where the installed
   shelf had nothing to say were exactly the turns an external could not speak.
2. The external floor was 2.2× the installed floor (0.40 vs `ITEM_FLOOR` 0.18).
3. Zero displacement: `must_not tier=external` made the installed ranking unassailable — a
   0.95 external could never beat a 0.19 installed — and slots were asymmetric (8 vs ≤4).
4. Chain routing was an installed-only network: the sidecar skipped `catalog:*` scopes, so
   CHAIN-HINT and ROUTE could never name an external.
5. The flywheel's manual default covered installed only (ADR-0043 D10); catalogs depended
   on remembering an opt-in flag.

## Decision

**ONE merged ranked pool. Externals compete on score alone.** Owner order; the unvetted-
content concern that motivated ADR-0032's safeguards is superseded by it (the promotion
valve + the get_skill lane remain the safety story).

1. `_retrieve` drops the tier filter when `EXTERNAL_OFFER` is on: one grouped query over
   both tiers, over-fetch to `RETRIEVE_LIMIT` (the ADR-0034 twin test still post-filters
   foreign rows), trim to `TOP_K`. A catalog row never takes the twin test — it is not
   Skill-tool-invocable anywhere here and the `get_skill` lane is its first-class path.
   The row's alias comes from its own payload scope (`catalog:<alias>`).
2. One floor: `ITEM_FLOOR` (0.18) for every row, both tiers. `EXTERNAL_FLOOR` and
   `EXTERNAL_SLOTS` are deleted; the getaway/actionability gates run tier-blind on the
   merged top — which removes asymmetry 1 by construction.
3. Render: externals INLINE in the ranked list, marked `[external:<alias>]`, sharing the
   same %-share pool, with one footer carrying the `get_skill` consumption instruction when
   any external row is shown. The separate "External catalog matches" annex block is gone.
4. Chain routing admits externals: the sidecar now records `catalog:*` scopes (server-side
   write + enforcer-side read, both gated on `EXTERNAL_OFFER`); CHAIN-HINT successors and
   ROUTE projections mark external names `[external:<alias>]`. KEEPOFF still filters —
   tier-equal. Honest limit: mined chains (ADR-0040) read Skill-invocation take sequences;
   `get_skill` takes ARE ledger rows (the PostToolUse matcher records them and
   `auto_promote.py` consumes them), but the chain layer mines only `auto`/`manual`
   events — `build_chains.load_sequences` and the enforcer's `_last_used_skill` both
   filter `ev not in ("auto", "manual")` — so a pull cannot enter a mined sequence or
   seed a hint. That is a design choice to make, not a recorder gap: a body pull is one
   step weaker than an invocation (following the SKILL.md inline is not observable).
   Recorded, not built.
5. Flywheel: a bare `--generate` covers EVERY scope — installed first, then each configured
   catalog, each scope capped by `--limit` — one lock, one closing reindex, one manifest
   record now tagged with its `scope` (the status card prefers the explicit field over the
   old total-matching inference). `--catalog <alias>` narrows; `--installed-only` restores
   the old default. `auto_flywheel` collapses to that single default call.
6. Ledger: `ext` keeps its shape (list of `[name, score]`) but records external rows inside
   the PRIMARY offer, not an annex. EPOCH v0.38.0 for offer-composition and external
   offer→take rates.

## Kill-switch (one-var revert)

`ENFORCER_EXTERNAL_OFFER=0` — legacy `ENFORCER_EXTERNAL_ANNEX=0` honored — restores the
ADR-0031 search-only tier exactly: `must_not tier=external` returns to the query, external
rows render nowhere, `ext` stays absent, catalog scopes leave the visible sidecar. The
pre-ADR-0034 byte-identical request shape additionally requires `ENFORCER_CROSS_HARNESS=0`.

## Consequences

- A catalog-heavy domain can now fill most of the TOP_K window with externals (measured
  live at ship: 6 of 8 rows on a catalog-flavored intent, ranked 0.73–0.80). That is the
  parity the owner ordered; the installed shelf keeps its resident-name advantage and the
  promotion valve converts demonstrated external usage into installed skills.
- The ADR-0032 "unvetted third-party text gets no cheap airtime" safeguard is consciously
  traded away at the offer layer; provenance marking (`[external:*]` + the get_skill
  footer) is the remaining signal.
- The foreign annex (ADR-0034) is untouched — a different axis (other harnesses, not tiers)
  — and keeps ADR-0036's competitive-margin sizing against the merged-pool top.
- New epoch for OFFER-composition metrics at ship; analyze.py's external offer→take
  consumer is shape-compatible and keeps working.

## Evidence

Implemented + verified 2026-08-28:
- `enforcer.py --selftest` case (10) rewritten: parity on → no tier filter, scope payload,
  merged ranking, alias map, inline render with shared share + footer, no annex block;
  kill-switch → `must_not tier=external` restored, zero external rows, no marker. Case (9d):
  catalog-scope sidecar successors hint with `[external:alias]`; parity off hides them.
  Case (11) re-pins `_annex_floor` for its one surviving consumer (foreign annex). Case (12)
  updated for the `(rows, ext)` return + the two-kill-switch pre-ADR-0034 shape pin. Green.
- Live e2e probe (`plans/260828-2115-catalog-tier-parity/e2e_probe.py`): in-process merged
  retrieval against the live index returns 6 external rows in the top-8 for a
  catalog-flavored intent; subprocess hook run emits a well-formed parity offer; ledger
  writes land in a throwaway dir.
- Flywheel: `--help` shows `--installed-only`; `flywheel_manifest.py --selftest` green.
