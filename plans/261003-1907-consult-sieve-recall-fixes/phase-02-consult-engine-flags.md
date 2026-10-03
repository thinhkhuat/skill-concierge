---
title: "Phase 2: Consult engine flags: installed slots and rank fusion"
status: todo
---

# Phase 2: Consult engine flags: installed slots and rank fusion

<!-- Updated: Red Team + Validation Session 1 - old phases 2 and 3 merged; no tuning (F2); _fuse_ranked untouched, RRF in _rrf_order (F11); deployment truth (F4) -->

## Goal

This phase adds two query-time flags to `consult_candidates`, both default OFF and read on every call:

- **`SKILL_CONSULT_SLOTS`.** Installed skills get reserved slots, and externals come back in their own block after them. The 1,994 external base points can then no longer push installed skills out of the sieve.
- **`SKILL_CONSULT_RRF`.** The sieve is ordered by reciprocal-rank fusion (RRF) across sub-goal queries instead of each skill's best raw score. One generic query can then no longer take most of the slots.

`search_skills`, `_fuse_ranked` and the router stay byte-for-byte as they are.

## Context (re-checked 2026-10-04)

**`consult_candidates` today** (`vendor/skill-search/skill_search/server.py:1276-1338`):
- It trims queries to 5 (`:1297`) and clamps `top_n` to 40 (`:1301`).
- It runs one mixed-tier `query_groups` call per query with `_scope_filter()` (`:1302-1306`).
- It fuses with `_fuse_ranked(group_lists, top_n, with_paths=True)` and filters the blocklist after the cut (`:1307-1308`).
- It back-fills missing paths (`:1312-1323`), attaches capsules (`:1324-1330`) and builds `out` (`:1331-1332`).

**`_fuse_ranked`** (`:1171-1218`) keeps each skill's best raw score (`:1185-1195`) and sorts by it (`:1196`). It builds rows with provenance and paths. There are exactly four calls: `:1252` and `:1253` (`search_skills`, complement path), `:1261` (`search_skills`), `:1307` (`consult_candidates`).

**The complement split this phase reuses.** `search_skills` behind `_search_complement_on()` (`:1241-1254`) runs one `_installed_only_filter()` query (`:932-941`) and one `_external_only_filter()` query (`:944-950`) per vector, and fuses each tier separately. Its `_arrange_tiers` (`:953-975`) merges the tiers by a 0.08 margin. That merge is not reused here, because Thinh asked for reserved slots with externals in a separate block (see plan.md, consistency sweep).

**Query embedding.** `embed_queries` (`:630-641`) may route to the index owner, so tests fake `embed_queries`, not `embed_batch`.

**Constants precedent.** `EXTERNAL_MARGIN` (`:99-103`) is a plain constant, fixed before the evidence runs so it cannot be swept afterwards.

**What this phase changes.** `ENGINE_ENV_KEYS` (`scripts/engine_env.py:19-34`) holds only index-shaping keys, and neither new flag enters it. No vendored test covers `consult_candidates` today.

## Files to Create / Modify

| File | Action | Owner |
|---|---|---|
| `vendor/skill-search/skill_search/server.py` | Add `_consult_slots_on()`, `_consult_rrf_on()`, `CONSULT_INSTALLED_SHARE = 0.7`, `CONSULT_RRF_K = 60`, `_rrf_order()`, and the branches inside `consult_candidates`; update its docstring | Phase 2 |
| `vendor/skill-search/tests/test_consult_slots.py` | Create | Phase 2 |
| `vendor/skill-search/tests/test_consult_rrf.py` | Create | Phase 2 |
| `vendor/skill-search/VENDORED.md` | Add one entry | Phase 2 |

This phase runs in parallel with phase 1, and finishes before phase 3.

## Requirements

1. **Flag readers.** `_consult_slots_on()` and `_consult_rrf_on()` return `os.environ.get(NAME, "0") != "0"`. They are read on every call.
2. **Fixed parameters (F2).** `CONSULT_INSTALLED_SHARE = 0.7` and `CONSULT_RRF_K = 60` are plain constants, pre-registered and never tuned. Each carries a comment naming this plan.
3. **`_rrf_order(group_lists, k)`** returns skill names in RRF order:
   - a skill's rank in a list is its 1-based position among the groups that carry hits;
   - its fused value is the sum of `1 / (k + rank)` over the lists where it appears;
   - ties break on the best raw score, then the name.

   `_fuse_ranked` is not edited. With RRF on, the consult path does three things in order:
   - calls `_fuse_ranked(lists, n_all, with_paths=True)`, where `n_all` is the number of distinct names across the lists, so every row is built once;
   - reorders those rows by `_rrf_order`;
   - cuts them to the tier's slot count.

   Each row's `score` stays its best raw score.
4. **Slots on:**
   - The query vectors are computed once.
   - For each vector, two calls run, each with `limit=top_n`: one `_installed_only_filter()` query and one `_external_only_filter()` query.
   - Each tier is ordered on its own, by MAX or by RRF according to the other flag.
   - `S = max(1, round(CONSULT_INSTALLED_SHARE × top_n))` installed slots, and `top_n − S` external slots. A tier with fewer rows than its slots lends the unused slots to the other tier.
   - `results` is the installed block, then the external block, with the row shape unchanged.
   - The response gains `"blocks": {"installed": i, "external": e}`, counted after the blocklist filter.
5. **Slots off, RRF on:** one mixed list per query, as today, ordered by RRF.
6. **Both flags off:** today's code path runs, line for line.
7. **Shared post-processing.** On every path, the blocklist filter, path back-fill, capsules, `capsule_coverage`, `note` and `warning` behave as today.
8. **Docstring.** The docstring of `consult_candidates` says the order is "best raw score by default, reciprocal rank when SKILL_CONSULT_RRF=1; `score` is always the best raw score". When slots are on, it says "installed rows first, then externals, counted in `blocks`".

## Implementation Steps

1. Add the two flag readers, the two constants and `_rrf_order`.
   Check: `grep -n 'SKILL_CONSULT_SLOTS\|SKILL_CONSULT_RRF' vendor/skill-search/skill_search/server.py` shows reads only inside the two reader functions. `git diff` shows no change between `def _fuse_ranked` and its `return out`.
2. Add the slot and RRF branches to `consult_candidates`, and update the docstring.
   Check: the tests below pass.
3. Write the `VENDORED.md` entry. It states:
   - both flags, read per call, and that they are not in `ENGINE_ENV_KEYS`;
   - the two fixed constants;
   - that `_fuse_ranked` is unchanged;
   - that deployment needs the shared-venv resync (automatic on a version bump, `bin/skill-search-mcp:55-116`, or `pip install --force-reinstall --no-deps vendor/skill-search`) plus an MCP restart, with no reindex;
   - "Not upstream: re-apply on re-vendor".

   Check: `grep -n "SKILL_CONSULT_RRF" vendor/skill-search/VENDORED.md` finds the entry.
4. Do not run `doctor --fix` or `./setup.sh` in this phase. Doctor's "Engine freshness" WARN is expected until release (plan.md, Rollback and deployment).

## Tests

The tests fake `embed_queries`, `_staleness_warning`, `_capsules`, `_qdrant.retrieve` and `query_groups` (by filter), in the style of `vendor/skill-search/tests/test_search_complement.py:22-38`. Each one checks behaviour and fails without the change.

`test_consult_slots.py`:
- `test_installed_rows_keep_their_slots_against_stronger_externals` — 30 externals at 0.90 and 10 installed at 0.50, with `top_n=20`: the result is 14 installed rows, then 6 external.
- `test_slot_path_queries_each_tier_with_its_filter` — each query issues one installed-only call (`must_not tier=external`) and one external-only call (`must tier=external`).
- `test_a_short_tier_lends_its_unused_slots` — 3 installed rows give 3 installed + 17 external. 2 external rows give 18 installed + 2 external.
- `test_blocks_count_rows_after_the_blocklist` — one blocked installed row lowers `blocks.installed` by one.
- `test_vectors_are_embedded_once_on_the_slot_path` — the `embed_queries` fake is called once for 3 queries.
- `test_slots_flag_is_read_per_call` — the flag set and then unset in one process changes the output.

`test_consult_rrf.py`:
- `test_rrf_lets_a_niche_first_place_beat_a_flooding_query` — query A returns 6 generic skills at 0.80 to 0.75; query B returns a niche skill first at 0.55. With `top_n=5`, MAX order drops the niche skill and RRF order keeps it.
- `test_rrf_rows_keep_the_best_raw_score` — `score` is the best cosine, not the fused value.
- `test_rrf_ties_break_by_best_score_then_name`.
- `test_rrf_orders_each_tier_when_slots_are_on` — with both flags on, both blocks are in RRF order.
- `test_rrf_flag_is_read_per_call`.

## Verification

```bash
cd /Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/vendor/skill-search
~/.claude/skill-concierge/venv/bin/python3 -m pytest tests/test_consult_slots.py tests/test_consult_rrf.py tests/test_fusion.py tests/test_search_complement.py -q
cd ../..
git diff --stat vendor/skill-search/skill_search/server.py
```

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Fewer externals reach the analyst under slots | Medium | Medium | Gate rule G5 (median >= 4 external rows) |
| RRF over both tiers lets the 70% external catalogue take more slots; the debugger's RRF evidence was installed-only | Medium | Medium | G5 caps the external share; the composite non-inferiority guard |
| Building all rows before reordering costs time | Low | Low | At most 5 × 40 groups; G6 bounds p90 |
| A live server keeps the old engine | High | Low | Expected until the release resync and a restart (plan.md) |

## Rollback

On a live machine, set each flag to `0` in each harness's MCP env and restart that server. The environment is fixed when the server is spawned (plan.md, Rollback and deployment). In code, revert the readers, the constants, `_rrf_order`, the branches, the docstring lines and the `VENDORED.md` entry, and delete the two test files. `_fuse_ranked` and `search_skills` need nothing.
