# Fix policy for the chisle-audit cuts (decided by the main session, AFK mode)

Worktree: `/Users/thinhkhuat/.worktrees/skill-concierge/chisle-cuts` (branch `chore/chisle-audit-cuts`,
base `main` 692cab1). Edit ONLY inside that worktree, ONLY the files your prompt assigns you. Never touch the
main checkout `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge` except to READ the findings files under
`plans/261009-0102-chisle-audit/findings/`. No git commit, no stash, no branch, no push: the main session commits.
Do NOT bump versions, do NOT edit CHANGELOG.md or the four manifests: the main session does that.

## What to apply

Apply a finding when ALL hold:
1. It is in your assigned files.
2. Its confidence is `high`, OR it is `medium` and is one of: deleting code a grep proves unreachable,
   an unused import/variable/constant/parameter, a docstring or comment that is wrong or restates the code,
   or a stale doc statement contradicted by the code (re-verify the contradiction yourself first).
3. It is behaviour-preserving: same outputs, same ledger rows, same exit codes, same files written.
   Real defects named in the findings (wrong behaviour) are fixed too, each with a test that fails before
   and passes after when a test is practical.
4. Re-verify every "no caller" claim yourself before deleting (`rg -n -w '<symbol>' --hidden -g '!plans/**' -g '!vendor/**' .`
   inside the worktree; check hooks.json, settings, `.mcp.json`, adapters, skills, tests, and string-built names).

## Do NOT apply (these are decided: skip, and record the reason given here)

- Moving `enforcer.py`'s or `doctor.py`'s `_selftest()` into tests/: structural move of 27 % of the hot file; the
  `--selftest` CLI is cited by immutable ADRs. Owner follow-up.
- Deleting the dominance-collapse or per-skill-tau features in enforcer.py: feature cuts are the owner's call.
- A shared `adapters/lib/` helper for the installers: installers are self-contained per harness by design;
  fix only the concrete drift (zcode exclude list), not the structure.
- Unifying harness detection across enforcer/doctrine/ledger into one module: changes ledger rows; owner follow-up.
  (A concrete missing case, e.g. doctrine not recognising OpenCode, IS a defect: fix it in place if verified.)
- doctor.py `_row()` helper rewrite of ~104 result dicts: high typo risk for little gain.
- `CLAUDE.md` → `@AGENTS.md` import; archiving `docs/plan.md`; anything in `docs/adr/`, `docs/journals/`,
  `vendor/`, `plans/`, CHANGELOG history entries.
- Removing runtime flags documented in AGENTS.md / docs/runtime-flags.md.
- Any finding marked `(check)` UNLESS your prompt explicitly approves it.
- Anything low-confidence.

## Verify before you finish

Run the tests that cover every file you changed (`python3 -m pytest -q -p no:cacheprovider tests/<files>`),
plus `python3 hooks/scripts/enforcer.py --selftest` if you touched hooks/, and
`python3 scripts/driftcheck.py driftcheck.json` if you touched docs, scripts or paths. Quote the summary lines.
A test you had to change must still test the same behaviour; never weaken or delete a test to make it pass,
except the tests of a file you were told to archive.

## Report

Write a disposition file `plans/261009-0102-chisle-audit/findings/<LETTER>-dispositions.md` in the MAIN checkout
(that one file is your only write outside the worktree): one line per finding in your area's findings file,
`<path:line> — FIXED | SKIPPED: <reason from this policy or your verification>`, then the test commands and their
summary lines. End your reply with `Status: DONE | DONE_WITH_CONCERNS | BLOCKED` and a one-sentence summary.
Timezone Asia/Saigon. English.
