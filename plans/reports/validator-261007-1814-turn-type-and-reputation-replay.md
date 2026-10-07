# Opus Validation Report

**Subject:** logic (offline replay analysis)
**Scope:** `plans/reports/analysis-261007-1814-jev-turn-type-gate-and-reputation-tiers.md` and its scripts/outputs in `plans/261007-1813-jev-turn-type-gate-replay/`
**Verdict:** NEEDS_REVIEW
**Date:** 2026-10-07
**Evidence Files Examined:** 12 (report, 4 replay scripts, 4 saved outputs, decisions-log.md, score.log, `scripts/calibrate_jev_gate.py`, `hooks/scripts/enforcer.py`, the 1752 diagnosis report, the 1807 handoff)

## Executive Summary

All quoted numbers reproduce. The three offline scripts I was asked to run, plus `intent_gate_baseline.py` and the fits-floor curve, give byte-identical output. The method has no error that reverses either verdict. Both verdicts claim more than the data shows. Verdict 1's "can safely skip about 1 % of turns" is too high: at the threshold with zero real-skill losses, the gate skips 1 of 300 traffic turns (0.3 %). Stacked on today's `fits` floor, it adds no skips at 0.15 or 0.20. Verdict 2 names pstack as part of the tier, but no pstack skill appears in the cached catalogue the simulation uses. Only the ak-* and Matt Pocock skills were tested.

## Observable Truths

| # | Claim | Status | Evidence |
|---|-------|--------|----------|
| 1 | `both` table rows at 0.15/0.20/0.25/0.30 (loss, UCB, no-skill skipped, traffic skipped) | ✓ | `curve.txt` "both" block; re-run byte-identical |
| 2 | pos 313, neg 85, unl 300; 628 turns scored, 0 failures | ✓ | `curve.txt:1`, `score.log`; my overlap check: pos∩unl 51, neg∩unl 19, pos∩neg 0, union 628 |
| 3 | latency p50 744 ms, p90 940 ms | ✓ | `curve.txt:2` |
| 4 | 29 real skill turns with `work` < 0.30; quoted examples and their skills | ✓ | `curve.txt` "positives with work < 0.30 (29)" list (git, recap, noob-mode, ak-brainstorm, pre-release-review all present) |
| 5 | fits floor 0.30 loses 0.3 % and skips 3.0 % of traffic | ✓ | re-ran `calibrate_jev_gate.py curve --shelf wide --variant ctx --catalog-hash f65af73783c60a68`: `0.30    0.3% (  1.8%)     3.0%` |
| 6 | Embedding intent gate: 11.8 % (UCB 15.9 %), 32.9 %, 22.3 %, none of three probes | ✓ | `intent-baseline.txt`; re-run byte-identical |
| 7 | Bypass of the intent gate on Jev turns at `enforcer.py:3104` | ✓ | `hooks/scripts/enforcer.py:3104` `if not det and not _jev_rows and not _is_imperative(prompt) and _intent_conversational(vector):` |
| 8 | Offline cookbook gates: 25/85 neg cached; prose_suffices ctx <0.40 → 2.9 %, 24 %, 8.2 % | ✓ | `offline-curves.txt` (ctx block, `0.40    2.9% (  5.4%)       24.0%        8.2%`) |
| 9 | Reputation families other 261, ak 46, Matt 7, pstack 0 | ✓ (numbers) / ⚠ (explanation) | `reputation-sim.txt:1`; pstack is absent from the catalogue, not merely rare (see Advisory 3) |
| 10 | Reputation table: Jev 100/177; soft 100/170, +2/−9; strict 37/151, +2/−28 | ✓ | `reputation-sim.txt`; re-run byte-identical |
| 11 | Probe scores `both` 0.19, 0.58, 0.13; GO 0.86; HOIVU 0.88 | ? | no saved output; `cmd_probes` prints only, never writes (`live_turn_type_replay.py` `cmd_probes`); re-running would be a paid call, which the task forbids |
| 12 | Verdict 1: "It can safely skip about 1 % of turns" | ✗ (overstated) | see Advisory 1 |
| 13 | Verdict 2: "pstack / Matt Pocock / ak-* always first makes the offer worse" | ⚠ | holds for ak-* + Matt; pstack untested (Advisory 3) |
| 14 | `offline_gate_curves.py` docstring: unl is "the hash-ordered traffic sample calibrate_jev_gate uses" | ✗ | replay scripts call `cal.pick(..., 300, 0)` (seed 0); `calibrate_jev_gate.py` CLI default `--seed 20260926` (line 1177/1204 region); the two samples share 50 of 300 turns |

## Key Dependency Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| live_turn_type_replay.py | calibrate_jev_gate.pick / reaches_gate / wilson_upper | import `cal` | PASS | same pool filters as calibrate (`pick`, lines 202-211) |
| live_turn_type_replay.py | offline_gate_curves.is_negative | import | PASS | neg = NO_SKILL ∧ rule ∈ {searched_then_skipped, skip_nosearch_conversational} ∧ ¬meta ∧ interactive ∧ English ∧ reaches_gate |
| reputation_tier_sim.py | cached wide `which` answers (cat f65af73783c60a68, ctx) | `cal.read_cache()` | PASS | 313/313 rows, every shortlist exactly 10 names |
| reputation sim "jev" order | live `_jev_decide` | `sorted(probs, key=-p)` | PASS | `enforcer.py:1992-1995` uses the same stable sort over the same dict order; `JEV_OFFER_ROWS = 5` (`enforcer.py:1554`). 128/313 rows tie at the 5th/6th boundary, and the sim and the live hook break those ties the same way |

## Blocking Issues (FAIL)

No blocking issues found. No quoted number is wrong, and no method error reverses either verdict.

## Advisory Suggestions (WARN)

1. **Verdict 1's "safely skip about 1 %" is too high. The open question's "~1 % it can safely catch" has the same problem.** Counts behind `curve.txt`, from my recount of `answers.jsonl`:
   - `both` < 0.15: 0/313 real skill turns lost, 1/300 traffic turns skipped (0.3 %).
   - `both` < 0.20: 3/313 lost (1.0 %), 2/300 traffic skipped (0.7 %). At this bar the gate skips real skill turns at a higher rate than it skips traffic.
   - Stacked on today's `fits` floor (0.30), measured on the 135 seed-0 traffic turns that also have cached fits answers:
     - at 0.15 and 0.20 the gate adds 0 traffic skips (2 → 2 of 135), while real-skill losses go from 1 to 1 at 0.15 and from 1 to 4 at 0.20;
     - at 0.25, traffic skips go from 2 to 4 of 135 and losses from 1 to 6.

   This makes the conclusion that the gate is weak stronger than the report states. The headline figure should be about 0.3 % with zero losses. The report never measured what the gate adds on top of the existing floor.
2. **The fits-floor comparison is not paired.** The fits curve (3.0 %) runs on calibrate's seed-20260926 traffic sample, 297 cached turns. The `both` curve runs on a seed-0 sample. The two samples share 50 of 300 turns, and the answers come from different model ids (jev-1.13.0 vs `typesafe/jev` through Command Code; `decisions-log.md` item 1 states this). Each figure stands on its own, but a side-by-side reading should say the samples differ. The docstring of `offline_gate_curves.py` is also wrong about which sample it uses (Truth 14).
3. **Reputation tier: pstack was never in the test.** Of the shortlist rows across all 313 turns, 0 belong to pstack. The rows are other 2358, ak 648, Matt 124, and no name contains "pstack". All 28 strict-tier losses had a gold skill of family `other`, pushed out by 50 promoted ak-* rows and 9 promoted Matt rows. The measured verdict is therefore "an ak-* + Matt-first tier makes the offer worse". The report says pstack is "barely covered", which understates the gap: pstack is not covered at all. Separately, `gold()` strips plugin prefixes (`calibrate_jev_gate.py:198-199`), so a used `pstack:how` would count as `other`. No such gold exists in this corpus, so this does not change the count today.
4. **The reputation metric rewards past behaviour.** Gold is the skill the agent actually used after seeing the offer it was given at the time. A policy that promotes skills agents rarely saw near the top cannot get credit for them. Given 28 lost against 2 gained, the direction holds. The report should still say that it measures agreement with past choices, not offer quality.
5. **Robustness checks I ran, none of which changes the conclusion:**
   - **ck:\* names.** 14 positives used `ck:*` skills, which `family()` classes `other` and which match no catalogue row. Inference, not verified: if each `ck:X` is the same skill as `ak-X`, then strict ranks the used skill 1st in 11 of those turns and Jev order in 9, and both put it in the top 5 in 13. Adding these turns moves the totals to 48 vs 109 ranked 1st, and 164 vs 190 in the offer.
   - **Matt Pocock rows classed `other`.** 2 of the 24 distinct `mattpocock-skills:*` rows land in `other`, because `family()` checks only the `~/.claude/skills` symlink.
   - **Name collisions.** In 12 shortlists, two rows share a base name after the plugin prefix is stripped, so one row's match can credit its twin.
6. **The report's text leaves out one fact about the reputation sim.** It runs on cached answers from the catalogue of 2026-10-03/04 on jev-1.13.0, not today's catalogue or provider. Only the script's docstring says so.
7. **Wording.** Verdict 1 says "git status", but the used skill was `git` (`curve.txt`, "so where am i now"). The report says the 1807 handoff "called the bypass unanalysed". The handoff's actual words are "Not verified: whether `_jev_rows` bypass at :3104 is intended" (`.handoff/handoff-2026-10-07-1807-jev-work-or-conversation-gate-design.md:84`).

## Validation Dimensions

- [x] **Number fidelity: PASS.** `diff` against the saved files printed IDENTICAL for `live_turn_type_replay.py curve`, `reputation_tier_sim.py`, `offline_gate_curves.py` and `intent_gate_baseline.py`. The fits-floor row matches the 1752 diagnosis report line 74.
- [x] **Population selection: PASS.** The three populations share one pool: English, interactive, not a skill-concierge session, and reaching the gate (1753 rows). pos and neg are disjoint. unl overlaps pos by 51 rows and neg by 19, which is expected for a traffic sample; the dedup in `cmd_score` accounts for 698 → 628. neg does not apply the interrupted/correction filters that pos uses, which is harmless.
- [x] **`convo` inversion: PASS.** Mean raw P(only conversation) is pos 0.205, unl 0.264, neg 0.348, so the inversion points the right way. Skip rates also rise from pos to neg.
- [x] **`both` = max of the two probabilities: PASS.** Skipping when max < t means both questions are below t, which matches "skip only when both agree".
- [x] **Wilson bound: PASS.** `calibrate_jev_gate.py:339-345` is the standard Wilson upper bound with z = 1.96. 0/313 gives 1.2 % and 3/313 gives 2.8 %, matching the table.
- [x] **Reputation `family()`: WARN.** See Advisory 3 and 5.
- [x] **Reputation sim measures the live offer: PASS.** Top 5 of the 10-row rerank Choice, ordered like `_jev_decide`. The live `fits` skip is not modelled, which affects about 1 of 313 turns.
- [x] **Verdict 1: holds in direction, overstated in size (WARN).**
- [x] **Verdict 2: holds for ak-* + Matt; the pstack part is untested (WARN).**

## Unverifiable Items

- The probe scores (0.19, 0.58, 0.13, 0.86, 0.88) were never saved. Re-running `probes` would be a paid Jev call, which the task forbids.
- The `score` run itself, i.e. that `answers.jsonl` holds genuine Jev answers. I checked only what is on disk: 628 rows, all from `commandcode` / `typesafe/jev`, matching `score.log`.
- Whether `ck:*` skills are the predecessors of the `ak-*` skills. Advisory 5 marks this as an inference.

## Context Gaps

- Side effects of the runs: each script run calls `load_enforcer()`, which creates a throwaway `jevcal-*` ledger directory under the system temp dir (`calibrate_jev_gate.py:94`). Python may also have refreshed `__pycache__/` in the replay folder. I wrote no other file.
- How the corpus's time span overlaps the pstack and Matt install dates: not measured. The Matt symlinks are dated 2026-10-06; the pstack cache dir was created 2026-09-29.

Status: DONE_WITH_CONCERNS

Summary: Every number the report quotes reproduces exactly: four replay scripts plus the cached fits curve, re-run with no paid calls. No method error reverses either verdict. The `convo` inversion points the right way, `both` really is "both below t", the Wilson bound is standard, and the reputation sim orders and breaks ties exactly as the live `_jev_decide` does. Both verdicts need narrower wording. Verdict 1 ("weak gate") holds and is stronger than stated: the zero-loss skip rate is 0.3 % of traffic, not about 1 %, and on top of today's fits floor the gate adds no skips at 0.15–0.20 while losing more real skill turns. Verdict 2 ("reputation tier worsens the offer") holds for ak-* and Matt Pocock, but pstack never appears in the cached catalogue, so the pstack part is untested. The metric also measures agreement with past agent choices. The five probe scores could not be checked without a paid call.
