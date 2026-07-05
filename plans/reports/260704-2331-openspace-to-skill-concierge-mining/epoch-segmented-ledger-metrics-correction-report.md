# Epoch-Segmented Ledger Metrics — Correction (supersedes all pooled figures)

- **Date:** 2026-07-05 00:16 (Asia/Saigon)
- **Why this exists:** an earlier effectiveness read (in chat) **pooled the whole ledger** (2026-06-26 → now) into single conversion/fallback rates. That is invalid — the config changed ~8 times in 8 days, so the pooled ledger mixes non-comparable populations.
- **Produced by:** a 2-agent team run — `epoch-compute` (metrics + independent recompute) and `epoch-auditor` (validity/confound audit). Both are folded in; this report was **corrected twice** — the pooled figures were retracted for per-epoch ones, then the per-epoch trend itself was retracted as noise after the auditor's return (see "What can and cannot be said").

> **Corrected mental model:** *In a system whose configuration changes almost daily, its telemetry is a sequence of short epochs, not one dataset — a metric is only valid for the config epoch it was collected under; pool across epochs and you measure a system that never existed.*

---

## Epoch boundaries (from version-bump commit timestamps on `.claude-plugin/plugin.json`)

| Epoch | Start (local) | Commit | Note |
|---|---|---|---|
| v0.2.1 | 2026-06-26 22:59:32 | d1acc32 | (52 pre-v0.2.1 events excluded, not folded in) |
| v0.3.0 | 2026-06-27 04:16:06 | b5207f3 | SKILL-FIRST doctrine gate |
| v0.5.0 | 2026-06-28 16:01:30 | a5770cd | retrieval floor 0.40 |
| v0.6.0 | 2026-06-28 23:29:04 | 902abc3 | actionability gate |
| v0.6.1 | 2026-06-29 01:06:35 | 6995fd8 | gate floors raised (ADR-0009 measured HERE) |
| v0.10.0 | 2026-06-30 01:00:52 | 5d8c43b | **multi-vector retrieval swap — comparability breaks here** |
| v0.11.0 | 2026-07-01 01:51:30 | 29e6af6 | doctrine rewrite |
| v0.12.0 | 2026-07-04 05:31:46 | f9ea878 | **current** — AUTHORIZED-SKIP + body-triggers |

Each epoch = `[start, next-start)`; v0.12.0 = `[2026-07-04 05:31:46, now)`.

## Per-epoch metrics (`analyze.py --since/--until` at each boundary; N shown)

| Epoch | Turns | Dodge % | Uptake % | Offers shown (band==offer) | Offer→take | Hit@k | Fallback % | Flag |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| v0.2.1 | 19 | 95% | 5% | 12 | 1/12 (8%) | 1/1 | 37% | **insufficient N** |
| v0.3.0 | 111 | 53% | 21% | 92 | 7/92 (8%) | 7/19 (37%) | 4% | OK |
| v0.5.0 | 47 | 49% | 6% | 33 | 1/33 (3%) | 1/3 | 12% | thin (right at threshold) |
| v0.6.0 | 15 | 53% | 7% | 9 | 1/9 (11%) | 1/1 | 8% | **insufficient N** |
| v0.6.1 | 104 | 62% | 20% | 42 | 5/42 (12%) | 6/16 (38%) | 25% | OK |
| v0.10.0 | 60 | 43% | 25% | 39 | 6/39 (15%) | 6/14 (43%) | 16% | OK |
| v0.11.0 | 217 | 72% | 19% | 75 | 8/75 (11%) | 8/23 (35%) | 60% | OK-N; 60% fallback confounds hit@k |
| **v0.12.0 (current)** | 27 | 33% | 48% | **15** | 5/15 (33%) | 5/10 | 36% | **insufficient N** |

**Sufficiency threshold:** N < 30 surfaced offers ⇒ no rate. Fails: v0.2.1 (12), v0.6.0 (9), **v0.12.0 (15, current)**. v0.5.0 (33) is over but thin.

**Independent cross-check:** a standalone raw-JSONL recompute (separate window-builder, offer-join, arithmetic; no import of `analyze.py`) agreed on **all 8 epochs — zero disagreements** on turns / dodge / uptake / offers-shown / take count.

## What can and cannot be said (revised after the confound audit)

The independent auditor (`epoch-auditor`) knocked down even the guarded per-epoch trend. **Both the original pooled figures AND the per-epoch trend are now retracted.** Corrected conclusions:

- **The 8→12→15% "trend" is NOT signal — it is statistically indistinguishable from noise.** Reproduced independently by strict offered-name-match (7/94, 5/54, 6/41 = 7.4% / 9.3% / 14.6%), but the raw conversions are **7, 5, 6 events**; binomial CIs are [2–13%], [1.5–17%], [3.8–25.5%] — heavily overlapping. You cannot reject "no change happened." Retracted as evidence of improvement.
- **Current epoch (v0.12.0) is 100% self-referential dogfooding.** All 27 turns / 19 takes / 4 sessions are this very meta-analysis arc (briefings, handoffs, "study OpenSpace", opus-validate, brief-me…). Its 33% conversion is not a product number in any sense. **No current-state rate exists.**
- **Even the largest epoch (v0.11.0, N=77) is majority non-representative** — on manual inspection only ~3 of 33 sessions are genuine organic questions; the rest are synthetic benchmark-harness prompts, smoke-test pings, `<task-notification>` spam, and meta-work. Raw N is a false proxy for usage in every epoch checked.
- **Comparability across v0.10.0 is doubly broken:** the CHANGELOG's "re-measure before reuse" admission, PLUS the v0.10.0 bucket itself straddles a mid-epoch tau-recalibration commit (2026-06-30 23:26) — 87% of its offers ran under thresholds the project disowns. The 8 boundaries also under-resolve: same-day micro-releases (0.10.x, 0.11.x) collapse into one bucket each, so even one "epoch" is not internally stationary.
- **Nothing is claimable:** no single conversion/fallback rate for "today" or "this week"; no epoch-vs-epoch ranking; the 8→12→15% figure is not evidence of improvement.

## § Workload / dogfooding + sub-epoch churn (auditor findings, folded in)

The per-epoch fix corrects *config* non-stationarity but not two deeper problems the auditor surfaced:

1. **Workload non-stationarity (dogfooding).** The traffic mix is not representative. v0.12.0 = 100% self-generated meta-analysis (every one of 27 prompts is this session's arc). v0.11.0 = majority synthetic-benchmark / smoke / task-notification / meta traffic (~3/33 sessions genuine). A keyword regex undercounts this badly (~26% recall) — it took a manual read of the prompts to see it.
2. **Sub-epoch config churn.** A tau-recalibration commit lands *inside* the v0.10.0 window; 87% of that bucket predates it. Same-day micro-releases are collapsed. So even a single "epoch" bucket is not internally stationary.

Auditor's per-epoch N with session diversity (the real floor): only v0.3.0 (94 offers / 11 sids) and v0.11.0 (77 / 33 sids) clear a session-diversity bar at all — and both fail the representativeness check on inspection.

## Bottom line

No valid current-state rate, and no valid cross-epoch comparison, is claimable from this ledger — not because the metrics code is wrong, but because **no epoch has simultaneously (a) held config still, (b) collected representative (non-dogfood) traffic, and (c) reached session-diverse N ≈ 30.** This sharpens the implication for finding #1 (the follow-through judge): it is a *measurement instrument*, and an instrument is only as good as its measurement conditions. Those conditions — config stability + real traffic + sufficient N — are the true precondition for any usefulness measurement, and they do not exist yet. Build the judge, but do not expect a trustworthy reading from it until the system holds still long enough, under real use, to accrue N.
