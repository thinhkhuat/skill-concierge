# Opus Adversarial Validation — OpenSpace→skill-concierge mining (5 reports)

- **Date:** 2026-07-04 23:44 (Asia/Saigon)
- **Validator:** Opus `agent-validator` (adversarial, refute-first; did not author the reports)
- **Subject:** the 5 reports in this directory (synthesis + 4 lanes)
- **Method:** opened source on both repos, checked 20 load-bearing `file:line` citations across 12 files; accepted no claim unread.
- **VERDICT: PASS** — safe to proceed to an implementation plan on the Tier-1 four, with 2 non-blocking advisories.

> ⚠ **EPOCH-VALIDITY CAVEAT** — added 2026-07-05. The citation audit below confirmed each figure is faithfully quoted from its source (e.g. ADR-0009); it did **not** certify any figure as current-state.
>
> **Corrected mental model:** *In a system whose configuration changes almost daily, its telemetry is a sequence of short epochs, not one dataset — a metric is only valid for the config epoch it was collected under; pool across epochs and you measure a system that never existed.*
>
> The ledger figures quoted here — offer→take, "~94% dodge", cosine 0.414 vs 0.457 — are **epoch-specific**, mostly **ADR-0009-era (v0.6.1, 2026-06-29)**, and predate the **v0.10.0 multi-vector retrieval swap** (its own CHANGELOG says *"re-measure before reuse"*). Read only per-epoch (`analyze.py --since/--until` at version-bump commit timestamps); the current epoch (v0.12.0) has N≈15 surfaced offers — **insufficient for any rate**. Corrected per-epoch figures accompany these reports in this directory.

---

## Citation audit — 20/20 CONFIRMED, ~0% hallucination

| # | Claim | file:line | Status |
|---|-------|-----------|--------|
| 1 | `skill_applied` is an LLM/transcript JUDGMENT, not execution telemetry (KEYSTONE) | `types.py:171-179` | CONFIRMED |
| 2 | Counter increment on the judgment | `store.py:573,587-588` | CONFIRMED |
| 3 | `fallback_rate` = not-applied AND not-completed | `store.py:579-583` | CONFIRMED |
| 4 | skill-usage-audit reads `~/.claude/projects/**/*.jsonl` transcripts (KEYSTONE) | `SKILL.md:24-27` | CONFIRMED |
| 5 | skill-concierge retrieval is PURE-DENSE, no lexical/LLM/telemetry (KEYSTONE) | `server.py:431-462` | CONFIRMED |
| 6 | OpenSpace cascade: BM25 pre-filter, "cosine decides final order" | `skill_ranker.py:107-137` | CONFIRMED |
| 7 | BM25 corpus = name+desc+body[:2000] | `skill_ranker.py:264-312` | CONFIRMED |
| 8 | Injection header "follow them — they are verified workflows" (KEYSTONE) | `registry.py:614-629` | CONFIRMED |
| 9 | "When in doubt, leave it out" cost polarity | `registry.py:696` | CONFIRMED |
| 10 | Plan-then-select (`brief_plan` before naming) | `registry.py:688-704` | CONFIRMED |
| 11 | "selected-but-not-applied ⇒ mis-selling description" diagnosis (KEYSTONE Lane 4) | `evolver.py:1573-1579` | CONFIRMED |
| 12 | 2 health rules key on execution-outcome (completion/effective) | `evolver.py:1582-1597` | CONFIRMED |
| 13 | `build_triggers.py` empty-trigger detection | `build_triggers.py:99-112` | CONFIRMED |
| 14 | Post-hoc gate rejected as anti-caveman | `mental-model.md:168-176` | CONFIRMED |
| 15 | Burden-of-proof-on-SKIP doctrine | `ADR-0015:34-37` | CONFIRMED |
| 16 | Architectural gap: top-k preview of 5, "none fit → skip" dodge | `mental-model.md:68-74` | CONFIRMED |
| 17 | Telemetry drop filter (selections≥2 & completions==0) | `registry.py:382-407` | CONFIRMED |
| 18 | search_tools hybrid cascade | `search_tools.py:404-425` | CONFIRMED |
| 19 | ADR-0011 hard-drop offer-suppression + ADR-0009 anti-correlation | `ADR-0011:1-30` | CONFIRMED |
| 20 | Lane 2's four items sit OUTSIDE the usefulness-rate plan | `plan.md:27-32` | CONFIRMED |

**Estimated hallucination rate: ~0% (0 misreads / 0 not-founds in 20 load-bearing citations, both repos).**

## Keystone through-line — TRUE
`skill_applied` is provably an LLM judgment over the transcript (types.py:171-179), not tool telemetry; skill-concierge reads the same class of artifact (`.jsonl`), which carries the assistant reasoning + tool-call trail a follow-through judge needs. Lane 4 correctly marks OpenSpace's *analyzer* port (needs a `traj.jsonl` recording skill-concierge lacks) as LOW/redundant, while Lane 2 routes the follow-through judge through the transcript reader that DOES exist. Internally consistent.

## BLOCKING findings
**None.** No keystone citation MISREAD or NOT-FOUND; through-line holds; every REJECT rests on a confirmed skill-concierge axiom.

## ADVISORY findings (non-gating)
1. **"completion_rate/task_completed = IMPOSSIBLE" is overstated — it's *untrustworthy*, not *uncomputable*.** OpenSpace's own `task_completed` (types.py:260, store.py:576) is itself an LLM judgment, so skill-concierge could compute the same weak guess. The reports' real point ("weak/gameable — do not launder it as completion") is correct; validator endorses stopping at "offered→followed." Only the word choice is imprecise.
2. **Tier-1 #4 (telemetry prior, HIGH) leans on the same ADR-0009 anti-correlated signal that got Lane 3's idea C deferred.** Disclosed via the "#4 depends on #1 landing first" sequencing + traffic-window/sample-floor caveats, and the injection points differ (rank-time prior vs hot-path preview) — but **re-ground #4 on #1's follow-through signal, not raw offer→take, before building.**
3. Minor: the "~47% behavioral compliance" figure in Lane 3's header is uncited background (ADR-0011 documents "~93% offered-turn dodge, 189/204", a different metric). No port recommendation depends on it.

## What held up (trust these)
- Every OpenSpace-side mechanism citation — BM25 corpus, cascade cosine-final-order, WORKFLOW-vs-REFERENCE header, cost polarity, plan-then-select, telemetry filters, evolver mis-selling diagnosis. All verbatim.
- Every skill-concierge axiom the REJECTs rest on — anti-caveman post-hoc rejection, burden-of-proof-on-SKIP, ADR-0009 anti-correlation, the top-k-preview gap. The three REJECTs are correctly reasoned, not strawmanned.
- Scope-collision clean: Lane 2's four are outside the existing plan.
- **#3 (BM25) does NOT collide with in-flight body-trigger retrieval** — body-triggers still route through the dense mpnet embedder; a true lexical signal remains net-new and complementary.
- Caveats honest and complete across all reports.

## Bottom line
Safe to build the Tier-1 four. Sequencing sound: **#2 (consumption framing) and #3 (BM25 fusion) are independent, well-grounded, cheap wins buildable now**; **#1 (follow-through judge) is the sensor and must precede #4 (graduated telemetry actuator).** Single finding to re-ground before building: **#4** — bind it to #1's follow-through signal rather than the raw ADR-0009 offer→take proxy. Read "completion = impossible" as "untrustworthy, don't ship it" — changes nothing in the plan.

**Status:** DONE_WITH_CONCERNS (PASS; 2 advisories, 0 blocking)
