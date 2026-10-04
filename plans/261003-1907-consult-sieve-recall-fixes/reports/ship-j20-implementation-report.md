# Ship J20: `consult_fit.py widen` implementation report

Status: DONE_WITH_CONCERNS. Backups: ~/_ARCHIVE/consult-widen-261004/ (originals of consult_fit.py, SKILL.md, test_consult_fit.py; smoke input/output beside them).

## Files changed
- scripts/consult_fit.py: `widen` subcommand (`widen_clean`, `jev_round_robin`, `jev_top`, `widen_rows`, `widen`, `widen_selftest`, `widen_main`); `main` dispatches on a first argument of `widen`. Nothing else in the file changed.
- skills/consult/SKILL.md: step 2 calls `consult_candidates` with top_n 40, then pipes the verbatim request plus the response into `widen`; fallback stated (non-zero exit or `jev.failed` -> first 20 sieve rows, card says `sieve: not widened`); `--top N` row notes it applies only when widen is off or fails.
- tests/test_consult_widen.py (new, 15 tests). test_consult_fit.py untouched.

## Port notes
- Same call shape as the gate: ts tier only, one attempt (`retries=0`), 3.0 s, state `{request, recent_context: "", skills_already_loaded_this_session: []}`, wide questions from the enforcer's `_jev_wide_questions(_jev_catalog())`, round-robin over chunks, top 10.
- Redaction matches `clean_prompt`/`gen_text`: system-reminder and injected-block strip, `_jev_redact`, whitespace collapse, 4000 chars. Half-token rule: a request over 4000 characters is cut and its last token dropped before redaction. The gate applied that rule from a corpus-truncated flag; a live request has no such flag, so over-the-cap is the equivalent trigger (my choice).
- Merge equals `sieve_recall.union_rows` on names and order (test compares against it). A Jev row that is also a sieve row keeps the sieve row's fields, `source: "both"`.
- Kill switch `SKILL_CONSULT_JEV_WIDEN=0` returns `rows[:20]` untouched (no `source` tag, no dedupe), `jev: {ms:0, failed:false, added:0, disabled:true}`. Jev failure (timeout, no key, empty catalogue, any exception) returns the merge with no Jev rows (so deduped and tagged `sieve`), `failed: true`, exit 0. Bad input (not JSON, empty task, rows without a name) exits 2 with a JSON error.

## Verification (tails)
- `python3 scripts/consult_fit.py widen --selftest` -> `WIDEN-SELFTEST-OK`
- `pytest tests/test_consult_fit.py tests/test_sieve_recall.py tests/test_consult_widen.py -q` -> `111 passed in 2.93s`
- `pytest tests/ -q` -> `938 passed in 115.08s`
- Mutation check (each removed in turn, test file run, then restored; file diffed identical to the good copy): half-token drop, secret redaction, reminder strip, kill switch, fallback catch, dedupe, cut, Jev-first order. Each made 1 to 5 tests fail.
- Live smoke (real `consult_candidates`, top_n 40, 3 queries, 39 rows; task "set up a pre-commit hook that runs the tests"; real TypeSafe call): exit 0, `jev: {'ms': 822, 'failed': False, 'added': 8}`.
  Rows: 1 jev mattpocock-skills:setup-pre-commit, 2 jev agent-skills:ci-cd-and-automation, 3 jev setup-pre-commit, 4 jev article-illustrations, 5 both agent-skills:git-workflow-and-versioning, 6 jev 9router-stt, 7 jev app-builder, 8 both ak-test, 9 jev ak-sowat, 10 jev vn-bctt-report, 11-20 sieve (antigravity:git-hooks-automation, superpowers-developing-for-claude-code:working-with-claude-code, antigravity:smart-git-automation, antigravity:unit-testing-test-generate, antigravity:push-skill-to-github, antigravity:create-branch, ak-web-testing, antigravity:gitlab-ci-patterns, antigravity:jest-skill, antigravity:odoo-automated-tests).

## Concerns
- Jev-only rows carry name and description only (the catalogue has no path), so the analyst cannot Read them by path; SKILL.md tells the agent to use `get_skill(name)`. The analyst template (agents/analyst.md) was not checked or edited.
- The round-robin puts rank 1 of every catalogue chunk first, so the smoke shows unrelated rows (article-illustrations, 9router-stt, vn-bctt-report) at ranks 4-10. That is the gated design, not a bug; only one smoke run, not a quality claim.
- The live smoke also shows `setup-pre-commit` and `mattpocock-skills:setup-pre-commit` as separate rows: they have different full skill keys, same as the gate.
- Not done by design: version bump, docs/ADR/CHANGELOG, server.py, enforcer.py, git, installers. `--top N` semantics are now documented as fallback-only; the orchestrator may want ADR/docs wording to match.
- Not checked: widen under a non-Claude harness, and the `--fast` path's 60-candidate cap with 20 rows (well under it).

Status: DONE_WITH_CONCERNS
Summary: `consult_fit.py widen` ships with kill switch, fallback, selftest and 15 mutation-checked tests; SKILL.md step 2 now uses top_n 40 and widen. Full suite 938 passed and the live smoke returned 8 Jev-added rows in 822 ms; Jev-only rows have no path (use get_skill).

## Review fixes
Backups: ~/_ARCHIVE/consult-widen-261004/review-fixes/. Files: scripts/consult_fit.py, scripts/consult_log.py, skills/consult/SKILL.md, skills/consult/agents/analyst.md, tests/test_consult_widen.py (now 34 tests; the log tests live there too).

1. **M1** `widen_clean` strips injected blocks and redacts over the whole text, then collapses, cuts to 4000 and drops the last token. Tests: a reminder straddling char 4000 never reaches fake Jev; a 6 KB leading block leaves the real request intact.
2. **M2** `widen` takes `{"task", "queries"}` and runs the sieve itself: `sieve_rows_from_engine` starts a child of `~/.claude/skill-concierge/venv/bin/python3` (override `SKILL_CONCIERGE_VENV_PYTHON`), cwd home, `.mcp.json` engine env, slots/RRF forced off, imports the installed `skill_search.server`, `consult_candidates(queries, 40)`. Jev runs in a thread while the engine runs. `candidates` is still accepted. Engine failure exits 4 with a JSON error. SKILL.md step 2 is one quoted-heredoc call; on non-zero exit the agent calls `consult_candidates(top_n 20)` and writes `sieve: not widened`.
3. **M3** Tests pin retries 0, timeout 3.0, ts tier only (bench `gw:g ts:first ts:second` gives exactly the first ts tier), empty `recent_context`, top 10, round-robin across three chunks (including chunk "10" ordering).
4. **Lows** Empty cleaned request skips Jev (`failed`). A Jev pick colliding with an external sieve row keeps the sieve fields minus `external`. Selftest restores all three env vars it sets. Docstring exit codes fixed and the `SKILL_CONSULT_JEV=0` note added (test: it does not stop widen). Every path tags rows with `source`; the kill switch returns `source: "sieve"`, `jev {ms 0, failed false, added 0, state "off"}`.
5. **SKILL.md / analyst.md** `--top N` removed (flag row and argument-hint); step 4 says "candidate rows"; card wording `sieve: not widened` / `sieve: widening off`; analyst.md says Jev-added rows are always installed skills.
6. **Logging** `consult_log.py --sieve widened|not-widened|off` and `--jev-added N` (invalid values are dropped, never an error); the SKILL.md logging step passes them from `jev.state` / `jev.added`. `widen`'s `jev` block gained `state`.

Mutation check (each applied alone, test file run, file restored and diffed identical): cut-before-strip, retries 1, timeout 30, all tiers, non-empty context, top 12, no round-robin, no empty-request skip, external kept, flags on, top_n 20, exit code, log fields dropped, env not restored. Each failed 1 to 9 tests.

Verification: `widen --selftest` -> `WIDEN-SELFTEST-OK`; widen+fit+sieve tests `130 passed`; `consult_log.py --selftest` OK.
Full suite: `937 passed, 20 failed`. All 20 failures are tests/test_codex_installer.py (19) and tests/test_installer_staging_cleanup.py (1). Cause read from the output: the installer refuses because the working tree's SSOT version is v0.58.0 while HEAD carries v0.57.1 (the release agent's uncommitted bump). They passed (938/938) before that bump; they will go green once the version change is committed. Not caused by this work, not re-run after a commit (no git).
Live end-to-end (new stdin shape, task "I'm adding a nightly backup job for my postgres database, it's urgent", 3 queries, installed engine, real Jev): exit 0, 0.86 s wall, `jev {ms 675, failed false, added 9, state widened}`; ranks 1-10 jev/both (ak-databases, cron-best-practices [both], ak-docs-seeker, skill-concierge:skill-search, ak-ask, mattpocock-skills:ask-matt, mattpocock-skills:wizard, ak-devops, agent-skills:incremental-implementation, ak-research), 11-20 sieve (antigravity:database-admin, vercel:cron-jobs, ...).

Not checked: a blind agent running SKILL.md step 2 end to end (the review recommended one); the `--fast` fit call's own inline-JSON pattern (predates this work, unchanged).

Status: DONE_WITH_CONCERNS
Summary: All six review items are fixed, each with a test that fails without it. The new stdin shape ran live end to end; the full suite shows 20 installer failures that come from the uncommitted v0.58.0 version bump, not from these files.

## Re-review fixes
Backups: ~/_ARCHIVE/consult-widen-261004/rereview/. Tests are in tests/test_consult_widen.py (now 42).

1. **HIGH (cwd)** `sieve_rows_from_engine` now runs the engine child in the caller's working directory (`cwd=os.getcwd()`, the child no longer `chdir`s home). Tests: the child reports the caller's cwd; a stand-in engine that lists `<cwd>/.claude/skills` returns a project-only skill through `widen(queries=...)`.
2. **MEDIUM (log CLI)** `--sieve` and `--jev-added` are plain strings at the CLI; a non-integer `--jev-added` becomes None and `append_verdict` drops any bad value, so the row is always written. CLI tests: `--sieve bogus`, `--jev-added abc`, both bad.
3. **Lows** Heredoc delimiter is `CONSULT_WIDEN_INPUT` in SKILL.md (test checks it and that no bare `EOF` line remains). `widen_clean` docstring corrected (the gate can differ for any request over 4000 characters). The engine child gets an allow-listed environment only (PATH, HOME, USER, LANG, TMPDIR, PYTHONPATH, VIRTUAL_ENV, harness identity vars, `ENGINE_ENV_KEYS`, and `SKILL_`/`QDRANT`/`EMBED_`/`DSH_`/`LC_`/`XDG_`/`HF_`/`TRANSFORMERS_`/`CLAUDE_` prefixes); test sets OPENAI/ANTHROPIC/TYPESAFE keys and shows none reach the child while `SKILL_COLLECTION`, PATH and HOME do. Engine timeout 90 s (test: under 120).

Mutation check (each alone, restored and diffed identical): cwd = home, full environment, 120 s timeout, `choices=` back on `--sieve`, `type=int` back on `--jev-added`, `EOF` delimiter. Each failed 1 to 3 tests.

Verification: `widen --selftest` -> `WIDEN-SELFTEST-OK`; widen+fit+sieve tests `138 passed`; `consult_log.py --selftest` OK. Full suite `945 passed, 20 failed`: the same 20 installer tests as before (19 in test_codex_installer.py, 1 in test_installer_staging_cleanup.py), caused by the uncommitted v0.58.0 version bump against HEAD v0.57.1; not touched by this work.

Live end-to-end, same stdin and same queries ("file list cleanup", "deduplicate rows in a csv file inventory", "tidy exported file listing"; task "clean up a messy file list csv"), run from a project folder with its own `.claude/skills` and from home (outputs: live-project.txt, live-home.txt):
- From `~/in-PROD/MY-WORKBENCH/VGP/csv` (project skill `filelist-cleanup`): `jev {ms 687, failed false, added 8, state widened}`; rank 1 is `both filelist-cleanup`, so the project skill is in the sieve rows; rank 9 is also `both firecrawl-parse`.
- From home: `jev {ms 740, added 8}`; `filelist-cleanup` appears at rank 2 only as a `jev` row (Jev found it, the sieve rows did not contain it), and the sieve block differs.
That is the cwd effect on the sieve rows, observed. Two earlier tries with queries that did not target a project skill (bocbang_v2, PROD-vien-go) showed no project skill in either run: those projects' skills match global same-named copies, so they proved nothing and are not counted.

Not checked: the full set of project-scope rows (the index holds 54 `project:` points across 3 project dirs; only VGP/csv was exercised live).

Status: DONE_WITH_CONCERNS
Summary: The engine child now runs in the caller's cwd, the log CLI always writes the row, and the lows are fixed, each with a test that fails without it. A live run from VGP/csv ranked the project skill `filelist-cleanup` first as a sieve+Jev row, while from home the sieve rows lacked it; the 20 installer failures remain from the uncommitted version bump.
