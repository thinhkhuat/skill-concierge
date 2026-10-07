# Opus Validation Report

**Subject:** logic (read-only transcript analysis)
**Scope:** `plans/reports/analysis-261007-2024-forced-search-value-after-whole-shelf.md`, its lever `plans/261007-2024-search-value-after-whole-shelf/search_value.py`, outputs `run2.txt` / `turns.jsonl`, the helpers it imports from `skills/skill-usage-audit/scripts/audit_skill_usage.py`, and raw `~/.claude/projects/**/*.jsonl` transcripts
**Verdict:** FAIL. The headline claim holds and was confirmed independently, but three stated facts are wrong and need correcting before the report stands as the record.
**Date:** 2026-10-07, 20:28-20:40 Asia/Saigon
**Evidence Files Examined:** 14 (report, lever, run2.txt, turns.jsonl, audit helper, doctrine, 8 session transcripts)

## Executive Summary

The headline result holds. On organic work turns, no `search_skills` call made after a whole-shelf ranking surfaced a skill that the ranking lacked and the agent then used. I confirmed this twice: by re-running the lever, and with a separate per-search scan that does not use the lever's turn splitting. Every number in the report reproduces exactly. Three supporting claims are false, though. "2 of 49" all-session cases is really 3 discovery cases plus 1 name lookup, and the script hides them through its class ordering and through turns merged from queued prompts. Prompts queued mid-turn are called "rare", but they make up 16.9 % of whole-shelf offers. The 41 "used a skill not in the offer" turns are described as the agent's own shelf knowledge, but 23 of them are explicit `(continuing)` rulings. The implication paragraph points in a defensible direction, but it rests on a smaller and more selected sample than it admits.

## Observable Truths

| # | Claim | Status | Evidence |
|---|-------|--------|----------|
| 1 | Organic table (8 classes x 3 epochs) | ✓ VERIFIED | Re-run at 20:28:23; the first 51 lines of `/tmp/sv-check.txt` are byte-identical to `run2.txt`; `cmp turns.jsonl /tmp/sv-check.jsonl` gives IDENTICAL. No numbers moved: no new whole-shelf turns between 20:27 and 20:28. |
| 2 | 24 of 252 organic turns searched, 31 calls | ✓ reproduces / ⚠ overstated | Re-run: `organic whole-shelf work turns: 252; searched: 24; search calls: 31`. 7 of the 28 unique organic queries were made after a *harness-message* `SKILL-CHECK` (6) or a *preview* offer (1), not after a whole-shelf ranking (detail below). |
| 3 | 0 organic `search_new_hit` | ✓ VERIFIED | Lever output, plus an independent per-search scan (`/tmp/sv_indep.py`): 0 organic searches under a whole-shelf offer were followed by use of a skill in the hits but not in the offer. The two organic hits it did find (`tk-create-docx` 10-07 16:16, `directional-prompting` 10-05 20:05) ran under an intent-margin `SKILL-CHECK` and a "No preview this turn" offer, so they are out of scope. |
| 4 | All sessions: search found the used skill on 2 of 49 searched turns | ✗ FAILED | The true count is 3 discovery cases plus 1 lookup of a skill the user had named. Missed: 10-06 23:05 `critical-thinker` (session 7aed91c6) and 09-27 23:07 `writing-for-agents` (5a429ce1), both classed `search_offer`. All 4 are in skill-concierge sessions. |
| 5 | 63 % of hits and 51 % of top-1 hits are `antigravity-*` | ✓ VERIFIED | 49 turns, 60 calls, 350 hits: 62.6 % / 50.8 % (`/tmp/sv_stats.py`). |
| 6 | Rank of the used offered skill: 1:85, 2:27, 3:15, 4:12, 5:3 | ✓ VERIFIED | Same counts per used skill and per turn (142 = direct_offer 136 + search_offer 6). No used skill matched an offer row only by suffix. |
| 7 | 41 direct_other turns = "the agent's own knowledge of the shelf did the job a search is supposed to do" | ✗ FAILED | 23 of 41 open with `USING: <skill> (continuing)` (`/tmp/sv_cont.py`), the doctrine's lawful continuation route (`hooks/doctrine/skill-first.md` rule 3 "Continuing a skill"), not shelf knowledge. 2 more were named in the prompt. |
| 8 | Unsplit queued prompts are "Rare; it can only move a turn between the search classes" | ✗ FAILED | 79 of 468 unique whole-shelf offers (16.9 %) came from `queued_command` attachments; 52 of them organic. Each one overwrites the enclosing turn's offer (`search_value.py` sets `cur["prim"], cur["annex"] = offer_rows(out)` on every offer) and never becomes its own turn. That shrinks the denominator and swaps the offer used for the in-offer test, which is how #4 lost `critical-thinker`. |
| 9 | Epoch start 76586ae; splits at 45ad2d9 / 88a01c0 | ⚠ PARTIAL | Hashes and times are correct (`git log`: 2026-09-26 21:20, 10-03 12:57, 10-06 23:21). The columns still pool later epoch commits: b847af9 (10-04 01:15, enforcer.py 316 lines changed), b4e6c3f (enforcer), and 399b6e2/57e97c3/8d73dc4/a16f3c9/bd2c14b (server.py, the retrieval behind `search_skills`). |
| 10 | Example turns (HOIVU 13:28 html-artifact-audit; "kill suspended shell job"; "broadcast message"; HOIVU 17:23 i18n at rank 6) | ✓ VERIFIED | `run2.txt` list output plus a raw dump of 832d2916 at 10:23:44Z. |
| 11 | Report window "20:24-20:45" | ⚠ INCONSISTENT | The report file's mtime is 20:27:58 and the lever outputs are 20:26-20:27, so 20:45 is after the file was written. |

## Key Dependency Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| search_value.py | audit_skill_usage.py | `sys.path` import; `norm`, `_same_skill`, `_prompt_text`, `_hands_over_work`, `_enforcer_output`, `_declared`, `_loaded_skill` | ✓ | Bodies read at lines 147-228. `_enforcer_output` accepts only `hook_additional_context`/`UserPromptSubmit` attachments. |
| offer parser | all whole-shelf offers | `HEAD` substring in enforcer output | ✓ | Census (`/tmp/sv_heads.py`): 673 head-bearing records in main transcripts are enforcer attachments. The rest are CLAUDE.md `instructions`, tool results and subagent records, none of them offers. No offers missed. |
| hit parser | search_skills results | JSON `results[].name`, regex fallback | ✓ | 831 results surveyed; 8 key shapes, all carrying `results`. 15 non-JSON: connection errors, rejections, and 2 from session 754a9f4c that the regex fallback parses correctly. |

## Blocking Issues (FAIL)

1. **False negatives for search value: the script's own target class misses real cases** (Truth #4). Two mechanisms:
   - (a) `classify` tests `search_offer` before `search_new_hit`. Any turn that used one offered skill plus a new search hit lands in `search_offer`.
   - (b) Queued prompts merge into the enclosing turn, and the last offer overwrites the governing one.

   The proven case: session 7aed91c6, 2026-10-06T16:05:09Z. A queued side-agent note produced an offer of `skill-concierge:skill-usage-audit, agent-skills:using-agent-skills, graft, prime-codebase, jevd`. At 16:05:29Z the agent ran `search_skills` "experiment design selection bias in evaluation labels, stratify results", got `critical-thinker` at rank 2, and invoked `Skill critical-thinker` at 16:05:35Z. The row stores the 16:08:44 offer `['which-skills','jevd',…]`, and because `jevd` was used it scores `search_offer`. Also missed: 5a429ce1 at 16:07Z, `writing-for-agents`, which the user named ("USING: writing-for-agents (per your note; finding it first)"). That one was a lookup, not a discovery.
   - **Impact:** the all-session figure becomes 3 (discovery) or 4 (with the lookup) of 49, not 2. The organic figure stays 0: the only organic candidate, 754a9f4c 09-27 13:48 `tk-gdelt-doctor`, was a findability test of a skill created that same turn, run under a harness-message `SKILL-CHECK` at 06:55Z (raw trace: `reindex` → `search_skills` → `get_skill tk-gdelt-doctor`).
2. **"Rare" is false** (Truth #8): 16.9 % of whole-shelf offers arrive through `queued_command`. The Limits section needs restating. Its effect also goes beyond moving turns between classes: it drops turns from the denominator and swaps the offer.
3. **Wrong characterization of the 41 direct_other turns** (Truth #7): 23 of them are `(continuing)` rulings. The sentence "the agent's own knowledge of the shelf did the job a search is supposed to do" is unsupported for most of the class.

## Advisory Suggestions (WARN)

1. **Searches are attributed to whole-shelf turns that did not govern them.** `isMeta` cross-session messages and `queued_command` attachments do not open turns, so a search made 22 minutes later in answer to a peer message lands in the earlier turn. Example: c00e3833, prompt 16:40:01Z, search at 17:02:43Z after a harness-message `SKILL-CHECK` at 17:02:33Z. Of the 28 unique organic queries, 7 were not made under a whole-shelf offer (`/tmp/sv_gov.py`), so the true searched-after-whole-shelf count is about 22 turns. The zero stands, but n is smaller than stated.
2. **The sample is small and selected.** 0 of ~22-24 gives a 95 % upper bound near 13 % on how often a search finds what the ranking missed (rule of three). The searched turns are also the ones where agents chose to search. The forced search was never run on the 35 `NO SKILL:` turns, so its counterfactual value there is unmeasured. "Has not once supplied" is accurate; "costs nothing to drop" is an inference.
3. **The uptake-only metric misses partial value.** For 4961eefc at 09-27 15:00, the search's top hit was `antigravity-brainstorming` and the agent used the installed `ak-brainstorm` 5 s later. Name matching cannot credit that. HOIVU 17:23 returned a fitting `antigravity-i18n-localization` that the agent ignored. Neither case changes the conclusion, but both should be listed as limits.
4. **Epoch pooling** (Truth #9). The zero count is not inflated by pooling. The antigravity-share figure, however, pools across five server.py retrieval commits, against AGENTS.md's telemetry rule. Either split at those commits or state the pooling.
5. **The doctrine edit came before this validation.** `hooks/doctrine/skill-first.md` was modified (uncommitted) at 20:34:29 and already carries the proposed rule ("A whole-shelf ranking is the third skip source since ADR-0082 (Proposed)"). That is legitimate if it is a draft under RULES [4], but the report's corrections should be applied before it is promoted.
6. **Classifier ordering.** If the lever is kept, rank `search_new_hit` above `search_offer` (or record both), and split turns on `queued_command` prompts that carry their own enforcer offer.

## Validation Dimensions

- [x] Reproduction: PASS. Every reported number reproduces exactly (Truths 1, 2, 3, 5, 6).
- [x] Turn segmentation: WARN/FAIL. A tool_result does not open a turn (correct: `_prompt_text` returns None for tool_result lists). But `queued_command` prompts and `isMeta` messages do not open turns, while task-notification string records do (dump of 754a9f4c at 07:34:15Z: a `<task-notification>` PROMPT opens a turn).
- [x] Search detection and hit parsing: PASS. The tool-name test covers the MCP name, and the parser handled every result shape found.
- [x] Used-skill matching (`norm` + `_same_skill`): PASS on the data. No suffix-only matches occurred. `_same_skill` can over-match across authors (`writing-for-agents` ~ `mattpocock-skills-writing-for-agents`); that happened only in a meta turn.
- [x] Resumed-copy dedupe: PASS. The key `(prompt[:200], int(t))` collapses copies, and the per-search scan (deduped by tool_use id) agrees.
- [x] Organic filter: PASS as defined (`"skill-concierge" in cwd`, `_hands_over_work`).
- [x] Whole-shelf coverage: PASS. The head census found no offers in an unparsed format.
- [x] False-negative hunt (task 3): FAIL. Found 2 misclassified turns, both meta sessions. Found 0 organic.

### Hand-checked turns (raw transcripts)

1. 832d2916 at 10:23:44Z, HOIVU 17:23 `search_none`: confirmed. The search hits had no i18n row above rank 6; the agent edited via Bash.
2. 754a9f4c, 13:48 `search_offer`: a findability test of a newly created skill under the harness lane. Not search value.
3. 5a429ce1, 23:05 `search_offer`: a user-named lookup. Misclassified, but not a discovery.
4. 7aed91c6, 22:57 `search_offer`: a real discovery (`critical-thinker`). Misclassified.
5. 7aed91c6 at 14:04Z, `search_new_hit` `architecture`: genuine. The `architecture` hit was at rank 6 and the agent ruled `USING: architecture` 4 s after the search.
6. c00e3833, 23:40 `search_offer`: confirmed `USING: ak-code-review` from offer row 1 at 16:40:08Z. The search came from a later peer message.
7. 4961eefc, 15:00 `search_new_other`: confirmed. The search returned `antigravity-brainstorming` and the agent used `ak-brainstorm`.
8. 51c0b1e6, 21:36/21:37 `direct_skip`: confirmed. "NO SKILL: this is a status check…" with no search.
9. 8690000d at 18:26Z (10-03 01:26), `search_new_other`: confirmed. The search hits lacked `unlazy`; the Skill `unlazy` call followed.
10. 14904909, 10-05 20:05 (out of scope): the search was governed by "No preview this turn". `directional-prompting` was used.

## Verdict on the main claim and the implication

- **Main claim ("Almost never… in none of the 24 did the search surface a skill… that the agent then used"): VERIFIED.** It holds under an independent method that does not rely on the lever's turn splitting.
- **All-session risk sentence: FALSE as stated.** The correct figure is 3 discovery cases plus 1 lookup out of 49, all in skill-concierge sessions; the qualifier "where the agent searched with specific terms" still fits.
- **Implication paragraph: directionally supported, overstated in its basis.** Organic searches after whole-shelf rankings have not produced uptake, so making the search optional while keeping it allowed is consistent with the data. Two things are not shown by the data: that the forced search is worthless (n ≈ 22, upper bound about 13 %, a selected sample, no counterfactual on `NO SKILL:` turns), and that the 41 direct_other turns show shelf knowledge (most are continuations). "Legalizes what agents already do on 13.9 % of turns" is accurate.

## Unverifiable Items

- Whether the Claude Code timestamps or the `date` clock explain the "20:45" end time. Not checked beyond the file mtimes.
- Harnesses other than Claude Code (the report says so itself).

## Context Gaps

- ADR-0082 (Proposed) was not read. Whether the doctrine draft is meant to stay a draft until validation is unknown to me.
- A `.harnesskit/` directory appeared in the lever directory at 20:28:17, the moment this validator started. None of my commands created it; it appears to be a hook artefact.

Scratch scripts used for verification (outside the repo): `/tmp/sv_stats.py`, `/tmp/sv_fn.py`, `/tmp/sv_indep.py`, `/tmp/sv_queued.py`, `/tmp/sv_gov.py`, `/tmp/sv_cont.py`, `/tmp/sv_rank.py`, `/tmp/sv_heads.py`, `/tmp/sv_dump.py`, `/tmp/sv_turn.py`; re-run output `/tmp/sv-check.jsonl`, `/tmp/sv-check.txt`.

Status: DONE_WITH_CONCERNS
