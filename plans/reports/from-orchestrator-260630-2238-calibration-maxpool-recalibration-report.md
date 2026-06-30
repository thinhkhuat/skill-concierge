# Calibration → MAX-pool recalibration (post-v0.10.1)

**Date:** 2026-06-30 · **Orchestrator:** calib-orchestrator · **Branch:** main (no git ops performed)
**Status:** DONE_WITH_CONCERNS — core ask shipped + gated green; a pre-existing engine naming bug limits live corpus coverage (decision flagged for controller).

Mirrors the offline calibrator to live MAX-pool retrieval, restores the doctor gate, recalibrates, reports the would-arm picture. Nothing armed; no live-routing change.

---

## Step 0 — reindex, gate restored

`doctor.py` BEFORE → `status: FAIL` (Retrieval health: 2 skills on disk unindexed + disk changed since last index).
Reindexed via the project-native guarded path `doctor.py --fix` → `fix_reindex` (skips legacy MEAN reapply because `SKILL_MULTIVECTOR` on — base vectors safe).

AFTER → `status: OK`:
```
[✓] Retrieval health    502 skills indexed; embedder + qdrant reachable (indexed 0m ago)
[✓] Multi-vector layer  1821 trigger points (+ base) of 2323 total — MAX-pooled retrieval
[✓] Corpus health       (updated after Step 2 — see below)
status: OK
```
Reindex delta: `indexed 500→502, points 2312→2323, embedded 12, deleted 0`.

**Note (benign):** doctor briefly flipped to WARN "index stale (indexed Nm ago)" between reindex and the gates. Cause = disk-signature mtime drift in the active workbench (a skill file's mtime ticked, no content change). Re-reindex was `embedded 0, deleted 0` (nothing actually changed) and the recalibration output was **byte-identical** across it (diff empty). Not a real index change. Final state OK.

---

## Step 1 — calibrator + corpus-health → live MAX-pool

**File changed (only one code file): `scripts/calibrate_thresholds.py`.**

The live enforcer (`enforcer.py` `_retrieve`) and server (`server.py` `search_skills`) score each skill by its single BEST point — Qdrant `group_by name, group_size=1` (MAX-pool over base + every trigger point). The old calibrator scored each prompt against ONE `base` vector only → no longer mirrored live retrieval (handoff Gotcha #5).

Function diff summary:
- `skill_vector(name)` (returned the lone `kind=base` vector, single `limit:50` scroll) → **`skill_vectors(name)`**: paginated scroll (Qdrant `next_page_offset`, `limit:256/page`) returning **ALL** of a skill's point vectors (base + triggers); cannot truncate.
- new **`max_cosine(qvec, vecs)`** = `max(cosine(qvec, v) for v in vecs)` — the per-skill MAX-pool equivalent of `group_size=1`.
- `run()`: per prompt `pos/neg = [max_cosine(embed(p), vecs) ...]` (replaces `cosine(embed(p), v_base)`). `embed(p)` still computed once per prompt.
- Module + function docstrings updated: state "calibration == live retrieval, reproduces the live MAX-pool score" — dropped the old "approximation" caveat (now accurate).
- `--selftest` extended with two `max_cosine` assertions (best-point pick; empty→0.0). `calibrate()`/`metrics_at()` math unchanged.

**`doctor.py check_corpus_health`: NO change needed.** It only READS `eval/thresholds.json` and tallies `status` counts (lines 384-403) — it does not compute separation itself. Regenerating the JSON suffices; verified by reading the function.

Acceptance: `--selftest` green; code maxes over base+trigger points; sanity run shows MAX-pool `pos_mean` ≥ old base-only on every resolvable skill (below).

---

## Step 2 — recalibration + would-arm picture

### CONCERN — engine double-prefix bug limits live coverage (pre-existing, NOT caused by this work)

The live index names 81 ClaudeKit skills with a **double prefix**: `ck:ck:ai-artist`, `ck:ck:plan`, … (canonical user-facing name is single-prefix `ck:ai-artist`). Root cause: `vendor/skill-search/skill_search/skills_discovery.py` `_namespaced_name()` (~line 51) prepends the plugin id `ck:` to skills whose frontmatter `name:` already self-prefixes with `ck:`. **In `vendor/` → out of my edit scope; needs a `setup.sh` venv rebuild to take effect.**

Proof it predates this task (did not arise from the Step-0 reindex): the reindex was `embedded 12, deleted 0`. Point-ids derive from names, so a `ck:`→`ck:ck:` flip would have deleted hundreds and re-embedded hundreds — it deleted 0. The names were already `ck:ck:` in the live index before I touched anything.

Consequence: 10 of the 14 `eval/scenarios` corpus skills key on single-prefix `ck:X`, which no longer resolves → the calibrator correctly WARN-skips them. The committed `eval/thresholds.json` therefore covers only the 4 non-`ck:` corpus skills. This is the truthful current state; I did NOT silently rewrite the corpus to the buggy `ck:ck:` name nor add a name-fallback that would key τ to a name live retrieval can't match.

### Committed `eval/thresholds.json` (truthful, as-is naming) — 4 resolvable skills

| skill | pos_mean | neg_mean | sep | τ | F1 | status |
|---|---|---|---|---|---|---|
| vn-author | 0.616 | 0.415 | 0.202 | 0.457 | 0.96 | ok |
| supabase | 0.515 | 0.355 | 0.160 | 0.316 | 0.92 | ok |
| tdd | 0.501 | 0.422 | 0.079 | 0.382 | 0.92 | ok |
| deep-research | 0.354 | 0.323 | 0.031 | 0.190 | 0.83 | weak |

Counts: **3 ok · 1 weak · 0 no-signal** (of 4). doctor Corpus-health line now reads `3/4 ok · 1 weak · 0 no-signal`.
(`eval/thresholds.json` is gitignored — regenerable artifact, not a tracked change.)

### MAX-pool ≥ base-only (the change works) — every resolvable skill lifted

| skill | base-only pos | MAX-pool pos | base status → MAX status |
|---|---|---|---|
| vn-author | 0.528 | 0.616 | ok → ok |
| supabase | 0.336 | 0.515 | ok → ok |
| tdd | 0.341 | 0.501 | ok → ok |
| deep-research | 0.138 | 0.354 | no-signal → **weak** (separation flipped positive) |

### Diagnostic — full 14-skill MAX-pool picture (name-mapped `ck:X`→`ck:ck:X`, throwaway probe, wrote nothing)

To give a complete before→after on all 14 corpus skills despite the naming bug, a labeled diagnostic mapped each corpus key to its live double-prefixed name and scored under the patched MAX-pool functions:

| status | base-only (14) | MAX-pool (14, name-mapped) |
|---|---|---|
| ok | 5 | **12** |
| weak | 5 | 1 |
| no-signal | 4 | 1 |

MAX-pool more than doubled the trustworthy-τ count (5→12 ok). Only `deep-research` (weak) and `ck:databases` (no-signal, neg slightly leads) fail to separate.

### Would-arm picture — REPORT ONLY, recommend DO NOT arm

Live floor: `GETAWAY_FLOOR=0.45` (operator-set, ADR-0009). Arming `ENFORCER_PER_SKILL_TAU` replaces the global 0.45 with each skill's τ (`_PER_SKILL_TAU.get(name, GETAWAY_FLOOR)`); a τ **below** 0.45 LOWERS that skill's bar → more offers.

Of the 12 ok skills (full diagnostic): **1** has τ ≥ 0.45 (vn-author, 0.457 — barely; near-neutral); **11** have τ < 0.45 → arming would lower their bar and add offers. (Committed-4 subset: same shape — only vn-author ≥ 0.45; supabase 0.316 and tdd 0.382 below.)

**Recommendation to controller: keep `ENFORCER_PER_SKILL_TAU` OFF.** MAX-pool lifted separation status (5→12 ok), but per-skill τ still sits below the live floor for 11/12 ok skills, so arming today broadly increases offer volume — the exact false-offer risk the owner deferred until post-deployment adoption data exists (handoff Open-Q #2). The picture marginally improved (1 ok-τ now clears 0.45 vs 0 before), not enough to flip the call. Additionally, with the `ck:ck:` bug live, τ keyed on the corpus name would never apply to the 81 mis-named skills anyway.

---

## Step 3 — mandatory gates (plan P3)

**Code reviewer (`ck:code-reviewer`) — PASS / Status: DONE.** All 5 acceptance points PASS: correctness (max_cosine = group_size=1 MAX-pool; pagination terminates + collects all points; embed once per prompt), no regression (calibrate/metrics byte-unchanged), contract (no external caller of renamed `skill_vector`), hard constraints (nothing armed; only `scripts/calibrate_thresholds.py` modified; no vendor/live-routing edits), lint/style (pure stdlib, docstrings accurate). Notes the new paginated fetch is strictly more correct than the old `limit:50` (could truncate >50-point skills). Two non-blocking informational notes, both pre-existing / not introduced here:
1. `cosine()` normalizes in Python vs Qdrant's stored-vector cosine — identical to old code, marginal-only if indexed vectors aren't unit-normalized.
2. `offset:null` on first scroll page not network-exercised by the no-network selftest (canonical Qdrant pattern; fine).

**Tester (`ck:tester`) — PASS / Status: DONE. 8/8 selftests green** (found 4 beyond the required 4):
`calibrate_thresholds`, `enforcer`, `multivector_experiment`, `doctor`, plus `build_triggers`, `enrich_index`, `build_prompt_intent`, `precision_eval` — all exit 0. No pytest/`tests/`/Makefile suite exists.

---

## Deliverable state

- Tracked worktree change (for controller review): **`scripts/calibrate_thresholds.py`** only.
- Regenerated artifact (gitignored): `eval/thresholds.json` (now 4 skills, MAX-pool).
- No git ops, no arming, no live-routing change, no vendor/ edits. Index multi-vector ON, base vectors intact.
- Final `doctor.py` → `status: OK`.

## Open questions / decisions for the controller

1. **`ck:ck:` double-prefix engine bug (81 skills).** The proper fix is in `vendor/skill-search/skill_search/skills_discovery.py` `_namespaced_name()` (don't prepend plugin id when base_name already starts with it) — but that is engine code, needs a `setup.sh` rebuild, and re-names ~81 live skills (affects search_skills/enforcer display + any future τ key). DECISION NEEDED: fix at the engine (correct, surfaces clean `ck:X` names live) vs. realign the corpus to `ck:ck:X` (bakes in the bug). I recommend the engine fix; until then calibration corpus coverage stays at 4/14 for real. Did NOT act on this — out of stated edit scope + a live-facing naming change is the owner's call.
2. **Per-skill τ arming** — recommend remain OFF (above). Re-evaluate after (a) the `ck:ck:` fix restores full corpus coverage and (b) a post-deployment adoption window exists.
3. **Recurring "stale" mtime drift** — the workbench environment intermittently ticks skill-file mtimes, flipping doctor to WARN(stale) without content change. Cosmetic; a reindex clears it. Worth knowing so it isn't mistaken for index corruption.

---
Status: DONE_WITH_CONCERNS
Summary: Calibrator now MAX-pools over base+trigger points (mirrors live `group_size=1`); doctor restored to OK; recalibrated; code-review + 8/8 tester gates green. Recommend keep τ OFF.
Concerns: Pre-existing `ck:ck:` engine double-prefix (81 skills, vendor/, out of scope) caps live corpus coverage at 4/14 — flagged for controller decision; nothing armed, no live path changed.
