# Handoff — Multi-vector retrieval arc (skill-concierge v0.10.0 → v0.10.1)

**Date:** 2026-06-30 · **Branch:** main (clean, in sync) · **Live version:** 0.10.1
**Status:** ✅ SHIPPED + ACTIVATED + VERIFIED. No open work blocking; open *questions* listed at end.

---

## TL;DR for the next session
skill-concierge now does **multi-vector MAX-pool retrieval**: each skill is indexed as a base point
(name+desc+body) PLUS one point per intent phrase from its description, and scored by its single best
point (Qdrant `group_by name, group_size=1`). Validated **2.2× rank-1 / 2.2× separation, flat
false-fire** on a shadow A/B, then wired live (index 500→2312 points, ~2 ms query). It is fully live in
both retrieval paths and verified de-duplicated. Two follow-on bugs were found and fixed (33 MB upsert
overflow; setup.sh would corrupt the index). The one thing that is *proven* is the recall lever; the
thing that is *NOT* proven is whether it raises real skill adoption — that needs a traffic window.

---

## The arc, in order
1. **Studied** the BM25-routing doc vs skill-concierge → found the missed mechanism: the doc scores by
   MAX over per-phrase vectors; skill-concierge had shipped a dormant MEAN-centroid overlay (the
   opposite). Report: `plans/reports/analysis-260629-2342-bm25-doc-missed-novelty-report.md`.
2. **/ck:cook "all actionable mechanisms"** → P0 safe fixes, P1 multi-vector experiment, P2 inert levers.
3. **Experiment** (shadow A/B, held-out): multi-vector wins. Report:
   `plans/reports/experiment-260630-multivector-max-pooling-vs-bare-ab-report.md`. Harness:
   `scripts/multivector_experiment.py` (`--build`/`--eval`/`--sweep`/`--selftest`).
4. **Floor sweep** → keep `GETAWAY_FLOOR=0.45` (the 0.20 "flood" was a floor artifact).
5. **Wired live** + **v0.10.0** shipped (commit 5d8c43b). Hit + fixed a 33 MB single-upsert overflow.
6. **v0.10.1** (commit 18278b0): fixed setup.sh (would corrupt the index) + doc touch-ups, after a
   bundled-skill review.
7. **Activated**: re-ran setup.sh (refreshes the venv COPY) → reloaded MCP → de-dup verified.
8. **gitignore** hygiene (commit 92378e5): ignore the pip `build/` artifact.

Commits: `5d8c43b` (multi-vector v0.10.0) → `18278b0` (setup fix v0.10.1) → `92378e5` (gitignore).

## What changed (code)
- `vendor/skill-search/skill_search/server.py` — `search_skills` → groups API; `build_index` → base +
  trigger layer (reindex-safe, per-chunk upsert, keyword payload index on `name`); inline `_split_phrases`
  (mirrors `build_triggers.py`); `MULTIVECTOR` flag (default on).
- `hooks/scripts/enforcer.py` — `_retrieve` → `/points/query/groups` REST (MAX-pool); plus the
  DEFAULT-INERT per-skill-τ (`ENFORCER_PER_SKILL_TAU`) and deterministic-route (`ENFORCER_DETERMINISTIC`,
  `config/deterministic-routes.json`) levers + selftests.
- `scripts/analyze.py` + `scripts/build_keep_off.py` — offered-turn denominator unified to `band=="offer"`.
- `scripts/doctor.py` — `check_multivector` + `check_corpus_health`; `fix_reindex` skips legacy reapply
  when multi-vector on.
- `scripts/calibrate_thresholds.py` — `skill_vector` prefers the `kind=base` point.
- `setup.sh` — guard the legacy `enrich_index.py --reapply` behind `SKILL_MULTIVECTOR=0`.
- Docs: ADR-0012 (multi-vector), ADR-0011 (Open→Resolved), journal, two bundled SKILL.md touch-ups.

## Current live state (verified 2026-06-30)
- Index `claude_skills`: 2312 points (500 base + 1812 trigger). doctor `status: OK`.
- MCP `search_skills`: de-duplicated, MAX-pooled, top scores lifted (~0.72 on a strong match). No stale.
- Enforcer: groups/MAX-pool live per prompt; `GETAWAY_FLOOR=0.45` unchanged.
- Default-inert levers OFF: per-skill τ, deterministic routes, runner-up collapse (`DOMINANCE_RATIO`),
  keep-off (`keep_off: []`).

## Gotchas the next agent MUST know
1. **The stable venv (`~/.local/share/skill-concierge/venv`) is a non-editable COPY** of the engine
   (ADR-0004). Editing `vendor/skill-search/...` does NOT change the running MCP until **`setup.sh`**
   re-runs (`pip install vendor/skill-search`) AND the MCP reloads. `/plugin update` + `/reload` do NOT
   refresh the venv. Verify the RUNNING artifact (de-dup `search_skills`), not the repo.
2. **Legacy MEAN reapply must never run on a multi-vector index** — it corrupts base vectors. It is
   guarded in BOTH `doctor.fix_reindex` and `setup.sh` (behind `SKILL_MULTIVECTOR=0`). If you add another
   reindex path, guard it too.
3. **Qdrant request limit ~33 MB** — any index build that scales the point count must batch the upsert
   (build_index does, per-chunk).
4. **Revert path:** `SKILL_MULTIVECTOR=0` + reindex (drops all trigger points, restores one bare vector
   per skill), then reload the MCP.
5. **calibrate / corpus-health are now approximate** — they score against a single `base` vector, which
   no longer mirrors live MAX-pool. Per-skill τ ships inert; treat its status as advisory.

## Open QUESTIONS (not blockers) — the real next steps
1. **Does multi-vector raise adoption?** Recall lever is proven; the behavioral payoff is NOT. Measure
   offered-turn conversion on a post-deployment traffic window via `scripts/analyze.py` (now on the
   `band=="offer"` denominator). Use the `skill-usage-audit` skill's methodology (held-out, drop
   self/meta, gate on volume). Its cosine↔adoption findings are single-vector-era — re-measure.
2. **Per-skill τ** could become live-useful now that separation doubled — recalibrate
   (`scripts/calibrate_thresholds.py`) against multi-vector MAX scores, then consider arming
   `ENFORCER_PER_SKILL_TAU` (currently all 5 ok-τ < 0.45 → arming would add false offers).
3. **Menu noise** — trigger phrases can collide topically (e.g. "token format" → `design-system`).
   rank-1 ≈25%, top-5 ≈46%; the agent picks via the %-share note. Watch confusion in the ledger.
4. **Corpus coverage** — only 14 skills have hand-written `eval/scenarios`; trigger layer covers all 498
   from descriptions. Expanding contrastive negatives for `weak`/`no-signal` skills (doctor Corpus-health)
   is the lever for those.
5. **Deterministic route tier** is shipped empty/inert — leave it unless a concrete, high-precision,
   unambiguous intent the semantic layer misses appears (tension with "false offers dominate").

## How to re-verify quickly
- `python3 scripts/doctor.py` → expect `status: OK`, Multi-vector layer ~1812 triggers, no stale.
- `search_skills("fix a failing supabase migration")` → `supabase-apply-migration` ONCE at ~0.72, no dupes.
- `python3 hooks/scripts/enforcer.py --selftest` → OK (incl. inert-lever checks).
