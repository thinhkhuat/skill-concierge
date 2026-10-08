# Chisle audit: the uncommitted Cline rework (branch feat/cline-plugin-v2)

Date: 2026-10-08. Scope: `git diff HEAD` plus the untracked Cline files in
`/Users/thinhkhuat/.worktrees/skill-concierge/cline-v2`. Lens: is each mechanism the simplest thing that
meets its stated need? I stopped at the first rung of the ladder that held for each one. The Cline platform
facts in ADR-0086 are taken as given. Read-only audit: this report is the only file written.

Requirements I kept fixed (no proposal below breaks them): the prompt is preserved; the menu reaches the
first model call inside Cline's 3 s limit; a deny refuses only that one call; one ledger turn row per run;
Cline-legal skill frontmatter; Command Code stays first with its 5.5 s span.

## Findings, biggest saving first

### 1. The file-hook fallback (about 590 lines kept, about 210 of them new in this diff)

**Rung that fails: "does it need to exist?"**

Where it lives:
- `adapters/cline/skill-concierge.cline-hook.cjs` (261 lines).
- `adapters/cline/hooks/*.cjs` (4 shims, 38 lines).
- `adapters/cline/mcp.json` (20 lines), plus its block in `scripts/check_mcp_env_parity.py`.
- The `--file-hooks` branch, `remove_plugin` and the mode parsing in `adapters/cline/install.sh:17-21, 42-52, 67-83, 109-118, 137-140`.
- The shim branch of `check_cline` in `scripts/doctor.py:2158-2172, 2207-2221`.
- The `add` path of `adapters/cline/mcp_row.py:36-44`.
- `tests/test_cline_bridge_modes.py` (118 lines), the Cline cases in `tests/test_adapter_exclusion_echo.py:78-98`, and `tests/test_cline_installer.py` (56 lines).

What the fallback does today (Fact, from ADR-0086 Context items 1 and 4, and from install.sh's own
header, lines 19-21): on Cline 3.0.69 and later, the UserPromptSubmit and TaskStart file hooks run
detached and Cline discards their output. So the fallback delivers no menu and no doctrine. Its
PreToolUse deny maps to `stop`, which ends the whole run. That breaks the refuse-only-this-call
requirement the owner chose.

It is also probably harmful on those builds (Inference). The detached `prompt_submit` process still runs
`enforcer.py`, and that writes an offer row for a menu the model never saw. In ledger terms, every such turn
looks like a dodge.

The only audience it serves well is a Cline build that is older than plugin support. This machine runs
3.0.70. The ADR verifies no older build and no hub host. On the VS Code extension hub, no plugin runs, and
the ADR does not say whether file hooks deliver there.

**Cut (option A, recommended): delete the fallback vehicle.** Keep only what plugin mode needs to retire
an existing install:
- `remove_shims`, with the shim names inlined.
- The `remove` action of `mcp_row.py`.
- One doctor finding for leftover shims.

Saving: about 590 lines across code, tests, descriptor and docs. Doing this also removes the duplicated
helpers in finding 8.

Risk of A: a user on a pre-plugin Cline build, or on a hub host where file hooks do deliver, loses the
ledger row and the "not for" echo. It also reverses ADR-0086 decision 6, so it is the owner's product call.

**Cut (option B, the floor if the fallback stays): revert the fallback to its HEAD behavior.** Change only
its header comment. This means dropping:
- the new `TaskStart.cjs` and `PreToolUse.cjs` shims;
- `taskStart` and `preToolCall` in the bridge (`.cjs:113-174`) and their dispatch lines (`.cjs:248-249`);
- `tests/test_cline_bridge_modes.py`;
- the two new names in `SHIMS` (`install.sh:42`) and `CLINE_SHIMS` (`doctor.py:2155`);
- their two `driftcheck.json` entries.

Saving: about 210 lines. Why it is safe: neither new shim has live evidence on any Cline build (the ADR and
`GATES.md` record none). On 3.0.69+, TaskStart's doctrine output is discarded, and the PreToolUse deny
ends the run, which is the behavior the owner rejected. Risk of B: on an untested older build, a blocklisted
skill would no longer be stopped by the fallback. HEAD never stopped it either.

### 2. The new `--print-for` mode in `doctrine.py` (27 lines)

**Rung that holds: "already in this codebase".**

Where: `hooks/scripts/doctrine.py:286-312` and `adapters/cline/skill-concierge.cline-plugin.ts:189-192`.

`doctrine.py` already prints the harness-adapted body as `hookSpecificOutput.additionalContext`. The
plugin already has a parser for exactly that field (`additionalContext()`, `.ts:103-106`). The plugin's
`ENV` already sets `SKILL_CONCIERGE_HARNESS=cline` (`.ts:52`). So the save-and-restore of the harness
variable inside `--print-for` does nothing that the environment does not already do.

Cut: delete the `--print-for` block. Have `doctrineRule()` return
`additionalContext(await run("doctrine.py", { hook_event_name: "SessionStart" }, HOOK_BUDGET_MS * 3))`.
Change `tests/test_cline_plugin.py:201-204` to parse that JSON instead.

Saving: 27 lines of Python, plus one CLI mode nobody else uses.

Risk: the rule text then carries the JEVD-ENV warning whenever `_jevd_warning()` fires. That matches what a
Claude Code SessionStart injects, so it is parity rather than a regression. The empty payload has no
`agent_id`, so the subagent suppression cannot trigger.

### 3. A hand-kept Agent Plugin MCP template plus a parity check

**Rung that holds: "already in this codebase".**

Where: `adapters/cline/agent-plugin/mcp.json` (21 lines), `scripts/check_mcp_env_parity.py:73-81`, and one
`driftcheck.json` entry.

`agent_plugin.py` already generates `plugin.json` from the SSOT. It can generate `mcp.json` the same way,
from `.mcp.json`. The steps are:
- take `mcpServers["skill-search"]`;
- substitute `${CLAUDE_PLUGIN_ROOT}` (the module already does this for skills, `agent_plugin.py:31,66`);
- set `type: "stdio"` and `command: "bash"`;
- pop `SKILL_TRIGGERS` and `SKILL_SERVER_RECORDS`;
- add the `$schema` URL.

The OpenCode plugin already derives its server from `.mcp.json` the same way
(`adapters/opencode/plugin/index.ts:84-99`).

Saving: about 30 lines and one file, for about 6 new lines in `plan()`.

The generated form also closes a drift class that the parity check cannot catch. That check only flags keys
that are *extra* or *different* in the template. A key that `.mcp.json` gains later and the template
lacks passes silently. The older `adapters/cline/mcp.json` already shows this: it lacks `SKILL_DSH_ROOTS`
and `SKILL_OPENCODE_ROOTS`, which `.mcp.json` has.

Risk: low. `test_manifest_and_mcp_point_at_this_checkout` (`tests/test_cline_agent_plugin.py:60-71`)
already checks the generated output.

### 4. Folding Claude-only frontmatter keys into `metadata`

**Rung that fails: "does it need to exist?"** (the folding, not the copies; copies are required, see
"Already minimal").

Where: `adapters/cline/agent_plugin.py:34-38` (`_scalar`), `:55` and `:60-65`, and
`tests/test_cline_agent_plugin.py:54-57`.

Nothing reads the folded values. I grepped `hooks/`, `scripts/` and the vendored engine. The only code
that touches `~/.agents/plugins` is the enforcer's existence test, `_cline_agent_plugin_skill`.
`next-skills` is read from the source repo's frontmatter, not from the copies. The insertion-index logic at
`:63-64` is the fiddliest code in the module.

Cut: write only the allowed keys and drop the rest.

Saving: about 13 code lines and 4 test lines.

Risk: if a later Cline build shows `metadata.argument-hint` to the model or the user, that hint disappears
from Cline. That is unverified either way, and no requirement depends on it.

### 5. Migration code for the unmerged first attempt

**Rung that fails: "does it need to exist?"**

Where:
- `adapters/cline/agent_plugin.py:104-105`, which unlinks a symlinked destination;
- `tests/test_cline_agent_plugin.py:89-95`;
- the `[ ! -L "$AGENT_DIR" ]` clause at `adapters/cline/install.sh:96`;
- the `_installed/local/*` stale-copy scan at `install.sh:104-108`.

Both guard against artefacts of branch `cline/0a565`, which used `cline plugin install` and a repo-root
link. That branch is not merged into `main` (`git branch --contains` lists only itself). On this machine,
`~/.agents/plugins/skill-concierge` is already a real directory (`test -L` returned NOT_LINK).
`~/.cline/plugins/_installed/local/` holds only `fast-jev.bundle.ts-67aae2a24e2c`, so no stale copy remains.

Saving: about 15 lines.

Risk: another machine that ran the unmerged branch would keep a stale link or copy. I know of none.

### 6. `scripts/doctor.py` loads `agent_plugin.py` through `importlib` (about 6 lines plus one import)

**Rung that holds: "already in this codebase".**

Where: `scripts/doctor.py:37` and `:2193-2201`.

`agent_plugin.py check <dest>` already exists, and it prints one `stale: <path>` line per drifted file.
`install.sh:134` uses it. Doctor already has a `_run()` subprocess helper (`doctor.py:217-218`).

Cut: call `_run([sys.executable, <agent_plugin.py>, "check", str(CLINE_AGENT_DIR)])` and report the first
`stale:` line. Then `plan()` and `stale()` stop being an import API that doctor depends on, and doctor
runs one code path, the same one the installer uses.

Saving: about 4 lines and the `importlib.util` import.

Risk: none I can see. The module is stdlib-only, so a subprocess call behaves the same as the in-process
load.

### 7. Small items in the plugin and the generator (about 5 lines in total)

- **`fire()` and `fireFile()`** (`.ts:78-91`). Two functions where one would do. Use
  `fire(path, args = [], payload?)` and pass `script(name)` at the five call sites. Saving: about 3 lines.
  Risk: none.
- **The manifest key reordering** (`agent_plugin.py:74`). It rebuilds the dict only so that `version`
  lands third. JSON consumers ignore key order, so `manifest["version"] = version` is enough. Saving: one
  convoluted line becomes one plain line. Risk: none; the test reads keys, not their order.

### 8. Helpers duplicated between the bridge (`.cjs`) and the plugin (`.ts`)

What is duplicated:
- the last-JSON-line parsers (`.cjs:72-81` against `.ts:93-106`);
- the self-heal list (`.cjs:63`, `.ts:53`, and also `adapters/opencode/plugin/index.ts:77`);
- the spawn helpers;
- the deny fallback message (`.cjs:171`, `.ts:240`).

**Do not share them across the two files.** Sharing would need the `.ts` module, running inside Cline's
jiti sandbox, to import a `.cjs` helper. That is unverified there, and it would couple the primary vehicle
to the fallback. Finding 1 option A removes the duplication outright.

If the fallback stays, there is a cheaper cut inside the bridge itself. This diff added two more hand-rolled
"parse the last JSON line" copies (`.cjs:134` and `.cjs:166`) next to `additionalContext()`. One shared
`lastJson()` inside the bridge saves about 6 lines.

## Already minimal (keep as is)

- **The dual enforcer pass, and `ENFORCER_LEDGER`** (`.ts:162-175`; `enforcer.py:1552-1553`).
  - Running the preview only *after* the full pass misses its deadline cannot fit. Python start-up plus
    about 0.3 s, added after a 2.7 s wait, overruns Cline's 3 s limit. So the two passes must start
    together.
  - Removing the full pass would drop Command Code's whole-shelf ranking.
  - Streaming an early result out of one enforcer run would be a far larger change.
  - `ENFORCER_LEDGER` is two lines of code. The existing knob that could silence the row is
    `SKILL_CONCIERGE_LOG`. Redirecting it would also move the ledger that the chain hint reads
    (`enforcer.py:957` `LEDGER`, read at `:1301` by `_last_used_skill`). That would change the preview's
    menu, so a dedicated flag is the smallest correct switch.
  - The flag-table row in `AGENTS.md` and `docs/runtime-flags.md` is required by the repo's flag drift
    check, not ceremony.
- **The `runs` map and its cap of 32** (`.ts:158-173`). State must survive across the several
  `beforeModel` calls of one run, keyed by `runId`. The cap is one line. A single-slot variable would save
  one or two lines, but it bets that one plugin instance never serves two top-level runs at once. Nobody has
  verified that for multi-task hosts, so it is not worth the bet.
- **The Agent Plugin copies themselves.** No copy-free route meets the requirements:
  - Eight of the ten skill bodies contain `${CLAUDE_PLUGIN_ROOT}`, which Cline does not expand.
  - Nine skills carry `argument-hint`, which Claude Code reads at the top level.
  - Every skill carries `user-invocable`, which the Cline loader rejects.

  A symlink or a source-side rename would either break Claude Code or show the model unexpanded paths.
  `sync` writes only changed files, and `check` gives drift detection, so the copy machinery is already
  lean.
- **`mcp_row.py` as its own file.** It replaces a `python3 - <<PY` heredoc. The owner's rules forbid piping
  a heredoc into `python3 -`. It also adds the `remove` action that plugin mode needs. Its backup,
  invalid-JSON refusal and "not ours, leave it" check protect the user's settings from data loss, so they
  stay. If the fallback goes (finding 1 option A), only its `add` branch goes.
- **`tests/cline_plugin_harness.mjs` (25 lines).** It is the smallest way to drive a TypeScript plugin from
  pytest. An inline `node -e` string would only move the same lines into Python.
- **The enforcer's Cline lane** (`_cline_agent_plugin_skill`, `enforcer.py:337-352`, and the two gate
  edits) and the harness-message regex line. Each is the minimum that serves its stated need.
- **The plugin hooks `beforeModel`, `beforeTool` and `afterTool`** (`.ts:208-266`). Each branch maps to a
  stated requirement, and none can be removed without losing one.

## Test volume

The new tests total about 490 lines (`test_cline_plugin.py` 217, `test_cline_agent_plugin.py` 129,
`test_cline_bridge_modes.py` 118, harness 25). They cover about 480 new lines of code. Each plugin and
generator test maps to one verified requirement, so the volume is proportionate.

The cuts follow from the findings above:
- `test_cline_bridge_modes.py` goes with finding 1;
- the doctrine test changes with finding 2;
- the link test goes with finding 5;
- four assertions go with finding 4.

Wall time is a separate, optional point, not over-engineering. Three plugin tests take 2.9 to 4.4 s each
(measured, `--durations`). The cause is `wait()` (`.ts:108-111`): it leaves its race timer pending, which
holds the Node harness open for about 2.7 s after the hook has returned. Clearing the timer would cut
about 8 s from the Cline test files. In Cline, the pending timer is harmless.

## Concerns found while auditing (correctness, not bloat)

1. **`tests/test_cline_installer.py` fails on this branch** (Fact; I ran it: `1 failed, 23 passed`).
   - The error is `KeyError: 'skill-search'` at `tests/test_cline_installer.py:53`.
   - The test runs `install.sh` with no flag, which is now plugin mode. Plugin mode removes the
     `skill-search` row instead of merging it, so the row the test expects is never written.
   - Gate G2 (whole suite) will fail until the test either passes `--file-hooks` or asserts the plugin-mode
     outcome. The `remove` path also writes through `safe_write`, so the symlink-and-mode property this test
     guards applies to it too.
2. **The Cline doctrine may name a tool that does not exist in plugin mode** (Inference, unverified).
   - `doctrine.py:247` rewrites the search tool to `skill-search__search_skills`.
   - ADR-0086 records that in plugin mode the tool is `skill-concierge_skill-search__search_skills_<hash>`.
   - Whether the model maps one name to the other was not checked live.
3. **The fallback probably writes offer rows for menus that were never delivered**, on Cline 3.0.69 and
   later (Inference from ADR-0086 Context item 1; see finding 1). Any fallback-mode Cline ledger data would
   inflate the dodge count.

## What I did not check

- I ran the four Cline test files only. I did not run the whole suite, `driftcheck`, or a live Cline
  session.
- I did not verify whether Cline's plugin sandbox can import a `.cjs` module (relevant only to sharing
  helpers, which I advise against).
- I did not verify whether file hooks deliver context on the VS Code hub host or on pre-3.0.69 builds.
  Finding 1 option A depends on that.
- I did not read the README, CHANGELOG or openwiki diffs for prose bloat. This audit covers mechanisms.

## Unresolved questions for the owner

1. **Keep the file-hook fallback?** ADR-0086 decision 6 keeps it. My pick is option A, delete it, because
   on every Cline build anyone has verified it delivers neither menu nor doctrine, and its deny ends the
   whole run. If you want it kept for unverified older builds, take option B (revert it to HEAD behavior).
2. **Should the Cline doctrine name the hashed plugin-mode tool, or a prefix the model can match?** That
   needs one live check.
