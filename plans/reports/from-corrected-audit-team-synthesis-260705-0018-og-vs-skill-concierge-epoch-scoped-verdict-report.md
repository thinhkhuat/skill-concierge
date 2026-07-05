# CORRECTED SYNTHESIS — OG (skill-search 0.1.0) vs skill-concierge (0.12.0): Epoch-Scoped Verdict

**Date:** 2026-07-05 00:18 (Asia/Saigon) · **Author:** orchestrating agent, synthesizing the corrected 4-agent audit
**Supersedes:** `from-audit-team-synthesis-260704-2312-…` (which pooled the ledger across ~15 config epochs).
**Inputs:** d1/d2/d3/d4-corrected-260705-0018 reports + the corrected handover, all this dir. Read-only.

## Bottom line (corrected)
The engine core is intact; the fork's real problems are **over-engineering** (proven, config-independent)
and — the key correction — **an enforcement layer whose value has NEVER been measured on real usage.** The
prior "measured net-negative" verdict is **withdrawn**: it was an artifact of pooling ~15 config epochs and
of a current window that contains **zero organic turns.**

## What changed vs the flawed pass, and what did not
| Finding | Prior pass | Corrected | Basis |
|---|---|---|---|
| Engine novelties kept | ✓ | ✓ **unchanged** | file-reads (config-independent) |
| ~840 LOC inert graveyard never fired | ✓ | ✓ **unchanged, hardened** | binary ledger fact: **0/601 offers** ever fired a route/keep-off drop — epoch-independent |
| Retrieval: multivector better, body-triggers UNMEASURED | ✓ | ✓ **unchanged** | offline held-out A/B, NOT the ledger |
| Service-free default lost / no recall number / cache rebuttal dropped | ✓ | ✓ **unchanged** | file-reads |
| **"63% bypass / 11% conv / enforcement net-negative"** | asserted as STRONG | ❌ **WITHDRAWN → INSUFFICIENT DATA** | epoch-pooled + 100%-meta current window |

## The corrected value picture (D4)
- Current config epoch = since **2026-07-04 05:32** (v0.12.0). Windowed: **27 offers / 17 surfaced.**
- **Composition: 100% self-referential** — 9 offers from this audit session, 4 subagent `<task-notification>`
  events, **0 organic task turns.** Genuine-turn `embed_timeout` ≈ 25% (n≈20) — modestly above the 15%
  pre-07-02 healthy baseline, but n is far too small to trust.
- **Verdict: the enforcement layer's value is UNMEASURED — organic n ≈ 0.** Not negative, not positive:
  never tested on real work. The 07-02 timeout spike pre-dates v0.12.0 → an **environmental ops incident**,
  triaged separately from enforcement design.

## What survives as trustworthy (config-independent; Opus-validated)
1. **Engine intact + retriever is the stronger substrate** (mpnet MAX-pool > OG whole-doc cosine — measured A/B).
2. **DELETE the inert graveyard** — ~840 LOC, `config/*.json=[]`, 0/601 fired. Pure KISS win, zero behavior risk.
3. **Enforcer is over-engineered on its own merits** — four inert stages threaded into the per-turn hot path,
   independent of the (unmeasurable) value question.
4. **Two gate knobs ship against their own data** (GETAWAY_FLOOR 0.45, AUTHORIZED-SKIP getaway leg) — owner-gated reopen.
5. **Recoverable losses:** service-free default (~10 LOC), a published recall number (harness exists), cache-rebuttal doc.

## Corrected recommendations (owner-gated; nothing applied)
1. **GENERATE clean measurement — now the #1, and a prerequisite for every value claim.** You cannot judge
   enforcement while the only data is the tool measuring itself. Freeze v0.12.0; add a ledger filter excluding
   subagent/`<task-notification>` traffic, skill-concierge-meta sessions, and the measuring session's own sid;
   accumulate **~80–150 organic offered turns.** Only then is "is enforcement worth its cost" answerable.
2. **DELETE the inert graveyard** [config-independent, safe now].
3. **Triage the 07-02 embed_timeout spike as an ops incident** (shim/Docker/load), decoupled from enforcement.
4. **Reopen the two against-data gate knobs with the owner.**
5. **Cheap sharpeners + service-free restore + recall number** — as before, unaffected by the correction.

## Unresolved
- Enforcement value: UNMEASURABLE until #1 yields organic data. The honest deliverable is a measurement plan,
  not a verdict.
- Body-trigger lift: UNMEASURED (offline A/B never run) — D3's gap, independent of the ledger.
