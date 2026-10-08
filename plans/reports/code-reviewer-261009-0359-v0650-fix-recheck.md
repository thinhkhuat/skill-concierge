# Re-check: fixes for the v0.65.0 review (commit `fa487f4`)

- Reviewer: code-reviewer (independent, read-only; no edits, no git writes)
- Date: 2026-10-09 04:15 +07 (Asia/Saigon)
- Worktree: `/Users/thinhkhuat/.worktrees/skill-concierge/maint-int`, HEAD `fa487f4`; baseline `main` = `aa6d7c2`
- Prior review: `plans/reports/code-reviewer-261009-0335-v0650-review.md`
- Method: `git archive` of `fa487f4` and `main` into `$TMPDIR/recheck-0359/{head,main}`; every hook run used a temp
  `SKILL_CONCIERGE_LOG` and `ENFORCER_LEDGER=0`; every installer run used `env -i`, a throwaway HOME, a hermetic
  PATH of linked system tools (no `claude`/`codex`/`omp`/`opencode`/`zcode` on it), and `/bin/bash` 3.2.57.

## Verdict

The Critical fix is correct and complete. `GETAWAY_FLOOR` is exactly the value main used on that leg with the
removed variable unset. Hook output is now byte-identical to main on 14 of 14 prompt × Python pairs, the
getaway leg included. Both new guard tests fail when the bug is put back. The symlink fix behaves identically to
main in 100 of 100 sandboxed installer runs, relative links and two-link chains included. The `__main__` guard
does what it claims in both modes. Nothing blocks release. One Medium item: the undefined-name gate can skip
silently and does not cover the vendored engine. Four Low items are wording, test strength, and one residual
part of the earlier L1.

## Critical / High

None.

## Medium

### M1. The undefined-name gate is optional, and narrower than the CHANGELOG says

- `tests/test_no_undefined_names.py:9` uses `pyflakes_api = pytest.importorskip("pyflakes.api")`. Nothing in the
  repo installs pyflakes: no requirements file, no CI, and `setup.sh` has no such step. It is present in this
  machine's pyenv 3.12.11 (pyflakes 3.4.0) and absent from `/usr/bin/python3` and `~/.claude/skills/.venv`. On any
  interpreter without pyflakes, the gate that closes the Critical bug's class reports as a skip, not a failure.
- `SHIPPED` (`tests/test_no_undefined_names.py:14-15`) globs `hooks/scripts/*.py`, `scripts/*.py`,
  `adapters/*/*.py` and `skills/*/scripts/*.py`: 53 files. It leaves out 8 shipped files under
  `vendor/skill-search/` (7 in `skill_search/`, among them `server.py`, `index_owner.py` and `findability.py`, plus 1
  in `scripts/`). Today those 8 are clean: `python3 -m pyflakes vendor/skill-search/skill_search/*.py` reports no
  undefined name. CHANGELOG.md:36 still says the test "fails on any undefined name in shipped Python".
- Fix: make a missing pyflakes fail the test (or vendor a pinned check), and add
  `vendor/skill-search/**/*.py` to `SHIPPED`. Linting the vendored code does not patch it, so VENDORED.md is not
  affected. If you keep the scope, narrow the CHANGELOG wording to match it.

## Low

### L1. The new comment and the CHANGELOG name the wrong importers

- `hooks/scripts/enforcer.py:74`, `doctrine.py:48`, `ledger.py:39`: `raise  # an importer (doctor, findability,
  skill_exclusions) handles the ImportError`. CHANGELOG.md:33-34 says "(doctor, the findability sweep)".
- Fact: `scripts/doctor.py` imports none of the three modules. It only checks that `enforcer.py` exists
  (`doctor.py:2091`) and reads the findability JSON. The in-process importers are:
  - `vendor/skill-search/skill_search/findability.py:189` (enforcer; catches `Exception`, verified below);
  - `hooks/scripts/skill_exclusions.py:38` (ledger; catches `Exception`);
  - `scripts/calibrate_jev_gate.py:96`, `scripts/jev_client.py:55` (through `trigger_filter.py`) and
    `scripts/precision_eval.py:280` (enforcer; no handler, so a harness-less copy now prints an ImportError
    traceback where it used to exit 0 silently).
  - Nothing imports `doctrine.py` in-process.
- These are offline tools, and a traceback beats a silent exit. This is a wording defect only. Fix: name the real
  importers per module, or say "an importer gets the ImportError".

### L2. The prior L1 is fixed for symlinks only: a lone copy given `--root` still exits 1

- Reproduction: copy `adapters/{claude-code,omp}/install.sh` alone into a dir and run
  `/bin/bash <dir>/install.sh --root <tree>`:
  - main: `==> skill-concierge → Claude Code sync (from: …/main)`, then `SSOT version: v0.64.1` (it proceeds);
  - HEAD: `!! …/lone/lib/sync.sh is missing: this installer needs the shared helpers in adapters/lib/.`, rc=1.
- CHANGELOG.md:23-26 implies this ("exits 1, naming the path, if it is missing"), and `--root` is undocumented,
  so the rating stays Low. The case is still not named as a change from 0.64.1.
- Related, not a regression: each installer now looks up its libs from two bases. `sync.sh` comes from the
  resolved real path, but `PYTHONPATH="$SCRIPT_DIR/../lib"` (claude-code `install.sh:186`, omp `:213,:258`,
  opencode `:104,:142`, zcode `:119,:152`) still uses the unresolved symlink dir. So the OMP installer called through
  any symlink with `--root` still dies with `ModuleNotFoundError: No module named 'safe_write'`. Main dies the same
  way at the same step (identical output in all 7 symlink layouts), so the fix is complete for what it claims.
  Resolving `SCRIPT_DIR` itself would fix both lookups at once.

### L3. The new tests are weaker than the behaviour they guard

- `tests/test_installer_shared_lib.py:84-89`, the symlink test:
  - it uses an absolute symlink only, with no relative link or chain;
  - its only assertion is negative (the "is missing" text is absent), so an installer that died earlier for any
    other reason would also pass. It could assert `rc == 1` and `Unknown option: --not-an-option` instead.
- `tests/test_getaway_leg.py:30`: it asserts `startswith("SKILL-CHECK:")` but does not pin the floor value in the
  text (`… < floor 0.45`), so a wrong floor constant would pass. My runs below cover this by hand.

### L4. Prior-review item not addressed (not claimed by this commit)

- `plans/reports/chisle-audit-261009-0102-whole-concierge.md:48` still says "all four shipped in v0.65.0" before
  shipping. It becomes true on release.

## Informational

- **The guard change also revives one `skill_exclusions` lane (undeclared, but toward main).** With `harness.py`
  missing, the pre-fix `cd70d4f` `ledger.py` called `sys.exit(0)` at import. That killed `skill_exclusions.py`
  outright, because its `except Exception` at :39 does not catch `SystemExit`. Now `ledger` raises an ImportError,
  `skill_exclusions` falls back to `_NAME_KEYS, GET_TOOLS = (), ()`, and the `read skill://<name>` lane echoes again:
  - stripped `cd70d4f`: rc=0, 0 bytes;
  - stripped HEAD: rc=0, 380 bytes, `SKILL-EXCLUDES: …`, identical to full HEAD and full main.

  The `Skill`/`get_skill` lane stays silent in that broken-install state. This is a fair outcome, but no document
  states it.
- `hooks/scripts/enforcer.py:44` `import tempfile` is flagged unused by pyflakes, but the exec'd
  `tests/enforcer_selftest.py` needs it (:277, :636, :1002, :1134). It is not an undefined name, so the gate
  ignores it. A later "unused import" cleanup would break `--selftest`; `test_enforcer_selftest.py` would catch that.

## Verification of each claimed fix

### 1. Getaway leg: `floor` → `GETAWAY_FLOOR` (`enforcer.py:3143`)

- **Same value as main.** Main `enforcer.py:3250` set `floor = _floor_for(cands[0][0]) if cands else GETAWAY_FLOOR`.
  `_floor_for` (:1266-1269) returns `_PER_SKILL_TAU.get(name, GETAWAY_FLOOR)`, and `_PER_SKILL_TAU` is `{}` unless
  `ENFORCER_PER_SKILL_TAU` is set (:1253). That variable is unset in this shell's env. With it unset, main's floor
  is `GETAWAY_FLOOR` on both branches. `GETAWAY_FLOOR` is defined identically on both sides: main :95, HEAD :105,
  `float(os.environ.get("ENFORCER_GETAWAY_FLOOR", "0.45"))`.
- **pyflakes:** `uvx pyflakes` on HEAD `enforcer.py`, `doctrine.py`, `ledger.py` and `doctor.py` reports no undefined
  names; the only report is `enforcer.py:44:1: 'tempfile' imported but unused` (see Informational). Main's
  `enforcer.py` is clean.
- **Original reproduction, main vs HEAD**, owner live on 6333/6363; `env -u CLAUDE_PLUGIN_ROOT -u
  SKILL_CONCIERGE_HARNESS SKILL_CONCIERGE_LOG=<tmp> ENFORCER_LEDGER=0 SKILL_OWNER_AUTOSTART=0`, the machine's other
  env unchanged. All 14 pairs had rc 0/0, empty stderr on both, and **byte-identical stdout**:

  | prompt | router | Py 3.12.11 | Py 3.9 (`/usr/bin/python3`) |
  |---|---|---|---|
  | cảm ơn bạn nhiều nhé, hôm nay trời đẹp quá | default | getaway, `top 0.42 < floor 0.45`, SAME | SAME |
  | thủ đô của nước Pháp là thành phố nào vậy | default | getaway, `top 0.35`, SAME | SAME |
  | what is the capital of france | `ENFORCER_JEV_ROUTER=0` | getaway, `top 0.25`, SAME | SAME |
  | hi there | off | silent (0 bytes), SAME | SAME |
  | please debug this failing pytest test in my repo | off | menu 3090 B, SAME | SAME |
  | write a Vietnamese report as a docx file | off | menu 2350 B, SAME | SAME |
  | viết giúp tôi một báo cáo tiếng Việt dạng docx | default | menu 2492 B, SAME | SAME |

  The injected text for the first prompt, on both trees: `SKILL-CHECK: full-catalogue retrieval ran (top 0.42 <
  floor 0.45); nothing cleared the floor. NO SKILL: hook-cleared is pre-authorized ONLY if …`
- **Positive control:** the same tree with `floor=floor` put back gives `rc=1`, 0 bytes of output and `NameError:
  name 'floor' is not defined` on both Pythons, so the reproduction does reach the leg.
- **The new tests fail on the bug.** In a copy with `floor=floor`, `test_getaway_leg.py` fails (`NameError` at
  `enforcer.py:3143`) and `test_no_shipped_python_references_an_undefined_name` fails (`enforcer.py:3143:68:
  undefined name 'floor'`): `2 failed, 1 passed`.

### 2. `__main__` guard (`enforcer.py:72-74`, `doctrine.py:46-48`, `ledger.py:37-39`)

- **Hook run, `harness.py` missing:** on `/usr/bin/python3` 3.9, each of the three gives rc=0, 0 bytes stdout, 0
  bytes stderr, and creates no log files. `tests/test_harness_import_failure.py` checks the same on 3.12.
- **Import:** each raises `ModuleNotFoundError: No module named 'harness'`, an `ImportError` subclass, on 3.9.
- **Findability (the motivating case):** with `harness.py` removed, `findability._load_enforcer()` returns `None`
  and the process continues; the full tree returns the module.
- **Every adapter runs the hooks as scripts** (`hooks/hooks.json:10,41,46,70`; the OMP, DSH, OpenCode, Command
  Code and Cline TS adapters spawn `python3 <script>`), so `__name__ == "__main__"` holds on every live hook path.
  The `spec_from_file_location` loaders use non-`__main__` names (`enforcer_cal`, `enforcer_jev_client`,
  `skill_concierge_findability_enforcer`), so they take the `raise` branch.
- **Mutation:** with `sys.exit(0)` only (the old form), the 3 `import` tests fail; with `raise` only, the hook-run
  tests fail for enforcer and doctrine. Both halves are pinned.

### 3. Installer symlink resolution (five installers, identical 7-line block)

- **Logic:** `while [ -L "$_self" ]` with `readlink` (no `-f`, so it works on macOS); a relative target is joined to
  `dirname` of the current link, so chains across directories resolve hop by hop. `_self` and `_link` are used
  nowhere else, and not in `adapters/lib/sync.sh`. A cyclic link cannot reach the loop: bash cannot open the script
  through one.
- **Sandbox matrix:** 5 installers × 10 layouts × 2 arg modes (`--root <tree>`, or none for zcode; `--bogus`), each
  run on HEAD and on main: **100/100 identical** after normalising tree paths, versions, SHAs, timestamps and bash
  line numbers. Identical means exit code, combined output, and the list of files written under HOME. The 10
  layouts:
  1. direct absolute path;
  2. `bash adapters/x/install.sh` from the tree root;
  3. absolute symlink;
  4. relative symlink;
  5. relative symlink invoked bare (`install.sh`) from its own dir;
  6. relative symlink invoked as `./install.sh`;
  7. a chain of two links (relative link → absolute link → real file);
  8. a chain of two relative links across directories (`c1/inst1.sh → ../c2/deep/inst2.sh → <relpath>`);
  9. a symlinked `adapters/` directory;
  10. a relative symlink reached through a symlinked directory (the `..`-logical-vs-physical case).

  Main had every helper inline, so a HEAD run that failed to find `sync.sh` would differ; none did.
- **Mutation:** with `cd70d4f`'s installers, `test_a_symlinked_installer_still_finds_the_lib` fails for all 5.
- **Limit:** in the sandbox no installer gets past its early exit: claude-code stops at "no
  skill-concierge@skill-concierge entry", codex and opencode at the missing CLI, and omp and zcode at their
  own errors. Main stops at the same points.

### 4. Self-test loaders: `globals()["_selftest"]()` (`enforcer.py:3213`, `doctor.py:2497`)

- Equivalent to the bare call: `exec(..., globals())` binds `_selftest` into the module dict.
- `enforcer.py --selftest` gives rc=0 `OK` on both 3.12 and 3.9. Doctor's self-test passes through
  `tests/test_doctor_selftest.py` in the full suite.

### 5. Wording

- `scripts/doctor.py:1247` is correct now: `scripts/calibrate_thresholds.py:53` is the remaining `SKILL_THRESHOLDS`
  reader.
- ADR-0088:56-62 and CHANGELOG.md:29-32 now describe the single-marker conflict cases and the wider
  `.commandcode` case.
- The ADR still quotes the 15-prompt lane check (ADR-0088:52), which had no below-floor prompt. Its claim is true
  now (table above), but the evidence it cites did not test the leg that broke.
- The CHANGELOG `byte-identical to 0.64.1` claim (:15) is now true for the 7 prompts tested.

### 6. Suite and drift

- Full suite in the worktree (`PYTHONDONTWRITEBYTECODE=1`, `-p no:cacheprovider`): 1451 passed, 16 failed. All
  16 (`test_jev_router.py` ×14, `test_reputation_badges.py` ×2) failed because I had exported `ENFORCER_LEDGER=0`,
  and these tests read ledger rows. Rerun without it (with `SKILL_CONCIERGE_LOG` still temp): `39 passed`. Net:
  **1467/1467**, which is 1453 + the 14 new tests.
- `GIT_OPTIONAL_LOCKS=0 git status --porcelain --ignored` gave the same 7 lines before and after: the worktree is
  unchanged.
- `driftcheck.py driftcheck.json` on the HEAD export: `IN SYNC`, rc=0.

## Not checked

- The Cline deferred path (`ENFORCER_LEDGER=defer`): running it conflicts with the "ENFORCER_LEDGER=0 for every
  hook run" rule. The fix is the same line, so it is covered by inference only.
- Jev-on English paths, to avoid metered calls. Live harness sessions in any of the eight harnesses.
- Installer stages past each early exit (CLI-gated in the sandbox). `curl | bash` / `bash -s` invocation: the
  `${BASH_SOURCE[0]}` reference precedes the new block on `SCRIPT_DIR`'s line in both versions, so behaviour is
  unchanged by inference, not by a run.
- `doctor.py --selftest` was not invoked directly; only through pytest.

## Recommended actions

1. M1: make a missing pyflakes fail the gate, add `vendor/skill-search` to `SHIPPED`, or narrow CHANGELOG.md:36.
2. L1: correct the importer list in the three comments and in CHANGELOG.md:33-34.
3. L2: optionally resolve `SCRIPT_DIR` itself, which fixes both the `sync.sh` and the `safe_write` lookups, and
   name the lone-copy `--root` change in the CHANGELOG.
4. L3: strengthen the symlink test (relative link, chain, positive assertion) and pin `floor 0.45` in the
   getaway test.

## Unresolved questions

- Should a harness-less copy keep the `skill_exclusions` `read skill://` echo it now regains (Informational), or
  stay fully silent as the prior commit made it? Product call; the current behaviour is closer to main.

Status: DONE_WITH_CONCERNS
Summary: All claimed fixes in fa487f4 are correct and change no behaviour against main. Hook output is byte-identical on 14/14 prompt × Python pairs including the getaway leg, installer runs match main 100/100 across relative links and two-link chains, and the new tests fail when the bug is put back. One Medium remains: the undefined-name gate skips silently without pyflakes and omits vendor/. Four Low items remain: importer wording, the lone-copy `--root` case, test strength, and the premature "shipped" line.
