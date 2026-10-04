# Iteration 2: Jev-union arms, strata, blocklist drop, decisions (build report)

Date: 2026-10-04. Owner of the edits: `scripts/sieve_recall.py`, `tests/test_sieve_recall.py` only. Backups: `~/_ARCHIVE/sieve-iter2-jev-261004/` (both files as they were, plus the iteration-2 cases and manifest from before the rebuild, dir 0700).

No arm was run on the iteration-2 cases and no recall figure on them was looked at. The only iteration-2 facts below are case-attribute counts.

## What was built

- Arms (all in `ARM2`): `A0@20`, `A0@40` (flags off), `SR40` (slots + RRF, top_n 40), `J20`, `J40`. A Jev arm is Jev's top 10, then the flags-off top_n 40 sieve rows in sieve order, deduplicated by full skill key, cut to 20 or 40 (`union_rows`). Jev's order is round-robin across catalogue chunks (`jev_round_robin`), ported from the diagnosis scratch code.
- Jev call (`jev_top`, `jev_setup`): through `scripts/jev_client.ask`, ts tier only, `retries=0`, timeout 3.0 s, empty `recent_context`, request = the case's `gen_text[:4000]`. Catalogue = the enforcer's `_jev_catalog()` (installed only). Any exception gives no Jev rows and the exception class name; the case still runs on sieve rows. Per case the result row records `jev_ms`, `jev_failed`, `jev_err`, `jev_names`. No ts tier, no key, or an empty catalogue aborts the run (a config error, not a per-case failure).
- One Jev call per case, shared by J20 and J40. A Jev arm's latency is max(sieve call at top_n 40, Jev call): the design under test runs them in parallel. A failed or timed-out Jev call counts its elapsed time.
- Stratum `offer_source` (`offer_source()`): `jev` only when the case's group is `offered` and the ledger row's `jev` field exists without `err`; everything else `embed_or_none`. Stamped on each case at build time.
- Blocklist drop (`drop_blocklisted`): at build time, after the per-label cap, using the enforcer's own `_blocked` (bare entry blocks every qualified twin). Iteration 1's `build_cases` call is unchanged (`blocked=None` adds nothing).
- Decisions (`DECISION2`, Holm m = 3): `D_J20` = J20 vs A0@20 on `embed_or_none`; `D_SR40` = SR40 vs A0@40 on all cases; `D_J40` = J40 vs A0@40 on `embed_or_none`. G1 to G5 as iteration 1 through the same `gate_rules`; G6 for the Jev arms is an absolute p90 <= 1500 ms (`g6_abs`), for SR40 baseline + 100 ms. I added no non-inferiority guard (the order lists G1 to G6 only).
- Fingerprint: `rules_sha256()` adds an `ITER2` block (decisions, arm table, Jev constants, G6 bound, strata, Holm m) only when `ITER >= 2`; the freeze records it, `check_freeze` compares it. Iteration 1 is still `97051cc4df983b33af26c3bdf30e4e7a29b2c7d0b0b32284c1754b38539cc251` (asserted by a test).
- CLI: `--iter 2 gate` dispatches to the new path after the existing freeze checks (so it cannot run before the freeze), and refuses `--arms/--combine/--composites`. New `replay-arms` runs the five arms on the spent set, refused for any iteration but 1.

## Tests

`python3 -m pytest tests/test_sieve_recall.py -q` -> `58 passed in 0.77s` (was 42). `python3 -m pytest tests/ -q` -> `919 passed in 123.49s (0:02:03)`.

New tests cover: round-robin order and numeric chunk sort; union order, dedupe by key, truncation, external flags; one attempt, ts tier, 3 s, empty context; Jev failure gives no rows and the case still scores on sieve rows; arm call flags and Jev latency as the slower call; stratum classification from fake ledger rows (ok, err, none, not offered, unknown); build stamps strata and drops blocked labels while the iteration-1 build adds nothing; the blocklist helper's bare/qualified rule; `cmd_build --iter 2` records counts, keeps `generation`, drops stale keys; iteration-1 hash unchanged and each iteration-2 constant moves the iteration-2 hash; `check_freeze` refuses a changed iteration-2 rule; decisions' primary sets and Holm m = 3 (six session gains: p 0.0156, adjusted 0.0469, which m = 5 would fail); absolute p90 for Jev arms and relative for SR40; primary stratum under 30 is INSUFFICIENT; gate dispatch and refusals.

Mutation check (`_RESEARCH_ARTIFACTS/iter2-jev-arm/mutate.py`, 23 single-line mutations, file restored byte-identical afterwards): 23 killed. One survived on the first pass (gate never dispatched to the iteration-2 path); I added `test_gate_dispatches_to_the_iteration_two_arms_only_after_the_freeze_checks` and it and the "freeze check removed" mutation are now killed.

## Plumbing check on the spent set (iteration 1, 83 cases, read-only)

Run: `~/.claude/skill-concierge/venv/bin/python3 scripts/sieve_recall.py --iter 1 replay-arms` (`_RESEARCH_ARTIFACTS/iter2-jev-arm/replay-iter1.out`), plus two more live repeats (`replay_dump.out`).

| Arm | Diagnosis | Live run 1 (CLI) | Live run 2 | Live run 3 |
|---|---|---|---|---|
| A0@20 / A0@40 | 33.7 / 36.1 | 33.7 / 36.1 | 33.7 / 36.1 | 33.7 / 36.1 |
| SR40 (@40) | 47.0 | 47.0 | 47.0 | 47.0 |
| J20 (@20) | 59.0 (run 2: 60.2) | 56.6 | 57.8 | 55.4 |
| J40 (@40) | 62.7 (run 2: 63.9) | 60.2 | 61.4 | 59.0 |

Jev calls: 83 per run, 0 failed; p50 831 / 862 / 839 ms, p90 969 / 1128 / 1011 ms.

- A0 and SR40 reproduce exactly. The union logic reproduces exactly: fed the diagnosis's saved Jev answers and engine rows it gives 59.0 / 62.7 (run 1) and 60.2 / 63.9 (run 2) (`offline_union_check.py`).
- The live J20 and J40 figures sit 2 to 3.6 points below the diagnosis, not on it. Cause: Jev is not deterministic. Top-10 overlap is 87.5% to 88.8% for every pair of runs, the diagnosis's own pair (88.6%) included, so my runs are no less similar to the diagnosis than the diagnosis is to itself. Jev top-10 label hits out of 83: diagnosis 46 and 47; my live runs 2 and 3 (the two with a per-case dump) 45 and 43. Same model id (`jev-1.13.0`), same catalogue size (604), one request per case. I cannot rule out a small drift in Jev itself; four to five samples do not separate it from noise. Expect the fresh-set gain from the Jev arms to carry about +/-3 points of Jev run noise, on top of the shrinkage from using unspent data.

## Iteration-2 counts (rebuilt: `build --iter 2`)

Rebuilt because the build had to change. Same 79 cases (ids identical; only the new `offer_source` field differs; pairs unchanged), `frozen: false`, queries file untouched, the three `generation` records carried over, `cases_sha256` changed (now `5c47324d49b27d4752c0331c97de63ad72a690e05da84b5d580c90d5f824c3af`).

- Cases after the blocklist drop: 79. Blocklist drops: 0 (the blocklist has 43 entries, `whereami` is on it, no iteration-2 label is blocked).
- `offer_source`: `jev` 56, `embed_or_none` 23 (primary stratum for D_J20 and D_J40). By group: offered/jev 56, not_offered/embed_or_none 19, offered/embed_or_none 4. Sessions in the primary stratum: 10 (of 18).
- Leak check: not computed.

## Concerns for the orchestrator

1. The primary stratum has 23 cases, under the G1 floor of 30. As built, D_J20 and D_J40 print INSUFFICIENT whatever Jev does, and only D_SR40 (all 79) can pass. 56 of 79 labels were in an offer the live Jev router made (circularity), which is why the stratum is small; the leak check can only remove more. Options (a decision for Thinh, I changed nothing): accept D_SR40 as the only decidable one, wait for more traffic, or relax the floor before the freeze.
2. G1 for D_SR40 is n >= 30 over all cases after the leak check, which was already the risk noted in the build report.
3. No non-inferiority guard exists in iteration 2, because the order did not list one.
4. `gate` under iteration 2 and the `evaluate2` path were exercised with fakes only; the real `gate` cannot run until the freeze.
5. I ran `git status --short` once, a read-only slip against the no-git rule. Nothing was staged or changed.

Scratch files (skill names, ids and numbers only): `_RESEARCH_ARTIFACTS/iter2-jev-arm/` (`mutate.py`, `offline_union_check.py`, `cmp.py`, `replay_dump.py`, `model_probe.py`, outputs).

Status: DONE_WITH_CONCERNS
Summary: Jev-union arms, strata, blocklist drop and the iteration-2 decisions are built and tested (58 tests here, 919 in the suite), with iteration 1's hash unchanged. The iteration-2 primary stratum is 23 cases (56 jev, 23 embed_or_none, 0 blocklist drops, 79 total), below the 30-case floor.

## Pool extension

Orchestrator decision: add unseen, non-circular iteration-1 corpus rows to iteration 2. Still no arm run and no recall figure on iteration-2 data; counts only. Backups before the change: `~/_ARCHIVE/sieve-iter2-jev-261004/pre-pool-extension/`.

### What changed
- `build_cases` takes `exclude_ids` and `pre_router`. `build --iter 2` runs it a second time over `real-turn-labels.jsonl` (iteration 1, read-only) with the 168 iteration-1 case ids excluded, MAX_PER_LABEL applied among the remaining rows only, blocklisted labels dropped, and every case stamped `source = pre_router_unseen`, `offer_source = pre_router`. Fresh cases carry `source = fresh`.
- Primary set for D_J20 and D_J40 is now every case that is not `jev` (`embed_or_none` plus `pre_router`; stratum name `not_jev`). D_SR40 is still all cases. The iteration-2 rules fingerprint moved with it (iteration 1 is still `97051cc4…`).
- `check_fresh` applies the session, time and cutoff checks to `fresh` cases only (the unseen rows are iteration-1 rows by design) and counts every case, unseen ones included, for the 30-case leak-check floor.
- Manifest (unfrozen) records `counts.source`, `counts.primary_cases`, `counts.primary_sessions` and `counts.pool_extension`. The three earlier `generation` records are kept.

### Build counts (104 cases; `cases_sha256` f836ee47…)
- Source: fresh 79, pre_router_unseen 25. `offer_source`: jev 56, embed_or_none 23, pre_router 25.
- Primary set before the leak check: 48 cases, 34 sessions.
- Pool: 310 eligible iteration-1 turns, 38 candidates after excluding the 168 cases, 25 cases after the per-label cap, across 9 labels and 24 sessions. 11 of those sessions (12 cases) are shared with spent iteration-1 case sessions. 0 blocklisted drops. 0 of the 25 rows carry a ledger `jev` field.

### Queries
`queries --iter 2 --workers 4`: 75 calls planned beyond the 249 keys already recorded, 75 made, 1 failed (`JSONDecodeError`, a `how` reply); `--retry-failed` made 1 call, 0 failed. 324 keys recorded, 0 failed or empty. Run output: `_RESEARCH_ARTIFACTS/iter2-jev-arm/queries-pool.out`. Not frozen.

### Leak check on the whole set (counts only)
47 of 104 cases are leak-dropped (fresh 33, pre_router_unseen 14); 0 labels no longer indexed; 0 cases lack d0 queries.

| Set | Cases after leak check | Sessions |
|---|---|---|
| D_J20 / D_J40 primary (not jev) | 29 | 17 |
| of which embed_or_none | 18 | 7 |
| of which pre_router | 11 | 10 |
| D_SR40 (all) | 57 | 26 |
| fresh source | 46 | 16 |
| pre_router_unseen source | 11 | 10 |
| jev stratum | 28 | 14 |

The Jev primary set is 29, one short of the G1 floor of 30 (n >= 30), so D_J20 and D_J40 would still print INSUFFICIENT as the set stands. D_SR40 has 57 and clears it. `check-fresh` was not run (it needs the freeze).

### Tests
`tests/test_sieve_recall.py`: 61 passed. `tests/`: 922 passed. Eleven new mutations (`mutate2.py`: no exclude, pre_router not stamped, source not stamped, primary excludes pre_router, pool not added, pool not blocked, shared sessions not counted, check_fresh session test keeps unseen, check_fresh floor drops unseen, primary_cases ignores pool, hash ignores sources) were all killed; the file was restored byte-identical.

Unresolved: how to reach 30 in the Jev primary set (one more case, more traffic, or a changed floor) is the orchestrator's call; I changed nothing.

Status: DONE_WITH_CONCERNS
Summary: The pool extension is built, queries are generated, and nothing is frozen; the Jev primary set after the leak check is 29 cases (17 sessions), one under the floor, and D_SR40 has 57.
