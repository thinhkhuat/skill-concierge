# E — adapters/ + setup.sh: dispositions

Worktree `/Users/thinhkhuat/.worktrees/skill-concierge/chisle-cuts` (base 692cab1). Line numbers are the findings' (HEAD) numbers.

## Findings (25)

- adapters/claude-code/install.sh:67-187 (shared adapters/lib/sync.sh) — SKIPPED: a shared `adapters/lib/` helper is not approved; installers stay self-contained per harness. The concrete drift it named (zcode exclude list) is FIXED, see Defects.
- adapters/codex/install.sh:1-71 (71-line header) — PARTLY FIXED: dropped the :336-341 guard comment, which restated the error text below it (now a one-line pointer to header step 5), and removed the header's "post-refresh mismatch check remains as a backstop" sentence, which became false once the backstop was deleted. SKIPPED the rest of the compression: medium-confidence prose that documents behaviour and observed Codex facts. It does not restate code, so the policy does not allow cutting it.
- adapters/commandcode/install.sh:40-74 (delete preflight heredoc) — SKIPPED: not behaviour-preserving. The preflight checks `hooks`/`mcpServers`/`skills` shape in all three files, but the compute phase checks `hooks`/`skills` only in settings.json. A `skills: 5` or `hooks: []` in either mcp.json is refused today and would be accepted. The preflight also names the file on a JSON parse error (compute prints the bare decoder message), and it lists every bad file at once.
- adapters/claude-code/install.sh:130-135 (+codex/zcode legacy `.staging.*` prune, tests) — SKIPPED: removing cleanup code for old install states is not approved (other machines may still have them).
- adapters/codex/install.sh:396-408 (unreachable backstop) — FIXED. Proof: `ENABLED_BEFORE=0` is set only in the `disabled)` case, which also sets `PLUGIN_INSTALLED=1`, and the guard then `exit 1`s. The backstop block is deleted. `ENABLED_AFTER` had no other reader, so its assignments are folded into `enabled|disabled) INSTALLED_AFTER=1`. tests/test_codex_installer.py:396 (message never appears) still passes.
- adapters/claude-code/install.sh:116-124 (9-line `_export_to` comment ×4) — FIXED in claude-code, codex, omp and zcode: cut to 3 lines. Codex keeps its "neither the version scan nor skill discovery reads" nuance as a 4th line.
- adapters/commandcode/install.sh:143-172 (migration filters) — SKIPPED: `(check)`, and removing cleanup for old install states is not approved.
- setup.sh:65-73 (ADR-0025 ledger migration) — SKIPPED: `(check)`, and removing cleanup for old install states is not approved.
- setup.sh:16-27 (+:129-133, :149-159 WHY comments) — SKIPPED: medium prose that explains WHY. It is neither wrong nor a restatement of the code, so the policy does not cover it.
- adapters/dsh/install.sh:203-219 (three copy-paste blocks) — FIXED: one loop over (MCP, UNLAZY, ENFORCER) in the same order, each step working on the previous result. SKIPPED the proposed `_append_block` one-liner: it is not byte-identical. When the existing text ends in "\n" after trailing spaces (`"x  \n"`), `rstrip("\n")` keeps the spaces and `rstrip()` drops them.
- adapters/commandcode/install.sh:102-111 (SERVER_ENV from mcp.json) — SKIPPED: `(check)`, not approved.
- adapters/omp/skill-concierge.ext.ts:191-201 (`skillNameFromPath`) — FIXED: deleted. `rg -n -w skillNameFromPath --hidden -g '!plans/**' -g '!vendor/**' .` returned only the definition.
- adapters/opencode/plugin/index.ts:343-351 (disposer) — SKIPPED: `(check)`, not approved. Whether OpenCode's host uses the disposer was not checked.
- adapters/commandcode/skill-concierge.mod.ts:137-153 (duplicate runLedger) — FIXED: `runLedger` is called once, before `if (trimmed.startsWith("/")) return { action: "continue" };`. Same payload, one call on both paths.
- adapters/lib/safe_write.py:1-29 (docstring) — FIXED (the wrong part): the stale per-function caller lists ("the Cline/ZCode manual MCP-fallback merges"; dsh and opencode missing) are replaced with `Callers: grep -rn safe_write adapters/`. SKIPPED trimming the accurate history paragraph: medium prose that is not wrong.
- adapters/omp/install.sh:235-237 (+zcode:185-187 hand-listed chmod) — SKIPPED: medium, and it changes behaviour (more files chmodded), so the policy does not allow it. Not a defect either: `git ls-files -s` shows every `adapters/*/install.sh`, `setup.sh` and `bin/*` tracked as 100755, and both the git-archive and tar export paths keep modes.
- adapters/cline/skill-concierge.cline-plugin.ts:64-65 (`run()` `args`) — FIXED: parameter dropped, `spawn("python3", [path], …)`, and the two `[]` arguments removed. `fire()` keeps its `args` because :258 passes `["sync"]`.
- adapters/dsh/skill-concierge.dsh.ts:104 (+:246 orphaned JSDoc) — FIXED: both one-line JSDocs stacked above the real JSDoc are removed.
- adapters/dsh/install.sh:105 (`import json, os, sys`) — FIXED: now `import sys` (`Path` comes from pathlib). No `json.`/`os.` use in the heredoc.
- adapters/omp/install.sh:21 (+zcode:15, dsh:18, commandcode:9, commandcode:246/251/253 stale prose) — FIXED, each checked against the code:
  - omp header: "byte-identical to this checkout's working tree" (the code runs `diff -q` against `$ROOT`).
  - zcode header: "a tar copy for non-git checkouts".
  - dsh header step 4: now lists the real checks (launcher present and executable, enforcer present, each profile's patch names skill-search and loads under DSH's parse rules, doctor's DSH row).
  - commandcode header step 5: "drops hook events Command Code does not support (UserPromptSubmit, PreCompact) and stale 0.20.8 / doctrine-patch SessionStart entries".
  - commandcode 5a: the comment and both printed lines now say "this checkout's file", not "repo HEAD" (the code reads the working-tree file). No test or doc parses that string; docs/caveats.md:569 still says "repo HEAD" (another lane's file, reported below).
- setup.sh:11-13 (+:183-184) — FIXED: removed the "Behavior flags" header (`ENFORCER_AUTHORIZED_SKIP` is hook-side, and setup.sh never reads it; the AGENTS.md Runtime flags table is the index) and the two-line note on the retired MEAN overlay (`scripts/enrich_index.py` does not exist).
- adapters/opencode/plugin/package.json:3-4 — FIXED the description, which said the manifest "exists for a future published-package form" although `install.sh:78` requires it. It now says the dir is loaded as a package and that install.sh requires the manifest. SKIPPED dropping `"version": "0.62.0"`: whether OpenCode's package loader reads `version` is unverified (the binary was not checked). Owner call: drop it, or add it to the version bump set.
- adapters/dsh/unlazy-dsh-stop.dsh.ts:24-25 (+dsh.ts:32-35 roadmap prose) — SKIPPED: low confidence.
- setup.sh:86-105 (`_acquire_engine_lock` duplicates bin/skill-search-mcp) — SKIPPED: low confidence and `(check)`; bin/ is outside this lane.
- adapters/cline/mcp_row.py:1-54 (Cline retirement code) — SKIPPED: low confidence, and the Cline retirement code is explicitly not approved.

## Defects seen in passing (3)

- adapters/zcode/install.sh:123-127 (non-git tar export lacks `--exclude='.zcode' --exclude='.unlazy'`) — FIXED: both excludes added. The comment now matches the three siblings, so the non-git branch is the same in all four installers. New tests in tests/test_installer_staging_cleanup.py:
  - `test_non_git_exclude_list_is_identical_across_the_four_installers`: a parity guard that closes the drift class.
  - `test_non_git_export_ships_no_scratch_dir[claude-code|codex|omp|zcode]`: behavioural. It runs the extracted `_export_to` against a non-git root holding all 14 scratch dirs.
  - Fail-before: against HEAD's zcode installer, 2 failed / 3 passed. The zcode case reported `AssertionError: ['.unlazy', '.zcode']` and the parity guard failed too. Pass-after: 5 passed.
  - A stale test comment (":48 … exclude-list difference already sits in ZCode's non-git-checkout branch") was updated.
- adapters/dsh/unlazy-dsh-stop.dsh.ts:127-128 (`cwdOf(ctx)`/`sessionIdOf(ctx)` read the plugin ctx) — SKIPPED: not approved in this lane, and there is no practical test (no DSH runtime harness in tests/). Evidence gathered points to a real defect:
  - DSH's own bridge `/opt/homebrew/lib/node_modules/@deepseek-ai/dsh/node_modules/@deepseek-ai/dsh-hooks-codex/lib/index.js:211` destructures `{ agent, … }` from the `agent/pre-step` EVENT, and `:305-307` reads `agent?.session.header.id` / `.header.cwd`.
  - The unlazy bridge reads `ctx.agent.session.id` / `ctx.session.id` from the plugin ctx. That is the wrong object, and `session.id` is not `session.header.id`.
  - Whether the Cordis plugin ctx exposes `agent`/`session` at all was not checked. Owner follow-up.
- adapters/commandcode/skill-concierge.mod.ts:188-213 (possible double ledger row for one skill load) — NOT A DEFECT, no change. Command Code 1.73.2 `/opt/homebrew/lib/node_modules/command-code/dist/cli.mjs` has exactly one `type:"skill_loaded"` emit site (`grep -c` = 1). It sits in the user-input slash-expansion path (`for(const e of l)y.emit({type:"skill_loaded",name:e})`, after `e.expansions` / `detectHostSlashSkillInvocation`). Its bundled reference `dist/bundled/mod-builder/reference/hooks-and-events.md:232` says: "`skill_loaded` | a skill was activated by an explicit user `/name` invocation". The model's `activate_skill` tool call emits `tool_completed` (:82, :225). The two rows log different events: a user `/name` load, and a model tool activation.

## Verification

- `bash -n`: OK on setup.sh and all 8 `adapters/*/install.sh`.
- TS parse (`esbuild <file> --loader:.ts=ts`): OK for the 4 changed .ts files.
- `tsc --noEmit --noResolve` on the cline plugin: no arity errors for the changed `run()` calls. The only error left after filtering out module and Node-typing errors is TS1470 (`import.meta` under CommonJS output), which the HEAD copy raises identically, so it predates this change.
- Baseline, before any edit, 13 adapter test files: `194 passed in 168.85s (0:02:48)`.
- After the edits, those 13 files plus test_port_agreement, test_port_env_guard, test_keep_off_consent, test_owner_cutover_tooling, test_shell_portability and test_engine_env (they read setup.sh):
  `python3 -m pytest -q -p no:cacheprovider tests/test_claude_code_installer.py tests/test_cline_agent_plugin.py tests/test_cline_installer.py tests/test_cline_plugin.py tests/test_codex_installer.py tests/test_dsh_installer.py tests/test_installer_head_version.py tests/test_installer_staging_cleanup.py tests/test_installer_write_discipline.py tests/test_opencode_adapter.py tests/test_safe_write.py tests/test_sibling_installers.py tests/test_adapter_exclusion_echo.py tests/test_port_agreement.py tests/test_port_env_guard.py tests/test_keep_off_consent.py tests/test_owner_cutover_tooling.py tests/test_shell_portability.py tests/test_engine_env.py`
  → `2 failed, 304 passed in 181.84s (0:03:01)`. Both failures come from OTHER lanes' edits in the shared worktree, not from this lane:
  - `test_sibling_installers.py::test_readme_054_1_line_mentions_the_zcode_missing_registry_entry_refusal`: `readme.index("`0.54.1` —")` raises ValueError because README.md's working-tree diff deletes that line (`git diff README.md` shows `-`0.54.1` — **published, ADR-0073 …`).
  - `test_port_env_guard.py::test_no_shell_script_expands_a_port_setting_outside_the_allowed_lines`: `FileNotFoundError: …/chisle-cuts/bin/embed-shim`, because `bin/embed-shim` is deleted (`D bin/embed-shim`) while the test still reads it.
- `python3 scripts/driftcheck.py driftcheck.json` → exit 0, "IN SYNC: every fact matches its source of truth."
- `hooks/` was not touched, so `enforcer.py --selftest` was not run by this lane.

## Not checked

- Whether OpenCode's loader reads `package.json` `version` or needs the setup disposer.
- Whether the Cordis plugin ctx carries `agent`/`session` (the unlazy defect above).
- No live harness run: the Codex, Command Code, OMP, ZCode, DSH and Cline installers were exercised only through their pytest fakes.
