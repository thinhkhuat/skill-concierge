# Fork B — ADR-0082 draft, mechanism and behaviour review

Date: 2026-10-07 ~21:10 (Asia/Saigon). Read-only review of the uncommitted draft. Scope: how the new text
behaves in a live agent; fork A covers evidence and premises.

## Verdict: SHIP WITH CHANGES

Strongest reason: the new skip names row 1 only, but agents take rows 2-5 often. In the transcripts, 60 of
160 organic whole-shelf turns that took an offered skill took one below row 1 (rank 2: 28, 3: 15, 4: 12,
5: 5; fact, `search_value.py` output in the private folder below). The rule's condition says "when no row
... fits" (`hooks/doctrine/skill-first.md` body line 14-15), but the ruling line and the audit check only
prove row 1 was considered. A letter-compliant agent can skip with a true row-1 reason while row 3 fits.
That makes the whole-shelf skip-bar lower than the take-bar, which rule 3 says must be the same line
(body line 27).

## 1. The text as a model reads it

- Fact: rule 1 says "A row that fits is a `USING:` now" (body line 14). The "loosely-adaptable ... is a
  `USING:`" bar lives only in rule 3 and is worded for search hits (body line 27-28). Before the draft, a
  whole-shelf no-fit always led to a search and then to rule 3's bar; now the agent can stop at rule 1, so
  the adaptation pressure is never stated on this path. Inference: this weakens the take-bar on exactly the
  turns the change targets.
- Fact: the skip line asks for "<what it does>; <why this task lies outside it>" about one skill. Inference:
  that is cheap to fill with a generic contrast ("diagnoses SSH; this is a file copy"), so it can become a
  reflex. The audit only checks the name and a reason of 3+ characters (`audit_skill_usage.py`,
  `_shelf_skip_ok`), so it cannot see a hollow reason; W40's hand-read is the only check. Acceptable if the
  wording below is added.
- Fact: the red-flags lead-in now says ruling out the top row "also answers each" row (body line 66-67).
  Consistent with rule 4; no contradiction found.

Proposed exact wording (keeps the skip one line for chat and one-liners, keeps adaptation pressure on real
work):

Rule 1, replace "A row that fits is a `USING:` now. When no row\n of a whole-shelf ranking fits, rule out its top row by name:" with:

```
A row that fits, even loosely adapted (3), is a `USING:` now. When no row of a whole-shelf
ranking fits even loosely, rule out its top row by name and the rows below it in the same reason:
`NO SKILL: whole-shelf — <top row>: <what it does>; <why this task lies outside it and the rows below>`
```

`WHOLE_SHELF_TAIL` (`hooks/scripts/enforcer.py:2751`), replace "None fit → rule out the top row by name:
NO SKILL: whole-shelf — <top row>: <what it does>; <why this task lies outside it>." with:

```
None fit, even loosely adapted → rule out the top row by name: NO SKILL: whole-shelf — <top row>: <what it does>; <why this task lies outside it and the rows below>.
```

The audit's parser still matches both (name after the dash, colon, reason). Body grows about 90
characters; the cap in `tests/test_doctrine_text.py:93` is 5,117, current 4,710.

## 2. Hand replay, 15 real organic whole-shelf turns

Sample: 5 turns that took an offered skill below row 1, 5 that took row 1, 5 `NO SKILL:` turns without a
search (seed 7). Prompts and offers are in
`~/.claude/skill-concierge/analysis-private/fork-b-261007/sample15.txt` (private; not quoted here).

| # | Class | Used (rank) | Would a row-1-only skip have dropped the used skill? |
|---|---|---|---|
| 1 | took offer | research-synthesis (5) | Yes: row 1 (`brief-me`) is easy to rule out; row 5 never addressed |
| 2 | took offer | ak-plan (3) | Likely: row 1 (`update-implementation-plan`) can be ruled out in one line |
| 3 | took offer | writing-for-agents (4) | Yes: row 1 (`rules-distill`) ruled out, the right skill sat at row 4 |
| 4 | took offer | directional-prompting (3) | No: row 1 (`rules-create-global`) itself fits; agent would take it |
| 5 | took offer | ak-bro (2) | No: row 1 (`ak-sumup`) fits loosely; chat-sized turn |
| 6 | took offer | mnemosyne-ops (1) | No: plain fit |
| 7 | took offer | tk-servers-ssh-doctor (1) | Borderline: a file move to the NAS; a loose adaptation a hollow reason could rule out |
| 8 | took offer | hooks-audit (1) | No |
| 9 | took offer | ak-git (1) | No |
| 10 | took offer | diagnose (1) | No |
| 11 | no-search skip | none | Used nothing. Real debugging work; row 1 `diagnose` fit loosely. The draft makes this skip lawful |
| 12-15 | no-search skip | none | No: status and chat turns; the skip is correct |

Count (judgment call, by hand): under a letter-only reading (rule out row 1, ignore the rest), 3 of 10
skill-using turns (#1, #2, #3) would have lost the skill used, plus 1 borderline (#7). Under the intended
reading ("no row fits"), 0 clear and 1 borderline. Whether the used skill actually helped in those turns is
not judged (I did not read the turn outcomes). The wording change in §1 closes the gap between the two
readings. Of the 5 no-search skips, 4 are correct chat skips; 1 (#11) is real work the draft would now
legalize.

## 3. Release mechanics

- Adapters do not restate the rule: no match for `whole-shelf`, `may have missed` or `NO SKILL` in
  `adapters/` or in `hooks/scripts/doctrine.py` (grep, empty). `_harness_adapt` rewrites only the full
  tool name and the slash form (`doctrine.py:138` docstring); the tail's bare `search_skills` is unchanged
  from before. No conflict.
- Who sees a whole-shelf ranking (ledger since 2026-09-26, `offer` events with a `jev` field and no
  error): Claude Code 519, OMP 44, Codex 1, Command Code 0 (1 offer, no `jev`), DSH 0 (no offers in the
  window), ZCode 0, Cline 0. Fact. So the change reaches Claude Code and OMP; Command Code and DSH, with
  `ENFORCER_JEV_BUDGET: "1.6"` (`adapters/commandcode/skill-concierge.mod.ts:85`,
  `adapters/dsh/skill-concierge.dsh.ts:152`), keep previews and the forced search in practice.
- Stale wording: `skills/skill-usage-audit/SKILL.md:43` still defines false-SKIPPING as "declared with NO
  same-turn `search_skills` call (the doctrine's hardest rule)"; the new third source is added two lines
  later, so the paragraph contradicts itself. Fix: "declared with none of rule 4's three sources (a
  same-turn search, a `SKILL-CHECK:` line, a whole-shelf top row ruled out by name)". The selftest
  comment at `audit_skill_usage.py:797` says "no search -> false"; still true for that case.
  `scripts/extract_turn_labels.py:340` names the case `false_skip_no_search` (label UNLABELLABLE); the
  ADR records it as a kept gap. No functional contradiction.
- Tests: `tests/test_ruling_parsers.py` + `tests/test_doctrine_text.py`: 59 passed in 27.29 s. Selftests:
  `audit --selftest OK`, `doctrine --selftest OK`, `enforcer --selftest OK`.

## Not checked

- Turn outcomes (whether the skills taken in the sample helped).
- How agents actually write the new line live; only W40 can show hollow-reason rates.
- Multi-intent offers (off on this machine's Claude Code); the row-1-only gap is wider there.

## Changes to make before ship

1. Rule 1 and `WHOLE_SHELF_TAIL` wording as in §1 (loosely-adapted bar; reason covers the rows below).
2. `skills/skill-usage-audit/SKILL.md:43` definition as in §3.

Status: DONE_WITH_CONCERNS

Summary: The mechanics are sound: adapters and the harness rewrite need no change, the audit and the three
selftests pass, and in practice only Claude Code and OMP get whole-shelf rankings. The behavioural gap is
that the skip line names row 1 only while 60 of 160 offered-skill takes were rows 2-5, and the
"loosely-adapted" take-bar is never stated on the new path; in a 15-turn hand replay a row-1-only reading
would have dropped the used skill in 3 of 10 skill-using turns (plus 1 borderline). Two wording changes
close it without making the chat skip longer; then ship.
