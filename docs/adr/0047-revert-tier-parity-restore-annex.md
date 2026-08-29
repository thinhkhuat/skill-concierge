# ADR-0047 — Revert catalog tier parity; restore the external annex, tuned

Status: Accepted + implemented (2026-08-29). Amended by [ADR-0048](0048-complement-annex.md)
(same day): the external annex this ADR restored now gates by the complement beat rule and
ranks by demonstrated usage; the annex SHAPE, floors' kill-switch, and everything this ADR
reinstated stand unchanged — `ENFORCER_ANNEX_COMPLEMENT=0` restores this ADR's margin rule.
Supersedes: [ADR-0045](0045-catalog-tier-parity.md) in full (the merged offer pool, the
tier-blind gates, catalog scopes in the chain sidecar, the every-scope flywheel default,
and the same-day option-(a) amendment that let mined chains ingest `get_skill` pulls).
Reinstates: [ADR-0032](0032-external-catalogs-first-class-annex.md) (additive annex +
zero displacement + usage-promotion), [ADR-0036](0036-dynamic-annex-sizing.md) for BOTH
annexes (external + foreign), and [ADR-0043](0043-catalog-flywheel-generation-and-bounded-parallel-workers.md)
Decision "default coverage stays installed-only".
Source: owner order in session, 2026-08-29 — "i find the new implementation is a
regression rather than an enhancement … so that the mechanism returns to before that
implementation", with one refinement: "refine the floor & other relevant values to be
more helpful than the ADR-0032-era".

## Context

ADR-0045 merged both tiers into one ranked pool: externals shared `ITEM_FLOOR`, the
`TOP_K` slots, and the %-share pool. Its own Consequences section recorded the cost
honestly: "a catalog-heavy domain can now fill most of the TOP_K window with externals
(measured live at ship: 6 of 8 rows)". One day of live use confirmed exactly that as the
dominant experience — the per-turn preview drowned the installed shelf in `[external:*]`
rows the Skill tool cannot invoke, trading the offer's actionability for catalog reach.
The owner judged the trade a regression and ordered the pre-parity mechanism back.

## Decision

**The ADR-0032 additive annex is the mechanism again — with two tuned defaults.**

1. `_retrieve` always carries `must_not tier=external`; the installed ranking and every
   gate (keepoff, blocklist, deterministic, getaway, actionability, tau, dominance,
   multi-intent) run on installed rows only. Zero displacement is an invariant again.
2. Externals return via the separate `_retrieve_external` query into a marked annex
   block ("External catalog matches"), consumed via `get_skill`, never sharing the
   %-share pool. ADR-0046 blocklist filtering now also covers annex rows (new — the
   pre-parity code predated the blocklist).
3. Chain sidecar/hints/ROUTE are installed-only again: the engine's
   `_write_next_skills_sidecar` skips `catalog:*` scopes; the enforcer no longer admits
   catalog scopes or tags `[external:*]` in hint/route lines. Parity-era catalog keys in
   the live sidecar are pruned once at deploy (the enforcer stopped reading them).
4. Mined chains read invocation events only (`auto`/`manual`); the `CHAIN_MINE_PULLS`
   pull-mining layer (0.38.1) is removed, not just defaulted off.
5. Flywheel `--generate` defaults to installed-only; catalogs are covered by
   `--catalog <alias>` and by the auto-flywheel per-alias loop (v0.35.1 shape).
6. Flag naming: `ENFORCER_EXTERNAL_ANNEX` is primary again; the parity-era
   `ENFORCER_EXTERNAL_OFFER` stays honored as an alias (either `=0` → the ADR-0031
   search-only tier). No install that pinned either name breaks.

### Tuned defaults (the "more helpful than ADR-0032-era" refinement)

| Var | 0032-era | Now | Rationale | Revert |
|---|---|---|---|---|
| `ENFORCER_EXTERNAL_FLOOR` | 0.40 | **0.32** | 0.40 was 2.2× the installed `ITEM_FLOOR` (the parity audit's asymmetry #2) and starved the annex on thin-inventory turns; 0.32 (~1.8×) still demands a strong match | env var =0.40 |
| `ENFORCER_ANNEX_MARGIN` | 0.05 | **0.08** | 0.05 was measured on the mpnet band (0.10+ saturates every annex at cap); 0.08 sits deliberately just under saturation so competitive externals widen the annex without it living at cap. Shared with the foreign annex, which widens slightly too | env var =0.05 |
| `ENFORCER_EXTERNAL_SLOTS` | 4 dyn / 2 fixed | unchanged | cap was never the complaint | — |

Caveat recorded: 0.08 is a reasoned pick between the measured 0.05 and the measured
saturation at 0.10 — not itself re-measured. If live annexes run at cap on most
offer-bearing turns, drop back toward 0.05.

## What survives from the parity era

- The substrate is untouched throughout: ADR-0031 catalog roots, `tier: external`
  payloads, fused `search_skills`, `get_skill` read-inline, symlink promotion.
- The flywheel manifest's explicit `scope` field and the status card's preference for
  it (pure observability, records truth either way).
- The ADR-0034 foreign annex and its ADR-0036 sizing (a different axis; never merged).

## Consequences

- Installed offers are actionable again: every primary row is Skill-tool-invocable here;
  externals are visibly fenced in their annex with the consumption instruction.
- Catalog reach drops by design — an external can no longer carry a turn the installed
  shelf scores below `GETAWAY_FLOOR` on (the ADR-0032 scope limit returns). The
  promotion valve remains the graduation path for genuinely used externals.
- EPOCH v0.40.0 for offer-composition, external offer→take, and mined-chain metrics:
  parity-era rates (v0.38.x–0.39.x) describe a mechanism that no longer exists — do not
  pool across this boundary.
- Implementation note: the revert was executed by reverse-applying the 4322bc7 and
  2a66d45 diffs (3-way), preserving the interleaved ADR-0046 blocklist work, then
  re-tuning the two defaults above. Selftest evidence at ship: enforcer, build_chains,
  analyze, flywheel_manifest all green; pytest suite green; driftcheck IN SYNC.
