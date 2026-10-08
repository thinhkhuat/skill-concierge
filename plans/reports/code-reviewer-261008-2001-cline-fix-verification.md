# Fix verification: Cline plugin rework (ADR-0086), branch feat/cline-plugin-v2, uncommitted

Reviewer: code-reviewer subagent, 2026-10-08, read-only. This report is the only file I wrote.
Prior review: `plans/reports/code-reviewer-261008-1852-cline-rework-review.md` (snapshot 19:50).
Ground truth for Cline: `~/.bun/install/global/node_modules/@cline/{core,agents}` 0.0.92 and the CLI binary `@cline/cli-darwin-arm64/bin/cline`. Every runtime quote below was copied from `rg -a -o` output.

## What I ran

- I ran `pytest -p no:cacheprovider tests/test_cline_agent_plugin.py tests/test_cline_plugin.py` with `PYTHONDONTWRITEBYTECODE=1`, using `~/.claude/skills/.venv/bin/python3`. I read both files first. Every write in them lands under `tmp_path`:
  - The plugin tests use stub scripts that log to `tmp_path/log`.
  - `sync` targets `tmp_path/skill-concierge`.
  - The two tests that run real scripts do not write elsewhere. `doctrine.py` has no write sites. `enforcer.py` runs with `SKILL_CONCIERGE_LOG=tmp_path` and `SKILL_OWNER_AUTOSTART=0`, and its only other write site is the owner-autostart stamp, which that flag disables.
- Result: `18 passed in 8.80s`. `git status --porcelain` was identical before and after the run. The mtime of `~/.agents/plugins/skill-concierge/.skill-concierge-managed.json` was unchanged.
- I did not run `tests/test_cline_installer.py`, `tests/test_cline_bridge_modes.py` or `tests/test_sibling_installers.py`. They execute `install.sh` and `doctor.py` end to end, and I verified L3 by reading the code instead.
- I ran several in-memory probes with `python3 -I -c`. None of them wrote a file.

## Verdicts on the claimed fixes

### H1: FIXED
- `skill-concierge.cline-plugin.ts:38` sets `HOOK_BUDGET_MS = 2000`.
- Every hook wait and child timeout uses that constant:
  - `beforeModel` waits at `:223` (`HOOK_BUDGET_MS - (Date.now() - started)`).
  - The preview pass uses it at `:172`.
  - `skill_guard.py` uses it at `:238`.
  - `skill_exclusions.py` uses it at `:266-267`.
- The full enforcer pass (`ENFORCER_TIMEOUT_MS = 20000`, `:169`) is never awaited past the budget.
- The doctrine rule uses `HOOK_BUDGET_MS * 3` = 6000 ms (`:193`). This is correct. In `@cline/core` `ps()`, the hook timeout and the contribution timeout are separate: `o=Fc(e.hookTimeoutMs,3000),s=Fc(e.contributionTimeoutMs,60000)`. Hooks are wired with `o` (`m.hooks=PF(n,p,o,d)`). Rules are wired with `s` (`wF(g,n,p,s,d)`), and `wF` calls `t.call("resolveRuleContent",…,{timeoutMs:r})`. Rule content is therefore bounded by 60000 ms, not 3000, so the 6 s budget is not a defect.
- Informational, not a defect:
  - The rule is resolved on every run. `executeRun` calls `composeSystemPrompt`, which calls `Mj(n)`, which runs `await e.content()`.
  - Each Cline run therefore spawns `doctrine.py` once. I measured 0.22–0.24 s per spawn (three runs, `/usr/bin/time -p`).
  - If `doctrine.py` fails, `run()` returns null, so the rule is empty and the run continues (fail-open).
- The test `test_slow_menu_…` asserts that the first call returns in under 2300 ms, and it passed. The cost of IPC on a long transcript is still unmeasured, as the prior report noted. The 1 s margin is a judgement call, not a measurement.

### H3: PARTLY FIXED (the plugin side is fixed; ledger.py does not stamp one of the three lanes)
- The plugin side is fixed. `afterTool` adds `agent_id` when `isSubagent(snapshot)` (`:260`), using `snapshot.agentId` and falling back to `"subagent"`. The test `test_a_subagent_skill_use_is_logged_as_a_subagent_row` covers this and passed.
- `hooks/scripts/ledger.py:135` computes `sub = bool(d.get("agent_id"))`. Two of the plugin's lanes use it:
  - The `Skill` lane (`auto`) stamps `sub: true` at `:188-189`.
  - The `get_skill` lane stamps it at `:226-227`.
- The `search` lane (`:210-214`) does not stamp `sub`, so a subagent's `search_skills` call still lands as a main-session `search` row. This gap predates this branch and affects every harness, Claude Code included. It is not a Cline regression. It is, however, one of the three lanes named in the task, so H3 is only partly fixed.
- Fix: add `if sub: ev["sub"] = True` to the `SEARCH_TOOLS` branch, and check that `analyze.py` treats a `search` row with `sub` the same way it treats `auto` and `get_skill` rows.

### M1: FIXED for the reported case, with a narrow edge case that the new filter now drops
- `findPrompt` (`:121-137`) skips a user message when `meta.displayRole === "system"`, when `"userRunSpan" in meta`, or when its text starts with `<hook_context` or `[SYSTEM]`.
- How Cline builds typed input:
  - In `@cline/agents`, `execute` pushes the input through `Qd(e)`. For a string, `Qd` builds `he("user",[{type:"text",text:e}])` with metadata `undefined`.
  - In `@cline/core`, `executeRun` appends `{id:crypto.randomUUID(),role:"user",content:v}`, with no metadata.
  - Fresh typed input therefore never carries `userRunSpan`, so the fix does not drop normal prompts.
- The `userRunSpan:0` writers are the completion reminder (`addUserReminderMessage`), the mid-run pending message (`consumePendingUserMessage`) and hook context (`userRunSpan:0,displayRole:"system"`). All three are correctly skipped.
- Edge case: Cline's own typed-user predicate is `Nt(e){return e.role==="user"&&e.metadata?.userRunSpan!==0&&…}`. A positive `userRunSpan` means a typed message.
  - Basic compaction (`DJ`) merges consecutive typed users into one message with `metadata:{...e[d].metadata,userRunSpan:p}` and no `displayRole`.
  - That projection runs in `prepareTurnForModelRequest`, before the `beforeModel` hooks (`n=await this.prepareTurnForModelRequest(n,e)` comes before `for(let o of this.hooks.beforeModel)`).
  - So if compaction fires on a run's first model call, and the new prompt directly follows an earlier typed message that got no reply (for example, a failed or aborted run), the merged message now gets skipped. `findPrompt` then returns an older prompt or null.
  - Before the fix, the merged text was used. That was not right either, but it was closer.
  - Severity: Low.
  - Fix: match Cline's predicate with `meta["userRunSpan"] === 0` instead of `"userRunSpan" in meta`.
- `test_a_runtime_reminder_is_not_mistaken_for_the_prompt` covers the reminder and passed.

### M7: FIXED for the claimed part only (the loader path is parsed as a JSON string)
- `scripts/doctor.py:2186-2191` matches `from\s+("(?:[^"\\]|\\.)*")` and passes the match to `json.loads`.
- I extracted the pattern with `ast` from the file and tested it in memory on two paths: a Vietnamese path that `json.dumps` writes as `à…ệ` escapes, and a path that contains `"`. Both round-tripped to the original path (`True`, `True`).
- If the JSON is malformed, `named` becomes `"?"`. The row then says "points at ?", which is an honest WARN.
- Not fixed, and not part of this claim: the false-OK cases in the prior M7 remain. Doctor still does not detect any of these:
  - a leftover `skill-search` row in `cline_mcp_settings.json` while in plugin mode;
  - a stale `_installed/local` copy;
  - a generated Agent Plugin left beside the shims in file-hook mode.

### H2: FIXED (doctor is now honest)
- `doctor.py:2209-2213` adds a WARN finding while `os.environ.get("CLINE_SESSION_BACKEND_MODE") != "local"`. The wording is conditional ("a Cline CLI session that attaches to a running hub … runs no plugin"), so it does not overclaim.
- The variable is real. The CLI reads it with `let o=process.env.CLINE_SESSION_BACKEND_MODE?.trim().toLowerCase();if(o==="local"||o==="hub"||o==="remote")return o;return"auto"`.
- Two small inaccuracies, both Low:
  - Doctor compares the raw value, but Cline trims and lowercases it. A value of `LOCAL` or ` local` therefore gets a false WARN. Fix: `.strip().lower()`.
  - Cline also forces a local backend on its own in two cases: yolo mode and sandbox (`forceLocalBackend:e.config.mode==="yolo"||e.config.sandbox===!0`), and when `CLINE_VCR` is set. Doctor's WARN is therefore conservative, never falsely reassuring.
- Doctor reads its own process environment. That is the right proxy only because the shared env home (`~/.config/harness-env.sh`) reaches every shell. Whether to set the variable is the owner's decision, and I have not judged it.

### L1: FIXED
- `agent_plugin.py:102-107` uses a per-process temp name (`.tmp-skill-concierge-{os.getpid()}`) and an atomic `replace`. The marker is now written through `_write` (`:133`), so it is atomic too.
- Two residual issues, both Low:
  - If a sync crashes between `write_bytes` and `replace`, it leaves a `*.tmp-skill-concierge-<pid>` file. Neither prune nor `check` ever removes or reports it.
  - When two syncs run at once, one can `rmtree` an empty `skills/<new>` directory (`:130-132`) between the other's `mkdir` and its temp write. The other process then raises `FileNotFoundError` and exits before writing its marker. The next session repairs this.

### L2: FIXED
- `_managed` (`:92-99`) keeps only entries that are non-empty strings, not absolute, and have no `..` part.
- `test_a_tampered_marker_never_prunes_outside_the_plugin_folder` covers both `../outside.txt` and an absolute path, and it passed.
- Residual: a symlink inside `dest` (for example, `dest/skills` pointing elsewhere) is followed for both writes and unlinks. Only `dest` itself is checked. This needs someone to plant a link, so it is Low.

### Symlink refusal in sync(): FIXED
- `sync()` returns 1 when `dest.is_symlink()` (`:117-121`). `test_sync_refuses_to_write_through_a_symlink` passed, and the target's files were unchanged.
- The installer's `set -e` turns that return code into an abort (`install.sh:99`).

### L9: PARTLY FIXED; the fix itself introduces a latent regression
- `convert_skill` (`:48-52`) now JSON-quotes every unquoted `  key: value` line under `metadata`.
- For the ten shipped skills (all plain `version:`, `author:`, `mcp-server:` scalars), the output is correct. The test passed, and it checks that every metadata line is quoted and that the name and description are within Cline's 64 and 1024 limits.
- I ran `convert_skill` in memory on shapes the repo does not use yet, then parsed the output with PyYAML:
  - A block scalar (`  note: |` followed by an indented line) becomes `  note: "|"` with the indented line still below it, which gives a **YAML ParserError**. The pre-fix code copied that shape verbatim, and it was valid. Cline would now reject the whole skill.
  - A nested map (`  owner:` / `    team: core`) stays a map. The inner line is quoted, but `owner` is still not a string, so Cline would still reject it.
  - A trailing comment (`  version: 1.0 # bump on release`) is folded into the value as `"1.0 # bump on release"`.
  - A flow map (`metadata: {version: 1.0}`) stays a number.
- Severity: Low, because no shipped skill uses these shapes today. The real gap is that no test parses the generated frontmatter as YAML. Fix: parse it in the test (PyYAML is already in the test venv) and assert that every metadata value is a `str`. Alternatively, have `convert_skill` refuse (raise) on any metadata child it cannot quote safely, rather than emitting broken YAML.

### L3: FIXED
- `install.sh:108-112` checks all four target shims for the generated marker before writing any of them. If any one is not ours, it exits 1 with nothing written.
- Residual: if a shim path is a symlink to a file that carries the marker, `>` writes through the link. This is Low and only applies to a hand-made layout.

## New defects found in the current diff

### N1 (Medium): The per-session `sync` overwrites an Agent Plugin folder that the installer refused to touch
- `install.sh:91-92` writes the plugin loader first. Only then does `:96-98` refuse an existing `~/.agents/plugins/skill-concierge` that has no ownership marker, and exit 1.
- Because the loader is already in place, the next Cline session loads the plugin. Its `setup` fires `agent_plugin.py sync` (`skill-concierge.cline-plugin.ts:206`) with the default destination.
- `sync()` (`agent_plugin.py:116-135`) checks only for a symlink. It never checks the marker, so it overwrites `plugin.json`, `mcp.json` and any colliding `skills/*` in the folder the installer had just refused to replace. It then writes its own marker, which hides the takeover from later installer runs.
- Fix (both parts):
  1. Move the marker check into `sync()`: if `dest` exists and has no `MARKER`, refuse. On the first install `dest` does not exist yet, so nothing breaks.
  2. Run the `AGENT_DIR` guard in the installer before the loader is written.

### N2 (Low): The file-hook fallback now gets a doctrine that names a tool that does not exist in that mode
- `hooks/scripts/doctrine.py:249` now rewrites the search tool to `skill-concierge_skill-search__search_skills_<suffix>` whenever the harness is `cline`.
- The `--file-hooks` bridge still renders this doctrine on TaskStart (`skill-concierge.cline-hook.cjs` `taskStart`, which runs `DOCTRINE` with `CLINE_ENV`). In that mode the server is the global `skill-search` row, so the real tool is `skill-search__search_skills`.
- On Cline 3.0.69+ the TaskStart output is discarded, so this only matters on the older builds that the fallback exists for. Whether any such build is in use is unverified.
- Fix: let the bridge pass a mode hint (for example, an env var) so that `doctrine.py` keeps the old name in file-hook mode.

### N3 (Low): The doctrine could name the exact tool instead of `<suffix>` (prior L11 is still open)
- Cline's MCP tool naming is deterministic. `@cline/core` defines `Zu=({serverName:e,toolName:t})=>{let n=`${e}__${t}`,r=Nz(n);if(r===n&&n.length<=HP)return n;let o=Lz(n),s=HP-Mz-UP;return`${r.slice(0,s)||Oz}_${o}`}`, where `Lz` is `sha1(n).slice(0,8)`.
- I checked this: `printf 'skill-concierge.skill-search__get_skill' | shasum -a 1` gives `d998a651`, which matches the live name quoted in the plugin comment. For `search_skills` the suffix is `4d64eb2e`.
- `doctrine.py` can therefore print `skill-concierge_skill-search__search_skills_4d64eb2e`, or compute it from the same formula, and the model would not have to guess.

### N4 (Low): Two documentation records are stale
- `docs/adr/README.md:84`, the ADR-0086 index row, still says "ships the skills (frontmatter folded into `metadata`)". The code now drops the keys Cline rejects. ADR-0086 itself (`:69-70`) and the CHANGELOG (`:24`) were corrected; this index row was not.
- `README.md:466` says "`0.63.0` — **committed on branch feat/cline-plugin-v2, not yet merged or pushed". The tree is uncommitted (`git status` shows M/A/?? entries), so that claim is false today. It becomes true only once the commit is made.

### N5 (Low, predates this branch): The fallback MCP template pins the main checkout
- `adapters/cline/mcp.json` hardcodes `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/bin/skill-search-mcp`, and `mcp_row add` merges it unchanged (`install.sh:64`, `mcp_row.py:37-44`). A `--file-hooks` install from any other checkout, this worktree included, therefore points the MCP row at the main checkout.
- The HEAD installer did the same, so this is not new. I list it because the plugin path (`mcp_config()`) now resolves the root correctly, and the fallback is the only remaining machine-pinned path.

### N6 (Low): Coupling in `mcp_config()`
- `agent_plugin.py:66` hardcodes `"command": "bash"` and ignores `.mcp.json`'s `command` (currently `/bin/bash`). If `.mcp.json` ever changes its interpreter, the generated `mcp.json` would keep running `bash` with the new args.
- `test_manifest_and_mcp_point_at_this_checkout` pins `bash`, so the test would not catch that drift.

## Checked and sound
- `ENFORCER_LEDGER=0` gates `_append_offer` (`enforcer.py:1552-1553`), which is the enforcer's only ledger write site (`:1586`). The flag is documented in `AGENTS.md:85`, `docs/runtime-flags.md:17` and the CHANGELOG. `test_enforcer_ledger_switch` passed for both values.
- `lane()` matches the live naming: both `…__get_skill_d998a651` and `…__search_skills_4d64eb2e` map to the right lanes, and the test passed.
- `doctor.py` runs `agent_plugin.py check`, which is read-only (`stale()` only reads).
- The installer's plugin mode removes only shims that carry `SHIM_MARK` (`install.sh:70`). `mcp_row remove` deletes only a row whose first argument ends in `/bin/skill-search-mcp`.

## Not re-verified
- M2, M3, M4, M5, L4–L8 and L10 from the prior report. They were outside this task.
- The IPC overhead behind H1, on a long transcript.
- Whether a hub session starts Agent Plugin MCP servers.
- `tests/test_cline_bridge_modes.py`, `tests/test_cline_installer.py` and `tests/test_sibling_installers.py`. I read none of them closely except `test_cline_installer.py`, and I ran none of them.
- `driftcheck.py`. I did not run it, so whether the stale ADR index row (N4) trips any driftcheck rule is unverified.

## Recommended actions, in priority order
1. N1: add a marker guard to `sync()` and move the installer's `AGENT_DIR` guard ahead of the loader write.
2. H3 residual: stamp `sub` on the `search` lane in `ledger.py`.
3. L9 regression: make the test parse the generated frontmatter as YAML and assert that every metadata value is a string; refuse metadata shapes that cannot be quoted safely.
4. M1 edge case: use `meta["userRunSpan"] === 0`.
5. N2 and N3: render the exact hashed tool name in plugin mode and the plain name in file-hook mode.
6. H2 nit: normalise the env value with `.strip().lower()`.
7. N4: correct the ADR index row and the README "committed" claim.

## Unresolved questions
- Does any machine still run a Cline build older than 3.0.69 through `--file-hooks`? If so, N2 is live.
- Does `analyze.py` already exclude `search` rows by some other signal? If it does, the H3 gap only affects the raw counts.
