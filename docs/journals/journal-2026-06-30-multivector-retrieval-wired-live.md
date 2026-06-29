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

---

## Update — v0.10.1: the setup.sh bug + the activation gotcha (2026-06-30)

A bundled-skill review (user asked "do the bundled skills need updating?") surfaced two things bigger
than any SKILL.md edit:

- **setup.sh would have corrupted the multi-vector index.** It ran `enrich_index.py --reapply`
  unconditionally — the legacy MEAN overlay, which mean-enriches the base vectors on top of the trigger
  layer. I'd guarded `doctor`'s `fix_reindex` for this but MISSED `setup.sh`. Now guarded behind
  `SKILL_MULTIVECTOR=0`. Shipped **v0.10.1** (commit 18278b0).
- **The stable venv is a non-editable COPY** (`pip install vendor/skill-search`, ADR-0004). So 0.10.0's
  new retrieval code was NOT live in the MCP after `/plugin marketplace update` + `/reload-plugins` —
  those refresh the plugin cache + reload MCP processes, but NOT the venv. Only `setup.sh` refreshes the
  venv copy. My earlier "just restart the MCP" advice was wrong; the real activation is
  **setup.sh → reload**.

Ran setup.sh: venv now carries the new code (`query_points_groups`/`MULTIVECTOR` present), and the index
stayed intact — base-vector parity `cos=1.00000` (bare, NOT mean-corrupted) proves the guard worked.
Post-reload `search_skills` returns DISTINCT skills (no dupes) at the lifted 0.717 top score, no stale
warning, doctor `status: OK`. Multi-vector is now fully live in BOTH the enforcer and the MCP.

### Bundled-skill verdicts
- skill-search SKILL.md — no drift (generic prose). · setup SKILL.md — prose fine; the SCRIPT was the bug.
- doctor SKILL.md — check-matrix table had drifted; added Enrichment/Multi-vector/Corpus-health rows.
- skill-usage-audit SKILL.md — added a caveat that its cosine↔adoption findings are single-vector-era.

### Scars
1. **Two layers ran the same legacy reapply** — `doctor.fix_reindex` AND `setup.sh`. Retiring a mechanism
   means grepping EVERY caller of its reapply, not just the one you remember.
2. **"The venv is a copy" silently defeats a code change.** Verify the RUNNING artifact (what the MCP
   process loaded), not just the repo. The de-dup `search_skills` test was the only honest proof of live.
3. The 33MB Qdrant upsert overflow (0.10.0) + this venv-copy gotcha are both "the obvious step had a
   non-obvious failure at scale/deploy" — incremental verification (count after migrate, parity after
   setup, de-dup after reload) caught each one immediately.
