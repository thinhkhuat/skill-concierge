# Opus Validation Report: ADR-0082 draft (whole-shelf ranking as a skip source)

**Subject:** implementation + logic (uncommitted draft)
**Scope:** `git diff` of `hooks/doctrine/skill-first.md`, `hooks/scripts/enforcer.py`, `skills/skill-usage-audit/scripts/audit_skill_usage.py`, `skills/skill-usage-audit/SKILL.md`, `tests/test_ruling_parsers.py`, `AGENTS.md`, `CHANGELOG.md`, `docs/adr/README.md`, `docs/epoch-watch.md`, `openwiki/architecture/enforcement-gate.md`, plus the new `docs/adr/0082-whole-shelf-ranking-is-a-skip-source.md`. `plans/261006-2034-commandcode-jev-endpoint/perf/live_jevd_hook.py` ignored as instructed.
**Verdict:** FAIL. One blocking defect: the audit's matcher breaks ADR decision 4's own contract ("another row's name ... stays false"). The doctrine and the offer line are consistent with each other and do not open a skip under a preview.
**Date:** 2026-10-07, 20:40-20:46 Asia/Saigon. File fingerprints (md5) were identical at 20:41:58 and 20:46:15, so the review covers one stable state. The ADR changed once during the review (20:39:46); this report reviews the later text.
**Evidence files examined:** 19

## Executive summary

The doctrine text is clear about the main point. A preview keeps the forced search: rule 1 says so (`skill-first.md:38`), and rule 4 and red-flag row 1 limit the new source to "a whole-shelf ranking". The enforcer's closing line (`enforcer.py:2751-2753`) says the same thing. The audit is the weak part. `_shelf_skip_ok` checks whether the top row's name appears anywhere in the line, so naming row 2 counts as lawful whenever row 1's name is part of row 2's name (`git` inside `ak-git`). A ruling with no reason at all also counts, and so does a skip under a preview that arrives later in the same audit turn. W40 relies on this audit as its safety net, so these gaps weaken the very control that is meant to catch the risk this ADR accepts. All requested tests pass.

## Commands run (raw results)

```
$HOME/.claude/skills/.venv/bin/python3 -m pytest -q tests/test_ruling_parsers.py tests/test_doctrine_text.py
58 passed in 27.87s
python3 skills/skill-usage-audit/scripts/audit_skill_usage.py --selftest        -> exit 0
audit --selftest OK: false-SKIPPING verdict + H1 harvest filter + SELFREF parity + re-rule counting + both skip-ruling forms + enforcer-output-only authorization
hooks/scripts/enforcer.py --selftest (SKILL_CONCIERGE_LOG=tmp)                     -> enforcer --selftest OK ... exit 0
hooks/scripts/doctrine.py --selftest                                              -> doctrine --selftest OK ... + omp harness adaptation
python -m pytest -q tests/test_jev_router.py                                      -> 20 passed
python3 scripts/driftcheck.py driftcheck.json                                     -> exit 0
```

(No `.venv` exists in the repo; the skills venv was used.)

Matcher probe (in-process, `_shelf_top` + `_shelf_skip_ok`):

```
'pr' True | NO SKILL: whole-shelf — ak-git: commits; this is a project question
'git' True | NO SKILL: whole-shelf — ak-git: commits; not that
'plan' True | NO SKILL: whole-shelf — ak:plan: plans; not a plan
'pstack:recall' False | NO SKILL: whole-shelf — recall: recaps; this is an edit
'recall' True | NO SKILL: whole-shelf — pstack:recall: recaps; this is an edit
'tui-fundamentals' True | NO SKILL: whole-shelf — tui-fundamentals
'tui-fundamentals' True | NO SKILL: whole-shelf — x: y; tui-fundamentals and x both miss it
'anthropic-skills:docx' False | NO SKILL: whole-shelf — docx: word; not word
bad-name row: 'foo' None      (row "foo.bar")
```

End-to-end audit over fixture transcripts (the test file's own `_audit`/`_hook`/`_say` helpers, temp dir):

```
offer_after_ruling            shelf_skip= 0 false= 1   (timing correct)
shelf_then_preview_same_turn  shelf_skip= 1 false= 0   (preview governs, still counted lawful)
substring_git_names_row2      shelf_skip= 1 false= 0   (row 2 named, counted lawful)
name_only_no_reason           shelf_skip= 1 false= 0
row1_in_reason_only           shelf_skip= 1 false= 0
```

Short names do occur as offered top rows. A ledger scan of the last 40k rows found, among others, `af`, `read`, `seo`, `tdd`, `pdf`, `cron`, `ak:git`, `ck:git`, `ck:plan`. It also found names that start with `@` (`@oh-my-opencode:start-work`, `@code-yeongyu:lsp`) and names with spaces (`Verification Before Completion`).

## Observable truths

| # | Claim (source) | Status | Evidence |
|---|---|---|---|
| 1 | Previews keep the forced search (ADR D3) | ✓ | `skill-first.md:38` "When no row of a preview fits, rule `SEARCH:`"; `enforcer.py:2749` PREVIEW_TAIL unchanged |
| 2 | Doctrine and offer line say the same thing | ✓ | `skill-first.md:35-38` vs `enforcer.py:2751-2753` |
| 3 | Audit counts `shelf_skip` only when the ruling names row 1 (ADR D4) | ✗ | substring probe: `git`/`ak-git`, `pr`, `plan`; `audit_skill_usage.py:299-300` |
| 4 | "another row's name ... stays false" (ADR D4) | ✗ | `substring_git_names_row2` → shelf_skip=1 |
| 5 | Name is accepted "with or without its plugin prefix" (ADR:48) | ✗ | `pstack:recall` top + bare `recall` → False |
| 6 | "the same line under a preview stays false" (ADR D4) | ⚠ PARTIAL | true when the preview is the only offer in the turn (test turn three); false when a preview follows a whole-shelf offer in the same audit turn (`shelf_then_preview_same_turn`) |
| 7 | An offer that arrives after the ruling does not count | ✓ | `audit_skill_usage.py:729-737` sets `shelf_at_skip` at ruling time; probe `offer_after_ruling` → 0 |
| 8 | A copied ranking in the agent's text does not count | ✓ | test turn four; `_shelf_top` reads only `_enforcer_output` (`:646-650`) |
| 9 | `_skip_verdicts` returns four counts; every caller updated | ✓ | callers `:747-749`, `:946`, `:966`, `:972`, selftest `:797`; external importers (`scripts/extract_turn_labels.py`, `plans/.../search_value.py`) do not unpack the tuple (grep of `A.`/`au.` attributes) |
| 10 | Doctrine body 4,135 → 4,488 chars (ADR:59) | ✓ | measured: HEAD 4135, draft 4488; cap `tests/test_doctrine_text.py:93` = 5117 |
| 11 | Evidence numbers in ADR match the corrected analysis | ✓ | ADR:23-30 now says 305 turns, 0 of 22, 3 of 46, matching the analysis report after the validator's corrections |

## Findings, most severe first

### 1. BLOCKING: `_shelf_skip_ok` is a substring test, so naming another row passes

- Where: `skills/skill-usage-audit/scripts/audit_skill_usage.py:294-300`
  ```python
  low = line.lower()
  return any(f in low for f in {top.lower(), top.lower().replace(":", "-")})
  ```
- What goes wrong:
  - (a) A top row whose name is part of another name or word passes when the agent names a different row: `git` ⊂ `ak-git`, `pr` ⊂ "project", `plan` ⊂ `ak:plan`. Short names like these do reach the top of real offers (see the ledger scan above).
  - (b) Row 1's name anywhere in the reason passes ("— prime-frontend: …; tui-fundamentals neither").
  - (c) A prefixed top row named bare (`pstack:recall` → `recall`) is rejected. The ADR says the opposite at ADR:48 ("with or without its plugin prefix"), and the docstring example (`pstack:recall`, `pstack-recall`) shows two prefixed forms only.
- Why it matters: ADR decision 4 promises that "another row's name ... stays false". (a) and (b) break that promise. (c) undercounts lawful skips, which inflates W40's false-skip baseline. W40 is the only live control on the risk the ADR accepts.
- Fix: parse the one name token that follows `whole-shelf —` and compare it as a skill name, not as a substring:
  ```python
  _SHELF_RULING = re.compile(r'(?i)NO SKILL:[*`\s]*whole-shelf[*`\s]*[—–-]+[*`\s]*(?P<name>[^\s`*]+?)[`*]*:\s*(?P<why>\S.*)')
  def _shelf_skip_ok(line, top):
      m = top and _SHELF_RULING.search(line or "")
      return bool(m) and _same_skill(norm(m.group("name")), norm(top))
  ```
  `norm` already folds `:` into `-`, and `_same_skill` (`:200-202`) already accepts a bare name against a prefixed one in both directions. Add tests for the `git`/`ak-git` case, the reason-only mention and the bare-name case.

### 2. HIGH (release step, outside the diff): private prompts sit next to files the release must commit

- Where: `plans/261007-2024-search-value-after-whole-shelf/turns.jsonl`, `turns-v2.jsonl` (about 630 KB together; turns-v2 has 544 rows and 80,233 characters of `prompt` text from `HOIVU`, `VGP`, `postiz-app`, `news-tracking` and other projects), and `run1-3.txt` (they contain `prompt:` lines). The directory is untracked and not ignored (`git check-ignore` printed nothing). `gh repo view` reports `PUBLIC`.
- Why it matters: the ADR (lines 20-22), the CHANGELOG and W40 all cite this lever directory and its report. A release commit made with a broad `git add` would publish client prompts. The repo already has a rule for this: the Jev calibration corpus lives under `~/.claude/skill-concierge/jev-calibration/`, "never the repo" (AGENTS.md, `ENFORCER_JEV_ROUTER`).
- Fix: commit only `search_value.py` and the two reports. Move `turns*.jsonl` and `run*.txt` under `~/.claude/skill-concierge/` or gitignore them. Also check that the analysis and validator reports quote no client prompt verbatim. The untracked `.harnesskit/` directories (`.harnesskit/`, `docs/adr/.harnesskit/`, `plans/261007-2024-.../.harnesskit/`) are tool state, are not ignored either, and should stay out of the commit.

### 3. MEDIUM: the audit accepts a ruling with no reason

- Where: `audit_skill_usage.py:265` (`_SHELF_RULING`) and `:294-300`. Probe: `NO SKILL: whole-shelf — tui-fundamentals` → shelf_skip.
- Why it matters: the doctrine requires `<what it does>; <why this task lies outside it>` (`skill-first.md:36`). W40's second trigger counts copy-paste rulings "that name the top row without a real reason". A ruling with no reason at all is the clearest case of this, and the audit should catch it without a person reading the transcript.
- Fix: the regex in finding 1 already requires `name:` followed by text. For a stricter check, require a `;` clause: `(?P<what>[^;]+);\s*(?P<why>\S.*)`.

### 4. MEDIUM: a later preview in the same audit turn does not reset `shelf_top`

- Where: `audit_skill_usage.py:646-650`
  ```python
  top = _shelf_top(own)
  if top:
      cur["shelf_top"] = top
  ```
- Probe: whole-shelf offer, then a preview offer, then the shelf ruling → counted lawful. This is not a rare case. Queued prompts carry their own enforcer output but do not open audit turns; the earlier validator measured 79 of 468 whole-shelf offers arriving this way (16.9 %, `plans/reports/validator-261007-2024-forced-search-value.md` Truth #8). I confirmed in live transcripts that a `queued_command` attachment is followed by its own `hook_additional_context` UserPromptSubmit output.
- Why it matters: this breaks ADR decision 3 ("previews keep the forced search") inside the audit.
- Fix: let the latest enforcer output govern, with `if own: cur["shelf_top"] = _shelf_top(own)` (assign `None` too). Add the fixture `[_user, _hook(SHELF), _hook(PREVIEW), _say(line)] → false`.

### 5. MEDIUM: red-flag rows 2-4 and the worked example still order SEARCH unconditionally

- Where: `skill-first.md:76-78` ("I searched earlier." → "SEARCH here"; "I'm still in <skill>" → "new work: SEARCH (3)"; "You told me to use `<tool>`" → "SEARCH") and `skill-first.md:83` ("Worked example: no row fits → `SEARCH: …`").
- What goes wrong: under a whole-shelf ranking, rule 1 now makes the top-row skip the default. Rows 2-4 and the example, which the model reads every turn, still say SEARCH with no qualifier. This opens no dodge, because it points to the stricter path. It does give the model mixed instructions, and only row 1 carries the new alternative. The ADR's evidence is that the search is pure cost on these turns, and these rows keep that cost.
- Fix: state the alternative once in the table's lead-in, for example `6. **Red flags — a thought that skips without a source (4). Rule instead (under a whole-shelf ranking, ruling out its top row by name (1) is also lawful):**`. Restore row 1 to its HEAD text, and mark the example as a preview (`Worked example (a preview): …`). The doctrine ends up about the same length, and every row agrees with rule 1.

### 6. MEDIUM: the checkable form covers row 1 only (multi-intent leads and annex rows)

- Where: `enforcer.py:2775-2793`. `_ranked_mandate` applies multi-intent leads-first ordering to router rows as well (`:2296`, `:3142-3143` pass Jev rows into it). `ENFORCER_MULTI_INTENT` defaults to ON in code (`:2617`) and is OFF only in this machine's Claude Code (ADR-0055). Whole-shelf offers also carry the external and foreign annex blocks (`:3127-3143`), and rule 5 says those hits still count.
- What goes wrong: when the offer says "Reads as N distinct intents — the first N rows are the strongest fit per intent", ruling out row 1 says nothing about the leads for intents 2..N. Annex rows are never addressed either; an agent can reasonably argue they are not "rows of the ranking", since CHANGELOG:667 itself notes that the ranking never judged them. The precondition "no row fits" (`skill-first.md:34-35`) covers these rows in principle, but nothing visible or audited does.
- Fix (pick one): (a) doctrine: "rule out the top row of each intent the offer names", with the audit checking the first N rows; or (b) keep row 1 only and record in the ADR's Consequences that multi-intent leads and annex rows are covered by judgment alone, and add them to W40's hand-read sample. (b) is the smaller change.

### 7. MEDIUM: the ADR rejects ADR-0056's named alternative without saying why

- Where: ADR:12-18 quote ADR-0056's "the fix is the getaway leg's wording, not a new skip class" (`0056:78-79`, quote verified byte-exact). The ADR has no "Alternatives considered" section.
- What is missing: the evidence that rules out that alternative already exists. `plans/reports/diagnosis-261007-1752-hoivu-default-vi-routing-misfires.md`, "Correction 18:07", shows conversational turns getting Jev fits of 0.82, 0.59 and 0.48, so no fit floor or getaway wording can separate them. The same diagnosis (Defect 2) shows that the motivating HOIVU turn's whole-shelf ranking was "confidently wrong" (`tui-fundamentals` first at fit 0.49). The new source leans harder on the label's claim that every skill was judged, and the ADR's Risks line does not mention known misranking.
- Fix: add a short "Alternatives considered" section (tune the getaway or fit floor: rejected, cite Correction 18:07; skip by naming any row: rejected by the owner, already cited). Extend the Risks bullet with the HOIVU misranking and why the search would not have fixed it there either (the catalogue had no i18n skill, per diagnosis Defect 3).

### 8. LOW: W40's automatic leg goes blind by design after go-live

- Where: `docs/epoch-watch.md:18-22`.
- What goes wrong: after the change, agents mostly stop searching on whole-shelf turns, so `search_value.py --list search_new_hit` will report close to zero no matter what is being missed. The hand-read sample is the only real detector. Also, `audit_skill_usage.py` reads Claude Code transcripts only (`PROJECTS`), so shelf skips on Codex, OMP, ZCode and Cline are not measured.
- Fix: in W40, add an offline counterfactual. For a sample of `shelf_skip` turns, replay `search_skills` on the prompt and check whether a hit beats the named top row. This also fills the gap the earlier validator flagged ("the forced search was never run on the 35 `NO SKILL:` turns"). State the Claude-only scope in the row.

### 9. LOW: stale definitions left in the files the draft touched

- `audit_skill_usage.py:14-17`, module docstring: "did a 'SKIPPING' declaration fire WITHOUT a real search_skills call ... 'no search, no skip'". This is now the false-skip definition minus two sources.
- `audit_skill_usage.py:475`, `_false_skip_turns` docstring: "NO same-turn search and NO authorized marker". The code now also excludes `saw_shelf`.
- `skills/skill-usage-audit/SKILL.md:41-43`: the false-SKIPPING rate is defined as "declared with NO same-turn `search_skills` call (the doctrine's hardest rule)". The paragraph corrects this further down, but the defining sentence is stale.
- `scripts/extract_turn_labels.py:340`: a lawful shelf skip with tools or more than 15 words gets the rule name `false_skip_no_search`. The UNLABELLABLE label is right, because the label would come from the router's own ranking and be circular, but the rule name now calls a lawful skip false. Rename it, or add a `shelf_skip_circular` branch.
- ADR:55-56: "The 36 search-free skips seen on whole-shelf turns become lawful when they name the top row." Past turns cannot become lawful. Reword to "skips like the 36 …".
- Fix: one-line edits in each place.

### 10. LOW: `_OFFER_ROW` cannot read every real skill name

- Where: `audit_skill_usage.py:264`, `^\s*•\s+([A-Za-z0-9][A-Za-z0-9:_\-]*)`.
- What goes wrong: a top row that starts with `@` (`@oh-my-opencode:start-work` appears in real offers) does not match, so `.search` moves on and returns row 2 as the top. A name with a space or a dot is cut short (`Verification Before Completion` → `Verification`; probe `foo.bar` → `foo`). In the last 40k ledger rows no such name led a Jev (whole-shelf) offer, so the impact today is theoretical.
- Fix: match the first bullet line only and take everything up to the share or the dash, for example `^\s*•\s+(.+?)(?:\s+\(\d+%\))?\s+—\s`, then use `.match` on that one line.

### 11. Advisory: ADR index row for 0062

`docs/adr/README.md:91` still reads plain "Accepted" for 0062. The index has a precedent for this case ("Accepted (amended by 0018)", line 27). Add "(amended by 0082)" when 0082 is accepted, not while it is Proposed.

## Requested checks

1. **Doctrine text.** It cannot be read as permission to skip under a preview: rule 1 (`:38`), rule 4 (`:58`) and red-flag row 1 (`:75`) each limit the source to a whole-shelf ranking. It cannot be read as permission to skip by naming any row: "its top row" appears at `:35`, `:58` and `:75`. The red-flag row does not contradict rule 4. It does contradict rows 2-4 and the worked example (finding 5). A hollow reason is textually held to the same bar as rule 3 (`:47-49`), so no new textual hole opens. The friction is gone, though (no tool call), and the audit cannot grade reasons (findings 1 and 3), so W40's hand-read is the only guard. Rule 3's post-search bar is unchanged and matches the shelf form's structure.
2. **Enforcer line.** `WHOLE_SHELF_TAIL` matches the doctrine. No other enforcer string states the old whole-shelf rule: `:1347`, the "No preview this turn" fallback, and `:2749`, PREVIEW_TAIL, still require a search, which is correct. Adapters (`adapters/*`) pass the hook text through without rewriting it (grep found no handling of offer text). `doctrine.py` `_harness_adapt` (`:138-`) rewrites only tool and slash names, and the draft adds none. The doctrine selftest passes, including the OMP rendering.
3. **Audit.** Timing ✓ (Truth 7). The 4-tuple and every caller ✓ (Truth 9). Set and reset of `shelf_top`: findings 4 and 10. False positives: findings 1 and 3.
4. **Stale "two sources" text.** Current-state surfaces are updated: AGENTS.md:29, openwiki `enforcement-gate.md:37-55`, SKILL.md:48-51. The remaining hits are historical records and are correct to keep: CHANGELOG:963, README:516 (the 0.47.1 release note), ADR-0056:42, ADR-0062:25, `docs/adr/README.md:67` (0056's row), and `docs/skill-first-enforcement-mental-model.md:225-240` (an old doctrine quoted as history). Stale in-scope text: finding 9.
5. **Tests.** All green (raw output above). The draft's new test covers the five cases it names. It misses the cases in findings 1, 3 and 4.
6. **Over-engineering.** Nothing material. The 4-tuple, the contract test `test_whole_shelf_head_matches_the_enforcer` and the separate `shelf_skip` tally are each needed. The maintainer note at `skill-first.md:18-19` repeats the ADR, but it sits outside the injected body, so it costs nothing per turn. Finding 5's fix also shortens the doctrine.

## Unverifiable items

- Whether models actually write hollow reasons under the new line. That can only come from live traffic (W40).
- Whether the multi-intent "N intents" note ever appears on a whole-shelf offer in practice. MULTI_INTENT is OFF in this machine's Claude Code, and I did not query other harnesses' ledgers.
- I did not read the analysis and validator reports in full for verbatim client prompts (finding 2 asks the author to check this).

## Context gaps

- None blocking. I did not re-derive the evidence numbers; I relied on the analysis report as corrected after `validator-261007-2024-forced-search-value.md`.

## Unresolved questions for the caller

- Finding 6: should the ruling cover each intent's lead (a doctrine change plus an audit check of the first N rows), or stay at row 1 with the gap written into the ADR? My pick is the second: it is smaller, and MULTI_INTENT is off where most traffic runs.
- Finding 2: where should `turns*.jsonl` live? My pick is `~/.claude/skill-concierge/forced-search-value/`, following the jev-calibration precedent.

Status: DONE_WITH_CONCERNS
Summary: The doctrine and the enforcer line are consistent with each other. They keep the forced search for previews, and nothing in them allows a skip by naming a row other than the top one. The audit that W40 relies on is unsound, though. `_shelf_skip_ok` uses a substring test, so naming row 2 passes whenever row 1's name is part of it (`git` inside `ak-git`, `pr` inside "project"). A ruling with no reason passes. A prefixed top row named bare is rejected, which contradicts ADR:48. A later preview in the same audit turn does not clear the whole-shelf top. That is a blocking FAIL against ADR decision 4's own contract; the fix is about ten lines (parse the name token, compare with `norm`/`_same_skill`, reset on every enforcer output, plus three tests). Separately, the lever directory the ADR cites holds about 80k characters of client prompts in an untracked, unignored folder of a public repo, and those files must stay out of the release commit. Medium items: red-flag rows 2-4 and the worked example still order SEARCH unconditionally; the top-row check ignores multi-intent leads and annex rows; the ADR does not record why ADR-0056's "fix the getaway wording" alternative was rejected, though the HOIVU diagnosis already holds that evidence. All requested tests pass: 58 pytest, audit selftest exit 0, enforcer and doctrine selftests OK, 20 router tests, driftcheck 0.
