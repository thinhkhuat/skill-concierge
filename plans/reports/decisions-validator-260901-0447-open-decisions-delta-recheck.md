# Delta re-check — open-decisions-260901-0429-validated.md (post-correction revision)

Validator: independent (same validator as the 0431 pass) · Date: 2026-09-01
Scope: revised sections R1–R6 + §7 of `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/plans/reports/open-decisions-260901-0429-validated.md`, checked only against the 0431 findings and fresh probes of newly introduced claims.

**VERDICT: PASS** — all 3 blocking findings resolved; prior advisories resolved; 2 new minor advisories introduced.

## Blocking resolution

| # | Finding (0431) | Resolution in revision | Status |
|---|---|---|---|
| B1 | R5 orca "root-absolute, dead, FIX" | Rewritten WORKING/KEEP: commands described as `"${HOME-}/.orca/agent-hooks/claude-hook.sh"` — HOME-relative, OSTYPE guard (.cmd Windows / .sh Unix), correct counts (×12), script 3.6K executable, wiring correct. Matches the settings.json strings I re-read at 0431. | RESOLVED |
| B2 | R3 bctt "~1,900 longest" | Corrected: exactly two vn skills >1,100 (news-coverage-tracker 1,442, deep-dive 1,114), bctt 472 = shortest, 1,900 named as the audit's already-withdrawn misattribution; options/recommendation retargeted to the two real long ones. All figures match census + live disk exactly. | RESOLVED |
| B3 | R2 "five GoalBuddy agents" | Now "the three validators and the three GoalBuddy agents first (6 files)". 3+3=6; fleet=3 verified (deployed dir, goal-prep/agents tomls, codex tomls, goal-execution.md:300-302). | RESOLVED |

## Prior advisories

| # | Advisory (0431) | Resolution | Status |
|---|---|---|---|
| A1 | R1 omitted source-tree doctrine copies | Note added naming vn-deep-dive-report copy, vn-canu bundle copy, sub-agent-templates.md — all match my 0431 grep. | RESOLVED |
| A2 | R4 byte figure stale | Date-stamped: audit-time 734/51,409 attributed to 2026-08-31; live "736 / 51,717" matches my recount byte-for-byte. | RESOLVED |
| A3 | R5 phantom "config" in ~/.orca | Contents list now agent-hooks/, claude-agent-teams-bin/, keybindings.json — matches actual listing. | RESOLVED |
| A4 | R6 "twice"/"months" unverifiable | Dropped; now "diverged before the 2026-08-31 sync (how long is unverifiable — the workbench root keeps no git history)". Divergence-before-08-31 is true (roadmap item 3 edited "real drifted copies" 08-31; full byte-identical sync landed 09-01 — the sentence does not claim the fix date, so it stands). | RESOLVED |
| A5 | Register/jargon | OSTYPE guard now glossed inline; "root-absolute" survives only as the named withdrawn reading. Adequate. | RESOLVED |

## New issues introduced by the corrections

1. [ADVISORY] R5/§7 attribute the false path reading to **two tools** ("hooks-audit, and this arc's own regex inventory") both dropping the `${HOME-}/` prefix. Only the first is evidenced: hooks-audit's txt displays the bare `/.orca/...` 12× (its `extract_script_path`, scripts/audit-hooks.py:52-59, extracts "the first absolute script file path", which matches the `/.orca/...` substring — mechanism confirmed at source). No artifact anywhere (skill-concierge plans/reports, workbench plans/reports, .scratch) shows a second display of the dropped-prefix form. The second-tool attribution is UNVERIFIABLE from artifacts — soften to the evidenced tool, or mark the second as recollection.
2. [ADVISORY] Header staleness after revision: line 3 still reads "two earlier suggestions were caught overstated during that verification" and "Status: DRAFT pending independent validation", while §7 now logs six withdrawals (three drafting-time, three caught by independent validation) and validation has completed. Technically defensible readings exist ("two" = the merge + gate items; DRAFT = pending owner), but next to the revised §7 the header reads stale — refresh both lines.

## Non-finding hairs (no action required)

- R5 says "-f/-x existence checks"; the actual Unix branch tests `-f && -r && -x`. Subset statement — true, not false.
- R5 "the integration is live": wiring + script existence/executability verified; runtime firing is inferred, not traced. Acceptable.
- §7.4's "I verified the ~/.orca directory existed but never re-read the command strings before publishing" is the author's uncorroborated self-account of the drafting process — unverifiable, but it is a confession in a withdrawal log and the load-bearing fact (commands are `${HOME-}`-relative) is independently verified.

Status: DONE
