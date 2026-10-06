# A/B/C test: does Jev pick the right skill more often when it sees more of each skill's text?

**Answer: no.** Neither richer text raised recall of the skill the user actually used. Both are "not proven" under the
rules fixed before the run, and both scored slightly below today's text.

Run 2026-10-06 23:08-23:15 (Asia/Saigon), ordered by Thinh ("200 turns + noise check"). Written up by the main session
from the run agent's results; every number below was re-read from `_RESEARCH_ARTIFACTS/results.json` and jevd's own
call log.

## What was tested

Jev's wide pass ranks all 567 skills in 3 chunks and keeps the top 5 of each chunk, a 15-name shortlist. Each skill
appears as a short text. Four versions of that text:

| Version | Text per skill |
|---|---|
| A | today: the description, first 160 characters |
| A2 | A sent again, to measure how much Jev disagrees with itself |
| B | the skill's "use this when…" line (`when_to_use`) first, then the description, 160 characters |
| C | the description (160) plus up to 3 flywheel example requests, at most 320 characters |

Answer key: the skill the user actually invoked on that turn. Primary measure: is it in the 15-name shortlist?

**Sample:** 200 English turns (fixed seed), drawn only from turns where the hook's offer could not have shaped the
choice: the used skill was not in the offer, or no offer was recorded. This answers the side-agent concern that an
offer ranked from today's text would tilt the answer key toward version A. The rule was written into `prereg.md`
before the first call.

## Result

| Version | Recall | Gains vs A | Losses vs A | p (exact McNemar) | p (Holm) | Decision |
|---|---|---|---|---|---|---|
| A | 79.0 % (158/200) | – | – | – | – | baseline |
| A2 | 79.0 % (158/200) | 1 | 1 | 1.00 | – | noise floor |
| B | 78.0 % (156/200) | 1 | 3 | 0.625 | 1.00 | not proven |
| C | 77.5 % (155/200) | 4 | 7 | 0.549 | 1.00 | not proven |

- **Noise floor (fact):** A and A2 disagreed on 2 of 200 turns (1 %). Command Code's Jev is nearly deterministic.
- **What the run could detect (fact):** for C, a change of about 5 points or more (80 % power). B changed only 4
  turns in total, so it could not have been proven either way: B rewrites only 116 of 567 skills, and only 60 sampled
  turns used one of them. On those 60, A found 45 and B 43 (0 gains, 2 losses).
- **Inference:** a gain from C of 5 points or more is unlikely; a smaller gain cannot be ruled out.
- **Mean reciprocal rank (secondary, untested):** A 0.504, A2 0.510, B 0.496, C 0.518.
- **Exploratory, not pre-registered:** on the 149 turns whose prompt did not name the skill, A 71.8 %, B 70.5 %,
  C 70.5 %.

## Cost and safety

- **Calls:** 805, all to Command Code through jevd (800 answered, 5 failed and succeeded on their one retry).
  jevd's own log for 23:08-23:16 shows 800 `commandcode` 200s and 5 pinned 502s, and **no TypeSafe call**.
  TypeSafe was removed in code (key unset, only the `commandcode` rung allowed, asserted before the first call).
- **Input tokens (estimate, the hook's own counter, not billed usage):** 25.2M (A 5.7M, A2 5.7M, B 5.6M, C 8.3M).
- **Wall time:** 6 min 22 s; latency p50 about 1.3-1.4 s per wide call.

## Caveats

- Command Code serves the unpinned `typesafe/jev`; results compare the versions with each other, not with the 0.30
  fit floor tuned on `jev-1.13.0`.
- The answer key is the skill the agent invoked, which is not always the best skill.
- Turns the offer could not shape lean toward cases where the agent picked a skill itself, often by name (51 of 200
  named it). Results may not carry over to turns where the agent took an offered skill.
- Only the wide pass was tested; the rerank and the final offer were not.
- Only 1 of the 200 turns came after the Jev router went live (2026-09-26 09:47), so no before/after split is readable.

## Recommendation (judgment)

Keep today's text. The flywheel example requests stay where they help today, the embedding search. Revisit only if a
larger, B-focused test is wanted: one that samples only turns whose used skill has a `when_to_use` line.

## Open questions

1. Retest B on turns whose used skill has `when_to_use` only? It is the only fair test of B; about 200 such turns
   would be needed for a 5-point effect.
2. Does pinned `jev-1.13.0` on TypeSafe behave the same? Needs Thinh's yes before any TypeSafe call.

## Files

`prereg.md` (unchanged after the first call), `abc_wide_recall.py`, and `_RESEARCH_ARTIFACTS/` (`catalog.json`,
`questions.json`, `sample.json` with turn ids only, `prep-meta.json` with the enforcer's sha256, `pilot.json`,
`calls.jsonl`, `results.json`, `run.log`).
