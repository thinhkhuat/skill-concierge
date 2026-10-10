# Code review: OpenCode v2 live fixes (uncommitted, v0.65.1, ADR-0089)

Date: 2026-10-09 (Asia/Saigon). Reviewer: code-reviewer subagent. Read-only lane: no repo files edited. The only write is this report.

## Scope

- Files reviewed (working tree against HEAD): `adapters/opencode/install.sh`, `adapters/opencode/plugin/index.ts`, `scripts/doctor.py`, `hooks/scripts/enforcer.py`, the engine's `skill_search/skills_discovery.py`, `tests/test_opencode_adapter.py`. New files: `tests/test_opencode_plugin.py`, `tests/opencode_plugin_harness.mjs`, `tests/test_opencode_install_dedupe.py`.
- Reference: `docs/adr/0089-opencode-v2-live-fixes.md`. Also checked: the captured OpenCode v2 docs in `plans/261009-1026-opencode-v2-fix/_RESEARCH_ARTIFACTS/` (plugins, skills, mcp-servers), the live `~/.config/opencode/opencode.json` (read only), `~/.config/opencode/plugin/context-injector.ts` (read only), and today's OpenCode rows in the real ledger (read only).
- How things were run: a copy of the working tree without `.git`, in a throwaway `$TMPDIR` folder. Every installer run used its own `XDG_CONFIG_HOME`, with `SKILL_CONCIERGE_VENV` pointing at a missing path and `SKILL_CONCIERGE_LOG` pointing at a temp folder. Nothing touched port 49374, `~/.config/opencode`, `~/.claude/skills` or the real ledger.

## Overall assessment

The six fixes do what ADR-0089 says, and the main paths are sound:

- The engine change is minimal.
- The legacy-copy retirement cannot follow a symlink and cannot delete anything that is not byte-identical to a repo skill.
- Every plugin handler still fails open.

Nothing found is Critical. The weak points:

- The de-duplication rule removes a foreign plugin entry when that entry is written as a relative, `~/` or `file://` path. Demonstrated below.
- The legacy copies are retired only if they match the current repo's version of each skill.
- The installer will point OpenCode at whatever copy ran it last, including a temporary Claude Code cache folder.
- Several tests are weaker than they look. One is flaky, one cannot catch the regression it names, and four fail inside the real checkout today.

## Test run (as requested)

`python3 -m pytest -q tests/test_opencode_plugin.py tests/test_opencode_install_dedupe.py tests/test_opencode_adapter.py`

- **Inside the real checkout:** `4 failed, 22 passed`. All four failures are `test_opencode_install_dedupe.py` installer tests. The installer refuses to run: `!! .claude-plugin/plugin.json says v0.65.1 but HEAD carries v0.65.0.` (see M4).
- **In a copy without `.git`:** `26 passed in 63.66s`.
- **ADR claim "four of its five tests fail on the 0.65.0 plugin": verified.** I put HEAD's `index.ts`, `install.sh` and `doctor.py` into the copy and re-ran. Result: `8 failed, 2 passed`. All four failing plugin tests fail on the old code, and `test_blocklisted_skill_is_denied_only_that_call` passes on it. The installer and doctor tests also fail on the old code, except the lookalike negative control.
- **Related suites:** `test_enforcer_selftest`, `test_doctor_selftest`, `test_cline_agent_plugin`, `test_foreign_scope_completeness` and `test_no_undefined_names` gave `47 passed`.
- **Other checks:** `scripts/driftcheck.py driftcheck.json` exits 0. All four installer heredocs compile under `/usr/bin/python3` (3.9.6).

## Critical

None found.

## High

None found.

## Medium

### M1. De-duplication removes a foreign plugin entry written as a relative, `~/` or `file://` path

**Where:** `adapters/opencode/install.sh:126-137`, `:144-150`

- `is_skill_concierge()` calls an entry "ours" if the path ends in `adapters/opencode/plugin` and `Path(p)` does not exist. That path is resolved against the installer's current folder.
- OpenCode resolves relative plugin paths "from the config file containing the entry" (captured plugins doc). It also accepts `file://` URLs. The skills doc says `~/` paths resolve from home.
- So the following are all judged "dangling" and replaced by this checkout's entry:
  - a valid foreign relative entry;
  - a `file://` or `~/` entry;
  - an entry on an unmounted volume.
- The first match is overwritten in place (`plugins[ours[0]] = ...`) with no message. Only the second and later matches print `-=`.

**Demonstrated:**
- Config: `plugins` held a relative entry `./<subdir>/acme/adapters/opencode/plugin` and a `file:///nonexistent/acme/adapters/opencode/plugin` entry.
- The relative folder existed next to `opencode.json`, with a `package.json` named `acme-opencode`.
- The installer was run from another folder.
- Result: `"plugins": [{"package": "<this checkout>"}]`. The acme plugin vanished silently. A backup file exists, but nothing tells the user.

**Impact:** The path suffix is unusual, so this is narrow. It is still a yes to "can it remove an entry that is not ours".

**Fix:**
- Before classifying, normalise each entry: strip `file://`, expand `~`, and resolve relative paths against `Path(cfg_path).parent`.
- Treat a path as dangling only if that resolved path does not exist.
- Print the entry being replaced in the first slot too.

### M2. Legacy copies from an older plugin version are never retired, and doctor then warns forever with a fix that cannot work

**Where:** `install.sh:232-238`, `doctor.py:2244-2246`

- Retirement requires `(d / "SKILL.md").read_text() == want.get(name)`, meaning the current repo's text.
- The old installer synced copies to the repo text of the day it last ran. Since the adapter was added (`d91fd40`), `skills/` has already changed once (`db91b7c`, v0.64.1).
- A user who ran the 0.65.0 installer and upgrades after any later edit to a skill therefore keeps every stale copy in `~/.claude/skills`. That is the duplicate-listing bug #2 this release is meant to cure.
- The message for those copies is wrong: "it differs from the repo copy (remove it by hand if unwanted)" makes an untouched old copy sound like a user edit.
- The marker survives, so doctor's "old skill copies still in ...: run adapters/opencode/install.sh" stays WARN. Re-running the installer never clears it.
- The same permanent WARN also follows from the designed case of a copy the user really edited. Probe: a legacy marker with one kept name gives a doctor WARN that the installer cannot fix.

**Fix:**
- Compare against every historical version of each `SKILL.md`, not just the current one. For example, ship a small list of hashes, or have the installer match against `git log` blobs when run from a checkout.
- Word the doctor finding so that kept copies point at removing them by hand, not at re-running the installer.

### M3. Running the installer from any other copy re-points OpenCode at that copy, including a short-lived Claude Code cache folder

**Where:** `install.sh:144-150`

- This is by design ("keeps exactly one entry, pointing at the copy it runs from"). But the original incident was an agent running the installer inside `.../plugins/cache/skill-concierge/skill-concierge/0.64.0/...`.
- With 0.65.1, the same action silently swaps the workbench entry for the versioned cache folder. The plugin then loads that copy's hooks, through `resolvePluginRoot` -> `__dirname/../../..`.
- When Claude Code updates and garbage-collects that version folder, OpenCode loses the plugin. Doctor run from the workbench will WARN "missing", but nothing stops the swap.

**Fix:** Refuse, or require `--root`, when `$ROOT` contains `/plugins/cache/`. Alternatively, keep an existing entry that points at a live git checkout and print a warning instead of replacing it.

### M4. Installer tests depend on the developer's git state and the real HOME

**Where:** `tests/test_opencode_install_dedupe.py:27-37`

- The tests run the real `install.sh` from the real checkout. Step 2's git gate refuses whenever `plugin.json` differs from HEAD, so the suite is red in the normal "bump, test, commit" order. Today: 4 failures.
- Step 6 runs the real `scripts/doctor.py` with the real `HOME`. That is not hermetic, and it is most of the 60 s run time.

**Fix:** Either:
- export the tree into `tmp_path` (like `_export_to`) and run the installer there; or
- add a test-only switch that skips the git gate and the doctor call.

### M5. The plugin test for "refused call not logged" is flaky

**Where:** `tests/test_opencode_plugin.py:126-127`

- The assertion fixes the order of two ledger rows written by separate detached `python3` processes (`runLedger` -> `spawn(..., detached)`). They can land in either order.
- Reproduced: 3 rounds x 12 parallel runs gave **5 failed / 31 passed**, with `At index 0 diff: ('child', 'child') != ('s1', None)`. Serial runs: 20/20 passed.

**Fix:** Compare `sorted(...)` or a set.

### M6. The child-session test cannot catch a regression that logs a turn row for a child

**Where:** `tests/test_opencode_plugin.py:113-114`

- The "no turn row" check reads the ledger stub log right after node exits, without waiting. The ledger write is detached, so a wrongly written row usually lands after the check.
- Mutation run: I moved `runLedger({hook_event_name: "UserPromptSubmit"...})` above `if (child) return;` in `index.ts`. `test_subagent_child_session_gets_no_doctrine_menu_or_turn` still passed 5/5.
- The enforcer assertion catches the more common regression, because the enforcer runs synchronously. The ledger half of fix #4 is not pinned.

**Fix:** Call `logged("ledger.py", wait_for=1)` with a short deadline and assert it is still empty. Better: add a sentinel top-level session in the same run and wait for its row.

### M7. Subagent scoping depends on a race the plugin cannot see

**Where:** `index.ts:222-235`, `:258`

- **What happens when the lookup is late or fails.** If `ctx.session.get` has not resolved by the first `context` call, the child is governed as top level: it gets the doctrine without `agent_id`, a menu, and a turn row. `doctrineDone` then pins that for the session. The ADR documents this fallback.
- **How strong the evidence is.** Fact: one live child session (11:29:38 today) shows no child rows in the ledger, so the lookup landed in time there. Inference: the ADR says an *awaited* `session.get` deadlocks, so `get` probably waits on something the hook holds. How long it waits under load, or with a slow first model call, is unmeasured.
- **Probe results with the harness.** I gave `get` a 200 ms delay and called `context` at 20 ms. The child got `['SKILL-FIRST doctrine', 'MENU for: count files']` plus a turn row. A rejected lookup gave the same result.
- **What is missing.** No telemetry records how often the fallback fires.

**Fix:** Add a cheap field to the turn row, for example `parent_lookup: "pending"` when `!parentOf.has(sid)`, so the rate becomes measurable. Also consider checking whether the `context` event itself carries the session or agent identity.

## Low

- **L1. The installer drops plugin `options`.** `install.sh:148` rewrites the entry to `{"package": plugin_dir}`, which erases any `options` on our own entry on every run. The plugin entry shape `{package, options}` is documented. Probe: `{"package": R, "options": {"x":1}}` became `{"package": R}`. The plugin reads no options today, so the impact is nil now. The old code left an existing entry untouched.
- **L2. A malformed legacy marker crashes the installer after the config is already written.** `install.sh:223`, `:229`. A marker that is a JSON list (`AttributeError: 'list' object has no attribute 'get'`) or has non-string names (`TypeError ... 'PosixPath' and 'int'`) aborts step 4 with exit 1. By then step 3 has written `opencode.json` and the skills are copied, but the reindex and verify steps never run. Path traversal names (`../..`, `/etc`) are safe: their content never matches a repo skill, so they are only listed as "left in place" (probe confirmed). Fix: validate `isinstance(old, list)` and keep only `str` names that are in `want`.
- **L3. A null `skills` key fails the install.** `install.sh:151-153`. `"skills": null` raises `skills is NoneType, not a list`, because `setdefault` does not replace an explicit null. `"plugins": null` behaves the same way (existing behaviour). Treating `None` as `[]` is safe.
- **L4. A legacy folder that is a symlink to the new owned folder makes the installer delete its own fresh copies.** `install.sh:221-242`. In that contrived case (`skills -> skill-concierge-skills`), both markers are the same file. Step 4 copies the skills, then "retires" them all, and verify fails (exit 1, probe L4). Fix: skip retirement when `legacy.resolve() == dest.resolve()`.
- **L5. Doctor reports OK on an empty skills folder.** `doctor.py:2241-2243`, `:2252`. The check is only `is_dir()`, yet the OK detail says "skills present". Probe: an empty `skill-concierge-skills/` gives `ok | ... skills present`.
- **L6. Doctor and the installer disagree on what counts as a copy.** `doctor.py:2227-2238`.
  - Doctor counts copies by path suffix only. A lookalike plugin, which the installer keeps on purpose (`test_installer_keeps_an_unrelated_plugin_at_a_lookalike_path`), gives a permanent "2 skill-concierge plugin entries ... run install.sh" WARN that the installer cannot clear (probe confirmed).
  - The `skills` check is an exact string compare: a hand-written `~/.config/opencode/skill-concierge-skills` WARNs.
  - A `skills` value that is a string containing the path passes as OK, because of the substring `in` (probe confirmed).
  - Fix: share one classifier with the installer.
- **L7. Turn rows are lost in a few cases** (`index.ts:242-244`, `:257`, `:273-276`):
  - When two prompts are admitted before one model call, only the second gets a turn row and a menu. Probe: `turns: [('s', 'second ask')]`.
  - A prompt aborted before any model call gets no row.
  - Turn logging now also depends on `event.system` being an array.
  - The old prompt-hook logging had none of these losses. Menu timing is unchanged from 0.65.0 (it was already pushed at the next model call), so `delivery: "steer"` prompts behave as before. For queued prompts, if OpenCode fires the `prompt` hook at queue time, the menu lands in the running turn. That was equally true before. This is an open question, not verified.
- **L8. Some per-session maps grow without limit.** `index.ts:216-221`. `parentOf` and the existing `doctrineDone` grow for the life of the service. A `pendingPrompt` entry for a session that never reaches a model call also stays. About 100 bytes per session, so negligible unless the service runs for months.
- **L9. The `<system-context>` strip never eats user text, but has edges.** `index.ts:182`. The regex is anchored at the start and lazy. Probes:
  - A block that is not at the start is kept.
  - An unclosed tag the user typed is kept.
  - A block that is the whole prompt gives no turn and no menu (correct).
  - A block whose body contains a literal `</system-context>` leaks the rest of the block into the ranked prompt.

  `context-injector.ts:70-75` emits a bare `<system-context>` with no attributes, so the match is right for the plugin it targets.
- **L10. Duplicate plugin copies outside the global `opencode.json` go unseen.** Neither the installer nor doctor looks at a global `opencode.jsonc`, project configs, or `~/.config/opencode/plugins/` package folders. OpenCode merges all of these, so a duplicate copy there is invisible. This scope predates the change.
- **L11. Some comments are stale.**
  - `doctor.py:2190-2195` and `:2205` still say "re-rooted plugin skills under ~/.config/opencode/skills/".
  - `install.sh:107-108` says "Everything else is preserved except the plugins array", but the `skills` array is now written too.
  - `install.sh:22` and step 6 do not verify the `skills` registration or the single entry.
- **L12. The new adapter test is not hermetic.** `tests/test_opencode_adapter.py:226` asserts `Path.home()/".config"/...`. With `XDG_CONFIG_HOME` set, it fails, together with the existing `test_opencode_roots_default_on_and_scopes_present`. It inherits the existing pattern.
- **L13. A successful native `skill` activation has not been shown to log under the new gate.**
  - The new gate at `index.ts:328` now also covers the `auto` ledger row; before, it covered only the echo.
  - Fact: the 11:28-11:30 `search` and `get_skill` rows show that `status === "completed"` arrives on this hook.
  - Unverified: there is no OpenCode `auto` row after the fix (the only two are from before it). The `result.metadata.error` clause is not exercised by any test.
  - One live successful `skill` call would close this.

## Edge cases found while scouting

- **The engine change is safe for other harnesses.**
  - `OPENCODE_CONCIERGE_ROOT` sits behind `OPENCODE_ROOTS` (`skills_discovery.py:177`) and is last in `SKILL_DIRS`. Under first-writer-wins, it can only add names no earlier root holds.
  - `_scope_for` (`:1031`) checks it only after every other personal root, and paths are not resolved before scoping.
  - No other harness's scope or ordering changes. Turning `SKILL_OPENCODE_ROOTS` off still drops all three roots.
  - Under Claude Code, the rows are `opencode-personal`, which is foreign, so they appear only in the annex. That is the point of fix #2.
- **The enforcer twin set** gains the owned folder (`enforcer.py:244`, `:636`). This is consistent with discovery.
- **`doctrine.py` honours the OpenCode `agent_id`.** Fed `{"hook_event_name":"SessionStart","session_id":"ses_abc","agent_id":"ses_abc"}` with `SKILL_CONCIERGE_HARNESS=opencode`, it printed nothing (rc 0), as `_is_subagent` (`doctrine.py:115-129`) requires.
- **Retirement safety holds:**
  - It refuses symlinked entries (`setup2 -> repo/skills/setup` was kept).
  - It refuses folders with extra files.
  - A real folder whose `SKILL.md` is a symlink to the repo file is removed. `rmtree` unlinks the link, and the repo file was confirmed intact.
  - `shutil._use_fd_functions` is True on both Python 3.12.11 and 3.9.6.
- **Re-running the installer changes nothing:** the second run gave an identical `opencode.json`, "0 added, 10 kept, 0 pruned".
- **Bad configs fail cleanly.** A missing `opencode.json` is created with both keys. JSONC, `plugins` as a string, and a top-level list all exit 1 with the file left unchanged.
- **The live state matches the ADR:**
  - The live config holds exactly one plugin entry plus the `skills` entry.
  - Doctor's OpenCode row reports `ok` against it.
  - From 11:27 today, ledger `q` values no longer start with `<system-context>`.

## Positive observations (risk calibration only)

- Every handler has its own outer try/catch. `lookUpParent` catches both a synchronous throw and a rejection, so there is no unhandled rejection. `pendingPrompt` is consumed once per admission, so no double menu is possible: the hooks are synchronous and JS runs on one thread.
- `write_registry` still refuses to write if the file changes while the installer runs, and keeps a backup.

## Recommended actions (in priority order)

1. M1: resolve relative, `~/` and `file://` entries the way OpenCode does before calling one dangling, and print what the first slot replaced.
2. M2: retire legacy copies by matching against historical versions, and fix the doctor message for copies that must be removed by hand.
3. M3: guard against running from `*/plugins/cache/*`.
4. M4-M6: make the installer tests independent of git state and HOME, sort the ledger rows in the flaky assertion, and wait before asserting that a row is absent.
5. M7: record a lookup-pending marker so the fallback rate can be measured.
6. Then L2, L3, L5 and L6 (one shared classifier), and L11's comments.

## Plan / ADR follow-ups

- ADR-0089 decisions 1-6 are present in code. Decision 1's wording ("whose directory no longer exists") is implemented relative to the installer's current folder, not to the config's folder (M1).
- The ADR does not mention the M2 and M3 behaviours. Both are worth a line in its Consequences, or should be fixed before the commit.

## Metrics

- Type coverage: not applicable. `index.ts` is untyped (`any`) and there is no tsconfig, so no typecheck was run.
- Test coverage: not measured.
- Lint issues: not run separately. `test_no_undefined_names` (pyflakes) passed.

## What I did not check

- No live OpenCode run, by instruction. Every OpenCode runtime claim beyond the ledger rows and the captured docs is the ADR's evidence, not mine.
- Whether OpenCode fires the `prompt` hook at queue time or at dequeue time (L7). Not verified.
- Whether `context` also fires for hidden title or compaction calls with the same `sessionID`. If it does, they would take the turn's menu, as in 0.65.0. Not verified.
- One disclosure: early on I ran `git status --short` twice. Git may refresh `.git/index` stat data when it can take the lock. No content changed, but strictly that is an index write. Everything else was `git diff`, `git show` to stdout or temp files, and `git log`.

## Unresolved questions

1. Was the live blocklist-refused call's shape `status: "error"`, or `status: "completed"` with `result.metadata.error`? The tests pin only the first.
2. Should a copy-swap (M3) ever be allowed without `--root`? This is your call. I recommend refusing for cache paths.

Status: DONE_WITH_CONCERNS
