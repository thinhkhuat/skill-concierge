# Cline's first menu: embedding preview vs Jev wide pass vs full Jev (replay, 2026-10-08)

## Result

Jev's wide pass alone makes almost as good a first menu as the full Jev route, and far better than
the embedding preview that Cline's first model call carries today. It also fits Cline's 2-second wait
on nearly every turn.

| Menu (top 5) | hit@1 | hit@3 | hit@5 | Time |
|---|---|---|---|---|
| Embedding preview (today's first call) | 12.9% | 21.9% | 27.5% | p50 127 ms |
| Jev wide pass only | 34.8% | 63.9% | 71.2% | p50 1,255 ms, p90 1,490 ms |
| Full Jev (wide + rerank) | 43.8% | 66.1% | 75.1% | p50 2,062 ms, p90 2,364 ms (Jev calls only) |

Population: 233 real turns where the agent used a skill and that skill is still installed today. hit@k
means a skill the agent actually used in that turn is among the menu's top k.

- The rerank adds 9 points at the top row and 4 points in the top five. The wide pass carries most of
  the value.
- ~~The wide pass plus the enforcer's ~0.35 s startup fits inside the 2 s wait on 96% of turns.~~ **Retracted
  (22:20, independent validator):** the replay timed the Jev request alone, in one 17-minute window. In 90 live
  Command Code turns (Oct 7–8) the wide pass took p50 1,786 ms and p90 2,498 ms including the catalogue read, so
  only 36–52% of turns would fit the 2 s wait. See `validator-261008-2151-cline-first-menu-replay.md`.
- Like-for-like check: on the 275 turns (all 313) where the preview reached its normal offer lane,
  top-5 hits were preview 19.3%, wide 50.9%, full 53.8%. The gap is not an artefact of empty preview menus.
- The full route never said "no skill fits" on these turns (0 of 233), so the wide pass losing that
  verdict costs nothing on this population. This population holds only turns where a skill was used,
  so it cannot measure how often the verdict correctly skips a no-skill turn.

## Method

- Script: `plans/261008-2151-cline-first-menu-replay/first_menu_replay.py` (`run`, then `report`).
- Corpus: `calibrate_jev_gate`'s positives (`~/.claude/skill-concierge/jev-calibration/real-turn-labels.jsonl`):
  English, interactive, outside skill-concierge's own sessions, reaching the Jev gate, the skill loaded and
  used in the same turn, not interrupted, not corrected next turn. 313 turns; 233 whose used skill is on
  today's 549-skill shelf (Claude Code's view).
- State sent to Jev: the live `ctx` variant (prompt, tail of the previous assistant message, skills loaded).
- Preview: the enforcer run as a subprocess with `ENFORCER_JEV_ROUTER=0` and `ENFORCER_LEDGER=defer`,
  exactly as the Cline plugin runs it; its offered list read from the handed-back offer row.
- Wide: the enforcer's own `_jev_wide_questions` over the catalogue (3 chunks of at most 250); the
  shortlist (`_jev_shortlist`, top 5 per chunk) ordered by within-chunk probability, top 5 shown.
- Full: `_jev_rerank_questions` on that same shortlist and `_jev_decide`, the live policy. One wide answer
  feeds both Jev menus, so they differ only by the rerank.
- Provider: jevd pinned to `commandcode` (`typesafe/jev`), 6 workers. 0 of 310 turns failed.
- Answers are cached at `~/.claude/skill-concierge/analysis-private/261008-2151-cline-first-menu-replay/replay.jsonl`
  (outside the repo: the corpus holds private prompts).

## Limits

- The corpus is Claude Code turns, not Cline turns. The used skill is a Claude Code skill, and the menus
  were built on Claude Code's shelf. Cline's shelf differs (its own roots plus the Agent Plugin).
- The corpus is older than today's shelf: 80 of 313 used skills are no longer installed. The "all" rows
  of the report count those as misses for every menu alike.
- Within-chunk probabilities are not strictly comparable across chunks; ordering the wide shortlist by
  them is the thing being measured, and it held up.
- Timings were measured under six concurrent calls; one-at-a-time calls are faster (live jevd p50 for
  Command Code over 3 days: 1.1 s per call).

## Corrections from the independent validation (22:20)

- Preview hit@5 is 22.7 %, not 27.5 %: on 33 turns the enforcer shows the model a skip message, not the
  preview's menu. Exact-name scoring (no short-name matching) gives 27.0 / 67.4 / 70.4 % for preview / wide / full.
- Paired over 233 turns: wide vs full hit@5 −3.9 points (95 % CI −8.0 to +0.3, not significant); hit@1 −9.0
  points (p 0.009, significant); wide vs preview hit@5 +43.8 points (+36 to +51).
- The smallest chunk (49 skills) supplied 36 % of wide top-5 rows; see the ordering result below.

## What was decided (2026-10-08)

- The 10-second harnesses (Claude Code, Codex, ZCode, OMP, OpenCode) keep the full route (Thinh, 22:26,
  "keep-full for the 10-second harnesses is locked-in"). Wide-only would save one of two requests per routed
  turn but only ~10 % of the question text (wide ~96,000 characters, rerank ~11,000) and ~0.8 s, and lose
  ~21 % relative top-1 accuracy and the "no skill fits" verdict (5 % of live Jev turns, 34 of 661 in 14 days).
- Command Code and DSH already get the full route through jevd's TypeSafe tier inside their 1.6 s budget
  (probes: 0.62–1.07 s), so they keep it.
- Cline's first model call takes the best menu ready inside its 2 s wait: Command Code full, then a TypeSafe
  full-route backup started 0.5 s into the turn, then Command Code's early wide menu, then the embedding preview
  (Thinh 22:37 + 22:52). Live: 3 of 3 turns carried the TypeSafe full menu at 0.68–0.94 s.
- **Superseded (~22:56, final):** that design billed both providers on most Cline turns (~4 Jev calls), the
  "Both" option Thinh had declined. He chose **TypeSafe only for Cline**: one full route on jevd's TypeSafe tier
  (`ENFORCER_JEV_TIER=typesafe`), the embedding preview as fallback. The early wide menu and the backup were
  removed. Live: 3 turns at 751 / 673 / 822 ms, no Command Code call.
- Wide rows are ordered by lift (probability × chunk size). On the same 312 wide answers: raw hit@5 71.2 %,
  lift 70.8 %; hit@1 36.1 % vs 36.5 %. Equal quality; lift chosen because raw order always puts a one-option
  chunk's skill first.

## Unresolved questions

- How fast is TypeSafe's full route across many live Cline turns (3 measured so far)?
- Would a replay on Cline's own shelf and prompt-only input keep these numbers?
