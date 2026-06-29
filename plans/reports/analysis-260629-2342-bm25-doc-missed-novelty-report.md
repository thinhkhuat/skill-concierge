# BM25 Routing Doc — Missed Novelty for skill-concierge

**Date:** 2026-06-29 23:42 · **Scope:** Re-study the "Smart-Suggest Routing: Regex + BM25" design doc against the current skill-concierge codebase + the prior `from-xia-bm25` analysis, and surface only what is *genuinely not yet done*.

**Method:** 3 read-only evidence agents (engine internals, hook layer, prior-art) + direct source reads of `server.py` / `enrich_index.py` for the headline claim. Every load-bearing claim is cited `file:line`.

> **Correction (2026-06-30):** the original draft implied the MEAN-pooling enrichment overlay is *live*. It is **not** — `doctor` reports `Enrichment overlay: not enriched (no overlay in use)` (a reindex rewrote the vector-only overlay bare and `--reapply` never ran). So the live index is the **bare single description vector** per skill; the MEAN-pooling code is **dormant**. This *strengthens* the finding below: live retrieval has zero phrasing signal at all, and the MEAN overlay isn't even reindex-robust — whereas the doc's MAX over real per-phrasing **points** is. The MEAN-vs-MAX framing below is retained as the design contrast, now labelled "dormant MEAN" vs "live bare" vs "proposed MAX".

---

## Bottom line

You already mined this doc well — 7 mechanisms adopted, 5 correctly rejected, negation/staleness/confidence/β²=4 all shipped. **One thing slipped through, and it's the doc's single most important idea.**

| # | Missed / not-done | Why it matters | Cost |
|---|---|---|---|
| **1** | **MAX-pooling over per-phrasing vectors** (multi-vector index). Live is one bare vector/skill; the dormant enrichment does the *opposite* (MEAN). MAX over per-phrasing points is unimplemented in any form. Prior-art mislabeled "adopted." | Directly attacks your own stated ceiling ("substrate measures topic, not intent"; cosines stuck in a compressed 0.18–0.40 band). Reuses corpus you already have. | Low — shadow collection + existing eval already exist |
| 2 | **Per-skill calibrated τ wired LIVE** | You compute it (β²=4) and write `thresholds.json`, but the enforcer still uses one global floor (0.45). The doc's whole point is per-skill thresholds at runtime. | Known-deferred (Phase D), not missed — but #1 changes its calculus |
| 3 | **A deterministic enforcement engine** (the doc's *other* hook — not the BM25 ranker) | You retired lexical entirely. A tiny, near-zero-false-positive "this exact intent MUST route to skill X" layer is a different tool from BM25 ranking. | Low, but tradeoff vs your "false-offers dominate" finding |
| 4 | **Corpus-health operator report + scenario coverage** | Only ~15 of ~500 skills have scenarios; `no-signal`/`weak` statuses aren't surfaced as a fix-list. Enabler for #1 and #2. | Low |

---

## The headline: you implemented MEAN where the doc says MAX

This is subtle, which is why it was missed. The prior `from-xia-bm25` report logged *"Best-single-match per skill (max over positives, not sum): ADOPTED"*. What actually shipped is the inverse pooling.

**What the doc proposes** (verbatim): *"For each skill, the score is the **maximum** across that skill's positive scenarios rather than a sum. This is deliberate: the best single matching scenario is sufficient evidence for routing."* → each phrasing is its own representation; a query that matches **one** distinctive phrasing scores high even if it's far from the skill's average.

**What skill-concierge does:**
- **One vector per skill.** `desired[_point_id(s["name"])] = (s, text, _content_hash(text))` — keyed by skill name, single point (`vendor/skill-search/skill_search/server.py:305-308`). The embedded text is `name + description + body` (`server.py:237-239`).
- **Live = bare single vector (no overlay).** `doctor` confirms `Enrichment overlay: not enriched` — the live index is exactly the one description vector above, no phrasing signal at all.
- **The dormant enrichment, when run, MEAN-pools.** `enriched_vector = MEAN( [live S] + [embed(trigger) ...] )` (`scripts/enrich_index.py:6`, computed at `:151`), written back as a vector-only update to the **same point** (`:152-157`), each trigger weighted `1/(N+1)` (`enrich_index.py:7-8`). It is currently OFF and is not reindex-robust (a reindex rewrites it bare). Either way — bare or MEAN — it is the *opposite* of the doc's MAX over separate per-phrasing points.
- **Retrieval scores against that single centroid:** `qvec = embed(query); _qdrant.query_points(..., limit=TOP_K)` (`server.py:356-357`).

**Why MEAN is the wrong pooling for your specific problem:** mean-pooling pulls every phrasing toward the topical centroid — it *manufactures* the "average topic" vector. That is precisely the failure your own journals name: cosines compressed into 0.18–0.40 (`enforcer.py:258-265`), "substrate measures topic, not usefulness/intent," dodged-median cosine (0.445) *above* taken-median (0.408). Mean-pooling **dilutes** the one distinctive phrasing that would have discriminated intent. MAX-pooling keeps it.

Note the irony already in your code: `enrich_index.py:277` calls enrichment a *"separation lever"* and the selftest asserts *"enrichment moves S toward the trigger"* — but averaging toward a centroid is a *de-separation* operation once N triggers pile in; you're moving the vector toward the **mean** of all triggers, not preserving any one. The doc's MAX is the actual separation lever.

### How to integrate (and validate cheaply)
1. **Index each scenario/trigger as its own Qdrant point**, payload `{name, kind: "scenario"}`, instead of (or alongside) the centroid. You already generate the phrasings (`eval/triggers.json`, `eval/scenarios/*.json`).
2. **Retrieve skill score = MAX over its points** — Qdrant returns per-point hits; group by `name`, take the max. Drop-in over `search_skills` (`server.py:352-363`).
3. **A/B on the shadow collection you already have** (`claude_skills_shadow`, `enrich_index.py:47`) via `scripts/precision_eval.py` — measure recall/precision and, crucially, whether the **taken-vs-dodged cosine separation** widens (your real ceiling metric). No live risk.
4. Keep the centroid point too if you want a hybrid (max(centroid, best-scenario)); let the eval decide.

This is the highest-leverage item: it's the doc's defining mechanism, it targets the exact ceiling you've documented, and the corpus + shadow harness to test it already exist.

---

## Full doc-mechanism ledger (what happened to each)

| Doc mechanism | Status in skill-concierge | Evidence |
|---|---|---|
| BM25-plus lexical ranker (K1/B) | **Rejected — correct** (semantic beats it cross-lingual) | ADR-0002; prior-art table |
| Positive-only IDF / posting lists | N/A (no lexical) | — |
| **MAX over per-scenario scores** | **MISSED — shipped MEAN (centroid) instead** | `enrich_index.py:6,151`; `server.py:305-308` |
| Per-skill corpus `positive[]`+`negative[]` | Adopted | `eval/scenarios/*.json` |
| Min counts (≥8 pos/≥2 neg) → `excluded` | Variant: no hard min; uses take-rate `keep-off` instead | engine agent; ADR-0011 |
| LOO cross-scoring | Adopted (calibration) | calibrate_thresholds.py |
| Auto-calibration F-beta **β²=4** | Adopted exactly | `calibrate_thresholds.py` `BETA2=4` |
| `ok`/`excluded`/`conflict` (F1-gated) status | Variant: `no-signal`/`weak`/`ok` (separation + F1≥0.60) | calibrate_thresholds.py |
| **Per-skill τ live at runtime** | **Computed, NOT wired** — enforcer uses global `GETAWAY_FLOOR=0.45` | `eval/thresholds.json` unused; `enforcer.py:66` |
| SHA/manifest fingerprint + cache skip | Adopted (MD5 disk signature + manifest) | `server.py:103-129` |
| Detached background rebuild | Adopted but **debounced/doctor-driven** (rejected per-prompt detach as racey on Qdrant) | prior-art Phase B |
| Confidence = share of top-N + "pick intent" | Adopted verbatim | `enforcer.py:258-275` |
| Negation short-circuit | Adopted but **narrowed** (negation + invocation-meta verb, not broad veto) — an improvement | `enforcer.py:175-189` |
| Two-engine **additive** (regex ∥ ranker) | Collapsed to one (semantic) — see #3 below | ADR-0002 |
| Bilingual FR/EN corpus | Adopted + **exceeded** (multilingual mpnet + VN imperative gate) | ADR-0003; `enforcer.py:96-108` |
| Node/zero-dep, settings wiring, scale notes | N/A (impl details; you use Python/Qdrant) | — |

---

## Secondary not-done items

### #2 — Wire per-skill τ live (known-deferred, but #1 reopens it)
You have the machinery: `calibrate_thresholds.py` outputs per-skill `tau` with honest status. The enforcer ignores it and gates on one global `GETAWAY_FLOOR=0.45` (`enforcer.py:66`). Safe path: use per-skill τ **only where calibration shows strong separation (`ok`)**, fall back to the global floor elsewhere — so a thin/weak corpus can never set a bad threshold. **Caveat:** if you adopt #1 (max-pooling), recalibrate τ against the new multi-vector scores — the old single-centroid τ won't transfer.

### #3 — A deterministic enforcement tier (the doc's *other* engine)
You rejected the BM25 *ranker* (right call). But the doc runs **two** engines: BM25 for coverage **and** regex for *enforcement* — "intercept a specific intent reliably, such as 'create a PR without mentioning the changelog fragment.'" That's not ranking; it's a handful of exact-pattern → guaranteed-route rules. skill-concierge has imperative/refusal *gates* but no positive "pattern X MUST surface skill Y" map.
**Tradeoff (be honest):** your data says the dodge is dominated by **false offers**, not missed routes — so any new offers must be near-zero-false-positive. A deterministic exact-pattern layer *can* be (unlike semantic), but keep it tiny and audited, or it re-adds the noise you've been cutting. Worth it only for a few genuinely unambiguous, high-stakes intents.

### #4 — Corpus-health report + coverage expansion
The doc treats `excluded`/`conflict` as an operator maintenance signal ("check the output before committing"). You compute `no-signal`/`weak` but don't surface them as a **fix-list**. Add a one-line `doctor`/calibrate report: *"these N skills are weak/no-signal — add contrastive negatives."* And only ~15 skills have scenarios at all — #1 and #2 are only as good as corpus coverage, so expanding scenarios (even 5–10 high-traffic skills) is the cheap enabler.

---

## Already handled — no action (verified, so you can see nothing was skipped)
Negation guard (narrowed, shipped v0.7.0), staleness/manifest detection (shipped), confidence-as-share (shipped), β²=4 calibration (mirrored), bilingual→VN (exceeded), detached rebuild (debounced by design), `excluded`/`conflict` (replaced by separation taxonomy + take-rate keep-off), prompt-complexity classifier (empirically rejected), verification-gate / velocity-governor / learning-capture / injection-scanners (correctly rejected).

---

## Open questions
1. **#1 priority:** want me to prototype multi-vector max-pooling on `claude_skills_shadow` and run `precision_eval.py` to measure the separation delta? (Read-only to live; pure experiment.)
2. **#3 appetite:** is a deterministic enforcement tier in-charter, given your "false-offers are the real problem" finding — or is that a deliberate no?
3. The prior-art "max-over-scenarios: ADOPTED" label — confirm it was aspirational and never implemented, so this report's headline isn't double-counting something you already shelved.
