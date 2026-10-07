# Jev "work or conversation?" gate, and source-reputation tiers: replay results

Date: 2026-10-07 (GO order). No hook or doctrine code changed. Scripts, raw outputs and the decisions log:
`plans/261007-1813-jev-turn-type-gate-replay/`.

## Verdict

1. A prompt-level "work or conversation?" Jev question separates real skill turns from the rest only
   weakly. With no real skill turn lost (bar 0.15) it skips 0.3 % of traffic; on top of today's fits floor it adds no skips at 0.15 or 0.20 (validator). In Thinh's history, many conversational-looking turns did
   use a skill (recap, whereami, noob-mode, brainstorm, git status), so "conversation" does not mean
   "no skill".
2. A hard reputation tier (pstack / Matt Pocock / ak-* always first) makes the offer worse: the skill the
   agent really used drops out of the 5-row offer in 28 of 177 turns, and ranks first in 37 turns instead
   of 100. A soft boost (+0.10) is also net negative (2 gained, 9 lost).

## Method

- Corpus: `~/.claude/skill-concierge/jev-calibration/real-turn-labels.jsonl` (behavioural labels, no hand
  labels), same selection rules as `scripts/calibrate_jev_gate.py`: English, interactive, outside
  skill-concierge's own sessions, reaching the Jev gate.
  - pos: 313 turns where the agent loaded and used a skill that same turn.
  - neg: 85 turns labelled NO_SKILL (searched then skipped, or skipped as conversation).
  - unl: 300 hash-ordered traffic turns.
- Jev via jevd pinned to Command Code (`typesafe/jev`), state = live `ctx` variant. 628 turns scored,
  0 failures, latency p50 744 ms, p90 940 ms.
- Questions: `work` ("is the user asking the assistant to carry out a task now…") and `convo` ("is this
  only conversation… with no new work", inverted). `both` skips only when both agree.
- "False-NO" = a real skill turn the gate would skip; 95 % Wilson upper bound in brackets.

## Turn-type results (`curve.txt`)

| gate `both` below | real skill turns lost | no-skill turns skipped | traffic skipped |
|---|---|---|---|
| 0.15 | 0.0 % (1.2 %) | 2.4 % | 0.3 % |
| 0.20 | 1.0 % (2.8 %) | 5.9 % | 0.7 % |
| 0.25 | 1.6 % (3.7 %) | 9.4 % | 2.0 % |
| 0.30 | 3.2 % (5.8 %) | 10.6 % | 5.3 % |

For comparison, today's `fits` floor 0.30 loses 0.3 % and skips 3.0 % of traffic (2026-10-07 curve on
cached catalogue f65af73783c60a68).

This session's probes (bare state): the three conversational turns scored `both` 0.19, 0.58, 0.13; the
"GO pls" turn 0.86; the HOIVU one-liner 0.88. A bar of 0.20 would catch two of the three and neither work
turn. The HOIVU one-liner is a work turn: no turn-type question skips it.

The 29 real skill turns with `work` < 0.30 are mostly questions that a skill served: "so where am i now"
(git), "what have we done last session?" (recap), "explain M5, … noob-mode" (noob-mode), "lets discuss R9
further" (ak-brainstorm), "is everything ready to get deployed?" (pre-release-review). Full list in
`curve.txt`.

Caveat: "used a skill" is what the agent did under the SKILL-FIRST doctrine, which pushes skill use, so
some positives may be turns where the skill was not needed. Behavioural labels cannot separate the two.

## Baseline: the embedding conversational gate ADR-0061 bypasses (`intent-baseline.txt`)

It skips 11.8 % of real skill turns (UCB 15.9 %), 32.9 % of no-skill turns, 22.3 % of traffic, and none
of this session's three conversational probes. ADR-0061 was right to bypass it on Jev turns
(`hooks/scripts/enforcer.py:3104`); this corrects the 18:07 handoff, which called the bypass unanalysed.

## Cookbook prompt-level gates, cached (`offline-curves.txt`)

The 2026-09-26 run's three TypeSafe cookbook gates and the ADR-0060 question, on the same populations
(only 25 of 85 no-skill turns cached). Best: `prose_suffices`, ctx, below 0.40 loses 2.9 % and skips
24 % of no-skill turns and 8.2 % of traffic. None beats the new `both` gate by a margin the small neg
sample can show.

## Reputation tiers (`reputation-sim.txt`)

Cached Jev wide answers for the 313 real skill turns; live offer = top 5 of Jev's 10-row shortlist.
Families of the skill actually used: other 261, ak 46, Matt Pocock 7, pstack 0 (the Matt Pocock links
date from 2026-10-06 and pstack's install is also recent, so the corpus barely covers them).

| policy | used skill ranked 1st | used skill in the 5-row offer | vs Jev order |
|---|---|---|---|
| Jev order (today) | 100 (31.9 %) | 177 (56.5 %) | — |
| soft +0.10 for reputable | 100 (31.9 %) | 170 (54.3 %) | 2 gained, 9 lost |
| strict tier first | 37 (11.8 %) | 151 (48.2 %) | 2 gained, 28 lost |

Re-ordering only inside Jev's shortlist is the most favourable case for the idea; a tier over the whole
catalogue would also pull in skills Jev never shortlisted.

## Open questions

- Whether the `both` gate is worth shipping as a soft signal (menu still shown, search not forced) for the
  ~1 % it can safely catch; the measured traffic benefit is small (0.7 % at 0.20).
- Whether reputation is worth testing in its narrow form: a tie-break among skills that do the same job
  (duplicates such as `code-review` vs `ak-code-review` vs `agent-skills:code-review`). Not measured.

## Validator corrections (2026-10-07, independent agent)

Report: `plans/reports/validator-261007-1814-turn-type-and-reputation-replay.md`. Every quoted number
reproduced byte-for-byte from cached data; method sound. Corrections, now applied above where stated:

- Verdict 1 is stronger than first written. The earlier "can safely skip about 1 % of turns" was too high:
  with zero real skill turns lost the gate skips 0.3 % of traffic; at 0.20 it removes real skill turns
  (1.0 %) faster than it trims traffic (0.7 %); stacked on today's fits floor (135 traffic turns with both
  answers) it adds no skips at 0.15 or 0.20, and at 0.20 lost real skill turns rise from 1 to 4.
- Verdict 2 holds for ak-* and Matt Pocock only. pstack has 0 rows in the cached catalogue's shortlists,
  so the pstack part was never tested. The metric rewards agreement with past agent choices, which
  favours the existing order; at 28 lost vs 2 gained the direction still holds.
- The traffic sample here (seed 0) differs from calibrate_jev_gate's default sample, and the fits-floor
  comparison is on a different model id (jev-1.13.0 vs Command Code's typesafe/jev). Docstring fixed.
- The five probe scores were not saved and were not re-checked (re-running them is a paid call).

## Where the raw outputs live (moved 2026-10-07 21:00)

`curve.txt`, `offline-curves.txt` and `answers.jsonl` quote prompt text or carry private corpus turn ids,
so they moved out of the public repo to
`~/.claude/skill-concierge/analysis-private/261007-1813-jev-turn-type-gate-replay/`. The scripts stay in
`plans/261007-1813-jev-turn-type-gate-replay/`; `live_turn_type_replay.py` now writes there.
