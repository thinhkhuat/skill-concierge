---
phase: 1
title: "Enrichment rollout"
status: pending
effort: "spike 1d, then staged ~3-6d (LLM-gen path)"
priority: P1
dependencies: []
effort: "spike 1d, then staged ~3-6d (LLM-gen path)"
---

# Phase 1: Enrichment rollout — index query-style utterances, staged & precision-gated

## Overview
Make retrieval discriminate by enriching each skill's indexed vector with **query-style
trigger utterances**. The recall lift is validated AND red-team-confirmed to generalize
out-of-style (live→shadow rank-1 6%→88% on fresh, sloppier prompts). But the first-draft
rollout was **NO-GO**; this hardened version fixes the source assumption, the
unrepresentative shadow, the missing precision test, the floor interaction, and the
overlay mechanics. Direction is sound; execution is staged and gated.

## Requirements
- Functional: enriched vectors lift correct-skill rank-1 AND keep it above the live floor,
  WITHOUT enriched skills cannibalizing prompts meant for other skills.
- Non-functional: survives incremental reindex; atomic, verified rollback; embed-space parity.

## Architecture & the four corrections

**(A) Trigger SOURCE — the cheap path is likely dead; prove it before committing.**
The engine already embeds `name + description + when_to_use + body[:4000]`
(`vendor/skill-search/skill_search/server.py:237`, `skills_discovery.py:80`). So parsing
"Use when…/Triggers:" prose from SKILL.md re-adds text the vector ALREADY has — unlikely to
reproduce the PoC lift, which came from hand-authored **query-style utterances** (the
`eval/scenarios` positives). **Step 0 experiment (mandatory gate):** on the 14 corpus skills,
enrich with (a) parsed SKILL.md prose vs (b) the hand-authored query utterances; score BOTH
through `calibrate_thresholds.py`. If (a) doesn't recover most of (b)'s separation → the primary
source is **LLM-generated query utterances** per skill (Haiku, separation-gated per batch), and
effort is re-estimated up (multi-day, token-bearing) — NOT the "cheap 2-4d spike".

**STEP-0 RESULT (2026-06-28, measured on 5 skills — gate PASSED with a refinement):** the red-team C1 claim ('prose source dead, text already embedded') is **REFUTED**: prose-*phrase* enrichment (split description → embed each → centroid) **flipped all 3 inverted skills positive** (debug −0.060→+0.061, payment −0.013→+0.100, ai-artist −0.074→+0.075) and improved 4/5 — the phrase-split-centroid MECHANISM, not new text, is what extracts intent. BUT utterances are the ceiling (debug 0.245, vn-author 0.374) and prose can HURT (vn-author prose 0.115 < stored 0.314, fragmenting a long VN description degraded it). **Refined source strategy: per-skill MEASURED choice** — prose-phrase as the cheap floor (fixes inversions), utterances (LLM-gen) as the ceiling, the separation harness picks the better source per skill (and never ships a source that regresses a skill below its stored separation, per vn-author). Effort: back down from 'multi-day LLM-only' to 'prose-phrase baseline + targeted utterance-gen where measured to help'.

**(B) Enrich ALL 495 in shadow BEFORE any recall/precision number.**
A 14-of-495 shadow lets an enriched centroid beat 481 bare-description competitors for free —
red-team measured 57% of cross-domain controls spuriously rank-1 an enriched skill. The headline
90% and "5/70 precision cost" are unmeasurable from it. Build the full enriched shadow first;
all magnitude claims come from there.

**(C) Cross-skill precision harness (494-way) — gate `--live` on THIS, not self-on-negatives.**
The named guard (self-on-own-5-siblings) would never catch haiku→vn-author. Build a harness that
(1) runs each skill's held-out positives through FULL 495-way retrieval and reports a
confusion matrix among enriched skills (sibling cannibalization, worst in dense clusters:
`vn-*`, `officecli-*`, `ck:*`↔`agent-skills:*`), and (2) runs a **cross-domain true-negative
set** (haiku / CI / regex / csv-style prompts that belong to NON-enriched skills) and reports how
often any enriched skill fires above floor. Gate the live swap on these numbers.

**(D) Rank≠offer — re-verify and re-tune the global floor.**
The enforcer gates on hardcoded `GETAWAY_FLOOR=0.20` / `ITEM_FLOOR=0.18` (`enforcer.py:65-66`).
Centroid averaging shifts the absolute cosine scale, so a rank win can still fall below 0.20 →
fewer offers → WORSE. Re-verify "clears-floor" at the LIVE 0.20, and sweep/re-tune the global
floors against the enriched distribution as part of Phase 1 (not deferred to Phase 3).

## Overlay mechanics (red-team M1/M2/M5/M6)
- **Vector-only update, never `upsert`** — use `PUT /collections/{c}/points/vectors`; a full
  upsert clears payload → skills go dark → doctor FAILs → auto-reindex reverts. Post-swap assert
  all 495 payloads still carry `name`.
- **Embed parity** — `enrich_index.py` MUST embed via `skill_search.server.embed` under the
  deployed env (fastembed==0.8.0, mpnet-768); assert the cosine≈1.0 parity check as a HARD gate
  (0.5.1 CLS-pooling mismatch = silent garbage).
- **Enrichment marker** — write `payload.enriched=true` (+ `enrich_source_hash`) so `doctor` can
  count enriched-vs-raw points and detect per-skill erosion. Correct reindex model: a vector-only
  overlay SURVIVES an incremental `--reindex` (content_hash-gated); the real risks are
  force-`--rebuild` (total wipe), a changed SKILL.md (that point reverts to description-only), and
  newly-added skills (never enriched). Handle all three explicitly; hook re-apply into doctor/setup.
- **Atomic rollback** — take a Qdrant collection **snapshot** (`POST /collections/{c}/snapshots`)
  before the swap; `--live` refuses to run without a verified snapshot. Restore = single step.
- **m2** — flat mean weights description `1/(N+1)`; cap N or weight description explicitly so desc
  influence is consistent across skills.

## Related Code Files
- Create: `scripts/build_triggers.py` (source utterances → `eval/triggers.json`), `scripts/enrich_index.py`
  (`--shadow`/`--live`/`--revert`, vector-only update via engine embed), `scripts/precision_eval.py`
  (494-way confusion matrix + cross-domain true-negative set).
- Modify: `scripts/doctor.py` (enriched-marker freshness + reindex re-apply), `setup.sh`,
  and ONLY if step-0 forces vendored sourcing: `vendor/skill-search/*` (avoid by default).
- Reuse: `scripts/calibrate_thresholds.py` (separation gate), `eval/scenarios/*` (seed truth).

## Implementation Steps
1. **Step-0 gate:** parsed-prose vs authored-utterance separation on the 14 → choose the source. Re-estimate effort.
2. Generate utterances for all 495 → `eval/triggers.json` (separation-gated batches; LLM-expand where parsing is thin).
3. `enrich_index.py --shadow` builds a **full-495** enriched shadow via the engine embed path (parity-checked).
4. `precision_eval.py`: recall on a fresh OUT-OF-STYLE / independently-authored split AND the cross-domain true-negative + sibling confusion matrix.
5. Re-verify clears-floor at live 0.20; sweep global floors on the enriched distribution.
6. Gate: recall lift holds OOD, cross-skill false-positive rate within an agreed bound, offers don't drop at the live floor.
7. Snapshot → `enrich_index.py --live` (vector-only update) → assert payloads intact → monitor; `--revert` from snapshot on regression.

## STEP 2–4 RESULTS (2026-06-28, fresh agent) — full-495 shadow built & gated

**Verified enrichment recipe (reverse-engineered from the 14 step-0 shadow vectors, then
re-derived clean).** `enriched = flat_mean( [live S] + [engine_embed(trigger) ...] )`. Stored
vector S IS included; flat mean (so description weight = 1/(N+1), N capped at 12 in
`build_triggers.py`). Reconstruction of the predecessor's 14 shadow vectors confirmed
best_k=6 across all 14 (their PoC used first-6 positives as the train split).

**Embed parity (M5) PROVEN, gate is live.** The live index was built with the deployed
engine path — `skill_search.server.embed`, fastembed==0.8.0, mpnet-768, mean-pooling.
Re-embedding a skill's exact indexed text (`_skill_text`, md5-verified against
`payload.content_hash`) reproduces its live vector at **cosine=1.00000**. The shim (:6363,
sentence-transformers) agrees with fastembed to the same numbers, so the ~0.99 PoC-E residual
was the predecessor's slightly different composition, NOT pooling drift. `enrich_index.py`
re-asserts cos>=0.999 at run time and ABORTS on drift (a 0.5.1 CLS index would fail here).

**Source = uniform prose-phrase for all 495 (v1).** Deliberate per red-team point-(c): a mixed
utterance(14)+prose(481) shadow confounds source-strength with cannibalization. Uniform removes
that; utterances layered separately to isolate the ceiling. `build_triggers.py` split each live
`description` (incl. when_to_use) into intent phrases: 495/495 skills, 0 empty, 1790 phrases
(median 3, max 12). Written to `eval/triggers.json`.

**Full-495 cross-skill precision gate (`precision_eval.py`, 168 pos / 70 neg, floor 0.20):**

| metric | LIVE | SHADOW (prose) | Δ |
|---|---|---|---|
| correct rank-1 % | 11.9 | 29.8 | +17.9 |
| correct top-5 % | 26.2 | 54.8 | +28.6 |
| clears-floor % | 54.2 | 99.4 | +45.2 |
| true-neg false-fire % | 1.4 | 0.0 | −1.4 |

**CORRECTION (advisor-caught).** The `true-neg false-fire` column above is NOT a precision
gate — it counts only the negative's OWN labeled skill firing rank-1, so it is blind to the
real failure mode: WRONG skills clearing the floor. Measured properly, the offer-set CROWDS:

| offer-set (skills clearing floor 0.20 / query) | LIVE | SHADOW |
|---|---|---|
| mean | 87 | 298 |
| median | 35 | 310 |
| p95 | 333 | 465 |

Centroid enrichment shifts absolute cosines up broadly, so at the hardcoded 0.20 floor the
enriched index offers ~⅔ of ALL 495 skills per query (median 310). So "clears-floor 33→69%"
above is real but MISLEADING — the correct skill clears, but so do ~300 others. There IS a
precision cost; it lives in the absolute-scale shift (plan point D), which `true-neg false-fire`
cannot see. The cross-domain sibling confusion (banner-design, perf-opt, tdd) is real ordering
noise but secondary to the crowding.

**The lever is salvageable — the floor re-tune is the precondition.** Sweeping the shadow floor
(168 positives), at τ≈0.40 the offer set (median 20) matches live's (median 35 at 0.20) AND the
correct skill is offered **79% vs live's 33%** at comparable budget — a real 2.4× offer-side win,
gated entirely on re-tuning 0.20→~0.40:

| τ | median offers | correct clears |
|---|---|---|
| 0.20 | 310 | 99% |
| 0.30 | 103 | 93% |
| **0.40** | **20** | **79%** |
| 0.45 | 8 | 64% |

RANK-based gains (rank-1 11.9→29.8%, top-5 26→55%, utterance ceiling 67%/90%) are
scale-invariant and stand regardless of the floor. `precision_eval.py` now reports offer-set
crowding as the real gate (the false-fire column is retained but demoted).

**METRIC FIX + FLOOR 0.40 VALIDATED (re-run on request).** `precision_eval` had computed
clears-floor/rank over only the top-10 (it undercounted the correct skill whenever it ranked
>10 but still cleared the floor) — fixed to read the full 495; the table above now shows the
corrected clears-floor (the earlier 33→69 was the top-10 artifact). Re-running at the re-tuned
floor:

| @ floor | clears-floor (live→shadow) | offer-set median (live→shadow) | true-neg fire |
|---|---|---|---|
| 0.20 | 54.2% → 99.4% | 35 → 310 | 1.4% → 0% |
| **0.40** | 10.7% → **79.2%** | **0 → 20** (p95 140) | 0% → 0% |

Apples-to-apples, each index at its sane floor — **enriched@0.40 vs live@0.20**: correct-skill
offered **79.2% vs 54.2%**, offer-set median **20 vs 35** (TIGHTER), rank-1 **29.8% vs 11.9%**.
0.40 is validated: at it the enriched index beats live on BOTH axes (more correct-skill offered,
less crowding). NOT yet wired into the live `enforcer.py` (GETAWAY_FLOOR=0.20) — that edit
couples to the `--live` index swap (0.40 against the current un-enriched live starves it to
median-0 offers), so it lands together with step 7, not before.

**Ceiling probe (prose vs utterance, identical held-out last-6 positives of the 14, full 495-way):**

| source | rank-1 | top-5 | clears-floor |
|---|---|---|---|
| prose-phrase | 31% | 57% | **99%** |
| utterance | **67%** | **90%** | 100% |

Two reframes: (a) the PoC's "90% rank-1" was inflated by the biased 14-shadow; the honest
full-495 utterance ceiling is **67% rank-1 / 90% top-5** (still ~5× live). (b) the clears-floor
99% in this table is at the un-retuned 0.20 floor where ~300 skills also clear — so it reflects
the scale shift, not a solved offer gate (see the CORRECTION above). Utterances' real edge is
ORDERING (rank-1 31→67%), which survives any floor.

**Decision for the next agent.** Direction confirmed (rank gains real, scale-invariant), but
precision is NOT flat — the floor re-tune (was step 5, deferred) is now a PRECONDITION, not a
nicety: at 0.20 the enriched index offers ~⅔ of all skills. Order of operations:
1. **Re-tune the global floor FIRST** (sweep says ~0.40 restores live-comparable offer-set with
   2.4× correct-skill-offered). Without this, enrichment makes offers WORSE, not better.
2. Then the utterance go/no-go: LLM-gen for 481 buys ordering (rank-1 31→67% on the 14) — worth
   it only if the live dodge is ordering-driven, not offer-driven. Measure the live dodge against
   the re-tuned prose shadow before committing the multi-day token spend.
Steps 6–7 (snapshot, --live) unchanged; nothing has touched `claude_skills`.

New scripts (run under the engine venv — see header of each): `scripts/build_triggers.py`,
`scripts/enrich_index.py` (`--shadow`/`--live`/`--revert`, vector-only, snapshot-gated live),
`scripts/precision_eval.py`. All have `--selftest` (green).

## WENT LIVE (2026-06-28, on user "go live") — steps 6–7 done

`enrich_index.py --live` swapped `claude_skills` to the prose-phrase enriched vectors:
parity gate cos=1.0, **Qdrant snapshot taken** (`claude_skills-3273000707820787-2026-06-27-21-28-32.snapshot`),
495 vector-only updated, all payloads carry `name`. `enforcer.py` GETAWAY_FLOOR default
0.20→**0.40** (ITEM_FLOOR left at 0.18 — NO measured basis to retune; flagged for follow-up).

**Post-swap verification:** precision_eval shows LIVE == prior SHADOW (rank-1 29.8%, top-5 54.8%,
clears-floor@0.40 79.2%, true-neg fire 0%); real queries through the live search path fire @0.40
with the right skill on top (vn-author 0.647, supabase 0.637, ck:debug 0.526). enforcer
`--selftest` green.

**ROLLBACK:** `enrich_index.py --revert` (restores vectors from current live — only valid until
a reindex) OR restore the Qdrant snapshot above; then revert enforcer GETAWAY_FLOOR to 0.20.

**OPEN — doctor status: FAIL (PRE-EXISTING, not caused by enrichment).** Index/disk drift: 84
skills on disk not indexed, 82 indexed skills deleted from disk. Enrichment preserved the 495
points exactly (vector-only), so this is orthogonal staleness that predates the swap. CAUTION:
the fix (`reindex`) currently WIPES enrichment (force-rebuild → vectors from description; M1) —
the enrichment-re-apply hook into doctor/setup is NOT built yet. So do NOT reindex until that
hook exists, or the live enrichment is lost. This is now the top follow-up.

## REINDEX-SAFE RE-APPLY HOOK (2026-06-28) — closes M1 "hook re-apply into doctor/setup"

A reindex rewrites changed/new points BARE (fresh payload, no `enriched` marker, description-only
vector); a force-rebuild resets all. Without re-apply, any reindex silently undoes the live
enrichment. Built `enrich_index.py --reapply` + wired it everywhere reindex runs:

- **`--reapply` (idempotent):** enriches ONLY points missing the `enriched` marker — exactly what a
  reindex bared. Recomputes the bare base from SOURCE text (`embed(_skill_text)`, == stored bare at
  cos 1.0) rather than trusting the stored vector, so it **cannot double-enrich** even on a
  marker/vector desync. Regenerates triggers from each point's CURRENT description (a changed
  SKILL.md gets fresh triggers), refreshes `eval/triggers.json`, vector-only update. Targets LIVE by
  default. Skips indexed-but-deleted-from-disk points (no source).
- **doctor:** new "Enrichment overlay" check (WARN when enriched-mode + some points bare, fix=reapply);
  `fix_reindex` now chains reindex→reapply; `reapply` registered as an auto-fixer. So `doctor --fix`
  refreshes the index AND restores enrichment in one pass.
- **setup.sh:** runs `--reapply` right after its reindex (idempotent + no-op on a never-enriched index).

**Proven:** faithful bared-point restore cos=1.00000; desync (marker cleared, vector enriched) →
recompute-from-source, no double-enrich; idempotent second run = no-op; doctor alarm fires on a bared
point and clears after reapply. All `--selftest` green.

**Then run end-to-end on the real corpus (snapshot first):** `skill-search --reindex` → index 495→498
(86 embedded bare, 82 dead dropped, 412 kept enriched) → `--reapply` re-enriched the 86 (parity cos=1.0
on a genuinely-new skill). triggers.json pruned 580→498. doctor: **FAIL→WARN** — Retrieval health ✓ (498
indexed), Enrichment overlay ✓ (498/498). Staleness cleared without losing enrichment — the hook
works in production. (The "Duplicate MCP" warning was later found to be a FALSE POSITIVE — the repo's
own `.mcp.json` template, unexpanded `${CLAUDE_PLUGIN_ROOT}`, projected as a project MCP only when CWD
is the source repo; `check_dup_mcp` fixed to exclude template projections.)

## Success Criteria
- [x] Step-0 decided by measurement: trigger source that actually reproduces the lift (not assumed cheap).
- [x] Full-495 enriched shadow exists; all numbers come from it, not the 14-shadow.
- [ ] OOD recall lift confirmed on an independently-authored split (treat 90% as a ceiling).
- [~] Cross-skill precision (MEASURED, gate now in precision_eval.py): sibling confusion + offer-set crowding — FAILS at floor 0.20 (median 310/495 offered); passes only after floor re-tune to ~0.40. So: sibling confusion matrix + cross-domain true-negative firing rate within bound (the haiku/CI/csv class does NOT fire an enriched skill above floor beyond the agreed limit).
- [~] Offers do not decrease at the live `0.20` floor — at 0.20 offers BALLOON (35→310); floor re-tune to ~0.40 required and is now a precondition. Original:; global floor re-tuned if needed.
- [~] Overlay: vector-only update + embed parity (cos=1.0) + `enriched` marker PROVEN on the shadow (495 points, payloads intact). `--live` snapshot gate EXERCISED on the live swap (snapshot created, payloads intact); `--revert` built + selftest-covered but not yet exercised (rollback also available via the Qdrant snapshot).

## Risk Assessment
- **Cheap-source assumption false (C1)** → step-0 gate; LLM-gen is the likely real path; re-estimate.
- **Sibling cannibalization at scale (C2/empirical)** → full-495 shadow + confusion matrix BEFORE live; bound it.
- **Rank-up but offers-down (M3)** → re-verify at live floor; re-tune global floor in-phase.
- **Payload wipe / dark skills (M1)** → vector-only update + post-swap payload assert.
- **Embed-space drift (M5)** → engine embed path + fastembed 0.8.0 + parity gate.
- **Non-atomic rollback (M6)** → Qdrant snapshot pre-swap; refuse live without it.
- **Magnitude optimism (M4)** → independently-authored OOD eval; 90% is a ceiling.
