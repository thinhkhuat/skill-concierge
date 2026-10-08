# Code review: v0.64.1 -> v0.65.0 (`main..maint/integrate`)

- Reviewer: code-reviewer (independent, read-only)
- Date: 2026-10-09 03:58 +07 (Asia/Saigon)
- Worktree: `/Users/thinhkhuat/.worktrees/skill-concierge/maint-int` (HEAD `cd70d4f`, 6 commits over `main`)
- Scope: everything in `git diff main..HEAD` (41 files), judged against CHANGELOG `[0.65.0]` and ADR-0088.

## Verdict

**Do not ship as is.** One Critical defect: removing `_floor_for` left a reference to the deleted local
`floor` in the getaway branch, so every below-floor turn the Jev router does not decide now crashes the
enforcer with `NameError`. That is every low-fit Vietnamese prompt with default flags. The declared claim
"with both variables unset, hook output is byte-identical to 0.64.1" (CHANGELOG.md:15, ADR-0088:52) is false.
The fix is one token. The other three parts (self-test move, shared installer lib, shared harness detector)
behave as declared, apart from the Low items below.

## Critical

### C1. Getaway leg crashes: `NameError: name 'floor' is not defined`

- **Where:** `hooks/scripts/enforcer.py:3141`, introduced by commit `09ba04e` (lever removal).
  ```python
  if not _hits and not _jev_rows and top < GETAWAY_FLOOR:
      _append_offer(sid, "getaway", ...)
      _authorized_skip_inject("getaway", sid, top=top, floor=floor)   # `floor` no longer exists
  ```
  The old line `floor = _floor_for(cands[0][0]) if cands else GETAWAY_FLOOR` was deleted; this use was not
  updated. The `NameError` is raised while evaluating the call arguments, so the `try` inside
  `_authorized_skip_inject` never runs. `main()`'s `except (OSError, UnicodeError, ValueError, TypeError,
  AttributeError, KeyError, IndexError, OverflowError)` does not include `NameError`, so the error escapes,
  prints a traceback and exits 1.
- **What changes:**
  1. Claude Code, ZCode and other harnesses: the `SKILL-CHECK:` authorized-skip line for the getaway leg is
     never injected. The hook exits 1 with a traceback on stderr, which Claude Code reports as a hook error.
     The `getaway` offer row is still written, because `_append_offer` runs before the crash.
  2. Cline (`ENFORCER_LEDGER=defer`): `_DEFERRED` is never written, so the `skillConciergeOffer` row is lost.
     **The ledger loses rows** on this path.
- **Reach under default flags:** getaway runs only when `_jev_rows` is empty: on non-English prompts (the
  router is English-only, `enforcer.py:2193`), with no Jev key, when Jev fails, or with `ENFORCER_JEV_ROUTER=0`.
- **Reproduction** (main and HEAD trees exported with `git archive`; the owner was running):
  ```
  P='{"hook_event_name":"UserPromptSubmit","prompt":"cảm ơn bạn nhiều nhé, hôm nay trời đẹp quá","session_id":"rv-vn","cwd":"/tmp"}'
  echo "$P" | env -u CLAUDE_PLUGIN_ROOT -u SKILL_CONCIERGE_HARNESS SKILL_CONCIERGE_LOG=$TMPDIR/x ENFORCER_LEDGER=0 \
      SKILL_OWNER_AUTOSTART=0 python3 <tree>/hooks/scripts/enforcer.py
  ```
  Observed output:
  ```
  old [cảm ơn bạn nhiều nhé, hôm nay trời đẹp quá] rc=0 out={"hookSpecificOutput": {... "SKILL-C...
  new [cảm ơn bạn nhiều nhé, hôm nay trời đẹp quá] rc=1 out= err=NameError: name 'floor' is not defined. Did you mean: 'float'?
  old [thủ đô của nước Pháp là thành phố nào vậy] rc=0 ...
  new [thủ đô của nước Pháp là thành phố nào vậy] rc=1 ... NameError
  ```
  The same happens on `/usr/bin/python3` (3.9.6), with `ENFORCER_JEV_ROUTER=0` on the English prompt "what is the
  capital of france", and on the Cline deferred path (`old rc=0 hasOffer=1`, `new rc=1 hasOffer=0`).
  `uvx pyflakes hooks/scripts/enforcer.py` flags it as `enforcer.py:3141:68: undefined name 'floor'`.
- **Why CI missed it:** 1453/1453 tests pass. No test drives `main()` into the getaway branch; the self-test
  calls `_authorized_skip_inject("getaway", top=0.30, floor=0.45)` directly (`tests/enforcer_selftest.py:197`,
  `:232`). The ADR's 15-prompt lane check (ADR-0088:52) evidently had no below-floor prompt. My own 20-prompt
  old/new comparison (Jev off) differed on exactly this one prompt and matched on the other 19.
- **Fix:** `floor=GETAWAY_FLOOR` at `enforcer.py:3141`. Then close the class of bug:
  - Add a test that stubs `_embed` and `_retrieve` to return a top score below `GETAWAY_FLOOR`, runs `main()`,
    and asserts exit 0 plus the `SKILL-CHECK:` output.
  - Add a pyflakes undefined-name gate over `hooks/scripts/*.py` and `scripts/*.py`. It must allow the two
    names the `--selftest` loaders define through `exec`: `enforcer.py:3213` and `doctor.py:2497`.

## High

None.

## Medium

None. (The `--root` regression below is undeclared, but it affects only an undocumented way of calling the
installers, so I rate it Low.)

## Low

### L1. Running an installer through a symlink or as a lone copy with `--root <checkout>` no longer works

- **Where:** `adapters/claude-code/install.sh:47-53`, `codex/install.sh:79-85`, `omp/install.sh:39-45`,
  `opencode/install.sh:34-40`. The lib path comes from `SCRIPT_DIR` and is checked *before* argument parsing
  (`while [[ $# -gt 0 ]]` at :55 / :87 / :47 / :42).
- **What changes:** in 0.64.1, a symlinked or copied installer given `--root <full checkout>` ran normally,
  because every helper was inline. In 0.65.0 it exits 1 with `<symlink dir>/../lib/sync.sh is missing`. Plain
  symlink calls *without* `--root` failed in both versions (old: Python traceback on
  `<wrong ROOT>/.claude-plugin/plugin.json`; new: the clean message, exit 1 in both), so that case is no regression.
- **Reproduction:** `ln -s <tree>/adapters/claude-code/install.sh $T/links/install.sh;
  /bin/bash $T/links/install.sh --root <tree>` with a sandbox HOME and a hermetic PATH.
  Old: `SSOT version: v0.64.1` then `!! no skill-concierge@skill-concierge entry ...` (it proceeds).
  New: `!! .../links/../lib/sync.sh is missing` (exit 1). The same holds for codex, omp and opencode.
- `--root` appears in no README, docs or openwiki page (rg), hence Low. Two ways to fix it:
  1. Resolve `BASH_SOURCE` through symlinks.
  2. Source the lib after argument parsing, falling back to `$ROOT/adapters/lib/sync.sh`.
  Otherwise, declare the change in the CHANGELOG.

### L2. The ADR describes the ledger-change class too narrowly

- ADR-0088:56 says ledger rows change only in "several env markers set at once" cases. My differential fuzz
  (14,784 env×path cases, main's three copies extracted with `ast` vs `harness.running_harness`) found 1,312
  ledger differences. These include single-env-var **path-marker conflicts**, for example:
  - `CLAUDE_PLUGIN_ROOT=/x/.claude/...` + script in `/.zcode/` or `/.dsh/`: old row stamped `zcode`/`dsh`,
    new row unstamped;
  - `DSH_SHELL=1` + script in `/.zcode/`: old `zcode`, new `dsh`.

  `tests/test_harness_detector.py` pins and annotates all of these (`cpr-claude+file-zcode`,
  `dsh-shell+file-zcode`, ...), and no live adapter produces them (DSH always sets `SKILL_CONCIERGE_HARNESS`,
  ZCode sets `ZCODE_PLUGIN_ROOT`). This is a wording defect in the ADR, not a code defect.
- In the same vein, CHANGELOG.md says the `.commandcode` marker "can change an offer row's `harness` from
  `claude` to `commandcode`". Fuzz shows it can also change `zcode`/`dsh`/`codex`/`omp`/`opencode` to
  `commandcode`, when `CLAUDE_PLUGIN_ROOT` carries `/.commandcode/` and the script path carries another
  harness's marker (30 cases, all conflicting-signal).
- Doctrine: an unknown `SKILL_CONCIERGE_HARNESS` (for example `foo`) used to block detection and render Claude;
  it now falls through to detection. This is covered by "the enforcer's answer wins" and pinned in the table
  (`explicit-foo+ompcode`), but the ADR does not name it.

### L3. A missing `harness.py` breaks the "never raises" contract of in-process importers

- `enforcer.py:66-72` calls `sys.exit(0)` at import. `vendor/skill-search/skill_search/findability.py:175-194`
  (`_load_enforcer`, documented "Returns None (never raises)") catches only `Exception`, so `SystemExit`
  escapes and ends the detached findability sweep. `scripts/calibrate_jev_gate.py:87` is exposed the same way.
- Applies only to a partial copy with no `harness.py` (git-archive caches ship it). Fix: catch `SystemExit` in
  `_load_enforcer`, or raise `ImportError` when not `__main__`.

### L4. Stale comments and records

- `scripts/doctor.py:1247`: "the same SKILL_THRESHOLDS env seam the enforcer and calibrator already use". The
  enforcer no longer reads `SKILL_THRESHOLDS`.
- `plans/reports/chisle-audit-261009-0102-whole-concierge.md:48`: "all four shipped in v0.65.0" is written
  before shipping. GATES.md G8 and G9 are still `pending`.
- ADR-0088:52 ("Hook output is unchanged ... 15 prompts") and CHANGELOG.md:15 ("byte-identical to 0.64.1") are
  false until C1 is fixed. Under RULES [28], correct them in the same change.

### L5. A generic module name, and first-import-wins

- `from harness import running_harness` uses a bare top-level name. In a process that imports enforcers from
  two checkouts, or already holds another `harness` in `sys.modules` (the engine process running findability),
  the first `harness` loaded wins. Hook processes are fresh interpreters, so they are unaffected.
- A more specific name (`sc_harness.py`) would remove the risk. Informational only.

## Checks that passed (evidence)

1. **Harness detector (item 1)**
   - Precedence in `hooks/scripts/harness.py:30-56` matches main's enforcer copy: explicit alias, then
     `OMPCODE`, then absolute `ZCODE_PLUGIN_ROOT`, then `DSH_SHELL`, then markers of `CLAUDE_PLUGIN_ROOT` then
     `__file__`, then `claude`.
   - Within one path, markers are checked in doctrine's old order (`.omp`, `.codex`, `.zcode`,
     `.commandcode`, `.dsh`/`.ohdsh`, `.cline`, `.opencode`, `.claude`).
   - Fuzz differences in the enforcer: 114, all from the declared `.commandcode` addition.
   - Live doctrine SessionStart output, old vs new on `/usr/bin/python3`: identical in 10 env setups
     (none, commandcode, `foo`, `OMPCODE`, `.codex` CPR, `DSH_SHELL`, cline, opencode, `ZCODE_PLUGIN_ROOT`,
     `.commandcode` CPR).
   - Ledger rows, old vs new: identical in 7 setups. Claude rows carry no `harness` key (`_native_harness`
     returns `""` where main returned `None`; both are falsy at `ledger.py:89` and `:45`).
   - With `harness.py` missing, enforcer, doctrine and ledger on Python 3.9 each give rc=0, empty stdout,
     empty stderr, no log dir.
   - `tests/test_harness_detector.py`: 312 passed, 77 table rows.
2. **Lever removal (item 2)**
   - No reference to `_floor_for`, `_apply_dominance`, `DOMINANCE_RATIO`, `PER_SKILL_TAU` or `_THRESHOLDS_*`
     remains outside CHANGELOG, ADRs and plans.
   - Former `_apply_dominance(shown)` site: with the ratio unset, main returned the same list, so removing it
     changes nothing.
   - Former `_floor_for` site: see **C1**.
   - Menu output old vs new matched on 19 of 20 prompts; the 20th is C1.
3. **Self-test loaders (item 3)**
   - `enforcer.py:3202-3213` and `doctor.py:2489-2497` exec the body into module `globals()`. The bodies use
     `global` and `__file__`, which still resolve to the host module.
   - The `from __future__ import annotations` in `tests/enforcer_selftest.py` rebinds an `annotations` global
     the enforcer already holds (same object).
   - A copy without `tests/` gives `enforcer --selftest` rc=2 and `doctor --selftest` rc=2, each with a
     one-line message. The normal hook path in that stripped copy is unaffected (rc=0, menu printed).
   - Old and new `--selftest` both pass. The only output difference is the dropped "gap-collapse +
     per-skill-tau (inert)" labels.
   - `tests/doctor_selftest.py` is a verbatim move plus a 9-line header (diff: `0a1,9` only).
   - `tests/enforcer_selftest.py` is verbatim except the header plus `from __future__`, and sections (5)/(6),
     which lost their dominance and tau asserts. The lone-candidate render check is kept. These edits belong to
     the lever removal, so it is not a pure move.
   - Line counts are confirmed: 4592 to 3221 and 3038 to 2529.
   - `compile()` median of 30, three runs, Python 3.12: main 17.46 / 18.34 / 17.48 ms; HEAD 10.81 / 10.65 /
     10.71 ms. No import-time cost added beyond one small sibling import.
4. **Installer lib (item 4)**
   - Ignoring comments, `_ver_ge` and `_is_own_checkout` are identical to every main copy, and `_export_to`
     matches claude-code, codex and zcode. OMP's copy differs only by the legacy prune; it is kept as
     `_omp_export_to` and is now the only export that OMP calls (`omp/install.sh:113`, `:195`).
   - `_refuse_unexportable_checkout` equals the inline blocks of claude-code, omp and zcode. Codex and opencode
     keep their own blocks.
   - 30 sandbox runs on `/bin/bash` 3.2 (5 installers × help / plain / cwd=/ / symlink / symlinked dir /
     relative path; throwaway HOME, hermetic PATH, versions normalised) gave identical output, exit code and
     written files, except the symlink cases (L1).
   - The missing-lib refusal is pinned by `tests/test_installer_shared_lib.py`.
5. **Docs (item 5)**
   - AGENTS.md, `docs/repository-layout.md`, `docs/caveats.md` §§ OMP/Command Code, `docs/runtime-flags.md`,
     `docs/epoch-watch.md` and openwiki `enforcement-gate.md` / `operations.md` match the code. I checked the
     epoch-watch `_post_json` / `_OPENER.open` / `except TimeoutError` claim at `enforcer.py:2402,2409,3089-3094`.
   - `driftcheck.py driftcheck.json` gives rc=0, "IN SYNC".
6. **Full suite:** `pytest -q -p no:cacheprovider tests` gives `1453 passed in 159.20s`.

## Not checked

- No live harness session (Claude Code, Codex, OMP, ZCode, DSH, Cline, OpenCode) was driven; hook behaviour
  was checked by direct invocation only.
- Jev-on English paths were not exercised (to avoid metered calls), so the `jev_skip` and Jev-menu paths are
  unverified here. They do not touch the changed code apart from the shared `RUNNING_HARNESS`.
- Installer git-checkout paths (HEAD export, version refusal) were covered only by the existing suite, not by
  my own old/new runs. Running them needs a scratch git repo, which I avoided under the no-git-write constraint.
- Ledger rows with `ENFORCER_LEDGER` on were not compared (instructed `ENFORCER_LEDGER=0`). The shown set that
  feeds the row was compared through hook output.

## Recommended actions (in order)

1. Fix C1 (`floor=GETAWAY_FLOOR`). Add the end-to-end getaway test and the pyflakes undefined-name gate.
   Rerun the 20-prompt old/new comparison, including below-floor and Vietnamese prompts.
2. Correct CHANGELOG.md:15 and ADR-0088:52/56 once C1 is fixed; ADR-0088 is unreleased, so amend it before acceptance.
3. Either source `sync.sh` after argument parsing with a `$ROOT/adapters/lib` fallback, or declare the `--root`
   from a symlink or copy change (L1).
4. Optional: catch `SystemExit` in findability's `_load_enforcer` (L3); fix the stale doctor comment and the
   premature "shipped" line (L4).

## Unresolved questions

- Should a missing `harness.py` make doctrine fall back to Claude rendering rather than inject nothing? The
  current choice (exit 0, no doctrine, no jevd warning) is declared; this is a product call, not a defect.

Status: DONE_WITH_CONCERNS
Summary: v0.65.0 behaves as declared in the self-test move, installer lib and harness detector (apart from Low items), but the lever removal left `floor=floor` at enforcer.py:3141, so every below-floor turn the Jev router does not decide (for example any low-fit Vietnamese prompt under default flags) now crashes the enforcer with NameError, and the release must not ship until that one-token fix and a covering test land.
