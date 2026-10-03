# Code review: consult sieve recall fixes (uncommitted, since HEAD b4e6c3f)

Reviewer: code-reviewer subagent, read-only, 2026-10-04 (Asia/Saigon). No repo edits, no git writes, no network, Jev or gateway calls. The only files I wrote are this report and the probe scratch in `reports/_RESEARCH_ARTIFACTS/code-review/` (`equiv_probe.py`, `equiv_probe_control.py`, `server_head.py` = `git show HEAD:vendor/skill-search/skill_search/server.py`).

## Scope
- `scripts/sieve_recall.py` (new, 1181 lines, untracked, sha256 `bd539776c54ad054bf8a571e440a3f2a296a2962a4bb3ab9321882d7beecd649`)
- `tests/test_sieve_recall.py` (new, 400 lines)
- `vendor/skill-search/skill_search/server.py` (+89/-7; sha256 `a858ad8d…2921`, the same as `phase-03-gate-meta.txt` records)
- `vendor/skill-search/tests/test_consult_slots.py`, `test_consult_rrf.py` (new), `vendor/skill-search/VENDORED.md` (+16)
- Not reviewed: `AGENTS.md`, `CLAUDE.md`, `README.md` and `CHANGELOG.md` became modified while I worked (another agent's lane, outside my brief).

## Verdict
No Critical or High findings. Both flags off: the server behaves exactly as at HEAD (proved below). Privacy holds on the data actually frozen. The defects are in the gate instrument's fidelity to its own pre-registration and in how auditable it is. None changes this run's outcome, because no decision passed.

## Proven (reproduced)

**P1. Flags off, behavior is identical to HEAD.** `equiv_probe.py` loads HEAD `server.py` and the working tree side by side with identical fakes (embedder, `_qdrant.query_groups`/`retrieve`, capsules, staleness, blocklist, disabled plugins). It runs 400 random scenarios × `SKILL_ROW_ORIGIN` 0/1. Each scenario has 1-6 queries including empty ones, 0-45 groups with duplicate names, five scope kinds including `catalog:` and `claude-synced`, missing paths, and `top_n` set to None/0/1/5/20/40/99/"7". Each scenario compares the `consult_candidates` output, the `search_skills` output, `_fuse_ranked` (with and without paths) and the exact sequence of qdrant call arguments. Result: `trials 800 mismatches 0`. Positive control (working tree with `SKILL_CONSULT_SLOTS=1`): `trials 800 mismatches 650`, so the probe can detect a difference. By code reading too, the off path differs from HEAD only by `_consult_tier_rows(group_lists, top_n, False)`, which returns `_fuse_ranked(group_lists, top_n, with_paths=True)` (server.py:1266-1270). `blocks` is added only when the slots flag is on (server.py:1413).

**P2. The flag readers are read per call and are kept out of `ENGINE_ENV_KEYS`.** `_consult_slots_on`/`_consult_rrf_on` (server.py:122-127) read `os.environ` on every call. `grep CONSULT scripts/engine_env.py` finds nothing. Neither flag appears in any `.mcp.json`, adapter, hook or setup file.

**P3. Private files and keys.** `jev-calibration/` is `drwx------`. The four sieve files (`sieve-eval-cases.jsonl`, `-queries.jsonl`, `-manifest.json`, plus the inputs) are `-rw-------`. `write_private` creates files with 0600 through a tmp file and `os.replace`, and `_append` does the same. `_ensure_dir` applies 0700. The key appears only in the `Authorization` header inside `flywheel_llm.chat` (flywheel_llm.py:162-163). sieve_recall never reads or prints it. A scan of all 518 query records found 0 strings shaped like `Bearer …` or `sk-…`.

**P4. Privacy of the frozen data.** All 168 cases' `gen_text` equals `gen_text(labels.prompt)` recomputed. None contains `<system-reminder`. Running `_jev_redact` a second time changes none of them. None starts with a prefix that `_jev_typed_user_text` rejects (`_JEV_NOT_TYPED`, `_HARNESS_MSG_RE`). For the 12 fidelity `task` texts: 0 change on redaction and 0 reminder tags.

**P5. Tests.** `tests/test_sieve_recall.py` 25 passed. Vendored `test_consult_slots.py` + `test_consult_rrf.py` 14 passed. Full vendored suite 302 passed. Full repo `tests/` 886 passed (engine venv, Python 3.12).

**P6. The gate statistics are correct where checked.** Holm step-down (sieve_recall.py:311-321) stops at the first failure, with m fixed at 5. `INSUFFICIENT`/not-run decisions enter as p = 1.0 (:1079). The session sign test (:298-308) nets gains and losses per session and returns p = 1.0 when no session is discordant. This deliberately overrides `PE.sign_test_p`, which returns 0.0 for n = 0 (precision_eval.py:250-251). The override is correct and tested (test :219-220). The bootstrap is seeded and paired, and its units are sessions or pairs (:324-350). G1-G6 thresholds match phase-01 R5. The leak check matches the pre-registered wording ("dropped from every arm when any generated query contains…").

## Findings

### Medium

**M1. `ship_choice` ranks on raw p. Pre-registration says Holm-adjusted p, with a tie going to the larger gain.** Confirmed.
- Where: `scripts/sieve_recall.py:395-399` and `:1103` (`passed[d] = {"p": r["p"], …}`, raw p). Phase-01 R5: "only the single passing decision with the smallest Holm-adjusted p ships; a tie goes to the larger gain."
- Failure scenario: slots p = 0.010 (gain 5), rrf p = 0.012 (gain 9), the other three p = 1. Both pass Holm (0.010 ≤ 0.01, 0.012 ≤ 0.0125). Their adjusted p are 0.05 and max(0.05, 0.048) = 0.05, a tie, so the pre-registered rule ships **rrf**. The code ships **slots**. Reproduced: `ship_choice raw: slots  pre-registered (adjusted p, tie->gain): rrf`.
- Impact: none on this run (0 PASS). It is a latent pre-registration breach in the shipping decision.
- Fix: compute Holm-adjusted p (cumulative max of `(m - rank) * p` in sorted order, capped at 1) inside `evaluate` and pass it to `ship_choice`.

**M2. Nothing pins the gate instrument to the evidence.** Confirmed.
- Where: `phase-03-gate-meta.txt` records HEAD, the diff stat and the server.py sha256. It does not record `sieve_recall.py`, which is untracked in git. The manifest (`_freeze`, :760-783) hashes the inputs, cases, queries and system texts, but not the gate constants (`MIN_N`, `G2_GAIN_PTS`, … :54-63) or the script.
- Failure scenario: the plan says "changing a rule after the freeze voids the gate" (module docstring :13-14), but the code cannot detect such a change. A later edit to a constant or to `evaluate` leaves `check_freeze` (:927-935) green, and the published verdict cannot be tied to the code that produced it. The script's mtime (05:05:33) is after the first freeze (22:04:53Z = 05:04:53 local). That edit was the disclosed parser fix (phase-01 implementation report, item 2), so this time it is accounted for, but only by prose.
- Fix: write `sha256(sieve_recall.py)` and a dict of the gate constants into the manifest at freeze time. Have `check_freeze` compare both, and print the script sha in the gate output. Commit the script with the verdict.

### Low

**L1. The default-OFF flags turn ON for any value except the exact string `"0"`.** Confirmed: `''`, `'false'`, `'off'`, `'no'` and `' 0'` all make `_consult_slots_on()`/`_consult_rrf_on()` return True (server.py:122-127). An `.mcp.json` env entry such as `"SKILL_CONSULT_SLOTS": ""` or `"false"` would enable a flag that failed its gate. This matches the sibling convention (`_search_complement_on`, server.py:106-107), so changing only these two would make them inconsistent with it. A fail-safe reader for default-OFF flags would be `os.environ.get(k, "0").strip().lower() in ("1", "true", "on", "yes")`; apply it to the class (all default-OFF readers) or leave it.

**L2. The prompt is truncated before it is redacted.** Plausible, not realized in the frozen set. `extract_turn_labels.py:418` stores `prompt = txt[:4000]` raw, and only afterwards does `clean_prompt` (sieve_recall.py:141-147) strip reminders and redact. Two things can then slip through. A `<system-reminder>` block cut by the 4000-char limit loses its closing tag, so `_JEV_REMINDER_RE` (enforcer.py:1576, which has no `\Z` alternative) leaves it in. A token like `sk-…` cut below its 16-char minimum is not redacted. Only 1 of 168 cases was truncated (4205 chars). Its tail holds no secret-prefix shape and its reminder tags are balanced. Fix: redact the full text upstream, or give the reminder regex a `|\Z` alternative as the private-key regex already has.

**L3. The 12 fidelity task texts skip sieve_recall's own cleaning.** `jobs_for` (:658-659) sends `_collapse(r["task"])[:4000]` directly. It relies on `consult_fit.extract_runs` having applied `_jev_typed_user_text` (consult_fit.py:226, present in b847af9). The probe confirms all 12 are clean. Defense in depth: run `gen_text()` on them too.

**L4. A test writes to the real private directory.** Confirmed. `test_generation_appends_resumes_locks_and_freezes` calls `S.acquire_lock(lock)` at tests/test_sieve_recall.py:145, before `CAL_DIR` is monkeypatched at :157. `acquire_lock` calls `_ensure_dir()` (:600), which runs mkdir and chmod on the real `~/.claude/skill-concierge/jev-calibration`. Reproduced: with `SKILL_CONCIERGE_HOME` set to a scratch dir, the test created `<scratch>/jev-calibration` with mode `drwx------`. It is harmless on this machine (the dir exists and is already 0700), but it is a side effect from a unit test. Fix: monkeypatch `CAL_DIR` at the top of the test.

**L5. Stale-lock takeover can race (TOCTOU).** Plausible, not reproduced. `acquire_lock` (:598-624) reads the pid, judges it dead, then `unlink`s. Two runners that both read the same dead pid can interleave: A unlinks and creates its lock, then B unlinks A's fresh lock and creates its own. Both then append to the queries file. The impact is small: `latest_records` keeps the newest record per key, so the cost is duplicate gateway calls. Fix: take an `fcntl.flock` on the lock file instead of unlinking it.

**L6. Slots path: blocked rows use up slots (flag ON only).** server.py:1376-1379 cuts to `n_inst`/`n_ext` first and applies `_blocked` after. A blocked installed skill therefore shrinks the installed block without a refill, and `blocks` counts the rows left after filtering. HEAD's off path filters after `top_n` in the same way, so this is consistent and not a regression. Note it if the flag is ever reconsidered.

**L7. Deviations from the plan's letter.** G3's lost-case list is re-implemented inline (:380) instead of using `PE.lost_gained_cases`, which phase-01 R5 names; this is a parallel re-implementation. The phase-01 risk table promises leak-drop "Counts printed per label", but the gate prints only the total (:983). The 51% drop and its label skew are disclosed in the phase-01 implementation report but are not visible in the gate output.

**L8. No test pins the privacy transform.** The only privacy test (`test_generator_never_receives_labels`) checks that labels are absent. Nothing checks that `clean_prompt`/`gen_text`/`task_sentence` strip `<system-reminder>`, `[Assistant Rules]` and injected skill lists, or that they redact a planted `sk-…`. If `_jev_redact` or the regexes stop matching, the generator would send unredacted text and the suite would stay green. P4 shows the current data is clean. Add one test with a fake enforcer, or with the real one through `_cal().load_enforcer()`.

### Informational
- The leak check drops 85 of 168 cases (51%). This is pre-registered and disclosed. The surviving set leans toward distinctive label names and holds 4 process-skill cases, and the composite guard rests on 24 pairs. The verdicts are valid for that set only (Inference).
- `CONSULT_INSTALLED_SHARE * top_n` uses Python's banker's rounding: `top_n` = 5 gives 4 installed slots (3.5 rounds to 4), and 15 gives 10 (float 10.4999…). This matches the "about 70%" in VENDORED.md. It is a constant, not tuned.
- `cmd_build` scrolls the base points twice (:539 `scroll_base_points`, then `index_state` :540). An index change between the two scrolls would make the manifest's index hash disagree with the points used for resolution. The window is narrow.
- Hooks, the MCP server and other harnesses: server.py changes add only module-level functions and constants, with no import-time I/O. The `consult_candidates` signature is unchanged. Neither the enforcer nor any adapter reads these flags. The vendored suite passes. I found no path that could break a hook or another harness while the flags are unset.

## Plan follow-ups (report only; I have not edited the plan)
- Phases 1-3: the instrument exists, the queries are frozen (sha matches the manifest; labels, cases and consult-eval shas match), the gate ran with an identical index lock, and all 5 decisions FAILED, so the flags stay OFF. This is consistent with `phase-03-gate-verdict.md` and the raw output.
- Before any re-run (for example the recall@40 question raised in the verdict): fix M1 and M2 and pre-register again.

## Unresolved questions
- Was `consult-eval.jsonl` (mtime 04 Oct 00:59) written by the `_jev_typed_user_text` version of `consult_fit.py` (committed 01:15 +0700)? The content probe is clean either way. I did not verify provenance.
- Should default-OFF flag readers move to a strict truthy parse across the class (L1)? That is Thinh's call, because it changes an established convention.

Status: DONE_WITH_CONCERNS
Severity count: Critical 0, High 0, Medium 2 (M1, M2), Low 8 (L1-L8), Informational 4.
