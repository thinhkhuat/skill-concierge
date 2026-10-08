# Code review: Cline plugin rework (ADR-0086), branch feat/cline-plugin-v2, uncommitted

Reviewer: code-reviewer subagent, 2026-10-08. The review is read-only, apart from this report and the incident restore described in section 0.
Snapshot: the files as they stood at about 19:50. The main session edited `agent_plugin.py`, `doctrine.py`, `doctor.py`, `install.sh`, the plugin TS and the tests while this review ran. Every line number below refers to the version current at 19:50.
Ground truth for Cline: the installed runtime `@cline/{core,agents}` 0.0.92 and `@cline/cli-darwin-arm64` 3.0.70 under `~/.bun/install/global/node_modules/@cline/`. Each runtime quote below was copied from `rg -a -o` output.

## 0. Incident caused by this review (restored)

At 19:48 I ran `pytest tests/test_cline_agent_plugin.py` while the main session was removing the symlink guard from `agent_plugin.sync()`. The old test `test_sync_replaces_a_link_left_by_an_earlier_install` linked `dest` to the real repo ROOT. With the guard gone, `sync()` wrote through that link into the worktree:
- It overwrote all 10 `skills/*/SKILL.md` files with the Cline-converted copies. The Claude-only keys were removed, and `$CLAUDE_PLUGIN_ROOT` was replaced by `/Users/thinhkhuat/.worktrees/skill-concierge/cline-v2`.
- It created `plugin.json`, `mcp.json` and `.skill-concierge-managed.json` at the worktree root.

Restore: `git status` had shown those 10 files clean before the run. I rewrote each one from `git show HEAD:<path>` and moved the three root files and backups of the damaged copies to `~/_ARCHIVE/skill-concierge-cline-rework-scratch-20261008/review/damage-backup/`. Afterwards `git status -- skills/` showed no changes. The main session confirmed the restore. It fixed the cause: `sync()` now refuses a symlinked destination (`agent_plugin.py:98-103`), and the test that linked ROOT is gone. I ran no tests after that point. Test results in this report come from reading the code, not from runs.

## Critical

None found.

## High

### H1. A hook that overruns 3 s fails the whole run and restarts the shared plugin sandbox. The 2.7 s budget leaves about 0.3 s for transport.
- `skill-concierge.cline-plugin.ts:36` sets `HOOK_BUDGET_MS = 2700`. `:207` starts the clock (`const started = Date.now()`) only when the hook begins running inside the sandbox. `:219` then waits up to `HOOK_BUDGET_MS - (Date.now() - started)` for the menu.
- The host's 3000 ms timer runs from before the IPC send (`core/dist/index.js`, class `Uc.call`). On expiry the host shuts the sandbox process down and rejects the call: `d.timeout=setTimeout(()=>{let c=this.clearPendingRequest(o);if(!c)return;this.shutdownProcess(c.child).catch(()=>{}),c.reject(Error(`${this.processLabel} call timed out after ${n.timeoutMs}ms: ${e}`))},n.timeoutMs)`.
- No layer catches that rejection:
  - The plugin composer: `beforeModel:async(n)=>{let r=n.request,o;for(let s of t){let i=await s.beforeModel?.({...n,request:r});`.
  - `createRuntimeHooks`.
  - `@cline/agents` `prepareModelRequest`: `for(let o of this.hooks.beforeModel){let s=await o({snapshot:this.snapshot(),request:n});`.
  - The error therefore reaches `execute`'s catch, and the run ends as `failed`. The same holds for `afterTool` in `executePreparedTool`, where the loop over `this.hooks.afterTool` sits outside the `try`.
- The 300 ms margin has to cover three costs:
  - JSON IPC of the whole transcript twice on the way in (`snapshot.messages` and `request.messages`), and of the full list on the way back.
  - Event-loop delay from the other plugins in the same sandbox. `ps()` builds one `Uc` for all `pluginPaths`, and this machine has eight more plugins under `~/.cline/plugins/_installed/`.
  - The python spawns in `startRun`.
- Failure scenario: a long session (several MB of tool output) where the full Jev pass is slow. The first model call of a new turn exceeds 3 s and the user's turn fails. Every plugin in the sandbox, other vendors' plugins included, loses its in-memory state.
- Status: inferred from the minified code and not reproduced live. The ADR's claim "Every hook answers within 2.7 s and fails open" covers only time inside the sandbox.
- Fix: measure the IPC cost on a large transcript, or cut the wait to about 1.5–2.0 s. The preview usually lands in about 0.3 s, so returning sooner costs little.

### H2. Plugin mode removes the only vehicle that works when the session runs in a hub. Doctor then still reports OK.
- `install.sh:102-103` (`remove_shims`, `mcp_row remove`) runs on every default install. The installer never checks whether this machine's sessions actually load code plugins.
- ADR-0086 (Consequences) and `docs/caveats.md` §26 admit that the CLI attaches to the VS Code extension's hub whenever that sidecar runs, and that the hub runs no plugin (`configExtensionCount: 0`). The workaround `CLINE_SESSION_BACKEND_MODE=local` is not set in `~/.config/harness-env.sh` (rg found no match) or anywhere else the installer writes.
- Failure scenario: VS Code is open and the user runs `cline`. The session runs in the hub, so there is no menu, no doctrine, no ledger and no blocklist deny. The global MCP row has also been removed. Whether the hub starts Agent Plugin MCP servers is UNVERIFIED. If it does not, the user also loses `search_skills`/`get_skill`. Before this change, file hooks at least wrote the ledger, the echo and the deny.
- `scripts/doctor.py:2171-2232` reports `OK` in this state, because it checks files on disk, not whether the plugin can run.
- Fix (pick one):
  1. Export `CLINE_SESSION_BACKEND_MODE=local` through `harness-env.sh`, recorded with its revert path. This is the one shared env home.
  2. Keep the PostToolUse and PreToolUse shims in plugin mode, guarded so they stay quiet when the plugin is active.
  3. Have doctor say plainly that hub sessions are ungoverned.

### H3. Subagent skill uses are logged as main-session uses (an ADR-0020 regression).
- `afterTool` (`skill-concierge.cline-plugin.ts:243-264`) has no `isSubagent` check, and its payload (`:251-255`) carries no `agent_id`. `ledger.py:135` sets `sub = bool(d.get("agent_id"))`, which marks subagent `auto`/`get_skill` rows so that the chain-hint reader and `analyze.py` can leave them out.
- Failure scenario: a `spawn_agent` subagent or teammate calls `skills` or `get_skill`. The row lands without `sub: true`, under the subagent's `conversationId` (or the parent's, UNVERIFIED). Skill uptake and conversion are inflated, and mined chains are polluted.
- `beforeModel` does exclude subagents (`:212`). The ADR line "Subagents … write no turn row" is true for turn rows, but subagent tool rows are not stamped.
- No test covers `afterTool` with `parentAgentId` set.
- Fix: in `afterTool`, add `agent_id: snapshot.agentId` to the payload when `isSubagent(snapshot)`.

## Medium

### M1. In yolo mode the "prompt" is Cline's completion reminder.
- `findPrompt` (`:119-133`) takes the newest user text message that lacks `displayRole: "system"`.
- In `@cline/agents` `execute`, the input is pushed first, then `let t=this.getCompletionToolReminderMessage();if(t)await this.addUserReminderMessage(t);`. `addUserReminderMessage(e,t={}){let n=he("user",[{type:"text",text:e}],{...t,userRunSpan:0})` sets no `displayRole` for that reminder.
- The reminder exists only when `requireCompletionTool` is true, which needs `submit_and_exit`. The CLI preset `yolo:{… enableSubmitAndExit:!0 …}` enables it, and modes `"act","plan","yolo"` are accepted, including for schedules.
- Failure scenario: every yolo or scheduled turn runs the enforcer on `[SYSTEM] This run is not complete until you call one of these terminal completion tools: …`. That text is logged as the turn's `q`, and the menu is placed after the reminder. The real prompt is never logged.
- Fix: skip user messages whose `metadata.userRunSpan === 0`, or skip text starting with `[SYSTEM] `. Add a test.

### M2. The menu is never stored in the transcript, which breaks provider prompt caching every turn (inference).
- `withMenu` (`:175-185`) puts the block into the request only. The core `prepareTurn` doc says returned messages "do not replace the canonical runtime transcript".
- Run N sends `[…, promptN, MENU_N, assistant…, tool…]`. Run N+1 sends `[…, promptN, assistant…, tool…, promptN+1, MENU_N+1]`. The shared prefix ends at `promptN`, so all of run N's assistant and tool content must be cached again at every new turn, and turn latency grows with session length.
- Fix: keep a `promptId → menu` map for the session and re-insert every past menu at its prompt, so the prefix stays the same. Alternatively, insert only at the tail and leave earlier runs untouched.

### M3. The model and the ledger can disagree about which menu was offered.
- `:221` uses `state.value || state.preview`. The offer row comes only from the full pass (the preview runs with `ENFORCER_LEDGER=0`), but on a slow Jev turn the model chose its first action from the preview.
- Call 2 of the same run then gets a different menu. A whole-shelf "no fit" `SKILL-CHECK` can replace a ranked preview after the model has already acted on that preview.
- When the full pass returns an empty string (an enforcer crash, the 20 s SIGKILL, or `ENFORCER_AUTHORIZED_SKIP=0` on a `jev_skip`), the preview stays on every call, against the doc's "later calls carry the full menu once it lands".
- Hit@k joins on `(sid, q)` will credit or blame the full menu for decisions made on the preview. The epoch note in the CHANGELOG does not mention this.

### M4. The live install points at the worktree.
- `~/.cline/plugins/skill-concierge.ts` currently re-exports `/Users/thinhkhuat/.worktrees/skill-concierge/cline-v2/adapters/cline/skill-concierge.cline-plugin.ts`, and `~/.agents/plugins/skill-concierge/mcp.json` runs the worktree's `bin/skill-search-mcp`.
- Removing the worktree after merge breaks every Cline session: the plugin import fails and the MCP server fails to start. This lasts until `install.sh` is run again from the main checkout.
- Doctor run from the main checkout only says "not this checkout".
- Fix: re-run the installer from `main` before deleting the worktree, and note this in the merge checklist.

### M5. A sandbox restart loses run state and runs setup again.
- The sandbox restarts on any plugin's hook timeout (H1) or after `CLINE_PLUGIN_IDLE_TIMEOUT_MS` (default `pF=1800000`). An idle restart mid-run needs a 30-minute stretch with no hook call, for example a long `run_commands`.
- On restart the host re-initialises the plugin (`Ki` matches "Unknown sandbox plugin id:", then `o()` initialises again). That clears `runs` (`:157`) and calls `setup` again (`:196-203`).
- Effects:
  - The next `beforeModel` of the same run calls `startRun` again, writing a duplicate `turn` row and a second full offer row.
  - The self-heal batch and `agent_plugin.py sync` fire again.
  - The in-flight full enforcer child of the dead sandbox loses its 20 s SIGKILL timer.

### M6. The docs no longer match the code (main-session edits after 19:36).
- `docs/adr/0086-…md:49` still says `doctrine.py --print-for cline`. `--print-for` is gone, and the plugin now calls `doctrine.py` with SessionStart output (`:187-190`).
- `docs/adr/0086-…md:67-69`: "the `.mcp.json` env minus two machine paths … held by `check_mcp_env_parity.py`" and "Claude-only keys move into `metadata` as strings". The code now copies the full `.mcp.json` env (`agent_plugin.py` `mcp_config`) and drops the Claude-only keys (`convert_skill`, `:34-49`). The parity block is gone.
- `CHANGELOG.md:24`: "(Claude-only frontmatter folded into `metadata`, which Cline requires)". This is now false, and Cline does not require it.
- `README.md:374` and `docs/repository-layout.md:12` name an `agent-plugin/` templates folder. That folder no longer exists; the manifest is now `adapters/cline/agent-plugin.json`. The driftcheck "doc-referenced path exists" check may fail on this. UNVERIFIED: I did not run driftcheck.

### M7. Doctor can report OK or WARN falsely.
- False OK, plugin mode:
  - Doctor does not check for a leftover `skill-search` row in `cline_mcp_settings.json`. That row means two skill-search servers.
  - It does not check for a stale `_installed/local` copy named `skill-concierge`. The sandbox's `duplicate_plugin_override` keeps whichever loads last.
  - It does not check the Cline version or the hub situation (see H2).
  - The installer's warning about stale installed copies was removed in this rework.
- False OK, file-hook mode: a generated Agent Plugin left beside the shims, which again means two MCP servers, is not flagged.
- False WARN: `doctor.py:2186` reads the loader with `from\s+"([^"]+)"`. The installer writes the path with Python `json.dumps`, which has `ensure_ascii=True`. A checkout path with non-ASCII characters (a Vietnamese folder name, for example) is therefore stored as `\uXXXX` escapes. The comparison fails, and doctor reports "points at …, not this checkout" for a correct install.

## Low

- L1, `agent_plugin.py:98-121`, concurrent session starts: two Cline sessions that start together both run `sync` (the setup `fire`). They share the same `*.tmp-skill-concierge` name, so one `tmp.replace()` raises `FileNotFoundError` and that process stops before pruning and writing the marker. There is a short window in which a SKILL.md is truncated while Cline reads it. The marker write at `:118` is not atomic.
- L2, `agent_plugin.py:85-95` and `:114`: paths from the marker are never validated. An entry like `../../x` in `.skill-concierge-managed.json` would unlink outside `dest`. This needs a corrupted or edited marker.
- L3, `install.sh:108-110`: file-hook mode writes `~/.cline/hooks/{UserPromptSubmit,PostToolUse,TaskStart,PreToolUse}.cjs` without checking for the mark and without a backup. The header (`:23-24`) claims "Touches only skill-concierge-owned files". On this machine the operator's own hooks have no extension or end in `.mjs`, so nothing is clobbered today. `TaskStart.cjs` and `PreToolUse.cjs` are new targets.
- L4, `install.sh:47-52`: `--no-mcp` was removed. Any caller still passing it now exits 1 with "Unknown option". The CHANGELOG does not mention the removal.
- L5, `install.sh:109`: `sed "s|…|$BRIDGE|g"` breaks on a path containing `|`, `&` or `\`, and a `"` breaks the generated `require("…")`. This was already the case before the change. The loader path is safe because it goes through `json.dumps`.
- L6, `install.sh:76-83`: `remove_plugin` runs `rm -rf "$AGENT_DIR"`, which also deletes any file the operator added inside the generated folder.
- L7, `enforcer.py:339-352`: `_cline_agent_plugin_skill` checks only `~/.agents/plugins`, which is Cline's default `df()`. Agent Plugins loaded from explicit `pluginPaths` are dropped from the offer. The path-traversal check (`"/"`, `".."`) is adequate. The fail-open branch returns True only on an `OSError` that `is_file()` does not swallow.
- L8, `enforcer.py:1652`: the anchored `You are Cline, an AI coding agent\b` would skip a real prompt that starts with that sentence, for example a user pasting the system prompt for review. In practice this is negligible.
- L9, Agent Plugin copies: `metadata` is copied verbatim. Cline rejects any non-string metadata value (`Frontmatter metadata value '…' must be a string.`), a description over 1024 characters (`nue=1024`) and a name over 64 characters. A future `version: 1.0` would therefore silently drop that skill in Cline. No test parses the output as YAML or checks these limits.
- L10: a mid-run user message (`consumePendingUserMessage`) gets no menu and no turn row, because the run already has state. A run started with no new input (`continue(void 0)` / `run("")` in core) would log the previous prompt again. UNVERIFIED whether a top-level run ever takes that path.
- L11, `doctrine.py:249`: the Cline doctrine tells the model to call `skill-concierge_skill-search__search_skills_<suffix>`, with a literal `<suffix>` placeholder. The model has to match it to the hashed tool name itself.

## Checked and found sound

- The enforcer runs in the session's working directory. The sandbox's `initialize` runs `if(n.cwd)try{process.chdir(n.cwd)}catch{}`, so project-scoped checks such as `Path.cwd()/.cline/skills` and project isolation see the session's workspace.
- The sandbox loads the `plugin` named export (`exportName||"plugin"`), and the loader re-exports both `default` and `plugin`.
- `runId` is a fresh `de("run")` on every `execute`, so run IDs are not reused. A missing `runId` collapses to the key `""`, but `execute` always sets one.
- Tool results have role `tool` with `tool-result` parts, so `textOf` ignores them. Cline's own hook-context messages carry `displayRole: "system"` and are skipped.
- On a skipped call, Cline still calls `afterTool` with `{output:{error}, isError:true}`. The `:257` check therefore writes no row for a refused call. The `skills` tool takes the `skill` field, which matches `:232`.
- The ledger and exclusions payload shapes match `ledger.py` (`Skill`, the `skill-search__…` suffix match) and `skill_exclusions.py` (`GET_TOOLS`, `_NAME_KEYS`). The `skill_guard.py` input key is `skill`.
- `mcp_row.py` is idempotent: no backup and no write when nothing changes. It refuses invalid JSON and removes only a row whose first argument ends in `/bin/skill-search-mcp`. A top-level JSON array in the settings file would crash it with `AttributeError` (Low).
- The installer refuses an existing `AGENT_DIR` with no marker (`:96-98`), which includes a link to the repo. `sync()` now refuses a symlink. That leaves setup's `fire(... ["sync"])`, which has no installer guard, safe as well.
- Current `convert_skill` keeps each allowed key's continuation lines and drops each removed key's. The multi-line and flow-mapping cases that broke the earlier fold-into-metadata version no longer apply.

## Tests

- `tests/cline_plugin_harness.mjs` imports the plugin with Node's own TS loader, not jiti, and not through the `~/.cline/plugins` loader file. Root resolution through the loader and jiti's handling of `import.meta.url` are therefore covered only by the live run.
- The harness calls hooks in-process, so the 3 s IPC limit (H1) is never exercised. `test_slow_menu_…` asserts `first["ms"] < 2900` on time inside the sandbox only.
- No test covers subagent `afterTool` (H3), the yolo completion reminder (M1), a compacted prompt (`findIndex` −1 puts the menu at the tail), or the YAML validity and Cline limits of the generated copies (L9).
- `test_every_skill_is_generated_with_cline_legal_frontmatter` collects keys with a regex and never parses the YAML. An invalid frontmatter that keeps only allowed key names would pass.
- `test_one_turn_row_per_run_…`: `logged("enforcer.py", wait_for=2)` returns as soon as two lines exist. A regression that spawns extra passes late could slip past, but extra passes would most likely have been logged by then. Adequate.
- `test_enforcer_ledger_switch`: the pair is meaningful, because both the enforcer and the ledger honour `SKILL_CONCIERGE_LOG`.
- The new symlink test the main session describes (`test_sync_refuses_to_write_through_a_symlink`) did not exist in the file when I read it. UNVERIFIED.
- The three failures I saw at 19:48 came from the half-edited tree: `--print-for` had been removed before its tests were updated, and the symlink guard was missing. They say nothing about the final state. I did not re-run any tests.

## Recommended actions, in priority order

1. H1: cut the first-call wait, or measure IPC on a large transcript before trusting 2.7 s.
2. H2: decide how hub sessions are governed (the env export, shims kept as a guarded fallback, or an honest doctor row).
3. H3: stamp `agent_id` on subagent `afterTool` rows.
4. M1: exclude `userRunSpan: 0` reminders from `findPrompt`.
5. M6: bring the ADR, CHANGELOG, README and repository-layout into line with the current code, then run driftcheck.
6. M2 and M3: make menu placement stable across turns, and record which menu the first call actually carried.
7. M4: re-install from `main` before removing the worktree.

## Unresolved questions

- Does Cline's hub (the VS Code sidecar) start Agent Plugin MCP servers and list Agent Plugin skills? This decides whether H2 also costs the user the search tools.
- How large is the IPC overhead on a long session? A timing probe that does not modify the worktree would settle H1.
- Does a top-level Cline run ever call `continue(void 0)` or `run("")` (L10)?
- Not checked: openwiki prose beyond the `CLINE_SESSION_BACKEND_MODE` line, `tests/test_cline_installer.py` and `tests/test_sibling_installers.py` (changed during the review), and the bridge's `tool_result` path.
