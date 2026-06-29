# Multi-vector retrieval arc — compressed context (skill-concierge v0.10.x)

> One-file orientation for the next agent. Load THIS for the whole arc cheaply; drill into the
> source-map docs only when you need depth. Dense by design — every line is load-bearing.

## TL;DR
skill-concierge retrieval went from **one bare vector/skill** → **multi-vector MAX-pool** (each skill =
base point + 1 point per description-derived phrase; scored by its single best point via Qdrant
`group_by name`). Validated **2.2× rank-1 & separation, flat false-fire** (shadow A/B), shipped live
(v0.10.0), patched (v0.10.1), activated, verified de-duped. **Recall lever proven; adoption payoff NOT
proven** (needs a traffic window).

## State now (verified 2026-06-30, main @ clean/in-sync)
- Live version **0.10.1**. Index `claude_skills` = **2312 pts** (500 base + 1812 trigger). doctor `OK`.
- **Live in both paths**: enforcer (`_retrieve`, per-prompt subprocess) + MCP `search_skills` — both use
  Qdrant `/points/query/groups` (group_size=1 = MAX-pool). De-dup confirmed.
- `GETAWAY_FLOOR=0.45` unchanged (floor sweep: 0.20 "flood" was an artifact; 0.45 = crowd-median 11).
- **Default-INERT** (off): per-skill τ (`ENFORCER_PER_SKILL_TAU`), deterministic routes
  (`ENFORCER_DETERMINISTIC`), runner-up collapse (`DOMINANCE_RATIO`), keep-off (`keep_off:[]`).

## Mechanism (the one idea)
A single description vector sits in mpnet's compressed 0.18–0.40 cosine band → "measures topic, not
intent" (the documented ceiling). Indexing each *phrase* as its own point and taking the **MAX** spreads
a skill across phrasing-space, so a query matching ONE distinctive phrase scores high. The dormant
enrichment overlay did the OPPOSITE (MEAN centroid). `build_index` builds the trigger layer natively
(`_split_phrases` on the description), so `--reindex` maintains it; toggle `SKILL_MULTIVECTOR` (default on;
`=0`+reindex reverts to bare).

## Verify (cheap)
- `python3 scripts/doctor.py` → `status: OK`, Multi-vector layer ~1812 triggers, no stale.
- `search_skills("fix a failing supabase migration")` → `supabase-apply-migration` ONCE ~0.72, no dupes.
- `python3 hooks/scripts/enforcer.py --selftest` → OK (incl. inert-lever checks).

## Gotchas (deploy traps that bit us — don't re-learn)
1. **Stable venv = non-editable COPY** (`pip install vendor/skill-search`, ADR-0004). Repo edits aren't
   live in the MCP until **`setup.sh`** re-runs + MCP reloads. `/plugin update`+`/reload` do NOT refresh
   the venv. Verify the RUNNING artifact (de-dup search), not the repo.
2. **Legacy MEAN reapply corrupts a multi-vector index.** Guarded in BOTH `doctor.fix_reindex` AND
   `setup.sh` (behind `SKILL_MULTIVECTOR=0`). Any NEW reindex path must guard it too.
3. **Qdrant ~33MB request cap** → batch the upsert per chunk (build_index does).
4. **calibrate / corpus-health now approximate** — score a single base vector, not live MAX. τ ships inert.

## Open (next steps, ranked)
1. **Prove/disprove adoption**: offered-turn conversion on a traffic window via `analyze.py` (now
   `band=="offer"` denom) + the `skill-usage-audit` methodology. Its cosine↔adoption claims are
   single-vector-era — re-measure.
2. **Per-skill τ**: recalibrate vs multi-vector MAX scores, then maybe arm (today all 5 ok-τ < 0.45 floor
   → arming adds false offers).
3. Menu noise from trigger collisions (rank-1 ~25%, top-5 ~46%; agent picks via %-share note) — watch.
4. Corpus coverage: only 14 skills have hand-written scenarios; expand contrastive negatives for
   `weak`/`no-signal` (doctor Corpus-health) — the lever for those.
5. Deterministic tier shipped empty/inert — leave unless a concrete high-precision intent appears.

## Commits (origin/main)
`5d8c43b` multi-vector v0.10.0 · `18278b0` setup.sh fix v0.10.1 · `92378e5` gitignore · `7bc716c` docs.

## Source-map (drill here for depth)
- Decision/rationale → `docs/adr/0012-multi-vector-max-pool-retrieval.md`
- Full handoff (verbose) → `plans/reports/session-handoff-260630-0115-multivector-retrieval-arc-report.md`
- Narrative + scars → `docs/journals/journal-2026-06-30-multivector-retrieval-wired-live.md`
- Why this was the missed idea → `plans/reports/analysis-260629-2342-bm25-doc-missed-novelty-report.md`
- A/B numbers + floor sweep → `plans/reports/experiment-260630-multivector-max-pooling-vs-bare-ab-report.md`
- Denominator-fix decision → `docs/adr/0011-ledger-derived-offer-suppression.md` (Resolved section)
