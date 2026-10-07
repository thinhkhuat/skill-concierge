# Does the forced search after a whole-shelf ranking find skills the ranking missed?

Date: 2026-10-07, first pass 20:24-20:28, corrected 20:55 after the independent validation
(`plans/reports/validator-261007-2024-forced-search-value.md`). Read-only analysis.
Method follows the `skill-concierge:skill-usage-audit` skill: the transcript store, not the invocation ledger.

## Answer

Almost never. On organic work turns (not skill-concierge sessions, prompts that hand over work), agents
searched after a whole-shelf ranking on 22 of 305 turns (22 calls). In none of the 22 did the search
surface a skill the ranking had not shown that the agent then used. Zero of 22 is a small, self-selected
sample: the 95 % upper bound on the true rate is about 13 %, and nobody measured what a forced search
would have found on the 36 turns that skipped without one.

Across all sessions, including skill-concierge's own, a search found a skill the ranking missed and the
agent used it on 3 of 46 searched turns, all three in skill-concierge sessions (10-06 21:03 `architecture`,
10-06 23:05 `critical-thinker`, 10-07 20:24 `skill-concierge:skill-usage-audit`). One more turn looked up a
skill the user had named (`writing-for-agents`).

The forced search is mostly not performed: agents ruled `NO SKILL:` with no search on 36 turns (11.8 %).

## Numbers

Source: every `~/.claude/projects/**/*.jsonl` transcript modified since 2026-09-26 21:20 (subagent files
skipped), deduplicated across resumed-session copies; a prompt typed while the agent works (a
`queued_command` attachment) opens its own turn. Epoch start = the 0.52.3 doctrine commit (76586ae); the
doctrine's search rule has not changed since. Columns split at the 0.56.0 (45ad2d9) and 0.59.0 (88a01c0)
enforcer commits; later enforcer and retrieval commits inside a column are pooled, which cannot create the
zero but does pool the hit-quality share below.

Organic work turns that got a whole-shelf ranking:

| Outcome | 0.52.3 | 0.56.0 | 0.59.0 | Total |
|---|---|---|---|---|
| Used a skill from the offer, no search | 117 | 28 | 15 | 160 (52.5 %) |
| Continued a skill already in play (`USING: <x> (continuing)`), no search | 20 | 4 | 0 | 24 (7.9 %) |
| Used another skill not in the offer, no search | 10 | 3 | 0 | 13 (4.3 %) |
| `NO SKILL:` without a search | 27 | 7 | 2 | 36 (11.8 %) |
| Searched, used a skill the offer already had | 3 | 1 | 0 | 4 (1.3 %) |
| Searched, used a new skill the search returned | 0 | 0 | 0 | **0** |
| Searched, used a skill from neither | 2 | 1 | 1 | 4 (1.3 %) |
| Searched, used no skill | 11 | 1 | 2 | 14 (4.6 %) |
| No ruling read, no skill (mostly queued prompts answered mid-reply) | 33 | 13 | 4 | 50 (16.4 %) |
| Total | 223 | 58 | 24 | 305 |

When a used skill was in the offer, it sat at rank 1 in 101 turns, rank 2 in 30, 3 in 16, 4 in 12, 5 in 5.

Search-hit quality (all 46 searched whole-shelf turns, 292 hits, epochs pooled): 65 % of hits are
`antigravity-*` external-catalogue rows. Examples: "kill suspended shell job process" returned `refactor`
and five antigravity refactoring rows; "broadcast message to all running peer sessions" returned Telegram
and Azure messaging rows.

## What the turns look like (hand review, judgment)

- The 36 search-free `NO SKILL:` turns are mostly status and chat: "where are we now", "how's the test
  doing so far?", "I freed the snapshot myself mate", "he's capable. its fine".
- The 4 "used a skill from neither" turns: the agent picked the skill from its own knowledge after a
  search that did not return it (10-07 13:28 HOIVU: searched "audit an HTML artifact for layout defects",
  got six antigravity rows, used `html-artifact-audit` anyway).
- The 4 "offer already had it" turns: the search confirmed the offer's own row.

## Side finding

The HOIVU 17:23 search ("set default UI language of a bilingual static web page") returned
`antigravity-i18n-localization` at rank 6, behind `progress-map`, `tavily-extract` and others. This closes
the open question in `diagnosis-261007-1752-hoivu-default-vi-routing-misfires.md`.

## Implication

Making the search after a whole-shelf ranking optional, not forced, fits the data: on organic traffic it
did not once supply the skill the agent used, it costs a tool round, and its hits are mostly external
rows. The evidence is thin (0 of 22, upper bound about 13 %) and the searched turns chose themselves, so
the change needs a live watch rather than a one-time proof. Every search that did find a missed skill came
from skill-concierge's own sessions, where the agent searched with specific terms.

## Corrections after validation (20:55)

- First pass said 24 searched of 252 turns and "2 of 49" overall. A classification-order bug filed a turn
  that used both an offered skill and a new hit as "offer already had it", and prompts queued mid-turn were
  merged into the turn before them, overwriting its ranking. Both fixed in the lever; the corrected counts
  are above (22 of 305 organic; 3 of 46 overall).
- First pass called queued prompts "rare". The validator measured 79 of 468 whole-shelf rankings (16.9 %).
  Retracted.
- First pass described 41 off-menu turns as the agent's shelf knowledge. Most were continuations of a skill
  already in play (24 of 37 after the fix). Retracted.
- First pass's header gave an end time (20:45) after the file was written (20:27). Corrected.

## Limits

- Claude Code transcripts only; Codex, OMP and the other harnesses are not read.
- The ruling is read from the first assistant text of the turn; 50 turns had none readable, mostly queued
  prompts the agent answered inside an ongoing reply.
- "Used" means a Skill-tool or `get_skill` load, or a `USING:` line not retracted by a re-rule. Whether the
  used skill was the right one is not judged.
- The 0.59.0 column (24 turns) is too small to read on its own.

## Artifacts

- Lever: `plans/261007-2024-search-value-after-whole-shelf/search_value.py`
  (`--list <class>` prints turns for review; `--json` writes every scored turn)
- Raw output and scored turns hold prompt text, so they live outside the public repo:
  `~/.claude/skill-concierge/analysis-private/261007-2024-search-value-after-whole-shelf/`
  (`run3.txt` corrected, `run2.txt` first pass, `turns-v2.jsonl`, `turns.jsonl`)

## Open questions

- Should the change also cover "Preview" offers (the embedding path)? Not analysed.
- The external-row flood in `search_skills` hits is a separate defect; is it worth its own look?
