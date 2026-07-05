# CORRECTED HANDOVER — Epoch-Scoped Re-Run: Original (skill-search 0.1.0) vs skill-concierge (0.12.0)

**Type:** corrected baseline + audit charter (supersedes the 2312 handover's DATA sections) · handed to the team
**Date:** 2026-07-05 00:18 (Asia/Saigon) · **Author:** orchestrating agent
**Why a re-run:** the prior pass pooled the invocation-ledger across ~15 config epochs and read the aggregate
as a current-state signal — an invalid foundation that produced a false "enforcement is net-negative" verdict.
This charter re-runs the SAME job with the corrected data discipline (now codified in `AGENTS.md` → Guardrails
and `CLAUDE.md`). READ-ONLY. Outputs → `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/plans/reports/`.

## THE CORRECTED MENTAL MODEL (binds every agent)
A metric is valid ONLY for the config epoch it was collected under. This repo changes what the ledger
measures almost daily, so the ledger is a **sequence of short epochs, not one dataset**. For ANY ledger
rate (fallback/conversion/dodge/hit@k): (1) window to the current epoch; (2) exclude subagent/harness/meta
+ self-session traffic; (3) if the clean sample is tiny → say **INSUFFICIENT DATA**, never pool backward to
inflate n; (4) a shift not aligned to a config commit is **environmental**, not a design property; (5) an
epoch-pooled or tiny-sample rate is **UNMEASURED**, never "measured."

## CORRECTED DATA FOUNDATION (established this session — verify, then use; do NOT re-pool)
- **Current epoch start = 2026-07-04 05:32** (v0.12.0 live; last metric-affecting commit `7a7da28`, 07-04 04:57).
- **Windowed `analyze.py --since "2026-07-04 05:32"`:** 87 events, 29 turn-windows, **27 offers**.
  - offered-turn conversion **5/17 (29%)** — *n=17, NOT reliable*.
  - fallback rate **9/27 (33%)**; genuine-only (excl. subagent) `embed_timeout` **5/20 (25%)**.
  - clean current-epoch surfaced-offers (genuine) **= 14**.
- **Verdict on the data-dependent value question: INSUFFICIENT DATA.** 14–20 clean offers cannot support a
  rate. Do NOT restate 63% / 11% / "net-negative" — those were epoch-pooled + contaminated artifacts.
- **Environmental context (NOT current-config signal):** per-day `embed_timeout` was 9–20% (06-27→07-01),
  spiked to 68% on 07-02 and ~54% on 07-04 — a sudden onset 2 days BEFORE v0.12.0 shipped ⇒ environmental
  (shim/Docker/load), an OPERATIONAL issue to investigate separately, not an enforcement-design property.
  Pre-07-02 healthy shim baseline ≈ 15% (context only; a different epoch).

## WHAT IS CONFIG-INDEPENDENT (stands from the prior pass — re-verify quickly, do not re-derive from scratch)
These rest on file-reads / OpenSpace's DB, NOT ledger rates, and were Opus-validated PASS:
engine novelties kept; ~840 LOC inert features (`config/*.json = []`, never armed — binary fact); OpenSpace's
closed-loop verified in its shipped DB; static over-engineering LOC counts; body-triggers UNMEASURED;
service-free default lost; our mpnet MAX-pool retriever > OG's whole-doc cosine. Confirm these hold; spend
your effort on the DATA layer that changed.

## AUDIT DIMENSIONS (one agent each) — SAME as before, corrected data rules
- **D1 — Missed-novelty** (config-independent): re-verify OG features dropped/diverged (service-free default,
  drift `warning`/`health`, proof harness, tests, cache-rebuttal). Table {feature → KEPT/DIVERGED/DROPPED →
  file:line}. No ledger rates involved.
- **D2 — Over-engineering** (mostly config-independent + ONE data point): the inert graveyard LOC + never-armed
  (binary ledger fact, epoch-independent — still valid). For any efficiency/value claim about the enforcer,
  apply the corrected discipline: current-epoch clean sample only, or INSUFFICIENT DATA. Do NOT claim
  "net-negative."
- **D3 — Retrieval fidelity** (config-independent): multivector measured-better (real A/B), body-triggers
  UNMEASURED. Unchanged by the data correction — re-confirm.
- **D4 — Ops-complexity & value** (data-dependent — THE one that must change): re-do the value question under
  the corrected discipline. Install/maintenance cost delta is static (keep). But the "is the enforcement
  layer worth its cost" verdict MUST be re-grounded: window to the current epoch, exclude contamination, and
  if n is tiny return **INSUFFICIENT DATA + what clean window would settle it** — NOT a negative verdict.

**All agents:** ground every claim in file:line or a windowed command; mark any ledger rate INSUFFICIENT
DATA/UNMEASURED unless it survives the 5-step discipline; distinguish design from environmental. Write to a
`{d1..d4}-corrected-...` report; end with Status + 1-line Summary + Unresolved.

## Unresolved (for the team)
- The enforcement-value question is currently UNMEASURABLE (n too small in the clean current epoch) — the
  honest output is a measurement PLAN, not a verdict.
- The 07-02 `embed_timeout` onset is an operational incident to triage separately from enforcement design.
