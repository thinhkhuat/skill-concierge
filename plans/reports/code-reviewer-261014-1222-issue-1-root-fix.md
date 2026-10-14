# Code review: GitHub issue #1 fix (Command Code mod root), uncommitted working tree

Reviewer: code-reviewer (read-only). Date: 2026-10-14, Asia/Saigon.

## Scope
- Files: adapters/commandcode/{install.sh, skill-concierge.mod.ts, mod_root.py (new), project_slug.py (new)}, adapters/{dsh,omp,opencode} root ladders, adapters/zcode/install.sh, scripts/doctor.py, tests/{test_commandcode_mod.py, commandcode_mod_harness.mjs, test_sibling_installers.py, doctor_selftest.py, test_no_personal_paths.py (new)}, docs (README, caveats, repository-layout, openwiki/operations, docs/issues/issue-1.md).
- Diff: 15 tracked files, +320 / -72, plus 4 untracked files.

## What I ran (evidence)
- `pytest tests/test_commandcode_mod.py tests/test_sibling_installers.py tests/test_no_personal_paths.py -rs`: 60 passed, no skips (the real-slugify comparison test ran).
- `pytest tests/test_doctor_selftest.py tests/test_builtin_selftests.py`: 5 passed.
- Full suite `pytest tests -q -x`: 1637 passed in 240.66s.
- `python3 scripts/driftcheck.py driftcheck.json`: "IN SYNC", exit 0.
- Python 3.9: `ast.parse(..., feature_version=(3,9))` passes for mod_root.py and project_slug.py; `/usr/bin/python3` (3.9.6) runs project_slug.py and mod_root round-trips `/x/é "q"`.
- End-to-end sandbox (temp HOME, PATH python3 -> /usr/bin/python3 3.9.6), root path `<tmp>/clone dir/it's "q" người`: install.sh printed `verify: OK` and `mod reaches its hook scripts: yes`; the baked line was `const INSTALLED_ROOT = "/tmp/cr-issue1.IZbh/clone dir/it's \"q\" người";`.
- Loaded that installed copy through Command Code's own jiti (`command-code/node_modules/jiti/lib/jiti.mjs`, `createJiti(..., {moduleCache:false})`, `import(path, {default:true})`, the same calls as `importModFactory` in dist/cli.mjs): enforcer stub ran, no notice. Unrendered copy with no env: notice posted, nothing spawned. Unrendered copy + SKILL_CONCIERGE_ROOT: enforcer ran. Copy run from inside the checkout: enforcer ran (`__dirname` rung works under jiti).
- Confirmed in dist/cli.mjs: the mod `ui.notify` buffers into pending notices that are flushed later (`flushPendingNotices`), and the built-in `update-notice` mod calls `e.ui.notify(...)` from its factory, so calling it from the default export is supported.
- Confirmed `getProjectDirName(e){return slugify(e.cwd)}` and `localMcpConfigPath` in dist/cli.mjs; @sindresorhus/transliterate 's replacement table has 0 ASCII keys, so the Python port is exact for ASCII paths.
- Read-only `python3 scripts/doctor.py`: `[✓] Command Code integration`. The real `~/.commandcode/mods/skill-concierge.ts` already carries `const INSTALLED_ROOT = "/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge";`, so the installer has already been run against the real HOME. The maintainer's install shows no regression.

## Overall assessment
The core fix is correct. The root is baked in, the ladder resolves in the stated order, there is no silent no-root path in the mod, quoting is safe for spaces, quotes and non-ASCII, it runs on Python 3.9, and it loads under Command Code's jiti. Installer verify and doctor now catch the issue-#1 state. No Critical or High defects. The remaining defects: a half-done sibling sweep in the ZCode fallback, two doctor verdicts that are too lenient, one test that cannot fail for the property it names, and a slug gap on non-ASCII paths.

## Critical Issues
None.

## High Priority
None.

## Medium Priority

### M1. ZCode `--mcp-fallback` still writes the maintainer's home into the server env
- Where: adapters/zcode/install.sh:161 rewrites only `args`. The env comes verbatim from adapters/zcode/mcp.json:14: `"SKILL_TRIGGERS": "/Users/thinhkhuat/.claude/skill-concierge/triggers.json"`.
- Evidence: the merge does `server = json.loads(src...)["mcpServers"]["skill-search"]`, then `server["args"] = [f"{root}/bin/skill-search-mcp"]`, then `servers["skill-search"] = server`. On any other machine the merged ZCode config points SKILL_TRIGGERS at a file that does not exist. The engine reads it at vendor/skill-search/skill_search/server.py:167-168 (`os.path.expandvars(os.environ.get("SKILL_TRIGGERS", ...))`), so the LLM trigger layer is silently empty for that server. This is the same machine-pinned-path class this diff sets out to sweep, in a write path the diff already edits. docs/issues/issue-1.md:70 defers the `.mcp.json` env literals in general, but this is a per-machine config write, not the shared descriptor.
- Inference (unverified): SKILL_TRIGGERS is index-shaping (ENGINE_ENV_KEYS). A fallback server with a different value could rebuild the shared index without the LLM layer. I did not test this.
- Fix (one line next to line 161, same as the Command Code installer's SERVER_ENV): `server["env"]["SKILL_TRIGGERS"] = str(Path.home() / ".claude/skill-concierge/triggers.json")`. On the maintainer's machine this gives the same value. Extend `test_zcode_mcp_fallback_points_at_this_checkouts_launcher` to assert it under the temp HOME.

### M2. Doctor rates the exact issue-#1 state (pre-fix copy, no env) as WARN, not FAIL
- Where: scripts/doctor.py:1807-1810 (`if baked is None:` appends a WARN finding: "installed mod predates its INSTALLED_ROOT line (a stale copy that finds no hook scripts on most machines)").
- Why it matters: a user who hits issue #1, pulls this fix and runs doctor before reinstalling still has a pre-fix copy that is inert. Doctor shows `[!]`, not `[✗]`, so the overall status is not a hard failure, although the copy is known not to work unless SKILL_CONCIERGE_ROOT is set. The check that decides this is already computed one line above (`resolves`, which includes the env rung). The pre-fix ladder's other rungs (`__dirname/../..` = $HOME, the personal path) are what this fix retires, so they should not count as a supported resolution.
- Fix: `if baked is None and not reaches(os.environ.get("SKILL_CONCIERGE_ROOT", "")): unreachable = "installed mod predates its INSTALLED_ROOT line and SKILL_CONCIERGE_ROOT is unset, so it does nothing in Command Code — re-run adapters/commandcode/install.sh"`. Keep the WARN when env reaches. On the maintainer's machine this only matters before a reinstall, which has already happened.

### M3. `test_skill_concierge_root_still_wins_over_the_installed_root` cannot fail for the property it names
- Where: tests/test_commandcode_mod.py:281-285.
- Evidence: the copy is rendered with `str(tmp_path / "elsewhere")`, a path with no hooks/scripts/enforcer.py, so the INSTALLED_ROOT rung can never match. If the ladder were reordered to `[INSTALLED_ROOT, env, __dirname]`, the env rung would still be the first that resolves and the test would still pass. It proves the env fallback, not its precedence.
- Fix: give both roots working stubs that log differently, e.g. a second fake root whose enforcer stub prints `"MENU from baked"`. Bake that root into the copy, set SKILL_CONCIERGE_ROOT to the fixture root, and assert the menu (or the log dir) comes from the env root.

## Low Priority

### L1. project_slug.py diverges from Command Code on non-ASCII paths; its only always-on test is tautological
- Where: adapters/commandcode/project_slug.py:15-22 (no transliteration step); tests/test_sibling_installers.py:850 (expected slug computed with the same project_slug.py); tests/test_sibling_installers.py:863-872 (the real-library comparison skips when `cmd` is not on PATH, e.g. CI).
- Evidence (run here): for `/Users/an/Tài liệu/skill-concierge`, Command Code's slugify gives `users-an-tai-lieu-skill-concierge`; project_slug.py gives `users-an-t-i-li-u-skill-concierge`. The docstring admits it, and the effect is that install.sh silently skips the project-local MCP override (`has_project` is false). A stale skill-search entry in that project's override would then survive a reinstall. Vietnamese folder names are a realistic case for this user.
- Fix (stdlib, still 3.9): before decamelize, apply the library's two steps that matter for paths: `s = unicodedata.normalize("NFD", s.replace("đ","d").replace("Đ","D"))`, then drop combining marks (`"".join(c for c in s if not unicodedata.combining(c))`). Add `"/Users/an/Tài liệu/Đồ án"` to the comparison list. Optionally print a stderr note in install.sh when the path is non-ASCII and no project dir matched, so the skip is not silent.

### L2. Doctor's OK can rest on doctor's own SKILL_CONCIERGE_ROOT, which Command Code may not have
- Where: scripts/doctor.py:1806 (`resolves = reaches(env) or reaches(baked)`); the selftest only asserts `!= FAIL`.
- Evidence: with a broken baked root and the env var set in the doctor shell, `resolves` is True, the stale comparison passes, and the row is OK. Command Code launched from the VS Code extension (the package ships `vsix/`) or a GUI does not inherit that shell's env, so the mod is inert while doctor says OK.
- Fix: when `baked` exists but is unreachable and only the env rung resolves, add a WARN finding: "installed root <baked> is gone; the mod works only where SKILL_CONCIERGE_ROOT is set — re-run install.sh".

### L3. Installer writes a mod it already knows is dead, then fails verify
- Where: adapters/commandcode/install.sh:226 (render, in the compute phase) vs :273-278 (reachability check, after the commit phase wrote settings.json, mcp.json and the mod).
- Evidence: `test_commandcode_verify_fails_when_the_root_has_no_hook_scripts` passes with exit 1, but by then every file has been written. The compute phase's contract is "Nothing was changed" on failure (:229), and the precondition `root/hooks/scripts/enforcer.py` is known before any write.
- Fix: in the compute `try`, `if not (Path(root) / "hooks/scripts/enforcer.py").is_file(): raise FileNotFoundError(...)`. Keep the verify check as a post-condition.

### L4. Stale comment and missing CHANGELOG line
- adapters/commandcode/install.sh:327 still says "Doctor's harness-specific row (WARN-only, so we surface it but don't fail on it)", but the row can now be FAIL (scripts/doctor.py, the `unreachable` return).
- docs/issues/issue-1.md:129 plans "docs/CHANGELOG", but CHANGELOG.md is unmodified (`git status`). Users of an existing install need the line "re-run adapters/commandcode/install.sh", because a pre-fix copy now shows a doctor WARN.

## Over-engineering pass
- mod_root.py (36 lines, shared by installer and doctor) is proportionate: it is the one place that defines a correct copy, and it rejects a reworded placeholder.
- project_slug.py: an 8-line port, with a test against the real library. Proportionate. The alternative of shelling out to Command Code's own slugify through node would remove the port's drift risk, at the cost of locating the Command Code install. Either is defensible; no change required beyond L1.
- The importlib loader for mod_root.py is written twice (scripts/doctor.py `_cc_mod_root`, tests/test_commandcode_mod.py `_mod_root`). This is minor; not worth a finding.
- `except (OSError, UnicodeDecodeError, ValueError)` in doctor: UnicodeDecodeError is already a ValueError. Cosmetic.
- Nothing else reads as speculative abstraction. The sibling-adapter edits are pure deletions of dead fallbacks. I verified that DSH (its patch YAML names `{root}/adapters/dsh/...`), OMP (a whole-tree DEST copy) and OpenCode (a checkout path in opencode.json) load from a complete tree, so `../..` still resolves there.

## Edge cases checked, no defect
- Root with spaces, `'`, `"` and non-ASCII: rendered with json.dumps (ASCII-escaped, valid JS), round-tripped by `baked_root`, and loaded and resolved under jiti.
- CRLF checkout: `read_text` translates newlines, so the regex `$` anchor is not affected.
- Unrendered or empty root: every script path is "", `existsSync("")` is false, nothing spawns, and the notice is posted once.
- Eager `__dirname` evaluation in the ladder array: defined under jiti (verified); the old code also evaluated it on the no-env path.
- `--root` pointing at an older checkout without the placeholder: `render` raises inside the compute `try`, and the run exits cleanly with nothing written.
- Pre-existing, not introduced here: SessionStart commands are built as `f'python3 "{root}/hooks/scripts/doctrine.py"'` (install.sh:193-197). A root containing `"` produces a broken shell word (in the sandbox it was written as `python3 "/tmp/.../it's "q" người/hooks/scripts/doctrine.py"`). This is out of scope for issue #1; `shlex.quote(root)` would fix it.
- Pre-existing: a root containing `:` breaks the `PYTHONPATH=...` imports in both heredocs. The compute phase fails before any write; the class is unchanged.

## Recommended actions (priority order)
1. M1: set SKILL_TRIGGERS from Path.home() in the ZCode fallback merge, and test it.
2. M2: FAIL a pre-fix copy unless SKILL_CONCIERGE_ROOT reaches the enforcer.
3. M3: rewrite the precedence test with two live roots.
4. L1: transliterate (NFD + strip marks + đ) in project_slug.py, and add a non-ASCII case.
5. L2, L3, L4.

## Metrics
- Type coverage: not measured (no tsc config was run against the mod; jiti load was verified instead).
- Tests: 1637 passed, full suite; changed files 60 + 5 passed.
- Lint: not run separately; pyflakes runs through tests/test_no_undefined_names.py, which passed in the full suite.

## Not checked
- A live `scripts/smoke.py commandcode` turn: not run, because it would drive the real Command Code under the real HOME.
- Windows / Git Bash paths (`/c/Users/...` baked into a Node-on-Windows mod).
- Whether a ZCode fallback server with a wrong SKILL_TRIGGERS actually reindexes the shared store (the M1 inference).

## Unresolved questions
- M2 is a policy call: should doctor FAIL a pre-fix copy that cannot be shown to resolve? My pick is yes, because the fix retires every rung that copy relies on except the env var.

Status: DONE_WITH_CONCERNS
Summary: The issue-#1 fix is correct, as verified under Command Code's jiti, Python 3.9 and odd root paths, and the full suite passes (1637). There are three Medium defects to fix before landing: the ZCode fallback still writes the maintainer's SKILL_TRIGGERS path, doctor only WARNs on an inert pre-fix copy, and the precedence test cannot fail.
