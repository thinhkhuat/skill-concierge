# Root Cause Analysis: GitHub Issue #1

## Issue Summary

- **GitHub Issue ID**: #1
- **Issue URL**: https://github.com/thinhkhuat/skill-concierge/issues/1
- **Title**: Command Code: mod installed to ~/.commandcode/mods/ cannot resolve its plugin root — silent fail-open without SKILL_CONCIERGE_ROOT
- **Reporter**: anhdtran22
- **Status**: OPEN (filed 2026-10-14, against 0.68.3 / `45ec811`)

## Assessment

| Metric | Value | Reasoning |
|--------|-------|-----------|
| Severity | High | On every machine except the maintainer's, the Command Code adapter never runs the enforcer, ledger or exclusion echo, and nothing reports it. `SKILL_CONCIERGE_ROOT` is a workaround, but nothing tells the user they need it. |
| Complexity | Medium | Four files carry the root logic (installer, mod, doctor, tests). The same hardcoded path also sits in three sibling adapters and in the ZCode MCP fallback. |
| Confidence | High | Every link below was read in source. Command Code's own mod loader and slug function were read in its installed bundle (1.82.x). |

## Problem Description

`adapters/commandcode/install.sh` copies the mod to `~/.commandcode/mods/skill-concierge.ts`. The copy finds its plugin root from its own location or from a path that exists only on the maintainer's machine. Everywhere else it resolves the root to `$HOME`, so every hook script spawn fails, and the mod's fail-open handlers make that silent.

**Expected behavior:** after `install.sh`, the mod reaches `<checkout>/hooks/scripts/*.py`. The live smoke (`scripts/smoke.py commandcode`) logs an offer row and a search row.

**Actual behavior:** the mod resolves `PLUGIN_ROOT = $HOME` and spawns nothing. The smoke fails, while `install.sh` prints `verify: OK` and doctor shows the Command Code row as OK.

**Symptoms:**
- `smoke.py commandcode`: `no offer row`, `no search row`.
- SessionStart stamps are written (those hooks use absolute paths in `settings.json`), so the install looks healthy.

## Reproduction

1. Clone the repo anywhere other than `~/in-PROD/MY-WORKBENCH/skill-concierge`, run `./setup.sh`, then `./adapters/commandcode/install.sh`.
2. Run `python3 scripts/smoke.py commandcode`.
3. Observe FAIL. With `SKILL_CONCIERGE_ROOT=<clone>` set, the same run passes.

**Reproduction verified:** Partly. The code path was traced in source: `__dirname` of a copied mod is `~/.commandcode/mods`, and `../..` of it is `$HOME`. The reporter ran the live failure and the env-var pass on Command Code 1.82.1. It does not reproduce on the maintainer's machine, because step 3 of the ladder below matches there.

## Root Cause

### Affected Components

- `adapters/commandcode/skill-concierge.mod.ts:37-54`: `resolvePluginRoot()`.
- `adapters/commandcode/install.sh:236-238`: copies the mod verbatim; `:254-262`: verify checks byte identity only.
- `scripts/doctor.py:1761-1849`: `check_commandcode()` checks file presence and byte identity only.
- Same defect class: `adapters/dsh/skill-concierge.dsh.ts:59`, `adapters/omp/skill-concierge.ext.ts:50`, `adapters/opencode/plugin/index.ts:64` (hardcoded workbench fallback); `adapters/commandcode/install.sh:45` (`REPO_PROJECT_SLUG` names the maintainer's checkout); `adapters/zcode/install.sh:152-170` (`--mcp-fallback` merges `adapters/zcode/mcp.json`, whose launcher path is the maintainer's absolute path).

### Evidence Chain (5 Whys)

```
WHY does the smoke log no offer row?
  → the mod never spawns enforcer.py              (skill-concierge.mod.ts:57 — ENFORCER_SCRIPT = join(PLUGIN_ROOT, "hooks/scripts/enforcer.py"))
WHY is the script path wrong?
  → PLUGIN_ROOT resolves to $HOME                 (skill-concierge.mod.ts:53 — `return candidate;` where candidate = resolve(__dirname, "../.."))
WHY does ../.. land on $HOME?
  → the mod runs from ~/.commandcode/mods/, not from the repo   (install.sh:237 — mod_dst.write_bytes(mod_bytes))
WHY is there no working fallback?
  → the only fallback is the maintainer's checkout path        (skill-concierge.mod.ts:49 — join(homedir(), "in-PROD/MY-WORKBENCH/skill-concierge"))
WHY did no check catch it?
  → install verify and doctor compare bytes, never resolve the root   (install.sh:258; doctor.py:1786)
ROOT CAUSE: the installer copies the mod out of the checkout but never tells the copy where the checkout is.
```

**Why this occurs:** the ladder was written for a mod that lives inside the repo. The installer copies it out (Command Code loads `~/.commandcode/mods/*.ts`, and the reporter found that a symlink is loaded under its link path, not its target). The maintainer's machine always matched the hardcoded fallback, which hid the defect.

### Related Issues

- The DSH, OMP and OpenCode adapters load their module from inside a complete tree (the checkout or the versioned plugin cache), so `../..` resolves there and those adapters work on any machine. Their hardcoded fallback is dead code that can only point at the wrong checkout.
- Cline already uses the right shape: own location, then `SKILL_CONCIERGE_ROOT`, no personal path (`adapters/cline/skill-concierge.cline-plugin.ts:50-56`).
- Out of scope here, reported separately: the shipped `.mcp.json` sets `SKILL_TRIGGERS` and `SKILL_SERVER_RECORDS` to the maintainer's home (`.mcp.json:13-14`), and `scripts/check_mcp_env_parity.py` holds every descriptor to those literals. The engine's own defaults resolve the same files from `Path.home()` (`vendor/skill-search/skill_search/server.py:168,179`). Those keys shape the index, so removing them needs its own change and reindex check.

## Impact Assessment

**Scope:** every Command Code install on a machine where `~/in-PROD/MY-WORKBENCH/skill-concierge` does not exist.

**Affected features:** the per-turn SKILL-FIRST menu, `turn`/`offer`/`manual`/`skill`/`search` ledger rows, and the exclusion echo after a skill load. The SessionStart doctrine and self-heal hooks keep working.

**Severity justification:** a whole harness adapter is inert, and the install, verify and doctor all report success.

**Data/security concerns:** none. No data is corrupted. The fallback can only spawn scripts under the user's own home directory.

## Proposed Fix

### Fix Strategy

The installer bakes the resolved checkout path into the copy it writes. The mod's ladder becomes: `SKILL_CONCIERGE_ROOT`, the baked root, its own location; it drops the personal path. When nothing resolves, the mod posts a `cmd.ui.notify` notice instead of staying silent. Install verify and doctor compare against the rendered copy and check that the baked root reaches `hooks/scripts/enforcer.py`. One small module renders the copy for both, so they cannot drift apart.

### Files to Modify

1. **`adapters/commandcode/mod_root.py`** (new): `render(source, root)` replaces the single `const INSTALLED_ROOT = "";` line with a JSON-quoted root; `baked_root(text)` reads it back. It is stdlib-only and runs on Python 3.9.
2. **`adapters/commandcode/skill-concierge.mod.ts`**: adds the placeholder constant and the new ladder, drops `homedir`, and posts the notice when no root resolves.
3. **`adapters/commandcode/install.sh`**: writes the rendered copy. Verify compares against the rendered copy and FAILs when the baked root lacks `hooks/scripts/enforcer.py`. The project-local MCP dir name comes from `adapters/commandcode/project_slug.py` (new), a port of Command Code's own slug rule (`@sindresorhus/slugify` defaults, applied to the physical path), instead of the maintainer's literal.
4. **`scripts/doctor.py`**: `check_commandcode()` compares against the rendered copy, and returns FAIL when the installed mod's root cannot reach `hooks/scripts/enforcer.py`.
5. **`adapters/{dsh,omp,opencode}`**: drop the hardcoded workbench fallback (sibling sweep).
6. **`adapters/zcode/install.sh`**: `--mcp-fallback` writes this checkout's launcher path instead of the literal in `mcp.json`.
7. **Tests**: the copied mod runs from an unrelated directory with no env var; the unrendered copy notifies; installer verify, doctor and slug cases; a guard test that fails when any shipped adapter source names the maintainer's checkout path.

### Alternative Approaches

- **Marker file** (`~/.commandcode/skill-concierge-root`): one more file to install, verify and clean up, for the same result. Rejected.
- **Symlink or one-line re-export loader** (the Cline shape): the reporter found that Command Code loads a symlinked mod under its link path. A re-export loader is untested on Command Code's jiti host. Rejected for now.
- **Only drop the personal path**: fixes nothing for other users; the env var would stay the only working route.

### Risks and Considerations

- An installed copy now differs from the repo file by one line, so every byte comparison must go through `render()`. That is why the renderer is shared.
- Moving the checkout after install breaks the baked root. Doctor now reports that as FAIL, and rerunning `install.sh` fixes it.
- The notice in print mode (`cmd -p`) appears only on a broken install, which is the point.

### Testing Requirements

1. A rendered copy in an unrelated directory, with no `SKILL_CONCIERGE_ROOT`, runs the enforcer stub (fails before the fix).
2. An unrendered copy in an unrelated directory posts the notice and spawns nothing.
3. Installer: the rendered copy holds the root; verify FAILs when the root has no enforcer.
4. Doctor: OK on a rendered copy; FAIL on a copy whose root lacks the enforcer; WARN on a stale copy.
5. The slug rule matches the project dirs Command Code itself created on this machine.
6. Guard: no shipped adapter source holds `in-PROD/MY-WORKBENCH`.

**Validation commands:**
```bash
python3 -m pytest tests/test_commandcode_mod.py tests/test_sibling_installers.py tests/test_doctor_selftest.py tests/test_no_personal_paths.py -q
python3 -m pytest tests -q
python3 scripts/driftcheck.py driftcheck.json
adapters/commandcode/install.sh && env -u SKILL_CONCIERGE_ROOT python3 scripts/smoke.py commandcode
```

## Implementation Plan

Mod placeholder and ladder → renderer → installer → doctor → siblings → tests → docs/CHANGELOG → full suite → live install and smoke on this machine.

This RCA document should be used by the `piv-implement-issue` skill.

## Next Steps

1. Review this RCA document.
2. Run the `piv-implement-issue` skill with issue #1 to implement the fix.
3. Run the `piv-commit` skill after implementation is complete.
