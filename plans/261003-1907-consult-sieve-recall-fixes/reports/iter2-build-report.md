# Iteration 2 build report (fresh held-out set)

Written 2026-10-04 ~09:32 (Asia/Saigon). Nothing frozen, no gate run, no git.

## Counts (read from the real runs)

- Iteration-1 corpus: untouched. sha256 still `ea585e0cd0d2d57a7e01ea7db1ff0ca4e2d7d255bcf6747c23c34ef5ed0c28e6` (matches the iteration-1 manifest). Newest ts_utc in it (the cutoff): `2026-09-26T09:05:44.285Z`.
- Extractor re-run with OUT at `real-turn-labels-iter2.jsonl`: 3592 rows. Not strictly after the cutoff: 3036 (the whole old corpus). In an excluded iteration-1 session: 0. Excluded uuid: 0. **Kept (fresh rows): 556.** Filtered file sha256 `0fbefcf637ef180ab0f302ec9e8243ca2e0cd91e44aaf054a7ec61a02e9ed05e`.
- Excluded iteration-1 sessions: 172 (iteration-1 case sessions plus every session of an iteration-1 corpus turn that is positive with >= 8 words, a superset of the sessions that fed cases). Zero fresh rows fell in them, so the exclusion is satisfied by time alone; it is still enforced at `labels`, `build` and `check-fresh`.
- Build (same rules as iteration 1, index points=44761 base=2914): eligible turns 85, before cap 80, **79 cases, 39 labels, 18 sessions**. Label resolution exact 86, key 0, short 0; not indexed 4; named in prompt 5; meta 1.
- **Cases per group: not_offered 19, offered 60, unknown 0** (not_offered sessions 8). English 73, process-group 16, composite pairs 39. cases sha256 `51afdc116e7c9d43766298f897a54ed9aaf480af522664e12b8547cdb52bb94d`.
- Dry leak check: not computable yet (queries still generating). It dropped 85 of 168 in iteration 1, so expect roughly half of 79, i.e. below the 30-case floor of `check-fresh`. See concern 1.

## Generation job

- Probe (per Thinh's 09:25 order): 12 jobs, `--workers 4`: 0 errors, no HTTP 429 (a 429 would be recorded as an `HTTPError` err; none), 12 of 12 replies present, 9.1 calls/min over 79 s. Probe output: `reports/_RESEARCH_ARTIFACTS/iter2-probe.txt`.
- Full run at **workers=4** (no fallback needed): PID **63776**, started 09:27, command `~/.claude/skill-concierge/venv/bin/python3 scripts/sieve_recall.py --iter 2 queries --workers 4`. 249 calls planned (79 x 3 plus 12 fidelity), the 12 probe keys are resumed, not repeated.
- Measured so far: 45 calls in about 3 minutes, roughly 15 calls/min (the final calls/min line is printed at exit). Expected finish about 09:45.
- Log: `plans/261003-1907-consult-sieve-recall-fixes/reports/iter2-genlog.txt` (no prompt text). It is block-buffered (nohup, no flush), so it fills only at exit; watch progress with `wc -l ~/.claude/skill-concierge/jev-calibration/sieve-eval-queries-iter2.jsonl`.
- One failure so far: a `how` reply that `json.loads` rejected (`JSONDecodeError: Extra data`), a model-output problem, not a rate or worker problem. Rerun `queries --workers 4 --retry-failed` after the run to retry failed keys, then `queries --freeze` (needs `iter2-prereg.md`).
- At exit the run appends `{workers, calls, failed, seconds}` to the manifest under `generation`.

## What was added (scripts/sieve_recall.py)

- Global `--iter N` (default 1). `iter_path`/`set_iter`: N >= 2 inserts `-iterN` before the extension for labels, cases, queries, lock, manifest. `consult-eval.jsonl` is shared by every iteration on purpose (real consult runs, not iteration data). Dir 0700 / files 0600 via the existing `write_private`/`_append`/`_ensure_dir`.
- `labels` (iter >= 2 only): runs the extractor in-process with `OUT` set to the iteration's labels file, then rewrites it with only fresh rows. `extract_turn_labels.py` is unchanged.
- `build` under iter >= 2: refuses unless iteration 1 is frozen and its labels sha matches its manifest; excludes iteration-1 sessions/uuids and the cutoff; manifest records `iteration`, `fresh` {cutoff_ts, excluded_sessions, excluded_uuids, rows_in_labels_file, rows_dropped_at_build, iter1 labels/cases/manifest sha256}, the labels sha under `inputs`, and case counts per group under `counts.groups`.
- `check-fresh`, `check-prereg` (exit 1 naming the failed check; print `FRESH-HELDOUT-OK` / `PREREG-MATCHES-RUN` only on success).
- `queries --freeze` under iter >= 2 refuses without `plans/261003-1907-consult-sieve-recall-fixes/iter<N>-prereg.md` and records `prereg_sha256`; `check_freeze` (used by `gate`) also rejects a prereg changed after the freeze; `gate` provenance line ends with `prereg sha256 <hash>` under iter >= 2.
- `queries --workers N` (default 1, serial path untouched) and `--limit N` (probe). Parallel path: thread pool, one lock around the append, `chat`'s own post-call pause stays per worker, resume and `--retry-failed` work.
- `rules_sha256()` prints `97051cc4df983b33af26c3bdf30e4e7a29b2c7d0b0b32284c1754b38539cc251` (checked). System texts and gate constants untouched.

## Files changed

- `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/scripts/sieve_recall.py`
- `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/tests/test_sieve_recall.py` (fixture now also redirects `ITER` and `PLAN_DIR` to tmp; 16 new tests)
- Backups: `~/_ARCHIVE/sieve-iter2-261004/` (originals of the three owned files plus `sieve_recall.iter2-final.py`).
- Private files created (0600): `real-turn-labels-iter2.jsonl`, `sieve-eval-cases-iter2.jsonl`, `sieve-eval-manifest-iter2.json`, `sieve-eval-queries-iter2.jsonl`, plus the lock while running.
- Scratch: `reports/_RESEARCH_ARTIFACTS/iter2-labels-run.txt`, `iter2-probe.txt`.

## Tests

- `python3 -m pytest tests/test_sieve_recall.py -q` -> `42 passed in 0.68s`
- `python3 -m pytest tests/ -q` -> `903 passed in 115.67s (0:01:55)`
- Mutation spot checks (each made one test fail): cutoff `<=` to `<`, freeze guard removed, leak floor lowered, prereg hash check removed, session-overlap check removed. One mutation did NOT fail a test: removing the append lock in the parallel path. The test proves every key is written once with intact lines, but each record is one `O_APPEND` write, so the OS keeps lines whole even without the lock; the lock is defence in depth that no test can demonstrate here.

## Concerns / unresolved

1. Sample size: 79 cases from 18 sessions, 19 not_offered. The `task` decision's primary set is the not_offered group, so it will be INSUFFICIENT at n < 30 (G1), and `check-fresh` needs >= 30 cases surviving the leak check, which looks unlikely (about 40 expected). Only about 8 days of new transcripts exist after the cutoff. Options for the orchestrator: wait for more traffic, or relax nothing (the 30 floor is pre-registered).
2. "Corpus rows that fed them" is read as a superset (positive and >= 8 words), not only the rows that survived index resolution; documented in `iter1_exclusions`.
3. Not run, by order: freeze, gate, `check-fresh` on real data (cannot pass before the freeze), `check-prereg`. `iter2-prereg.md` does not exist yet.
4. The `labels` extractor run took 11 s and read the live transcripts and ledger read-only.

Status: DONE_WITH_CONCERNS
Summary: Iteration-2 plumbing, fresh labels (556 rows, 0 overlap), a 79-case build and a 4-worker generation (PID 63776, probe clean) are done, with 903 tests passing. The set is small (79 cases, 19 not_offered), so the 30-case leak-check floor and the task decision's n are at risk.
