# Impact Analysis — v0.6.1 gate floors: dogfood + optimal-value finding (leak-corrected)

**Date:** 2026-06-29 10:20 | **Subject:** enforcer `MAX_SHORT_WORDS` (word floor) + `GETAWAY_FLOOR` (score floor)
**Question:** how are the operator-set values (5 / 0.45) doing, and what is optimal?
**Method:** (a) live ledger pre/post split via `analyze.py`; (b) replay the labeled `prompt_intent` corpus through the REAL enforcer fns and sweep both knobs; (c) HELD-OUT re-run after a leak was found; (d) adoption anti-correlation re-confirmed on the live ledger. Read-only; temp ledger/collection; tested the file's 0.45 default.

> **Correction note:** the first draft claimed "both objectives agree, lower the score floor" off an in-sample number. `_intent_conversational` queries the `prompt_intent` collection, which is BUILT FROM the corpus being replayed (932 pts = 466+466) — conversational prompts classified themselves. Re-run held-out: the intent gate's real noise-catch is **52.9%, not ~73%**. The direction (weakly toward 0.40) survives, but for the adoption-ledger reason below, NOT corpus redundancy. The corpus is weak corroboration, small-n.

## VERDICT — it is a VOLUME vs ADOPTION trade, and the operator already chose volume knowingly
- **Score floor 0.45 (the contested knob):** suppresses MORE offers (volume — the operator's stated goal, confirmed). The cost is real and not a leak artifact: **7 of the 12 taken offers across the FULL ledger (Jun 26-29) score below 0.45** (a BACKTEST, not post-change data) → the new floor would silence the majority of historically-ADOPTED offers (at 0.40, only 4/12 = 33% fall below). If the objective of record is adoption, optimal ≈ **0.40 or lower**; if it is nudge-volume, 0.45 is doing its job. The data cannot pick the objective — the operator owns it. NOT a directive to revert.
- **Word floor 5:** the confirmed live harm ("fix the parser bug" 4w, "update the handoff" 3w dropped) is a **gate-ORDERING bug** — the word floor runs BEFORE the imperative-veto built to protect short commands. That is architectural, not a value to tune; the fix is to run the imperative-veto first, after which the word-floor value matters far less. Do NOT read "keep 5" into the aggregate corpus J.
- **The real lever for the actual problem** (offered-turn conversion is **7%**, 12/167): per-skill DEMOTION of the chronically-offered-never-taken (`review-docs` 0/21, `skill-search` 0/19, `ck:journal` 0/18), not floor height. A cosine floor cannot separate "topically relevant but unwanted" — those score high anyway.

## 1. Live ledger — both instruments underpowered, cannot judge impact yet
- POST-ship (0.45/5): only **10 offered turns**; conv 2/10=20% vs PRE 10/157=6% — but the 2 "takes" are `verify-as-claimed`+`kickoff` (skills invoked THIS session verifying the gate → self-contaminated); 47% of post offers were degraded fallbacks (embed/Qdrant cold). N=10, contaminated → no verdict.
- The pre-ship backtest (ADR-0009: 147 offers) is the statistically solid leg, NOT the live post-ship window.

## 2. Adoption anti-correlation — BACKTEST over the full ledger (the solid leg)

> SCOPE: computed on ALL 12 taken offers in history (Jun 26-29), NOT the after-fine-tune window. It MUST be a backtest: a suppressed offer is never shown -> never taken -> invisible in post-change data, so suppressed-offer conversion can only be estimated from history. After-fine-tune taken offers = 2 (both `kickoff` 0.527 + `verify-as-claimed` 0.644, self/meta, both ABOVE 0.45) -> a post-change version is n=2 and useless. This estimates SUPPRESSED-offer take-rate; the after-change scoped replay (Section 6) measures SURVIVING-offer take-rate. Complementary, not the same.
Among OFFER-band turns in the live ledger: median top cosine **TAKEN 0.4227 < DODGED 0.461**. Taken-offer tops: 0.29, 0.33, 0.35, 0.39, 0.41, 0.42, 0.43, 0.49, 0.53, 0.58, 0.64, 0.64 — **7/12 below 0.45**. Higher cosine does NOT mean more wanted; raising the floor cuts the better-converting offers first. (n=12 taken — small but REAL adoption, not a proxy.)

## 3. Corpus replay — held-out, leak-corrected (weak corroboration)
- Intent gate noise-catch: **52.9% held-out** (vs ~73% in-sample) — a weak primary filter, which makes a score-floor backstop somewhat defensible.
- BUT in the 0.40→0.45 band specifically, that backstop catches ~1 conversational per ~6 actionable newly cut (held-out, ~7 prompts) — a poor insurance ratio, directionally aligned with the ledger. Small-n; corroborates, does not carry the conclusion.
- (Pure score-floor-alone separation favors 0.45 — but that double-counts noise the intent gate also catches; not decision-relevant for the deployed system.)

## 4. Recommended optimal values (honest, objective-dependent)
| Knob | If objective = ADOPTION | If objective = nudge-VOLUME | Highest-value action |
|------|------------------------|----------------------------|----------------------|
| score floor | 0.40 or lower (7/12 taken < 0.45) | 0.45 stands (suppresses more) | name the objective of record first |
| word floor | value secondary | value secondary | **fix ordering**: imperative-veto BEFORE word floor (architectural) |
| precision | — | — | demote chronically-dodged skills; the floor is the wrong lever for the 7% |

Only accrued post-ship adoption (re-run `analyze.py` offered-turn conversion once volume builds, split on `6995fd8`) settles whether the volume cut is worth its adoption cost. No value changed; per ADR convention a revert supersedes ADR-0009 with ADR-0010 — the user's call.

## Unresolved questions

0. **OBJECTIVE OF RECORD (operator-stated): correct-skill-selection-and-use rate** — rate at which an agent (a) knows the available skills and (b) invokes the RIGHT one. This is NOT offer->take (the ledger metric). **DATA-SOURCE CORRECTION:** the `skill-invocation-ledger.log` measures GATE COMPLIANCE and the operator flagged it INVALID for usage analysis; the correct usage infra is the `skill-usage-tracker` skill (reads the transcript store `~/.claude/projects/**/*.jsonl`, both channels). BUT both count only `Skill` tool-use + `/slash` and AGREE at **6 post-deploy** (684 lifetime). Neither captures the dominant path for this metric: **inline SKILL-FIRST use** (agent declares `USING <skill>`, reads SKILL.md, executes — no Skill-tool call) and subagent/Task use. The measurable proxy for the operator's metric is the **SKILL-FIRST declaration trail** in transcript text (`USING`/`SEARCH`/`SKIPPING`): ~11 genuine `USING <skill>` + 5 `SEARCH` + 6 `SKIPPING` post-deploy — already > the 6 the counters see. Caveat: the ~11h post-deploy window is meta-dominated (this verification session); no instrument has enough organic post-deploy data yet.


1. **Objective of record:** adoption (offer→take) or nudge-volume? The two diverge on the score floor; the operator owns this.
2. **Word-floor ordering:** move the imperative-veto before the word floor? (architectural; out of scope for a value tune, but it is the real word-floor fix.)
3. **Precision:** per-skill demotion of `review-docs`/`skill-search`/`ck:journal` (0/~20) — the actual lever for the 7% conversion.
4. n is small on every leg right now (taken=12, post-ship offered=10); direction is solid, magnitude provisional until volume accrues.

## 6. How to evaluate the values going forward (valid, scoped, low-noise)

The floor change is observable ONLY on turns where it actually ran, the traffic is organic, and the denominator is right. Everything else is noise to strip.

**Scoping funnel (demonstrated on the real post-ship ledger: 21 -> 3):**
| filter | why noise | effect |
|---|---|---|
| `t >= ship` (6995fd8) | pre-change turns aren't about the new values | baseline |
| drop `fallback` band | embed/Qdrant down -> floor never ran, not its decision | -6 |
| drop self/meta turns | sessions operating ON skill-concierge (dogfood/verification invoking verify-as-claimed/kickoff/handoff) = agent testing the gate, not a user helped | -7 |
| drop slash/trivial | already pre-gated | - |
| = valid organic offered turns | the only low-noise denominator | **3** (0 taken) |

**Denominator:** offered-turn conversion (surviving-offer take-rate) — NOT global dodge — plus the false-suppression count (actionable turns silenced). This is the ADR's named keep/revert metric.

**Design (kills the noise a naive before/after carries):** do NOT compare pre vs post — the floor changes WHICH turns get offered (population shift), traffic mix differs by day, windows are tiny. Instead **replay both thresholds (0.45 vs 0.40) over the SAME logged post-ship turns** — the ledger stores each turn's top cosine, so re-evaluate both floors on identical traffic; only the knob differs. Within-population A/B; time + traffic noise vanish.

**Irreducible gap:** conversion of a SUPPRESSED offer is unobservable (the agent never saw it). The replay gives surviving-offer take-rate; suppressed-offer take-rate must be estimated from the historical score->take curve (the anti-correlation backtest). That is why the backtest stays load-bearing.

**Stopping rule — gate on VOLUME, not calendar:** base take-rate ~7-20%; distinguishing a few-point change from noise needs ~50-100+ valid organic offered turns with enough takes. Currently 3. Accrue organic non-meta usage (ideally in projects that are NOT skill-concierge), then run the scoped replay. Calendar time is not the gate; organic offered-turn count is.
