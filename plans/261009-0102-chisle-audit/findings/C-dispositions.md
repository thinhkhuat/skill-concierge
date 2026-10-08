# C — dispositions (scripts big six)

Worktree `/Users/thinhkhuat/.worktrees/skill-concierge/chisle-cuts`. One line per finding in `C-scripts-big.md`, in its order.

- scripts/doctor.py:2523 — SKIPPED: policy (`_selftest` move not approved; `--selftest` is cited by ADRs).
- scripts/doctor.py:425 — SKIPPED: policy (`_row()` rewrite not approved).
- scripts/precision_eval.py:101 — FIXED (approved part only): removed the LIVE-vs-SHADOW comparison branch, `_exists()`, the `SHADOW`/`SKILL_SHADOW_COLLECTION` constant and the now-unused `urllib.error` import. Kept the `--mode 495` LIVE-only report and its default. One visible change: the report header suffix `(no 'claude_skills_shadow' collection — LIVE only)` is now `(LIVE only)`. Removing the whole mode was not approved.
- scripts/precision_eval.py:627 — FIXED: deleted the inline `--selftest` block and its argparse flag. The only `precision_eval --selftest` citation outside the script is a historical plan (plans/260628-0215…/phase-01:202). To keep coverage, I added the checks pytest lacked to tests/test_precision_eval_sets.py: `rank_of` hit and miss, and `cd_bar([], [])`. Every other selftest assertion was already pinned there.
- scripts/doctor.py:1571 — FIXED: `check_omp` and `check_claude_code` now call `_registry_entry_state` once. The four wrappers were replaced by one shared `_record_state(state, head)`; their docstring facts moved into comments.
- scripts/sieve_recall.py:1006 — SKIPPED: medium confidence, and a serial→pool refactor is not an allowed medium category.
- scripts/doctor.py:1108 — SKIPPED: marked `(check)` and not approved (a dict would collapse same-name rows).
- scripts/sieve_recall.py:1580 — SKIPPED: low confidence; the prompt says `jev_round_robin` stays duplicated (test_consult_widen compares the copies on purpose).
- scripts/calibrate_jev_gate.py:619 — FIXED (partly): deleted sieve_recall.py's `pctl` copy. Its 6 call sites now use `_cal().pctl`, a lazy import edge that already existed, so no new dependency. The now-unused `import math` went with it. consult_fit.py's `_pctl` stays: importing it would make the shipped consult skill's script depend on the offline calibration CLI, a new (acyclic) coupling for a 4-line helper.
- scripts/doctor.py:1806 — FIXED (read-once part): `check_commandcode` parses settings.json once, and step 4 reuses the parsed value. The suggested `any()` rewrite of the hook-marker loop was NOT applied. A differential run showed it changes output: for a settings.json with the marker in one event and a malformed block in a later event, the original adds "unreadable settings.json" and `any()` does not. So the original loop is kept.
- scripts/doctor.py:1869 — FIXED: one `_zcode_record()` reads the registry once for `check_zcode`. `_zcode_installed_path()` stays as a one-liner for tests/test_owner_cutover_tooling.py:281,294.
- scripts/doctor.py:1672 — SKIPPED: medium confidence, and merging duplicated scans is not an allowed medium category.
- scripts/analyze.py:170 — FIXED: `_window()` factory, and one merged `auto`/`search` orphan branch.
- scripts/doctor.py:2125 — SKIPPED: medium confidence; it drops check steps, so it is not an allowed medium category.
- scripts/analyze.py:524 — FIXED (3 of 4): one `header()` closure replaces the 3 byte-identical header blocks (latency, chains, default report). The `--continuation` header is NOT identical (it prints raw `--since/--until` strings and no event count), so merging it would change output. Left as is.
- scripts/doctor.py:1151 — SKIPPED: medium confidence; memoising `claude mcp list` is not an allowed medium category.
- scripts/sieve_recall.py:126 — FIXED: deleted `PART_TASK` and `CAP_NOTE`. Re-verified: `rg -w` finds them only at their definitions plus plans/ text. They are not in `SYSTEM` or `rules_sha256()`, and plan 261003-1907 is `status: completed`.
- scripts/calibrate_jev_gate.py:71 — SKIPPED: low confidence.
- scripts/calibrate_jev_gate.py:83 — FIXED: deleted `relevant_text()` (re-verified: `rg -w relevant_text` finds only the definition).
- scripts/doctor.py:2476 — SKIPPED: medium confidence; deduplication is not an allowed medium category.
- scripts/doctor.py:446 — FIXED: `except OSError: continue`.
- scripts/doctor.py:1060 — SKIPPED: low confidence.
- scripts/calibrate_jev_gate.py:367 — SKIPPED: not behaviour-preserving. `ms[len(ms)//2]` and nearest-rank `pctl(.5)` differ for even n (n=4: index 2 vs 1), so the printed p50/p90 would change.
- scripts/analyze.py:459 — FIXED: removed the unused `joined` and the duplicate `Counter as _C` import (uses `Counter`).
- scripts/calibrate_jev_gate.py:694 — FIXED: removed the unused `enf = load_enforcer()` in `cmd_live`. Note: an enforcer import failure now surfaces inside `live_catalog()`'s existing `try` ("live catalogue unavailable") instead of crashing `cmd_live` first. The test fixture no longer loads the real enforcer.
- scripts/sieve_recall.py:1285 — SKIPPED: medium confidence, and not purely an unused value. Dropping the K=40 call changes the engine call sequence and cache warmth of a pre-registered timed measurement.
- scripts/doctor.py:1827 — FIXED: `"skill" in name`.
- scripts/precision_eval.py:3 — FIXED: the docstring now describes the LIVE-only default mode in two lines, and the `--selftest` line is gone.
- scripts/doctor.py:2646 — FIXED: deleted the duplicate run_all-memo comment; moved the pruning comment to the `_pid_alive`/`_prune_server_records` asserts.
- scripts/doctor.py:58 — FIXED: dropped the "0.26.2 vs 0.27.0 live today" examples (:58, :1617) and changed "the other three harnesses" to "the other harnesses".
- scripts/doctor.py:1162 — FIXED: re-verified (enforcer.py:6 "via the local index owner", doctor.py OWNER_TITLE). "queries Qdrant" became "queries the index owner" in the docstring and both WARN detail strings.
- scripts/analyze.py:479 — FIXED: the banner is now `analyze --selftest OK` (no test or doc greps the old text).
- scripts/doctor.py:1917 — FIXED: "the the earlier" → "the earlier" (both places).

## Verification (worktree, 2026-10-09)

- `python3 -m pytest -q -p no:cacheprovider` over the 20 test files that reference these scripts (test_calibrate_cache, test_cline_agent_plugin, test_calibrate_live, test_consult_fit, test_cline_plugin, test_claude_code_installer, test_consult_widen, test_engine_env, test_codex_installer, test_findability_doctor, test_dsh_installer, test_jev_history, test_keep_off_consent, test_opencode_adapter, test_precision_eval_sets, test_port_agreement, test_jevd_bench, test_owner_cutover_tooling, test_trigger_filter, test_sieve_recall):
  - before: `452 passed in 171.27s (0:02:51)`
  - after: `458 passed in 169.51s (0:02:49)` (my 2 new tests included; the other added tests come from other lanes' concurrent edits to these files)
- `python3 scripts/doctor.py --selftest` → before `selftest ok` (exit 0); after `selftest ok` (exit 0).
- `python3 scripts/doctor.py` before and after:
  - Row labels: 30 → 30. The label list (`grep -o '^  \[.\] <label>'`) is identical.
  - The first post-edit run was byte-identical to the baseline. A later re-run differs only on live state:
    - Running-engine count 6→7.
    - Cline Agent Plugin 13→14 files.
    - Command Code row ✓→!: "installed mod differs from adapters/commandcode/skill-concierge.mod.ts". Another lane modified that adapter file in the worktree, and the ORIGINAL doctor code returns the same WARN on the same machine state (old vs new `check_commandcode` compared live: IDENTICAL).
- Differential harness, original vs edited doctor: `check_omp`, `check_claude_code`, `check_zcode`, `_zcode_installed_path` and `check_commandcode` over 79 registry/settings fixtures (missing, unparsable, list root, empty, list/dict entries, junk entries, malformed hook blocks), with exceptions compared too → `differential OK: 79 fixture comparisons identical`.
- `python3 scripts/analyze.py` output across 7 invocations (default, `--chains`, `--latency`, `--continuation`, `--since`, `--chains --since`, `--latency --since --until`) diffed before/after → IDENTICAL. `python3 scripts/analyze.py --selftest` → `analyze --selftest OK`.
- `python3 scripts/calibrate_jev_gate.py --selftest` → `selftest OK`.
- `ruff check --select F` on all six files → `All checks passed!`
- `python3 scripts/driftcheck.py driftcheck.json` → `IN SYNC: every fact matches its source of truth.`

## Not checked

- I did not run `precision_eval.py` (default mode) or `sieve_recall.py` subcommands live: they need the engine venv, a live owner or Jev calls. Their edits are covered by ruff F, pytest (test_precision_eval_sets, test_sieve_recall) and a reading of the code.
