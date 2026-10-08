# Code review: removal of the Cline file-hook fallback (plugin-only installer)

Date: 2026-10-08 (Asia/Saigon). Reviewer: code-reviewer subagent, read-only on the worktree.
Worktree: `/Users/thinhkhuat/.worktrees/skill-concierge/cline-v2`, branch `feat/cline-plugin-v2`, uncommitted on top of `1ccbd5b`.
Out of scope (in flux, not read): README.md, CHANGELOG.md, AGENTS.md, docs/**, openwiki/**.

## Scope

- Files reviewed: `adapters/cline/install.sh`, `adapters/cline/mcp_row.py`, `scripts/doctor.py` (`_cline_leftovers`, `check_cline`, lines 2143-2228), `scripts/check_mcp_env_parity.py`, `driftcheck.json`, `tests/test_cline_installer.py`, `tests/test_adapter_exclusion_echo.py` (Cline cases), `tests/cline_plugin_harness.mjs`, plus the Cline lanes of `adapters/cline/skill-concierge.cline-plugin.ts`, `hooks/scripts/doctrine.py`, `hooks/scripts/enforcer.py` and `adapters/lib/safe_write.py` for context.
- Deleted-file content checked against `git show HEAD:` (bridge shims, `mcp.json`, old `install.sh`) and, for the never-committed `tests/test_cline_bridge_modes.py`, against snapshot commit `6034eec` (read with `git show`, no state change).
- Fact: HEAD only ever shipped two shims (`UserPromptSubmit.cjs`, `PostToolUse.cjs`). `TaskStart.cjs` and `PreToolUse.cjs` existed only in the uncommitted intermediate state, so retiring all four is harmless over-coverage.

## How I verified (run vs read)

All runs used a copy at `$TMPDIR/cr-cline-review` (made with `cp -R`; the worktree has no symlinks, checked with `find -type l`). For the full-suite run I deleted the copy's `.git` pointer file first, so no test could reach the real worktree's gitdir. Afterwards `git stash list` in the worktree was still empty and `git status` was unchanged.

Ran:
1. `pytest` on the Cline-related files (`test_cline_installer`, `test_adapter_exclusion_echo`, `test_cline_plugin`, `test_cline_agent_plugin`, `test_sibling_installers`, `test_harness_regex_parity`, `test_blocklist`): **81 passed, 0 skipped**.
2. Full suite on the detached copy: **1082 passed, 3 failed**. All 3 failures need git (`git ls-files` with no repo). After `git init` plus one snapshot commit in the copy, two of them passed. The last one (`test_guard_would_have_caught_the_shipped_dsh_regression`) needs real history (`git show 7e6cecf:...`). All three are environmental and none touches Cline. An earlier `-x` run with the git link still in place failed `test_codex_installer` only because `plugin.json` says v0.63.0 while HEAD says v0.62.0, which is expected for an uncommitted bump.
3. `check_mcp_env_parity.py` gave OK. `driftcheck.py driftcheck.json` gave "IN SYNC".
4. `enforcer.py --selftest` under a throwaway HOME failed on two cross-harness foreign-scope lines. **The HEAD tree (`git archive HEAD`) fails identically under the same throwaway HOME**, so this is HOME-sensitivity that predates this change, not a regression.
5. Five `install.sh` scenarios under throwaway HOMEs (results below), plus ten malformed-settings cases against `mcp_row.py` and six against `doctor.check_cline`.

Read only (not run): the live Cline runtime. I did not start a Cline session, so how Cline treats a failing old shim is an open question.

## Overall assessment

The removal is clean. No code, test, config, skill, `bin/` or `setup.sh` file still references the deleted bridge, the `adapters/cline/hooks/` templates, `adapters/cline/mcp.json`, `--file-hooks` or `--no-mcp` as a live Cline mode. The ownership guards run before any write. The old-shim marker cannot match the new loader. A second run is idempotent. The retargeted echo test drives the real `skill_exclusions.py`.

There are no Critical or High findings. Two Medium findings concern the upgrade path and a test guard that lost coverage. The rest are Low robustness and coverage gaps.

## Critical issues

None.

## High priority

None.

## Medium priority

### M1. An existing install breaks on `git pull` until `install.sh` is re-run (upgrade hazard)
- Where: deletion of `adapters/cline/skill-concierge.cline-hook.cjs`. The old shims installed by HEAD contain `require("<ROOT>/adapters/cline/skill-concierge.cline-hook.cjs")("prompt_submit")` with no try/catch (HEAD `adapters/cline/hooks/UserPromptSubmit.cjs`).
- Scenario: a user on v0.62.0 updates the checkout but does not re-run `adapters/cline/install.sh`. Every Cline prompt and tool use then fires a shim that throws `MODULE_NOT_FOUND` and exits 1. The new plugin is not active yet either, because only `install.sh` writes the loader. Nothing auto-runs the Cline installer (I checked `setup.sh`, `scripts/`, `hooks/` and `skills/`; none call it). Doctor flags the leftovers, but only when someone runs doctor.
- Inference: the impact depends on how Cline treats a non-zero file hook (see Unresolved questions). It ranges from noisy errors to a cancelled tool call.
- Fix options: (a) keep a tombstone `skill-concierge.cline-hook.cjs` for one release that exports `() => process.stdout.write('{"cancel":false}')` and prints one stderr line telling the user to re-run `install.sh`; or (b) at minimum, make sure the 0.63.0 CHANGELOG carries an explicit "re-run adapters/cline/install.sh after upgrading" step. That file belongs to the docs agent; I did not check it.
- This machine: `~/.cline/hooks/` holds no `.cjs` shims today (checked with `ls`), so the live install is unaffected.

### M2. The installer write-discipline guard no longer covers the Cline settings write
- Where: `tests/test_installer_write_discipline.py:28` scans only `adapters/*/install.sh` text, heredocs included. In HEAD, the `cline_mcp_settings.json` write lived in a heredoc inside `install.sh`, so the guard covered it. It now lives in `adapters/cline/mcp_row.py:46`, which the guard never reads.
- Scenario: a later edit changes `safe_write.write_text(cfg_path, ...)` in `mcp_row.py` to `cfg_path.write_text(...)`. That breaks the symlinked-settings case and widens a 0600 mode, and the guard stays green. Only `test_cline_installer.py`'s symlink and mode test would catch it, and only for that one path.
- Fix: extend the guard to scan the Python helpers each installer calls, for example `sorted((ROOT / "adapters").glob("*/*.py"))` through `_py_write_offenders`. Allow-list `agent_plugin.py:_write`, which writes its own generated folder and not a user config. Inference: this shift may predate this exact step, because `mcp_row.py` existed as add/remove before it, but it is in the current diff against HEAD either way.

## Low priority

### L1. Malformed settings JSON crashes `mcp_row.py` with a traceback mid-install, leaving a half-finished install
- Where: `adapters/cline/mcp_row.py:20-22, 35-36`.
- Ran: a top-level list `[]` or `{"mcpServers":[1]}` gives `AttributeError`, rc 1. `{"mcpServers":{"skill-search":"str"}}` gives `AttributeError`. `"args": {"a":1}` gives `KeyError: 0`. `"args": 5` gives `TypeError`. None of these writes anything, so there is no data loss.
- Scenario (ran, scenario 4): `install.sh` has already written the loader and the Agent Plugin and removed the old shims (lines 55-67). It then dies at line 69 with a Python traceback, and the verify block never runs. The `install.sh:45` comment says "Both ownership checks run before anything is written", but the settings-file refusal (invalid JSON, rc 1) also lands after those writes.
- Fix: treat a non-dict root, `mcpServers` or row as "not ours, leave it" (`isinstance` checks plus `isinstance(args, list)` in `ours`). Optionally run `mcp_row.py` in a check-only mode before step 1, so an unreadable settings file stops the install before any write.

### L2. Doctor turns a WARN-only check into FAIL on a malformed `args`
- Where: `scripts/doctor.py:2168`. The `except` tuple covers `AttributeError` but not `KeyError` or `TypeError`.
- Ran: `"args": {"a":1}` gives `fail | the check itself crashed: KeyError: 0`. `"args": 5` gives `fail | ... TypeError`. `_run_check` keeps the rest of the report alive, but the overall status becomes FAIL for an optional harness whose contract is "WARN-only, never a failure" (comment at `doctor.py:2148`).
- Fix: `args = row.get("args"); if isinstance(args, list) and args and str(args[0]).endswith(...)`, or add `(KeyError, TypeError, IndexError)` to the `except`.

### L3. The `CLINE_SESSION_BACKEND_MODE` check reads doctor's environment, not Cline's
- Where: `scripts/doctor.py:2217`.
- Ran: `~/.config/harness-env.sh:102` exports `CLINE_SESSION_BACKEND_MODE=local`, yet this agent's process has it unset, because this session started before the export existed. Every doctor run from such a process (a long-lived Claude Code or Codex session, launchd) gives a false WARN even when Cline itself runs in local mode. The reverse is also possible: Cline launched from a GUI without that env, while doctor runs from a shell that has it, gives a false OK.
- Fix: word the finding as "doctor's environment lacks CLINE_SESSION_BACKEND_MODE=local; Cline sessions must inherit it". Or read the value from the source of truth (grep `harness-env.sh`) as well as `os.environ`. This is a wording and false-positive issue; it hides no defect.

### L4. The `mcp_row.py` backup copy is briefly created at the umask mode
- Where: `adapters/cline/mcp_row.py:44`, `shutil.copy2`. `copyfile` opens the destination with mode 0666 minus the umask (normally 0644) and only then applies `copystat`. For a 0600 settings file that may hold API tokens, the backup is readable by others for that short window. `safe_write.write_registry` exists to avoid this (`_write_fresh` at 0600, then `copymode`; see the module docstring). Same pattern as HEAD's heredoc, so not a regression, but the move to a stand-alone helper was the moment to reuse `safe_write`.
- Also: no changed-on-disk guard. A live Cline process that writes the file between read and write loses its update. Low, because the installer tells the user to start a new session.

### L5. Stale code comments that still describe the removed vehicle
- `adapters/claude-code/install.sh:31`: "deliberately no --no-mcp / --mcp-fallback flag here (unlike Cline / ZCode)". Cline no longer has `--no-mcp`.
- `hooks/scripts/doctrine.py:241`: "Cline (ADR-0051): the MCP server rides the plain global mcpServers map (no plugin namespace)". The same block now says the server comes from the Agent Plugin with a namespace, so the first sentence contradicts the code under it.

### L6. Test coverage lost or never added
- `use_skill` lane: the old echo test parametrized `use_skill`. The retargeted test (`tests/test_adapter_exclusion_echo.py`) dropped it, and `test_cline_plugin.py` never uses it. The plugin still routes it (`skill-concierge.cline-plugin.ts:154`), so that branch is now untested.
- Real `skill_guard.py` through the Cline lane: the deleted `test_cline_bridge_modes.py` drove the real guard (deny, bare-entry-blocks-qualified-twin, allow). `test_cline_plugin.py:155` uses a stub guard. The guard logic itself is covered by `tests/test_blocklist.py:55` (bare entry and qualified twin), and the plugin sends the same payload shape (`{"tool_name":"Skill","tool_input":{"skill":...}}`, same as `test_blocklist.py:40`). So the residual gap is only the end-to-end wiring. One real-guard case in `test_adapter_exclusion_echo.py` style would close it.
- Stringified params (`'"evil-skill"'`): the deleted test covered Cline's file-hook `mapParams` stringification. The plugin strips only leading `/` (`.ts`, `beforeTool`). Whether the plugin API can also deliver JSON-quoted values is unknown (see questions).
- `test_cline_installer.py` does not cover: idempotence on a second run, foreign-loader refusal, foreign Agent-Plugin-dir refusal, invalid-JSON refusal, a "not ours" row left alone, or that a backup file is created. I verified the first three by running them (below); the rest I verified only by reading.

## Scout and scenario results (ran)

Throwaway HOMEs, copy of the worktree:
1. Fresh HOME with no `~/.cline`: rc 0. The loader is written and the Agent Plugin check passes.
2. Second run on the same HOME: rc 0, **identical file set, byte-identical loader**. No backup appears, because there is no row.
3. Any option (`--no-mcp`): rc 1 with the usage line. HOME stays empty.
4. Foreign loader (`// mine`): rc 1, refused. Nothing else is created (no `~/.agents`). The guard runs before any write: confirmed.
5. JSON-list settings plus one marked shim: rc 1 with a traceback. The loader and Agent Plugin are already written and the shim is already removed (L1).
6. All four marked shims, plus an operator `UserPromptSubmit` (no extension) and a `Notification.cjs`: all four marked shims removed, both operator files kept.

Marker safety (Fact, ran): `grep -q "GENERATED by adapters/cline/install.sh"` does not match the generated loader (`GENERATED by skill-concierge adapters/cline/install.sh`), and it matches nothing under the generated `~/.agents/plugins/skill-concierge`. In the repo, the string appears only in `install.sh` itself, in `doctor.py` and in the test. The loop examines only `~/.cline/hooks/{UserPromptSubmit,PostToolUse,TaskStart,PreToolUse}.cjs`, so it can delete an operator file only when that file sits at one of those four names *and* carries the old marker. The old shims said "safe to regenerate; edits are lost", so that is acceptable. `grep` on an unreadable file returns 2 inside an `if`, which `set -e` does not treat as fatal. An absent `~/.cline/hooks` makes `-f` false. An absent settings file makes `mcp_row.py` return 0.

`mcp_row.py` cases (ran): missing file gives rc 0. `mcpServers: null` gives rc 0. A row with only `command` and no `args`, or `args` given as a string, is reported as not ours and left alone (rc 0). Our row is removed, the backup is named `cline_mcp_settings.json.bak-skill-concierge-YYYYMMDD-HHMMSS` beside the file (beside the symlink when the file is a symlink), and unrelated servers survive. Invalid JSON is refused with rc 1 and nothing written. Symlink plus 0600 is preserved (`test_cline_installer.py`, passed).

Question 6 (echo test realness), verified: `tests/test_adapter_exclusion_echo.py` imports the real `adapters/cline/skill-concierge.cline-plugin.ts`. The plugin's `findRoot()` resolves to the repo root, so `run("skill_exclusions.py")` runs the real `hooks/scripts/skill_exclusions.py`. The assertion needs `MARK`, text that exists only in the fixture `SKILL.md` and that only the real script could extract. It passed with no skip.

Question 1 (stale references): a grep over everything outside plans/, docs/, README, CHANGELOG, AGENTS, openwiki/, vendor/, graphify-out/ and graft/ found no reference to `cline-hook.cjs`, `adapters/cline/hooks`, `adapters/cline/mcp.json`, `file-hooks` or `test_cline_bridge`. `skills/`, `hooks/doctrine/`, `hooks/hooks.json`, `.claude/`, `.codex/`, `bin/` and `config/` have no Cline mentions at all. No caller passes options to the Cline installer. Only the two stale comments in L5 remain.

## Operational note (not a code defect)

The live loader `~/.cline/plugins/skill-concierge.ts` currently re-exports `/Users/thinhkhuat/.worktrees/skill-concierge/cline-v2/adapters/cline/skill-concierge.cline-plugin.ts`, and the live Agent Plugin was presumably built from this worktree too. Removing this worktree after the merge, without re-running `install.sh` from the main checkout, leaves Cline importing a missing file. Run `adapters/cline/install.sh` from the main checkout before deleting the worktree. Doctor run from main would flag the loader as "points at ..., not this checkout".

## Recommended actions (priority order)

1. M1: ship a one-release tombstone bridge, or confirm the 0.63.0 CHANGELOG has an explicit re-run step.
2. M2: extend `test_installer_write_discipline.py` to scan `adapters/*/*.py`.
3. L1 and L2: add `isinstance` guards in `mcp_row.py` and `doctor._cline_leftovers`; optionally pre-validate the settings file before the first write.
4. L5: fix the two stale comments.
5. L6: restore a `use_skill` echo case and add one real-guard deny case through the plugin harness. Add idempotence and refusal cases to `test_cline_installer.py`.
6. L3 and L4: reword the env finding; reuse the `safe_write` backup pattern.

## Metrics

- Tests: 81/81 Cline-related passed; full suite 1082 passed, 3 environmental git-history failures (explained above).
- Lint and typecheck: not run (the repo has no configured lint step for these files that I found; I did not search further).
- driftcheck: IN SYNC. mcp-env-parity: OK.

## Unresolved questions

1. How does Cline 3.0.70 treat a file hook (`PostToolUse.cjs`) that exits 1 with `MODULE_NOT_FOUND`? Ignore, log, or cancel the tool call? This decides whether M1 is cosmetic or blocking for upgraders. I did not run Cline.
2. Can the Cline plugin `beforeTool` context deliver JSON-quoted parameter values, as the file-hook `mapParams` path did? If it can, a quoted blocklisted name would slip past `skill_guard.py`.
3. Does the 0.63.0 CHANGELOG (docs agent, out of my scope) tell upgraders to re-run `adapters/cline/install.sh`?
4. `enforcer.py --selftest` fails two cross-harness lines under a throwaway HOME, on HEAD as well. Is that HOME-sensitivity known? It is outside this change.

Decisions made without grounding: none. Severity ratings are judgment calls based on the scenarios above.

Status: DONE_WITH_CONCERNS
Summary: The fallback removal is clean (no live references remain, the guards run before writes, the marker is safe, re-runs are idempotent, and the echo test drives the real script), but upgraders who pull without re-running install.sh hit a missing-bridge `require`, and the write-discipline guard no longer covers the moved settings write.
