# Phase 2 implementation report: consult engine flags

Status: DONE_WITH_CONCERNS (concerns are two plan-text deviations, below).

## Files
- `vendor/skill-search/skill_search/server.py`: `CONSULT_INSTALLED_SHARE = 0.7`, `CONSULT_RRF_K = 60`, `_consult_slots_on()`, `_consult_rrf_on()` (the only two reads of the env vars), `_rrf_order()`, `_consult_tier_rows()`, new branches and docstring lines in `consult_candidates`, `blocks` in the response when slots are on. The three `git diff` hunks sit outside `_fuse_ranked`; its body is unedited, and `search_skills` is unedited.
- `vendor/skill-search/tests/test_consult_slots.py` (new, 7 tests), `vendor/skill-search/tests/test_consult_rrf.py` (new, 6 tests).
- `vendor/skill-search/VENDORED.md`: one entry appended.
- Not touched: `scripts/engine_env.py`, `scripts/sieve_recall.py`, enforcer, findability. No git ops, no network, no Jev, no `doctor --fix`/`setup.sh`/venv reinstall.

## Proof the tests import the repo engine
`tests/conftest.py` already does `sys.path.insert(0, <vendor/skill-search>)` before importing `skill_search`. In addition `test_engine_under_test_is_the_repo_source` asserts `Path(server.__file__).resolve()` equals the repo's `vendor/skill-search/skill_search/server.py`; it passes. The revert-check below is the second proof: swapping the repo file changed the results.

## Test results
Vendored (engine venv, from `vendor/skill-search`), tests for this phase plus the plan's regression files:
`66 passed in 0.30s` (consult_slots, consult_rrf, curated_triggers, llm_trigger_cache_reset, fusion, search_complement).

Repo root `python3 -m pytest tests/ -q`: `861 passed in 114.94s (0:01:54)`.

## Revert-check (server.py restored to HEAD, tests run, then my version copied back; md5 3b2dd3c0... identical before and after)
Result with HEAD `server.py`: `11 failed, 3 passed`. The 11 failures are every slot test except the embed-once one, plus all RRF tests. The 3 that pass on HEAD, by design:
- `test_engine_under_test_is_the_repo_source` (path assertion).
- `test_vectors_are_embedded_once_on_the_slot_path`: today's code also embeds once, so it guards against regression; it cannot fail on HEAD. The plan's claim that each test fails without the change is not true for this one.
- `test_flags_off_reproduce_todays_output_exactly`: must pass on HEAD, that is its purpose. It compares `consult_candidates` output with flags unset against `_fuse_ranked(..., with_paths=True)` on the same fake data, checks the key set, and checks the calls are mixed-tier.
Backup of my version: `~/_ARCHIVE/sieve-p2-server-backup/server.py.new`.

## Deviations
1. Plan test 1 says "30 externals at 0.90 and 10 installed at 0.50, top_n=20: 14 installed then 6 external". Ten installed rows cannot fill 14 slots, and the lending rule (requirement 4) gives 10 + 10. I used 20 installed rows, which yields 14 + 6. The 10-installed case is covered by the lending test (3 installed gives 3 + 17).
2. Lending formula (not spelled out in the plan): `n_inst = min(len(inst), max(share, top_n - len(ext)))`, `n_ext = min(len(ext), top_n - n_inst)`. Both lending cases in the plan check out (3 gives 3 + 17; 2 external gives 18 + 2). Lending is decided before the blocklist filter; `blocks` counts after it, per the plan.

## Concerns / unverified
- Tests use faked `query_groups`, so real index behaviour (including real score distributions under RRF over both tiers) is unmeasured here; that is phase 3's gate.
- RRF on with slots off orders one mixed list; the plan's flagged risk (external share rising) is for the gate's G5.
- Doctor's "Engine freshness" WARN is expected; I did not run doctor.
