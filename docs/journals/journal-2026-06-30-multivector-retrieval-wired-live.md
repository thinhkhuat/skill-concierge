# Journal — 2026-06-30 — Multi-vector MAX-pool retrieval wired live

## What & why
Re-studied the BM25-routing design against skill-concierge and found the one missed mechanism: the
doc scores a skill by its single BEST phrase point (MAX-pool over per-phrase vectors); skill-concierge
shipped the opposite (one vector/skill; the dormant enrichment overlay MEAN-pools). MAX directly
attacks the documented ceiling — "substrate measures topic, not intent", cosines compressed 0.18–0.40.

Validated on the shadow collection, then (user chose full send) wired live.

## Results (shadow A/B, held-out {base,trigger})
rank-1 11.3→25.0 % (2.2x), top-5 26.2→46.4 %, separation 0.049→0.105 (2.2x), true-neg false-fire flat
1.4 %. Floor sweep: the "flooding" was a 0.20-floor artifact — at the live 0.45 floor crowd-median is 11
(< bare's 34 @0.20), pos-clear 64.9 %. So GETAWAY_FLOOR kept at 0.45 (no change). Live: index 500→2312
points (500 base + 1812 trigger), groups query ~2 ms, "fix a failing supabase migration" →
`supabase-apply-migration` 0.717 (bare ~0.51).

## How
- `build_index` now builds base + per-phrase trigger points (stable per-slot ids → incremental + reindex-safe;
  a plain reindex maintains the layer, unlike the old overlay). Gated by `SKILL_MULTIVECTOR` (default on).
- Retrieval (search_skills + enforcer `_retrieve`) → Qdrant `query/groups`, group_size=1 = MAX-pool;
  keyword payload index on `name`. No-op on a single-vector index (verified identical before migrating).
- ADR-0012.

## Lessons / scars
- **One-shot upsert overflowed Qdrant's 33 MB request limit at ~2.3k points** — the first force-rebuild
  deleted the collection then failed the upsert, leaving the live index EMPTY for a few minutes.
  Fix: per-chunk upsert. Caught immediately by inline post-migration count check. Lesson: any build that
  scales the point count must batch the WRITE, not just the embed.
- **Changing a shared helper has blast radius.** Adding a `band=="offer"` filter to `analyze._offer_conversion`
  silently broke `build_keep_off.py` (its windows had no `band` key → empty keep-off). Walking the callers
  (HARD-GATE) caught it; fix = stamp `band="offer"` in build_keep_off's window builder. Shared metric, one
  semantics.
- **A freshly-prototyped retrieval change can't fully hot-swap a persistent server.** The skill-search MCP
  runs old code until restart → dupes on the multi-vector index until reload. The enforcer (per-prompt
  subprocess) gets new code immediately. Activation = restart the MCP.

## Inert by data, not laziness
Per-skill τ + a deterministic route tier were wired + selftested but left OFF: all 5 `ok`-calibrated τ
sit < the 0.45 floor (one negative), so arming τ today would lower bars and add the false-offers the
owner tuned against. Multi-vector lifted separation 2.2x — recalibrate τ vs MAX scores before arming.

## To measure
Real adoption impact (offered-turn conversion, now band=="offer") over a post-deployment traffic window —
the central bet ("does surfacing the right skill more often raise take-rate?") is still unproven; the
recall lever is proven, the behavioral payoff is not.
