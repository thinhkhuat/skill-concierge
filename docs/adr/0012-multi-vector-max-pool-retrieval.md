# ADR-0012 — Multi-vector MAX-pool retrieval (trigger layer)

Status: Accepted (2026-06-30)
Relates to: ADR-0002 (semantic which+whether), ADR-0003 (embedder/store), ADR-0009 (gate floor),
supersedes the MEAN enrichment overlay (enrich_index.py) as the phrase-signal mechanism.

## Context
Each skill was ONE vector (`name+desc+body`). mpnet cosines sit in a compressed ~0.18–0.40 band;
the journals named the ceiling: "substrate measures topic, not intent" (dodged-median cosine 0.445 >
taken 0.408). The MEAN enrichment overlay tried to inject phrase signal by averaging trigger
embeddings INTO the one vector — but a centroid dilutes the one distinctive phrase, and the overlay
was not reindex-robust (a reindex rewrote it bare; it was found OFF). A re-study of the BM25-routing
design (`plans/reports/analysis-260629-2342-bm25-doc-missed-novelty-report.md`) identified the missed
mechanism: score a skill by its single BEST phrase point (MAX), not a centroid (MEAN).

## Decision
Index each skill as MANY points and MAX-pool at query time:
- **Build (`server.build_index`):** one `kind="base"` point (`name+desc+body`) PLUS one
  `kind="trigger"` point per intent phrase from the description (`_split_phrases`, ≤12, mirrors
  `build_triggers.py`). Stable per-(skill, slot) ids (`_point_id(f"{name}::trig::{i}")`) keep reindex
  incremental and reindex-SAFE — a plain reindex maintains the layer (no overlay/reapply). Per-chunk
  upsert (one-shot upsert overflowed Qdrant's 33 MB request limit at ~2.3k points).
- **Retrieve (`search_skills` + enforcer `_retrieve`):** Qdrant `query/groups` (`group_by="name"`,
  `group_size=1`) → top-K DISTINCT skills, each scored by its best point. A keyword payload index on
  `name` keeps it exact + fast. On a single-vector index this is identical to a plain top-k.
- **Floor:** KEPT at `GETAWAY_FLOOR=0.45`. A floor sweep on the multi-vector shadow showed the
  "flooding" was a 0.20-floor artifact; at 0.45 crowd-median is 11 (vs bare 34 @0.20), pos-clear 64.9%,
  false-fire flat. No threshold change needed.
- **Toggle:** `SKILL_MULTIVECTOR` (default ON). `=0` + reindex drops every trigger point and restores
  one bare vector per skill (clean revert).

## Evidence (shadow A/B, held-out {base,trigger}; report: experiment-260630-…)
rank-1 11.3→25.0 % (2.2x), top-5 26.2→46.4 %, separation 0.049→0.105 (2.2x), true-neg false-fire flat
1.4→1.4 %. Live spot-checks: "fix a failing supabase migration" → `supabase-apply-migration` 0.717
(bare ~0.51); conversational prompts still suppressed; groups query latency ~2 ms; index 500→2312 points.

## Consequences
- Recall lever moves materially (the documented ceiling), at the same floor, ~5x index points, no
  measurable latency cost.
- Residual menu noise: trigger phrases can collide topically (e.g. "token format" pulls
  `design-system` via "token architecture"); the right skill lands in the top-5 (46%) and the agent
  picks via the %-share + "pick the one matching intent" note. Expected (experiment confusion data).
- **Activation caveat:** the PERSISTENT skill-search MCP process runs the old single-vector code until
  it restarts, so its `search_skills` returns duplicate points on the multi-vector index until reload.
  The enforcer (fresh subprocess per prompt) uses the new code immediately. Restart the MCP / reconnect
  to fully activate.
- `calibrate_thresholds.py` now scores against a skill's `kind="base"` vector, which no longer mirrors
  live MAX-pool retrieval — per-skill tau / corpus-health status is now approximate (advisory only;
  tau ships inert per ADR-0009).
- The MEAN enrichment overlay is superseded; `doctor --fix` no longer runs the legacy reapply when
  MULTIVECTOR is on (it would mean-corrupt base vectors).

## Open / to measure
- Real adoption impact (offered-turn conversion) needs a post-deployment traffic window — measure via
  `analyze.py` (now band=="offer" denominator, ADR-0011) before judging the central bet.
- Per-skill tau could become live-useful now that separation doubled — recalibrate against multi-vector
  MAX scores before arming `ENFORCER_PER_SKILL_TAU` (currently inert).
