# Multi-vector (MAX-pooled) retrieval vs bare single-vector — SHADOW A/B

**Date:** 2026-06-30
**Script:** `scripts/multivector_experiment.py`
**Engine:** fastembed / paraphrase-multilingual-mpnet-base-v2 (768-d, cosine), engine path only.
**Collections:** LIVE `claude_skills` (read-only) vs SHADOW `claude_skills_shadow` (rebuilt; only mutated collection).
**Corpus:** `eval/scenarios/*.json` — 14 skills, 168 positives, 70 authored near-miss negatives. Floor = 0.20.

## What was built

SHADOW recreated at dim=768/cosine, then loaded as a **multi-vector** index — each skill represented by MANY points, scored by its single BEST point (MAX-pool), the opposite of `enrich_index.py`'s MEAN centroid:

| kind | points | source |
|---|---|---|
| base | 500 | every live point copied verbatim (vector + name) — keeps the full competitive field |
| trigger | 1805 | one point per trigger phrase, `eval/triggers.json`, ALL 498 skills (every skill multi-vector, not just the 14) |
| scenario | 168 | one point per scenario positive, the 14 eval skills |
| **total** | **2473** | (Qdrant confirms 2473) |

**Name resolution:** scenario labels carry one `ck:` prefix (`ck:ai-artist`) but the live index stores a double prefix (`ck:ck:ai-artist`, from the plugin install path). `canonical()` resolves each label to its real live point name, so the LIVE baseline can actually find the skill and SHADOW's trigger/scenario points share the base point's name for MAX collapse. All 14 scenario skills resolve to exactly one live point.

## Leakage guard (why the verdict is read off the held-out column)

The scenario positives are ALSO the eval queries. Indexing them and querying with them is train==test leakage (exact self-match cosine ≈ 1.0). So:

- **SHADOW (held-out)** — the verdict column — scores candidates `{base, trigger}` only. Trigger phrases come from skill *descriptions*, independent of the separately-authored scenario queries, so this is a legitimate generalization test. Scenario points exist in the index (per the build spec) but are held out of scoring.
- **leak (LOO)** — reference only — scores `{base, trigger, scenario}` minus the exact query point. Shown to expose the contaminated optimistic ceiling; NOT the verdict.

## Results (LIVE vs SHADOW held-out vs Δ; leak column for reference)

| metric | LIVE | SHADOW | Δ | leak(LOO) |
|---|---:|---:|---:|---:|
| correct rank-1 % | 11.3 | **25.0** | **+13.7** | 57.7 |
| correct top-5 % | 26.2 | **46.4** | **+20.2** | 83.9 |
| clears-floor % (0.20) | 53.0 | 99.4 | +46.4 | 100.0 |
| true-neg false-fire % | 1.4 | 1.4 | +0.0 | 10.0 |
| pos_mean (best pt) | 0.2306 | 0.4893 | +0.259 | 0.6346 |
| neg_mean (best pt) | 0.1820 | 0.3845 | +0.203 | 0.4829 |
| separation | 0.0486 | **0.1048** | **+0.056** | 0.1517 |

Recall counts: rank-1 19→42, top-5 44→78, clears-floor 89→167 (of 168). True-neg fires 1→1 (of 70).

**Offer-set crowding** (skills clearing floor=0.20 per query, of 495):

| | mean | median | p95 |
|---|---:|---:|---:|
| LIVE | 87.6 | 34 | 334 |
| SHADOW | 340.7 | 356 | 478 |

SHADOW (held-out) confusion — who steals a positive when the correct skill isn't rank-1: `ckm:banner-design` (5), `agent-skills:test-driven-development` (5), `create-image` (4), `ck:ck:remotion` (4), `vn-ares-research-report` (4) — all plausible topical neighbours.

## Reading the numbers

1. **Recall lever is real and large.** rank-1 more than doubles (11.3→25.0), top-5 nearly doubles (26.2→46.4), and **separation doubles** (0.049→0.105 — positives pull ahead of negatives twice as hard). Rank metrics are scale-invariant, so these gains stand regardless of any threshold choice. This is the documented "cosines compressed / topic-not-intent" ceiling actually moving.

2. **The clears-floor and offer-crowding numbers are a scale artifact, not precision.** MAX over up-to-12 phrase points lifts the WHOLE score distribution — correct skill AND competitors. So the 0.20 floor that was calibrated for single-vector scores now admits almost everyone (99.4% clear it; mean offers 87.6→340.7, p95 334→478 of 495). The floor is invalidated by the rebuild; it is not evidence of a fundamental precision loss.

3. **Underlying precision held.** On the authored near-miss negatives, false-fire stayed flat (1.4%→1.4%) and separation improved — i.e., after re-tuning the floor to restore LIVE-like crowding, the recall gains survive (scale-invariant) and the positive/negative gap is wider than baseline.

## VERDICT

Multi-vector MAX **beats** the bare single-vector baseline on the recall lever — rank-1 (+13.7, 2.2x), top-5 (+20.2, 1.8x), separation (2.2x) — and does **not** raise false-fire on labeled negatives. It does NOT satisfy the "without blowing up offer-crowding" clause against the *current* floor: crowding 4x'd, but that is a re-tunable scale shift (ranks are floor-independent; separation improved), not a true precision regression.

**Recommendation: WIRE-LIVE (conditional) — worth the retrieval rewrite, but ONLY bundled with a getaway-floor recalibration.** The 2x recall gain is too large to shelve, but the upward score shift means the existing 0.20 floor cannot be reused — ship multi-vector + a re-tuned floor (and accept ~5x index points and a MAX-collapse query path with a large limit). If the team will not re-tune the floor, do NOT ship: against 0.20 the offer set floods.

## Caveats / unresolved

- **Held-out is the honest A/B; leak(LOO) is contaminated** (rank-1 57.7%) and must not be cited as the gain.
- **The floor re-tune is not done here** — this experiment measures the lever, not the production threshold. A follow-up should sweep the floor on SHADOW to find the value that restores ~LIVE crowding, then re-confirm false-fire there.
- **Index/query cost:** SHADOW is ~5x LIVE points (2473 vs 500) and queries use limit=full-count for a correct MAX collapse; production sizing not assessed.
- SHADOW is left in the multi-vector state (not restored to the prior enriched build) — it is the experiment sandbox. Re-run `scripts/enrich_index.py --shadow` or this script's `--build` to reset as needed.

## Follow-up (2026-06-30) — floor swept + WIRED LIVE
The two unresolved caveats are now closed:
- **Floor sweep** (`multivector_experiment.py --sweep`, held-out {base,trigger}): the 0.20-floor flood
  is an artifact. At the live floor **0.45**: pos-clear 64.9 %, false-fire 1.4 %, crowd mean 18.9 /
  median 11 (LIVE bare @0.20 was 87.6 / 34). So **GETAWAY_FLOOR kept at 0.45** — no re-tune needed.
- **Production wiring:** `build_index` now builds base + trigger natively (reindex-safe, per-chunk
  upsert), retrieval uses Qdrant `query/groups` (MAX-pool), keyword index on `name`. Live index
  migrated 500→2312 points; groups query latency **~2 ms** (5x index, no cost). Gated by
  `SKILL_MULTIVECTOR` (default on; revert = `=0` + reindex). See ADR-0012.
- **Caveat:** the persistent MCP must restart to drop dup hits from its old single-vector code.
