# Validation: Cline first-menu replay (wide pass vs full Jev vs embedding preview)

**Subject:** analysis (replay study and its recommendation)
**Scope:** `plans/reports/replay-261008-2151-cline-first-menu.md`, its script `plans/261008-2151-cline-first-menu-replay/first_menu_replay.py`, the raw results `~/.claude/skill-concierge/analysis-private/261008-2151-cline-first-menu-replay/replay.jsonl`, the helpers in `scripts/calibrate_jev_gate.py` and `hooks/scripts/enforcer.py`, and the Cline plugin `adapters/cline/skill-concierge.cline-plugin.ts` (working tree).
**Date:** 2026-10-08 (Asia/Saigon)
**Validator:** independent; I did not write the analysis. I made no Jev, Command Code or jevd calls. The only live reads were the local index owner (to rebuild the 549-skill catalogue) and the local ledger file. All recomputation used my own scratch scripts under `$TMPDIR/val261008/`.

**Overall verdict:** SUPPORTED_WITH_CAVEATS. Both quality claims reproduce exactly and survive every leakage check. The latency claim ("fits the 2 s wait on 96% of turns; the figure is pessimistic") is contradicted by live telemetry and must be corrected before the design is sized. This is a blocking defect in the report as written, though it does not reverse the recommendation.

## Executive summary

Every number in the report reproduces from `replay.jsonl`. The comparison is fair: all menus are scored on the same turns, against the same gold, at the same k. No leakage favours the Jev menus. Where the gold could be biased at all, the bias favours the embedding preview, because every corpus turn predates the Jev router. "Wide is much better than the preview" is strongly supported (+43.8 points at hit@5, 95% CI +36 to +51). "Wide ≈ full" holds only at k=5, and only as "no significant difference": the CI still allows the wide pass to lose up to 8 points. At hit@1 the wide pass is significantly worse, by 9 points. The 96% latency figure comes from a 17-minute replay window. The live ledger shows Command Code wide passes are much slower: on 90 live turns (Oct 7-8), only about 36-52% would fit the 2 s wait. So the replay figure is optimistic, not pessimistic. The wide shortlist ordering also over-weights the small last chunk. That does not hurt on this shelf, but it is a structural hazard on other catalogue sizes.

## Observable truths

| # | Claim in the report | Status | Evidence (my recomputation) |
|---|---|---|---|
| 1 | 233 reachable turns of 313 | VERIFIED | 313 unique uuids, all with `full`; 233 reachable on the 549-skill catalogue rebuilt from the worktree cwd. The catalogue depends on cwd: from the MY-WORKBENCH root it is 568 (project isolation). |
| 2 | Preview hit@1/3/5 = 12.9 / 21.9 / 27.5% | VERIFIED | 30 / 51 / 64 of 233 |
| 3 | Wide hit@1/3/5 = 34.8 / 63.9 / 71.2% | VERIFIED | 81 / 149 / 166 of 233 |
| 4 | Full hit@1/3/5 = 43.8 / 66.1 / 75.1% | VERIFIED | 102 / 154 / 175 of 233 |
| 5 | "All" rows | VERIFIED (not in the report table, but the script prints them) | Preview 9.6 / 16.3 / 20.4, wide 25.9 / 47.6 / 53.0, full 32.6 / 49.2 / 55.9 (n=313) |
| 6 | Offer-lane like-for-like: 275 turns, 19.3 / 50.9 / 53.8% | VERIFIED | Same. On the reachable subset (n=200): 26.5 / 70.0 / 74.0% |
| 7 | Full route said "skip" on 0 of 233 | VERIFIED | One skip, among the 80 unreachable turns |
| 8 | Preview p50 127 ms; wide p50 1,255 / p90 1,490 ms; wide+rerank p50 2,062 / p90 2,364 ms | VERIFIED | Same. Preview max 233 ms; wide p95 1,617, p99 1,849, max 2,106 ms |
| 9 | Wide + 0.35 s fits 2 s on 96% of turns | VERIFIED as arithmetic on replay data (96.2%) | Steep sensitivity: +0.50 s gives 91.1%, +0.65 s gives 76.0%, +0.80 s gives 33.9% |
| 10 | "Calls ran six at a time … so this figure is pessimistic" | FAILED | The live ledger contradicts it (see Blocking issue 1) |
| 11 | "Live jevd p50 for Command Code over 3 days: 1.1 s per call" | UNVERIFIABLE | I made no jevd calls. The ledger gives a live wide-pass p50 of 1,786 ms and a rerank p50 of about 767 ms, so a mixed per-call p50 near 1.1 s is plausible but says nothing about the wide pass |
| 12 | "One wide answer feeds both Jev menus, so they differ only by the rerank" | VERIFIED | `first_menu_replay.py:71-87`. The rerank shortlist is `short`, filtered by the catalogue |
| 13 | "Wide ordered by within-chunk probability" | VERIFIED | `first_menu_replay.py:74-80` takes the max over `wide::` chunks; `_jev_shortlist` is `enforcer.py:2156-2162` |
| 14 | "Preview run exactly as the Cline plugin runs it" | PARTIAL | Same env flags and same payload shape (`cline-plugin.ts:209` vs `first_menu_replay.py:54-57`). But the replay ran it as Claude Code (no `SKILL_CONCIERGE_HARNESS=cline`), with 15 s embed/Qdrant timeouts inherited from `calibrate_jev_gate.py:94-96`, and it credited a menu on skip bands (Advisory 2) |
| 15 | "State sent to Jev: the live ctx variant" | PARTIAL | This matches Claude Code's live state. It does not match Cline's: the plugin payload is `{prompt, session_id}` with no `transcript_path` (`cline-plugin.ts:197`), so `_jev_context("")` returns an empty context (`enforcer.py:1849-1859`). Live Cline Jev gets the bare state (Advisory 3) |
| 16 | "0 of 310 turns failed" | UNVERIFIABLE (immaterial) | The file holds 313 complete records with `err: null`. The other 3 presumably came from an earlier `--limit` run |

## Check 1: reproducibility

Every table cell, the offer-lane check, the skip count, the latency percentiles and the 96% all reproduce exactly (rows 1-9 above). The reachable filter needs the catalogue from the worktree cwd (549). Run from another cwd, the same filter sees 568 skills.

## Check 2: fairness and leakage

- **Same turns, same gold, same k.** The `hit()` function (`first_menu_replay.py:116-117`) is applied identically to all three menus, with the same `reach` set and the same k. The reachable filter uses one shelf (`_jev_catalog()` bare names) for every menu, so it cannot favour one menu over another.
- **Gold provenance.** Gold comes from `final_names` on the agent's USING line, in a turn where the skill was loaded and executed (`calibrate_jev_gate.py:190-200`). All 313 turns run from 2026-06-27 to 2026-09-26 00:12 (+07:00). The Jev router landed at 2026-09-26 09:47 (commit 0b03c88), and `ledger_jev` is empty on all 233 reachable turns. No gold was chosen from a Jev menu. The agent was then looking at an embedding menu: gold was in that live offer on 83 of 233 turns, and on those turns the preview scores 61.4% against 8.7% elsewhere. Any selection bias therefore favours the preview, not Jev.
- **Session-skills leakage.** `session_skills` is computed from earlier turns only: `ctx_skills = recent[-3:]` (`extract_turn_labels.py:388`) is assigned before `note(tn)` (line 391). The gold skill was among the session skills on 28 reachable turns. The wide pass scores 71.4% there and 71.2% on the rest; full scores 75.0% and 75.1%. Jev gains nothing from it.
- **Gold named in the text.** On 40 turns the prompt names the gold skill, and every menu does better there. On the 166 turns where the gold name appears in neither the prompt, the previous assistant text nor the session skills, hit@5 is preview 28.3%, wide 69.3%, full 71.7%. The conclusions hold.
- **Bare-name collisions** (`split(":")[-1]`). The 549 catalogue holds 17 ambiguous bare names, and gold falls in that set on 20 reachable turns. Some hits match only by bare name, with no exact full-name match against `final_names`: preview 1, wide 9, full 11. Most are true twins with identical descriptions: `doctor` / `skill-concierge:doctor` (6 wide, 6 full) and `consult` / `skill-concierge:consult`. Three are a plugin skill no longer installed, matched to a standalone skill of the same name (`pdf:pdf`→`pdf`, `mattpocock-skills:grill-with-docs`→`grill-with-docs`). Under strict exact-name scoring, hit@5 is preview 27.0%, wide 67.4%, full 70.4%. The effect is small and roughly symmetric between the two Jev menus. Twins also waste menu slots: a top 5 holds a twin pair on 17 (preview), 13 (wide) and 15 (full) turns.

Result: the comparison is fair, and the leakage checks favour the preview where they favour anything.

## Check 3: wide ordering and chunk bias

- **What the script does.** It collects the 15 shortlisted names (5 per chunk, `enforcer.py:2156-2162`), maps each name to its probability (`max` over chunks; `first_menu_replay.py:74-78`) and sorts by it (line 80). `_jev_catalog` deduplicates names (`seen`, `enforcer.py:2129-2131`), so each name sits in exactly one chunk. Taking the max is then a harmless no-op, unless Jev returns a name outside its chunk's criteria; I found no such name. Rebuilding the catalogue order from the worktree cwd splits all 313 records' 15 wide names exactly 5/5/5 across chunks 0/1/2. The run-time order is therefore the one I analysed.
- **Chunk sizes:** 250 / 250 / 49. The catalogue share of each chunk is 45.5 / 45.5 / 8.9%.

| Chunk | Gold share (reach) | Wide top-5 rows | Wide top-1 | Full top-5 rows |
|---|---|---|---|---|
| 0 (250) | 38.2% | 31.1% | 27.0% | 45.6% |
| 1 (250) | 43.3% | 33.3% | 26.2% | 41.0% |
| 2 (49) | 18.5% | 35.6% | 46.8% | 13.4% |

The small last chunk is over-represented in the wide menu: about twice its gold share in the top 5 and 2.5 times at the top row. The rerank corrects this (13.4%). It explains part of the 9-point hit@1 gap. By the gold's chunk, wide hit@5 is 72.9% (chunk 0), 66.3% (chunk 1) and 76.9% (chunk 2); full is 80.0%, 72.3% and 69.2%.
- **Do alternatives do better here?** No. Rank-major ordering (within-chunk rank first, probability as tiebreak) gives hit@1/3/5 of 34.8 / 61.8 / 71.7%. Round-robin over chunks gives 14.6-24.0 / 61.8 / 68.2-72.1%. Probability ordering gives 34.8 / 63.9 / 71.2%. On this shelf the report's "it held up" is fair.
- **Hazard (inference).** The bias is structural. It depends on the catalogue size modulo 250. A tail chunk of a handful of skills, for example a 501-to-505-skill catalogue, gives its members inflated probabilities, and a 1-skill chunk gets probability 1.0, which puts that skill at the top of the wide menu on every turn. Cline's own catalogue (rebuilt with `SKILL_CONCIERGE_HARNESS=cline`) is 472 skills, split 250 / 222. That is a different regime from the one replayed: two chunks and a 10-name shortlist instead of 15.

## Check 4: preview fairness

- **Degradation under load: none found.** Preview latency was p50 127 ms and max 233 ms, with no `fallback` / `qdrant_down` band. Every preview has 6-8 offered rows. The bands were offer 275, intent_skip 36, getaway 2. The subprocess also inherited `ENFORCER_EMBED_TIMEOUT=15` and `ENFORCER_QDRANT_TIMEOUT=15` from `load_enforcer` (`calibrate_jev_gate.py:94-96`). That removes the live 0.5 s / 0.25 s caps, so if anything it favours the preview.
- **Same harness view: yes, and it is Claude Code's, not Cline's.** The script process and the preview subprocess share the environment (neither sets `SKILL_CONCIERGE_HARNESS`) and the cwd, so both use the 549-skill Claude view. Cline's view is 472 skills; 468 overlap. Gold is on Cline's shelf for 230 of the 233 turns, and on those hit@5 is preview 27.8%, wide 71.7%, full 75.2%. But on 82 of 233 turns the wide top 5 holds at least one skill that Cline cannot invoke. Cline's real menu would fill those slots with other skills, which the replay does not measure.
- **Skip bands credited with a menu.** On getaway and intent_skip the enforcer injects an authorized-skip message, not a menu (`enforcer.py:3345-3355`). The script still scores the `offered` list (`first_menu_replay.py:64`). Of the 233 reachable turns, 33 fall on those bands, and 11 of them are credited as preview hits. Scored as "no menu", the preview drops to 9.9 / 18.0 / 22.7%. The report's preview figure is slightly generous.
- **The preview's native 8 rows.** The live preview shows up to 8 rows. Its hit@8 is 35.6%, still far below the wide pass's hit@5 of 71.2%.

## Check 5: statistical strength (paired, n=233)

| Comparison | Difference | 95% CI (Wald; bootstrap agrees) | Discordant pairs | McNemar exact p |
|---|---|---|---|---|
| wide − full, hit@1 | −9.0 pts | [−15.4, −2.7] | 19 vs 40 | 0.009 |
| wide − full, hit@3 | −2.1 pts | [−7.0, +2.7] | 14 vs 19 | 0.49 |
| wide − full, hit@5 | −3.9 pts | [−8.0, +0.3] | 8 vs 17 | 0.11 |
| wide − preview, hit@1 | +21.9 pts | [+14.7, +29.1] | 68 vs 17 | <0.0001 |
| wide − preview, hit@5 | +43.8 pts | [+36.2, +51.4] | 114 vs 12 | <0.0001 |
| wide − preview (no menu on skip bands), hit@5 | +48.5 pts | [+41.0, +56.0] | 124 vs 11 | <0.0001 |

Wilson 95% intervals on hit@5: preview 22.1-33.5%, wide 65.1-76.7%, full 69.2-80.2%.

"Wide much better than the preview" is strongly supported. "Wide ≈ full" is supported only as "not significantly different at k=3 and k=5". The data still allow an 8-point loss at k=5, and the top-row loss of 9 points is significant. The report's own wording ("adds 9 points at the top row and 4 points in the top five") is accurate. Its headline "almost as good" should carry the CI.

## Check 6: latency

- **What the replay measured.** `cal.call` times only the Jev request (`calibrate_jev_gate.py:161-176`). The fixed 0.35 s must cover everything else: Node's spawn of `python3`, the enforcer import, the jevd ladder fetch (`_jevd_ladder`, `enforcer.py:2261`), the catalogue read and output parsing. Locally, the import plus the catalogue read (through the pyenv `python3` shim) took about 0.25 s of wall time over 5 runs. I could not time the jevd ladder fetch without calling jevd.
- **What live traffic shows.** The ledger's Jev event `wide_ms` runs from `t0` (`enforcer.py:2391`, before the ladder fetch) to the wide answer (`enforcer.py:2428`). It therefore includes the ladder fetch, the catalogue read, the context read and the wide call; it excludes only process start-up. Over 90 live successful Command Code turns from 2026-10-07 01:10 to 2026-10-08 21:51 (79 Claude Code, 7 Cline, 4 OMP), `wide_ms` was p50 1,786 ms and p90 2,498 ms. Hourly medians ranged from 1.3 to 2.4 s. The rerank part (`ms − wide_ms`) had p50 767 ms, close to the replay's 817 ms, so the wide side is where the replay and live traffic disagree. Share of live turns where `wide_ms` plus start-up stays within 2,000 ms: +0 ms 70.0%, +100 ms 60.0%, +200 ms 52.2%, +250 ms 46.7%, +350 ms 35.6%.
- **Conclusion.** The replay window (about 17 minutes on one evening, `replay.jsonl` last written 22:08) ran faster than live traffic, even at 6-way concurrency. Concurrency is not the dominant factor, so "pessimistic" is wrong. A realistic estimate is roughly 35-55% of turns, not 96%. In the proposed plugin design, two enforcer processes per turn would each send a wide call at the same moment, adding Command Code load. Neither the replay nor the ledger measures that.
- **Effect on the recommendation (inference).** If a late wide menu falls back to the preview, the expected first-call hit@5 is about P(in time) × 71.2% + (1 − P) × 27.5%. At P ≈ 0.45 that is about 47%, against about 28% today (the full menu fits the wait on only 2.6% of replay turns). The direction holds; the size of the gain is about half what the report implies. The same latency applies to the alternative "full pass emits the wide menu early" design, since time-to-wide is the same.

## Check 7: other findings that bear on the recommendation

- **Cline's live Jev state is bare, not ctx** (row 15). Indirect evidence suggests this hardly matters. On the same 313 turns, the cached `suite-scores.jsonl` rerank answers over the same retrieval shelf (jev-1.13.0) differ between `bare` and `ctx` by at most 4 discordant turns at k=1 and 1 turn at k=5. This is an inference from a different stage and an older model, not a measurement of the wide pass.
- **Precision is unmeasured.** The population holds only turns where a skill was used. The wide menu has no `fits` floor, so it will show 5 rows on every no-skill turn where the full route would have said "skip". The report states this limit correctly. It is still a real behaviour change for Cline's first call.
- **Cost.** The simple design adds one metered Command Code call per English turn. The report names this trade-off.

## Blocking issues

1. **The latency claim is contradicted by live telemetry.** Report text: "The wide pass plus the enforcer's ~0.35 s startup fits inside the 2 s wait on 96% of turns. Calls ran six at a time, which slows each one, so this figure is pessimistic." Evidence: 90 live Command Code turns in the ledger, with `wide_ms` p50 1,786 / p90 2,498 ms. Only 35.6-52.2% of them fit within 2 s after 0.2-0.35 s of start-up (Check 6). Impact: the design's expected benefit is about half what the report implies, and "pessimistic" must be retracted. The 96% figure must be re-stated as a figure for one replay window, or replaced with the live distribution.

## Advisory issues

1. **The wide ordering is biased toward the small last chunk** (35.6% of top-5 rows and 46.8% of top-1 rows from 8.9% of the catalogue). It is harmless on this shelf, but a near-empty tail chunk would pin its members to the top. Guard the ordering before shipping, for example by balancing chunk sizes in `_jev_wide_questions`, or by rank-major ordering, which ties at k=5 here.
2. **The preview is credited with a menu on getaway / intent_skip turns** (`first_menu_replay.py:64`). The preview's hit@5 should be 22.7%, not 27.5%. This understates the wide pass's advantage; it does not overstate it.
3. **The replay used Claude Code's harness view and the ctx state; Cline uses its own 472-skill view and a bare state.** On 82 of 233 turns the wide top 5 holds a skill that Cline cannot invoke. A Cline-view replay (`SKILL_CONCIERGE_HARNESS=cline`, bare state) would measure what Cline would actually show.
4. **"Wide ≈ full" should carry its CI**: −3.9 points at hit@5, 95% CI [−8.0, +0.3], p = 0.11; −9.0 points at hit@1, significant.
5. **Bare-name scoring counts twins as hits.** Strict scoring changes hit@5 by −1 / −9 / −11 hits (preview / wide / full). The effect is immaterial, but the report should say so.

## Unverifiable items

- The jevd ladder-fetch latency, and the "1.1 s per call" jevd figure. I made no jevd calls, by instruction.
- Whether the 17-minute replay window was unusually fast, or whether live `wide_ms` carries extra overhead (for example a slow ladder fetch). Either way, the live end-to-end number is what the 2 s wait sees.
- Two concurrent wide calls per turn against Command Code: not measured anywhere.
- The 3 records outside the "310" run.

## Context gaps

- No Cline-view, bare-state replay.
- No jevd-side timing that splits ladder fetch from call time.
- No no-skill population to measure what the wide menu does without a skip verdict.

Verdict: SUPPORTED_WITH_CAVEATS

Summary: the wide pass alone is a much better first menu than the embedding preview and is not significantly worse than full Jev at top 5, but the claim that it fits Cline's 2 s wait on 96% of turns is contradicted by live telemetry (about 35-55%), so the expected gain is roughly half what the report implies and that claim must be corrected.

Unresolved questions:

1. Does the slower live wide pass come from Command Code itself or from per-turn overhead (the jevd ladder fetch)? A jevd-side timing split would settle it, and the fix differs: overhead can be cut; provider latency cannot.
2. Should the first-menu design wait for the wide menu at all, given that it arrives in time on only about half of turns? Or should the plugin's 2 s wait be spent differently?
3. Would a Cline-view replay (472 skills in two chunks, bare state) keep wide at about 71%? 82 of 233 wide menus here include skills Cline cannot invoke.
4. Should the chunk-size hazard be fixed in `_jev_wide_questions` before any wide-ordered menu ships?
