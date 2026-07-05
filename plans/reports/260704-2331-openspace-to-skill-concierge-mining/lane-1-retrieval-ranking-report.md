# Lane 1 — Retrieval & Ranking: OpenSpace → skill-concierge fit analysis

- **Date:** 2026-07-04 23:31 (Asia/Saigon)
- **Reference (studied):** `OpenSpace/openspace/skill_engine/{registry,skill_ranker,retrieve_tool,fuzzy_match}.py`, `grounding/core/search_tools.py`
- **Target (fit-rated against):** skill-concierge `vendor/skill-search/skill_search/{skills_discovery,server}.py`, ADR-0003/0012/0016, `scripts/{enrich_index,build_triggers,multivector_experiment}.py`, `docs/multivector-retrieval-arc.md`
- **Lane question:** what does OpenSpace's retrieval do that skill-concierge's pure-dense Qdrant + MAX-pool does NOT, and would lift recall/precision WITHOUT an LLM call in the per-turn hot path?
- **Status:** DONE

> ⚠ **EPOCH-VALIDITY CAVEAT** — added 2026-07-05; supersedes any current-state reading of the ledger figures in this report.
>
> **Corrected mental model:** *In a system whose configuration changes almost daily, its telemetry is a sequence of short epochs, not one dataset — a metric is only valid for the config epoch it was collected under; pool across epochs and you measure a system that never existed.*
>
> Every ledger/telemetry figure cited here — offer→take, "~94% dodge", cosine 0.414 vs 0.457, any conversion/fallback rate — is **epoch-specific**, mostly **ADR-0009-era (v0.6.1, 2026-06-29)**, and must NOT be read as current-state. skill-concierge shipped ~8 config epochs in 8 days, including the **v0.10.0 multi-vector retrieval swap** whose own CHANGELOG says *"re-measure before reuse"* — so pooling across, or carrying a number past, an epoch boundary is invalid. The only valid read is per-epoch (`analyze.py --since/--until` at version-bump commit timestamps); the current epoch (v0.12.0) has N≈15 surfaced offers — **insufficient for any rate**. Corrected per-epoch figures accompany these reports in this directory.

---

## What OpenSpace's retrieval actually is (verified in code)

A **cascade**, not a score-fusion. `SkillRanker.hybrid_rank` (skill_ranker.py:107-137) runs BM25 to keep `top_k * 3` candidates (`BM25_CANDIDATES_MULTIPLIER=3`, :48), then embedding-cosine **re-ranks only those** and returns top_k by cosine. `search_tools.py._hybrid_search` (:404-425) does the same (`kw_top = keyword_search(..., top_k*3)` :408 → semantic re-rank :419). On top sits an **LLM selection/filter** layer (registry.py:340-503; search_tools.py:864-999) and **telemetry-driven filtering/re-ranking** (registry.py:382-407; search_tools.py:803-810).

skill-concierge is **pure-dense MAX-pool**: `search_skills` embeds the query once and calls Qdrant `query_points_groups(group_by="name", group_size=1)` (server.py:441-443) — no lexical signal, no LLM, no telemetry in the ranker.

## Fit table

| idea | OpenSpace source (file:line) | maps to skill-concierge unit | tier | why it fits (or not) | net-new vs present |
|---|---|---|---|---|---|
| **Lexical (BM25) signal fused with dense** | skill_ranker.py:264-312 (`_bm25_rank`, corpus = `name+desc+body[:2000]` :281-285); search_tools.py:215-254 | server.py `search_skills` :431-462 / enforcer `_retrieve` | **HIGH** | Directly attacks the documented mpnet ceiling ("measures topic, not intent," 0.18–0.40 band; ADR-0012:12-14, arc:22-24). Dense scores exact tokens / rare API names / acronyms LOW (`supabase`, `k6`, `WCAG`, `mermaidjs-v11`) — sometimes under `GETAWAY_FLOOR=0.45`. BM25 over the SAME corpus (name+description+`body_triggers`) rescues them. LLM-free; `rank_bm25` in-process is trivial at 500 skills / 3570 points, adds ~ms. **Adapt, don't replicate:** OpenSpace uses BM25 as a recall *pre-filter* then lets cosine decide final order (skill_ranker.py:131) — that would still demote an exact-match skill dense rates mid. skill-concierge needs true **fusion** (RRF or max-normalized blend of BM25 score with the MAX-pool group score) so lexical can *promote* rank, not just gate the candidate pool. | **Net-new** — no lexical layer today |
| **Telemetry-driven ranking prior** (downweight/drop skills that fire but never land) | registry.py:382-407 (drop `selections>=2 & completions==0`; `fallbacks/applied>0.5`); search_tools.py:803-810 (`quality_manager.adjust_ranking`) | Ledger organ → post-retrieval re-rank before the gate | **MED-HIGH** | skill-concierge already HAS the Ledger telemetry organ and an open question of "adoption payoff not proven / offered-turn conversion" (ADR-0012:54-55, arc:44-46). A cheap, LLM-free prior that penalizes skills repeatedly offered-but-not-taken is the exact analogue of registry.py:393-400, and it feeds the one metric the project says it can't yet move. **Caveat:** needs a traffic window first (arc:44-46) and a floor on sample size to avoid punishing new skills; keep it a soft score nudge, not a hard drop. | **Net-new** in the ranker (telemetry exists but is not folded into retrieval) |
| **Two-stage cascade order** (lexical narrow → dense re-rank) | skill_ranker.py:123-137; search_tools.py:404-425 | — | **LOW** | The cascade's purpose is cost control on huge catalogs (PREFILTER_THRESHOLD=10, registry.py:414). At 500 skills / 3570 points skill-concierge has no cost problem, and the cascade's "cosine decides final order" actively *loses* the lexical-promote benefit above. Take the lexical *signal*, drop the cascade *structure*. | Structure not wanted |
| **LLM plan-then-select** | registry.py:340-503 (prompt :676-704) | (would be) enforcer gate | **LOW / does-not-transfer** | Adds an **online LLM call** to the per-turn latency-critical gate — the exact thing skill-concierge was built to avoid (fast fresh-subprocess gate, ADR-0012:44-46). Excluded by mission. Marginal even in the user-invoked MCP path vs MAX-pool. | Deliberately absent |
| **LLM query expansion** (task → capability keywords appended) | search_tools.py:1001-1012 (`_generate_search_query`) | query preprocessing | **LOW** | Same LLM-in-hot-path problem. A non-LLM variant (static synonym/acronym expansion) is conceivable but low-value once BM25 already covers exact tokens. | Not worth it |
| **LLM server/utility split filter** | search_tools.py:864-999 | — | **N/A** | Structural to MCP *tool* routing (many servers, utility vs domain tools); skill-concierge retrieves flat skills, not servers. No mapping. | Irrelevant |
| **Content-addressed embedding cache** | skill_ranker.py:163-173 (`_content_key` = sha256(text)) | server.py:243 `_content_hash`, incremental `build_index` :393 | **LOW** | skill-concierge **already does this** (per-point content_hash → incremental reindex skips unchanged, server.py:393-411). | **Already present** |
| **Fuzzy SEARCH/REPLACE chain** | fuzzy_match.py:249-322 (`REPLACER_CHAIN`) | — | **NONE** | Wrong domain entirely: it locates code blocks for *edit application* (Levenshtein/whitespace-normalized matching), not skill retrieval. Zero transfer to the Retrieve lane. | Irrelevant |
| **Progressive disclosure** (rank on headers, load body after select) | registry.py:418-441, 554-630 | server.py `search_skills` returns {name,desc,score}; `get_skill` pulls full body :465-484 | **LOW** | **Already present** — results carry name+description+score; full SKILL.md is an explicit `get_skill` pull. | **Already present** |

## Bottom line

The single highest-leverage improvement is a **lexical (BM25) signal fused into the current dense MAX-pool ranker** — LLM-free, cheap at this corpus size, targeting exactly the weakness both codebases document about the mpnet embedder: dense cosine "measures topic, not intent" and under-scores exact tokens, rare API names, and acronyms that a keyword index nails. The critical adaptation is to **fuse** (RRF / max-normalized blend with the group score), not to copy OpenSpace's cascade, whose "cosine decides final order" step would throw the benefit away. Second, since skill-concierge uniquely owns a Ledger, a **telemetry-driven soft prior** that downweights offered-but-never-taken skills is a natural LLM-free win that feeds its one unproven metric — but only after a traffic window and with a sample-size floor. **Explicitly leave out** everything LLM-in-the-hot-path (plan-then-select, query expansion, server/utility filter) — it breaks the fast per-turn gate that is skill-concierge's whole design premise — and the fuzzy-match chain, which is edit-application, not retrieval.

## Concerns / unresolved

- The BM25 lift is reasoned from the documented mpnet ceiling, **not measured** on skill-concierge's own eval set — needs a shadow A/B (same harness as ADR-0012) to confirm magnitude before shipping default-on.
