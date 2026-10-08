# Code review: chore/chisle-audit-cuts (db91b7c, v0.64.1)

Reviewer: code-reviewer subagent, read-only. 2026-10-09 01:46 (Asia/Saigon).
Range: `main..chore/chisle-audit-cuts`, one commit `db91b7c`, 91 files, +1237 / -4375.
Worktree: `/Users/thinhkhuat/.worktrees/skill-concierge/chisle-cuts`.

## Verdict

I found no undeclared runtime behaviour change in the per-turn hooks, so there are no Critical
or High findings. Every behaviour difference I measured is either declared in CHANGELOG [0.64.1]
or happens only on malformed input. One Medium finding: the release docs this commit says it
fixed now contradict the `driftcheck.json` change in the same commit. Six Low findings are
listed below.

## Method and evidence

- Full suite on the branch: `1116 passed in 193.04s`. Run with `SKILL_CONCIERGE_LOG` pointed at a
  temporary directory; the real ledger file's size was checked before and after and did not change.
- For comparison, the full suite on a `git archive main` export: `3 failed, 1100 passed`. The
  failures were `test_installer_write_discipline`, `test_port_env_guard` and a
  `test_owner_jev_relay` connection reset. These are probably environmental (the export has no
  `.git`); I did not investigate further, and they say nothing about the branch.
- `python3 -m pyflakes` on all 43 changed or added Python files: no output on the branch. The same
  run on main found one unused import (`doctrine.py:414`) and one unused variable (`analyze.py:459`);
  the commit removed both.
- `scripts/driftcheck.py driftcheck.json`: `IN SYNC`. `check_mcp_env_parity.py`: OK on both trees.
- **Enforcer A/B test (old file from `git show main` vs new file).** 15 prompts × 14 configurations,
  output compared as the JSON written with `ENFORCER_LEDGER=defer` (the injected text plus the offer
  row, with `t`/`embed_ms`/`qdrant_ms` removed). Configurations covered:
  - live retrieval;
  - the embed service down (`SKILL_OWNER_EMBED_PORT=4999`) and the embed call timing out
    (`ENFORCER_EMBED_TIMEOUT=0.00001`);
  - the Qdrant index down (`SKILL_QDRANT_URL=http://127.0.0.1:4998`);
  - `ENFORCER_MULTI_INTENT=1` (one prompt really produced `n_intents=2`);
  - `SKILL_CONCIERGE_HARNESS` set to each of dsh, cline, opencode, zcode, omp, codex, commandcode;
  - DSH with a nonexistent `SKILL_DSH_HOME`;
  - the Jev router on, aimed at a refusing loopback endpoint.

  Result: `diffs 0` in every configuration. The bands covered were offer, fallback/embed_down,
  fallback/embed_timeout, fallback/qdrant_down, harness_skip, consult_route, negation,
  selfref_skip, the short-prompt drop and the slash-command drop. Exit code was 0 throughout.
- **Python 3.9 (`/usr/bin/python3`, 3.9.6).** On main, `import enforcer` and `import ledger` both
  fail with `TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'`. On the branch:
  every hook parses with `ast.parse(feature_version=(3,9))`; the enforcer self-test passes; and
  enforcer (offer, embed_down and Jev URLError legs), doctrine, ledger and skill_guard all run with
  exit 0. The declared fix is real.
- **ledger.py A/B.** 8 events (turn, manual+sub, Skill+sub, OMP `read skill://`, search+sub,
  get_skill, OpenCode get_skill, cline turn) under no harness override, dsh and omp: rows identical
  apart from `t`.
- **doctrine.py A/B.** 28 environments. The only differences are the declared ones:
  `SKILL_CONCIERGE_HARNESS=opencode|open-code` and the `CLAUDE_PLUGIN_ROOT` markers `/.cline/`
  and `/.opencode/`. `cmd` and `command-code` are unchanged.
- **check_mcp_env_parity.py A/B.** 9 changed-descriptor cases: an extra key, a differing
  `SKILL_SERVER_RECORDS` per descriptor, a missing dsh file, a missing codex file, and multiple
  failures at once. Return code and stdout identical in all 9.

## Critical

None.

## High

None.

## Medium

### M1. The versioning docs contradict the `driftcheck.json` change in the same commit
- `driftcheck.json` now mirrors root `package.json` **and** `adapters/opencode/plugin/package.json`
  (CHANGELOG: "both now move with every release").
- `AGENTS.md:58` still says to bump four files, "AND root `package.json` … so its version must stay in
  lockstep **even though driftcheck does not regex it**". That last clause is false after this commit,
  and the OpenCode `package.json` is not in the list.
- `CLAUDE.md:10` gives the same four-file list.
- `AGENTS-ONBOARDING.md:72` and `:87` say "the four manifests together". The CHANGELOG says this
  commit fixed "four manifests" statements.
- `docs/caveats.md` ("bump every manifest listed in AGENTS.md → Conventions") and `README.md:521`
  ("the exact list is in AGENTS.md") point readers at that incomplete list.
- Impact: someone following the documented release steps leaves the OpenCode manifest stale. That
  is the exact drift this commit fixed (0.62.0). `openwiki_parity_guard.py` runs the full driftcheck,
  so the commit is denied, but the docs send the releaser the wrong way first.
- Fix: list five manifests in `AGENTS.md:58` and `CLAUDE.md:10`, drop the "driftcheck does not
  regex it" clause, and change "four" to "five" in `AGENTS-ONBOARDING.md`.

## Low

### L1. The CHANGELOG cites an audit folder the commit does not contain
`CHANGELOG.md:10`: "Findings and one disposition line per finding: `plans/261009-0102-chisle-audit/`".
The folder is missing from the branch, but `plans/` is tracked (401 files) and not ignored. It exists
only untracked in the main checkout. Commit it, or drop the pointer.

### L2. "The self-test sat failing on main" does not hold for this commit's base
`CHANGELOG.md:19` and `tests/test_builtin_selftests.py:4` say the enforcer self-test "failed on main
(missing `opencode-personal` scope)". On the base commit (`692cab1`, v0.64.0) `enforcer.py --selftest`
prints `enforcer --selftest OK` (I ran it). The 0.64.0 entry itself (`CHANGELOG.md:133`) says 0.64.0
fixed that. Reword to "failed from 0.62.0 until 0.64.0".

### L3. caveats §3 still describes the old fallback
`docs/caveats.md:64-66` says the enforcer "falls back to mandate-only" when the owner is down or slow.
The enforcer docstring updated in this commit (`enforcer.py:22-27`) and `_fallback`
(`enforcer.py:3190-3196`) serve the Jev verdict first, then the named-route hits, and only then
MANDATE-ONLY. The A/B test confirms the code behaves the same as before; only the doc lags.

### L4. A doctor helper now has no production caller
`scripts/doctor.py:1868` `_zcode_installed_path()` is now called only by
`tests/test_owner_cutover_tooling.py:281,294`, because `check_zcode` reads `_zcode_record()` directly.
Either point the tests at `_zcode_record()` and delete the wrapper, or keep it and note that it is
test-only.

### L5. The SessionStart self-heal hooks now depend on a sibling module without a guard
`hooks/scripts/auto_reindex.py:29-30`, `auto_flywheel.py:35-36` and `auto_overrides.py:34` import
`selfheal` at module top, outside any `try`. Before this commit these hooks needed only stdlib to
load. If a copy ships without `selfheal.py` (for example a hand-copied hook), the hook exits non-zero
with a traceback instead of failing silently. Every installer exports the whole tree, so the risk is
low, and I found no case that triggers it. It is a new failure mode for the repo's fail-silent hook
rule all the same.

### L6. Small behaviour changes in offline scripts that the CHANGELOG does not declare
- `scripts/calibrate_jev_gate.py` `cmd_live`: the eager `enf = load_enforcer()` is gone, so the
  enforcer now loads lazily inside `live_catalog()`. That call sits in `try … except Exception`
  (`:714-718`). A broken enforcer import now prints `(live catalogue unavailable: <Type>)` and
  carries on; before, it crashed at the top of `live`. Harmless, possibly better, but not declared.
- `scripts/flywheel.py:234` `print_status`: the old `"PARTIAL…" if gen or err else "no-op"` became
  an unconditional "PARTIAL". The two differ only when a manifest's `totals` holds non-integer
  values (for example `error: null`), which `write_run` never writes.
- `scripts/flywheel_llm.py:297` docstring: "Skills that no longer `needs_work` are skipped" suggests
  a re-check during the run. `needs_work` is evaluated once, up front (`:298`). That matches the old
  per-generator behaviour, because each skill's check reads only its own cache and corpus entry.
  Only the wording is off.

## Checked and found equivalent (no finding)

**`hooks/scripts/enforcer.py`**
- `_has_skill_md`: same roots for each harness; OSError and ValueError still return True. For DSH,
  the old `_DSH_HOME.exists()` precheck is subsumed, and `_DSH_HOME` is always a `Path`
  (`enforcer.py:630-632`).
- `_tail_lines`: byte-identical logic for `_jev_context` and `_jev_history`.
- `_prob`: same range and NaN check.
- `_intent_plan`: `_intent_clusters`, `_qualifying_intents` and `_multi_intent_gate` are pure
  (`:2836-2885`), so computing clusters once is equivalent. The ledger's `n_intents` equals the old
  `min(len(qual), MAX_INTENTS)`.
- `_fallback`: same reason strings and the same `embed_ms`/`qdrant_ms` kwargs on all three outage
  legs.
- `_atop` → `top`: `cands` is not reassigned between them (`:3229-3290`).
- Removed `UNDER_*` constants: no remaining reference anywhere in the repo or the rest of the
  workbench (rg).
- `_owner_tier(rep)`, `_route_of(max_nodes)`, `_jev_direct_url` defaults: every caller already
  passed the arguments that remain.
- The `_jev_direct_url` noted change is a no-op in production. With `ENFORCER_JEV_CC_URL=""` the old
  code substituted the TypeSafe URL and then refused it for endpoint `cc` (`JEV_EP_HOSTS` at
  `:1600-1601`). It differs only when `ENFORCER_JEV_URL` is a loopback address.

**Other hooks and scripts**
- `ledger.py` `_log`: key order and rows identical (A/B above).
- `skill_names.py` parameter removal: no caller passed the removed arguments. `canonical()` already
  rebuilt the aliases on every call.
- `skill_exclusions.py`: when the `ledger` import fails, `GET_TOOLS`/`_NAME_KEYS` are `()`.
  `str.endswith(())` is False, so the echo is silently skipped and nothing crashes. Declared in the
  CHANGELOG. ledger now loads on 3.9, and `tests/test_skill_exclusions.py` runs this under
  `/usr/bin/python3`.
- `flywheel_llm.run_batch`: the merged except tuple drops `urllib.error.URLError`, but URLError is
  an OSError subclass. `live_skills(catalog)` keeps first-name/first-description semantics, and the
  `trigger_filter.all_descriptions` rewrite keeps first-alias-wins. `TRIGGERS_FILE =
  build_triggers.OUT` reads the same `SKILL_TRIGGERS` env.
- `flywheel.py`: `read_manifest()` covers the old try/except shapes.
- `doctor.py`: the single settings read gives the same findings for unreadable, list-shaped and
  mid-iteration-failure settings.
- `keep-on`/`blocklist` `reconcile`: same prefixes (blocklist keeps `"stripped"`).
- `analyze.py` `_window` and `header()`: same output.

**Adapters**
- Codex backstop: unreachable on main. `ENABLED_BEFORE=0` is set only together with
  `PLUGIN_INSTALLED=1`, and the pre-mutation guard exits on exactly that pair.
- Command Code mod: same `runLedger` call for slash prompts, then continue.
- DSH patch loop: same marker order. The heredoc passes pyflakes after removing `json, os`.
- Cline `run()`: all five call sites match the new signature.
- DSH unlazy bridge: DSH's own presets read `agent.session.header.cwd`
  (`~/.dsh/profiles/dsh-tui/node_modules/@deepseek-harness-tui/dsh-tui/presets/liangshen/skill-search.mjs:108`),
  so the fix reads the right field.
- OMP `skillNameFromPath` was unused on main.
- All five changed `.ts` files parse with esbuild, and all `install.sh` files pass `bash -n`.

**Deleted files**
- No code, hook, settings, adapter, `setup.sh`, `bin/` or skill reference remains to
  `migrate_qdrant_to_local.py`, `embed_server.py`, `bin/embed-shim` or
  `archive_qdrant_collection.py`. What remains are comments, ADRs and the container *name*
  `skill-concierge-embed-shim` used by doctor's revived-container check.
- The archive `~/_ARCHIVE/skill-concierge-retired-scripts-20261009/` holds all 4 files plus their
  3 tests. The `/jev` relay properties are still covered by `tests/test_owner_jev_relay.py` and
  `tests/test_jev_relay_timeout.py`.

**Docs spot-check (matches code)**
- `SKILL_TOP_K` 6 (`server.py:83`, `.mcp.json:10`); keep-on seed 31; five MCP tools.
- Ten skills, each with a bare `name:` and `user-invocable: true`.
- The defaults and files for the four newly documented flags (`enforcer.py:802`,
  `doctrine.py:52`, `skills_discovery.py:200,443`, `engine_env.py:25,30`).
- The skill-usage-audit `--until` hint was removed correctly: the script has no `--until`.
- `codex plugin remove` and `codex plugin marketplace remove` exist (`codex plugin --help`).

## Not checked

- I did not run TypeScript type-checking (`tsc`) on the adapters; only esbuild parsing and the
  existing node-driven tests.
- I did not do a live run in any harness other than calling hook scripts directly.
- I did not compare live `doctor.py` output old vs new: the copy from main would resolve ROOT to
  the temporary export.
- I did not run the auto_* hooks: they spawn real reindex and flywheel processes.
- I read only the changed parts of README/openwiki prose, not every line.

## Unresolved questions

- M1: should OpenCode's `package.json` become a formal fifth "manifest" in the Versioning rule, or
  stay a driftcheck-only mirror? The fix wording depends on that choice; I recommend listing it.
- L1: is `plans/261009-0102-chisle-audit/` meant to be committed with this branch?
