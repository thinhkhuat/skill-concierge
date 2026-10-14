# Review: PR #2 — "fix(commandcode): resolve the mod's plugin root from an installer-written pointer"

- **PR:** https://github.com/thinhkhuat/skill-concierge/pull/2 (anhdtran22:fix/commandcode-mod-root-resolution, head `dd127e4`)
- **Base:** `45ec811` (0.68.3). `main` is now `5f7b0ef` (0.68.5).
- **GitHub state:** OPEN, `mergeable: CONFLICTING`.
- **Date:** 2026-10-14

## Verdict

The PR is correct on its own base and well argued. It is now **superseded**: `main` fixed issue #1 in 0.68.4
(`5e62cde`) by a different route, and the PR conflicts with it in every file it touches except the ADR.
Recommendation: close it as superseded with thanks, and carry over its one durable idea that `main` lacks,
an ADR that records the decision.

## Evidence

- PR tests on its own base, in a throwaway worktree: `tests/test_commandcode_mod.py`, `tests/test_sibling_installers.py`
  and `tests/test_doctor_selftest.py` give **57 passed**. The PR body's full-suite claim (`1622 passed, 9 skipped`) was not
  re-run.
- The diff was read in full: mod, installer, doctor, tests, ADR-0091, CHANGELOG and the version files.

## How the two fixes compare

| | PR #2 (pointer file) | main 0.68.4 (root written into the copy) |
|---|---|---|
| Where the checkout path lives | `~/.commandcode/skill-concierge-root`, a second file | the copy's `INSTALLED_ROOT` line |
| Installed copy | byte-identical to the repo file | differs by one line; installer and doctor share `mod_root.render` to compare |
| Lookup order | env → own location → pointer | env → written-in root → own location |
| No root found, inside Command Code | silent: falls back to `$HOME` | `cmd.ui.notify` notice, every script path empty |
| Doctor | WARN finding | FAIL (including a pre-fix copy with no env var) |
| Uninstall | pointer left behind; README uninstall steps not updated | nothing extra to remove |
| Same defect elsewhere | not touched (DSH, OMP and OpenCode fallbacks, `REPO_PROJECT_SLUG`, MCP descriptors) | fixed in 0.68.4 and 0.68.5, with a guard test |
| Decision record | ADR-0091 | none |

Both designs are sound. The PR's case for the pointer, a byte-identical copy, is real; `main` pays for that with the
shared renderer instead. Switching designs now would buy nothing that `main` lacks.

## Findings on the PR (against its own base)

1. **Medium — still silent inside Command Code.** When nothing resolves, `resolvePluginRoot()` returns the sibling
   (`$HOME`) and every handler no-ops without a word (`skill-concierge.mod.ts`, the PR's new `resolvePluginRoot`).
   Install verify and doctor catch it; a session does not.
2. **Low — the pointer outlives an uninstall.** The ADR says so, but the README's uninstall steps were not updated.
3. **Low — doctor reports an inert mod as WARN.** The row stays non-OK, but `status: WARN` hides a dead adapter among
   routine warnings.
4. **Low — partial sweep.** The same hardcoded path stayed in the DSH, OMP and OpenCode adapters and in
   `REPO_PROJECT_SLUG` (`adapters/commandcode/install.sh:45`).

## Worth carrying over to main

- **An ADR for the decision.** `main` changed the Command Code root resolution with no ADR; the repo records such
  decisions (`docs/adr/`). ADR-0091 is free on `main` (latest is 0090). A `main` ADR should record the written-in root,
  the pointer file as the rejected alternative (crediting PR #2), and the symlink and settings-`env` routes the reporter
  verified live to have no effect.
- **A test that a set-but-useless `SKILL_CONCIERGE_ROOT` falls through.** `main`'s loop already skips it (it checks
  `hooks/scripts/enforcer.py` for every candidate), but no test pins it.

## Open questions

1. Close PR #2 as superseded with a thank-you reply? (Recommended.)
2. Write the ADR on `main` and add the fall-through test? (Recommended; a small docs and tests change.)
