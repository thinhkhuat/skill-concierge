# INTEGRATED FINAL — skill-concierge: Where It Stands, Where It Should Go

**Date:** 2026-07-04 23:33 (Asia/Saigon) · **Author:** orchestrating agent (research-synthesis)
**Integrates (both left intact):**
- `from-audit-team-synthesis-260704-2312-og-vs-skill-concierge-verdict-report.md` (Workstream 1 — fork vs vendored original 0.1.0)
- `from-openspace-study-team-synthesis-260704-2312-transferable-innovations-for-skill-concierge-report.md` (Workstream 2 — OpenSpace innovations)

Both rest on 7 dimension reports (D1–D4 audit; OpenSpace study A/B/C) + first-hand source reads, all in
this dir. Read-only study — nothing applied.

## Synthesis Overview
| Field | Content |
|---|---|
| **Question** | What is skill-concierge's true state vs the original it forked, and which changes would most improve it? |
| **Decision** | Choose the next build direction (owner-authorized); this brief is the evidence, not the decision |
| **Sources** | 2 synthesis reports over 7 agent audits/studies + live ledger telemetry + both codebases (fork, vendored OG) + OpenSpace |
| **Key conclusion** | The fork did NOT miss engine novelties and its retriever is the stronger of the two — its problem is **over-engineering + a dead-end measurement loop** (the loop exists but never feeds back). ⚠ **RETRACTED quantitative claim:** the earlier "the stack is bypassed on ~55–63% of turns / 11% conversion / enforcement is net-negative" is **NOT SUPPORTED** — the ledger pools ~15 config epochs (v0.2→v0.12) and the current-config (v0.12.0) epoch is <24h old with no clean organic data; see *Data-validity note* below. What survives is config-independent: engine intact, ~840 LOC inert never-fired, OpenSpace's loop as a target, over-engineering counts. OpenSpace's **closed feedback loop** remains the right direction, but the *magnitude* of the enforcement problem is currently **UNMEASURED**, not measured-negative. |
| **Shelf life** | The static findings hold; ALL rate/conversion figures are INVALID until re-measured under frozen v0.12.0 config on organic (non-subagent, non-meta) traffic — data that must be generated going forward, not mined from the mixed-epoch past. |

## Data-validity note (added after user challenge, 2026-07-04 23:57)
The ledger spans 2026-06-26→now across ~15 config epochs (gate-floor changes 06-29, multi-vector 06-30,
AUTHORIZED-SKIP+doctrine v0.12.0 07-04 05:32 — full list: `git log` on enforcer.py/skill-first.md/server.py).
Pooling a rate across them is invalid. Per-day `embed_timeout`: 9–20% (06-27→07-01), then a spike to
**68% on 07-02** and 54% on 07-04 — a sudden onset two days BEFORE the v0.12.0 code shipped, i.e. an
**environmental** break (shim/Docker/load), not a design property. The current epoch has ~19h of data,
dominated by this session's subagent fan-outs. Therefore no ledger-derived rate in this report is
decision-grade; treat them as retracted pending a clean measurement.

## Source basis (light quality note — 2 internal syntheses, not external literature)
Both syntheses are first-party, produced this session, each grounded in agent reports that cite file:line
from both trees and — critically — in **live `scripts/analyze.py` runs on the real ledger** (not vibes).
Highest-confidence inputs: the ledger telemetry (empirical) and the first-hand code reads. Lowest: any
agent claim judging a skill-concierge analog "from the brief" rather than re-reading our source — flagged
in Gaps. OpenSpace claims were verified against its **shipped SQLite DB**, separating its real mechanism
from its README hype.

## The integrated picture (one story, not two)
skill-concierge took a lean, service-free, ~4-command retriever (skill-search 0.1.0) and wrapped it in a
governance layer: enforcement hook, doctrine, ledger, multi-vector retrieval, Docker services, 16 ADRs,
~5,200 LOC. **The engine underneath is intact and slightly improved.** But the wrapper has three proven
problems (Workstream 1), and the fix for the deepest one already exists as a working pattern in OpenSpace
(Workstream 2). The line connecting them: *the fork built machinery to steer the model but never built
the loop to learn whether the steering works — and now measures that it largely doesn't.*

## Findings, by evidence strength

### STRONG evidence
1. **Engine novelties were NOT lost.** OG's drift `warning`, dark/stale `health`, token-proof harness,
   unit tests — all kept, two strengthened (D1, first-hand both trees). "Missed novelty" is largely a NO.
2. **~840 LOC of inert features never fired.** Per-skill tau, deterministic routes, dominance collapse,
   keep-off, legacy `enrich_index` — the live ledger shows 0 route hits, 0 keep-off drops, ever (D2).
3. **⚠ RETRACTED / MOVED TO UNMEASURED — the semantic stack IS bypassed, but the rate is not
   decision-grade.** `embed_timeout` is real and recurrent, but every rate figure here (63/55%, 11%
   conversion) is invalid: it pools ~15 config epochs and the current-config window is <24h old and
   subagent-contaminated (see *Data-validity note* at top). The per-day series shows the timeout is a
   **07-02 environmental onset** (9–20% before, 54–68% after), not a v0.12.0 design property. Correct
   status: the stack is *sometimes* bypassed and the enforcement-value question is **UNMEASURED**, NOT
   measured net-negative. (This item was mis-filed under STRONG evidence in the original; it is not.)
4. **OpenSpace's closed feedback loop is real.** record run → LLM "did each skill help?" → quality rates
   → threshold-triggered self-rewrite, verified in its shipped DB (226 skills, gen 0–3 lineage; study B).
5. **Our retriever substrate beats OpenSpace's.** mpnet-768 MAX-pool + Qdrant ANN > their English-only
   whole-doc cosine, brute-forced in Python (study A). The gap to close is the loop, not the retriever.

### MODERATE evidence
6. **Two-stage retrieval (over-fetch → exact-name rerank)** would sharpen precision cheaply; our path is
   single-stage today (confirmed in `enforcer._retrieve`). ~20 LOC, additive (studies A+C).
7. **Plan-then-select + abstain-to-empty doctrine** (OpenSpace `registry.py:676-704`) sharpens precision
   AND the skip decision at zero infra cost — directly relevant to our false-SKIPPING/getaway problems.
8. **Service-free default is recoverable** (~10 LOC) — the engine still supports embedded mode; only the
   setup path + `.mcp.json` force Docker (D1).
9. **Two gate knobs shipped against their own data** (GETAWAY_FLOOR 0.45, AUTHORIZED-SKIP getaway leg) —
   ADR-0009/0015 evidence argued against both (D2). Owner-gated revert.

### UNMEASURED (do not treat as proven either way)
10. **Body-trigger layer (+60% index, ADR-0016)** — improvement asserted by analogy, never measured; the
    promised A/B never ran (D3). The description-trigger MAX-pool layer IS measured better (narrowly).
11. **Whether closing the loop lifts OUR conversion** — extrapolated from OpenSpace's different context;
    plausible, unproven for us.

## Tensions / contradictions (surfaced, not smoothed)
- **Adopt auto-improvement, reject auto-generation.** OpenSpace's own DB proves auto-CREATING skills
  causes sprawl (226 skills, duplicate families — study B rejects it). But auto-IMPROVING existing
  skills' *retrieval metadata* is the valuable half. Resolution: take the metadata-rewrite loop; keep the
  hand-authored, curated catalogue.
- **The loop must not become the next over-engineering.** "Did it help?" per turn adds LLM cost — the
  exact per-turn tax Workstream 1 condemns. Resolution: async/batched, off the hot path; additive
  fail-silent `effect` event, never a blocking gate.
- **Invest more in enforcement, or strip it back?** Workstream 1 says the enforcement layer is currently
  net-negative; Workstream 2 offers ideas that ADD to it. Resolution: **sequencing settles it** — fix the
  bypass FIRST; you cannot judge (or improve) enforcement while its own retrieval is skipped on most
  turns.

## Integrated prioritized roadmap (proposals — owner-authorized before any build)
Ordered so cheap regression-fixes de-risk the measurement before the big feedback-loop investment:

1. **DISAGGREGATE, then INSTRUMENT + FIX the `embed_timeout` regression.** [STRONG basis] Highest
   leverage — the enforcement premise is unjudgeable while its retrieval is bypassed. Per Opus validation,
   split the two populations FIRST: genuine user turns (~55%, a real shim/contention regression) vs
   subagent-notification burst traffic (~94%, likely just gate it out like `/`-prefixed prompts at
   `enforcer.py:466`). Root cause uninstrumented; fixing the blended number chases a partial artifact.
2. **DELETE the inert graveyard** (`enrich_index`, `build_keep_off`+config, dominance-collapse; demote
   tau + routes to an ADR note). [STRONG] ~840 LOC KISS win, zero behavior change (they never fired).
3. **Cheap precision sharpeners:** plan-then-select doctrine text (#7) + exact-name rerank (#6). [MOD]
   Hours + ~20 LOC.
4. **Env-override gate tuning + revert the against-data floors** (#8/#9). [MOD, owner-gated] Cheaply
   unblocks fixing GETAWAY_FLOOR without a repo edit + deploy.
5. **Build the "actually helped?" `effect` signal** (Workstream 2 #2). [MOD] The measurement upgrade the
   audit demands; prerequisite for the loop. Async, additive.
6. **Close the loop: metadata self-improvement** (Workstream 2 #1). [STRONG mechanism / UNMEASURED lift
   for us] The big one — rewrite a skill's description/trigger-points from low take-rate. Needs #5 first.
7. **Settle the open measurements:** body-trigger A/B (#10) + publish a recall number on our universe +
   restore the service-free option (#8) and the cache-honesty doc section. [closes Gaps]

## Evidence gaps
| Gap | Why it matters | What fills it | Priority |
|---|---|---|---|
| Root cause of the ~55% genuine-turn embed_timeout (blended 63%) | Blocks judging the whole enforcement bet | Disaggregate user vs subagent traffic, then instrument the shim under contention | HIGH |
| Body-trigger lift unmeasured | +60% index shipped on faith | `SKILL_BODY_TRIGGERS=1` vs `=0` A/B + a body-only corpus | HIGH |
| No valid recall number on our universe | Retrieval quality asserted, not shown | Run `precision_eval.py` on the mpnet index | MED |
| "Never armed" proven for only 2 of 5 inert features | Delete-safety | Ledger/telemetry check on the other 3 | MED |
| Will closing the loop lift OUR conversion? | Justifies the biggest build | A/B after #5/#6 ship behind a flag | MED |

## Methodology notes / what this cannot answer
- **Source pool = 2 first-party syntheses** over agent audits I directed; constrained by my own charter
  framing. Mitigated by grounding in live ledger data + first-hand reads + OpenSpace's shipped DB.
- **Some analog judgments came "from the brief"** not a re-read of our source; the two load-bearing ones
  (single-stage retrieve; ledger has no `effect` signal) I cross-checked against code read this session —
  both hold. Others (progressive disclosure) need verification before building.
- **Cannot answer:** whether the enforcement premise (a per-turn tax lifts skill-first behavior) is
  ultimately right — that stays open until the 63% bypass is fixed and a valid benchmark exists.
- **Nothing here is applied.** All recommendations are owner-gated proposals from a read-only study.
