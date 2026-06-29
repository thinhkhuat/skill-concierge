# Actionability Gate Shipped (v0.6.0)

**Date:** 2026-06-29  
**Component:** skill-concierge enforcer  
**Status:** Shipped  
**Version:** 0.5.0 → 0.6.0  

## What Shipped

The enforcer now suppresses skill offers on non-actionable turns via an **actionability gate** — a per-turn classifier that detects when a prompt is conversational (status, opinion, meta) rather than task-shaped (imperative, tool-invoking), and silently skips the offer when the conversational signal dominates.

**Implementation:**
- Class-margin rule: compute mean cosine similarity of the prompt to top-K neighbors in each of two classes (actionable vs. conversational), suppress the offer iff `(conv_sim - act_sim) > 0.03`.
- Fail-open throughout: any missing data, timeout, error, or imperative-verb detection bypasses the gate and offers normally.
- Grounding corpus: 932 labeled prompts mined from `~/.claude/projects/` transcripts, balanced across classes, labeled by agent outcome (Edit/Write/≥3-tools → actionable; prose-only → conversational).
- Integration: new `scripts/build_prompt_intent.py` (idempotent, stdlib-only, self-testing); wired into `setup.sh` and `doctor.py` as an auto-repair step; new ledger band `intent_skip` for measurement.

## The Investigation

The live enforcer ledger showed **93% offered-turn dodge**: when a skill was surfaced, the agent took it 7% of the time. Analysis revealed:

1. **Cosine score does not predict adoption.** Dodged offers had higher median top scores (0.445) than taken ones (0.408) — so score-based fixes (margin gates, per-skill demotion) move the needle ~0%.

2. **The discriminating axis is intent, not score.** The 9 taken offers were imperative commands ("write the handoff" → session-handoff). The 127 dodged were conversational turns (status, approval, meta-discussion) that topically cleared the 0.40 floor but wanted no skill.

3. **Rejected alternatives, with evidence:**
   - **LifeOS-style LLM mode/tier classifier:** Wrong axis for skill selection (mode answers "how much effort," not "which skill"). Adds per-turn inference cost with no amortization in skill-concierge's charter. ✗
   - **Deterministic triviality short-circuit:** Tested on the live fallback band (11% of offers). Found: 0/18 fallback turns trivial — all were embed-timeout on long prompts, not chat trivia. A word-list would false-suppress legitimate offers ("what does this function do" → 0.560 → match). Live floor already triages empirically. ✗

## Design Iterations (Caught by Smoke Tests)

1. **Imperative-verb count alone (≥4 of 5 neighbors)** → wrongly suppressed 176/210 actionable turns; inert on novel phrasing.  
2. **Absolute neighbor count** → biased by the conversational minority class (~30%); fires 0/12 times on out-of-distribution test prompts.  
3. **Switched to class-margin** → mean similarity per class, margin-based suppress rule. Addressed the prior bias; final `M=0.03` → ~2% false-suppression on backtest, ~33% conversational suppressed on novel turns.  
4. **Corpus imbalance** → initial build was ~1170 actionable / 466 conversational. Rebalanced the corpus; gate then operated at spec.  

## Verification

- Smoke tests: conversational prompts silent, imperative/actionable prompts offer normally.
- Backtest: false-suppression ~2% on held-out labeled set; live edge cases passed.
- Full health check: `doctor.py` verifies collection exists, has balanced classes, fires deterministically on test prompts.
- Version in sync: plugin.json, marketplace.json, CHANGELOG.md, README badge all bumped to 0.6.0; driftcheck passed.
- Commit: `902abc3`; pushed and deployed via `/plugin update` + `/reload-plugins`.

## Known Limits

The gate is conservative (~33% recall of conversational noise). The embedder captures topic more than intent (68% kNN separability), so the signal is moderate. The effect on real-world offered-turn dodge is unknown pending measurement via the new `intent_skip` ledger band; collection of baseline data is ongoing.

The gate does not address the second-order problem: precision (chronic never-taken skills like `review-docs` 0/21, `ck:journal` 0/18). That requires negative anchors and firing-condition enrichment of the index — separate work.

## Post-ship dogfood (live 0.6.0 behaviour)

Exercised the live gate on three real conversational turns right after deploy. **The actionability gate fired 0 times** — each turn was caught by an EARLIER layer:

| prompt | what caught it |
|---|---|
| `good job` (2 words) | `MAX_SHORT_WORDS` pre-gate — returns before the embed |
| `my last turn good job…` (long) | `getaway` (top 0.395 < the 0.40 floor) |
| `well, that's good then` (4 words) | `getaway` (top 0.2535 < floor) |

Mechanism (the useful finding): the `GETAWAY_FLOOR` absorbs most conversational turns because casual acknowledgments match NOTHING in the catalogue (top ≈ 0.25). The actionability gate only runs on the narrow slice `{>2 words}` ∩ `{top ≥ 0.40}` ∩ `{non-imperative}` — conversational prompts that *topically* match a skill anyway (the smoke-test `"good direction we're heading…"`, which it did suppress). In this workload that slice is rare; the floor + pre-gate + imperative-veto do nearly all the work. **Caveat for reading the `intent_skip` band later: a near-empty band means "the floor got there first", NOT "the gate failed."**

## Architectural escalations (honest take, post-ship)

1. **The substrate measures topic, not usefulness/intent.** Everything rests on mpnet cosine over skill *descriptions*. This session proved that primitive doesn't carry the signal the system needs: cosine score did not predict adoption (dodged median top 0.445 > taken 0.408; ~68% intent separability). Every layer — the floor, the gate's kNN — inherits it. **The ceiling now lives in the substrate, not the structure.** Deepest architectural risk; not fixable by more organ-level tidiness.
2. **The Enforce organ is accreting an overlapping gate-stack.** Four filters deep per turn (≤2-word → refusal → `GETAWAY_FLOOR` → actionability gate → item floor), and the dogfood showed they *overlap* (the floor absorbs what the gate targets). The gate added real surface area (a 2nd Qdrant collection, a build pipeline, doctor checks, a tuning knob) for a small, narrow-surface gain. Watch the stack doesn't keep growing layer-by-layer.
3. **The central bet is still unproven (six versions in).** "Does enforcing skill-use improve outcomes?" remains unanswered — meta-contaminated data, dodge dominated by false-offers not compliance failures. Dominant *strategic* risk, distinct from code quality (which is sound).

## Next

Monitor the `intent_skip` band and offered-turn dodge metric as real usage accrues. If the gate's conservative recall proves limiting, widen it (lower margin, more conversational anchors). If precision becomes the bottleneck, move to negative-anchor enrichment. But the larger questions sit under all of that: (a) get a clean non-meta window to test whether enforcement helps at all, and (b) decide whether cosine-over-descriptions is the right primitive or the system needs a richer signal (intent / realized-outcome / usefulness) beneath every layer.
