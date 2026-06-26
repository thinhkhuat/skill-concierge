---
title: "skill-first x skill-search Fusion - P1 Implementation Task List"
description: "Ordered build breakdown of the locked P1 fusion design (warm embed shim + skill-first hook rewrite). Decomposes docs/plan.md into 4 sequenced phases for the implementing agent."
status: completed
priority: P1
branch: ""
tags: [skill-concierge, fusion, hook, embeddings, qdrant]
blockedBy: []
blocks: []
created: "2026-06-26T10:53:02.945Z"
createdBy: "ck:plan"
source: skill
---

# skill-first x skill-search Fusion - P1 Implementation Task List

## Overview

Ordered, granular build breakdown of the **already-locked** P1 fusion design in
[`docs/plan.md`](../../docs/plan.md). This file does NOT re-decide anything — it only sequences the
build. Authored in advisory mode; a separate agent owns implementation.

**Goal (unchanged from design):** retire the per-turn enforcement hook's weak lexical scorer and
point it at the SAME semantic Qdrant index skill-search already serves, so every prompt gets
semantically-relevant skill candidates instead of token-overlap guesses.

**Decisions already locked — do NOT relitigate (owner-approved 2026-06-26, `docs/plan.md:38`):**
- Embedder = **approach A**: persistent fastembed-mpnet HTTP shim, sidecar to the existing Qdrant
  container, serving the SAME model the index was built with → **no index rebuild**.
- **Hard client-side ~120ms embed timeout → mandate-only fallback** (budget enforcement, not just
  reachability).

## Current state (verified 2026-06-26)

- DONE — **Telemetry ledger LIVE.** `hooks/scripts/ledger.py` logs `turn`/`manual`/`auto`/`search`
  to `~/.claude/skill-telemetry/logs/skill-invocation-ledger.log`. The lexical-hook baseline is
  banking NOW. Do not reset it; snapshot it before go-live (Phase 4).
- DONE — **Retrieval substrate online.** Vendored skill-search engine + MCP `skill-concierge:skill-search`
  (Qdrant `localhost:6333`, collection `claude_skills`, fastembed mpnet-768, 509 indexed).
- TODO — **Warm embed shim** (Phase 1). Not started.
- TODO — **Hook rewrite** (Phase 2-3). Not started; the live enforcement hook is still the lexical
  `~/.claude/hooks/skill_first_nudge.py`, registered in `~/.claude/settings.json`.

## Phases

| Phase | Name | Status | Depends on |
|-------|------|--------|-----------|
| 1 | [Warm Embed Endpoint](./phase-01-warm-embed-endpoint.md) | Done | — |
| 2 | [Hook Rewrite](./phase-02-hook-rewrite.md) | Done | 1 |
| 3 | [Resilience and Budget](./phase-03-resilience-and-budget.md) | Done | 2 |
| 4 | [Acceptance and Rollout](./phase-04-acceptance-and-rollout.md) | Done — go-live executed (applies on restart) | 1,2,3 |

> **Build status (2026-06-26, `ck:cook --auto`):** Phases 1-3 implemented + verified. Phase 4
> acceptance/review/baseline done. **GO-LIVE EXECUTED on owner GO:** committed+pushed `12b61de`,
> plugin updated 0.1.2→0.2.0, lexical `skill_first_nudge.py` deregistered from `~/.claude/settings.json`
> (backup kept). Applies on next Claude Code restart; post-restart verification (one hook fires +
> before/after `analyze.py`) and the logman `RETENTION_DAYS=0` drop-in remain. See `reports/`:
> `code-review-260626-semantic-fusion-impl.md`, `test-260626-semantic-fusion-impl.md`,
> `baseline-260626-lexical-hook-snapshot.txt`.
>
> **Calibrated deviation:** embed timeout default = **90ms** (not the plan-nominal ~120ms). Measured
> python cold-start ~50ms made 120ms breach the co-equal ≲150ms total-budget criterion; 90ms holds the
> slow-path at ~140ms while keeping 3.75x headroom over the 24ms warm p95. Env-overridable
> (`ENFORCER_EMBED_TIMEOUT`).

Strict order **1 → 2 → 3 → 4.** Phase 2 cannot start until the embed endpoint answers health checks;
Phase 4 retires the lexical hook only after the acceptance suite is green and the baseline is snapshotted.

## Source of truth for the implementer

- Design + crux + A/B/C + acceptance: `docs/plan.md` (Design `:48`, Acceptance `:119`, Build log `:146`).
- Decision records: `docs/adr/0002-fusion-which-plus-whether.md`, `docs/adr/0003-embedder-and-vector-store.md`.
- Hook to supersede: `~/.claude/hooks/skill_first_nudge.py` (faithful copy of the which-skills lexical
  scorer; reads `~/.claude/which-skills/library.json` — both retired by this work).
- Embedder parity contract (MUST match the index build exactly): `SKILL_EMBED_MODEL=sentence-transformers/paraphrase-multilingual-mpnet-base-v2`, `SKILL_EMBED_BACKEND=fastembed`.

## Dependencies

No cross-plan dependencies. Self-contained within skill-concierge P1.

## Validation Log

### Session 1 — 2026-06-26 (ck:plan validate, Standard tier)

**Verification Results**
- Tier: Standard (4 phases → Fact Checker + Contract Verifier).
- Claims checked: file paths 6/6, symbols/contracts (`discover_skills` `server.py:287`, collection
  `claude_skills` `server.py:66`, dim 768 COSINE), landmine target. **Verified: all · Failed: 0 · Unverified: 0.**
- Contract finding: the engine embedder is configurable and its DEFAULT is `bge-small-en-v1.5`
  (384-dim), NOT the deployed mpnet-768 → the shim MUST use the deployed `SKILL_EMBED_*` env, never
  engine defaults.
- Risk sharpened: `fastembed` is unpinned (`pyproject: fastembed>=0.3`); installed **0.8.0**
  (mean-pooling); the index was built under 0.8.0. The health warning's "pin 0.5.1" suggestion is a
  **trap** (switches to CLS pooling → mismatches the 0.8.0-built index).

**Decisions confirmed (owner)**
1. Embedder parity → **pin `fastembed==0.8.0` in engine + shim, verify cosine ≈ 1.0, NO rebuild.** (→ Phase 1)
2. Shim runtime → **Docker sidecar next to the Qdrant container** (not launchd). (→ Phase 1)
3. Go-live → **(i) deregister `skill_first_nudge.py` from `~/.claude/settings.json`, then (ii) full
   plugin install via a marketplace release** (uses `hooks.json`; also clears the 0.1.1→0.1.2 cache drift). (→ Phase 4)
4. Baseline window → **owner signals ready** by inspecting `analyze.py`; no fixed window, no auto-swap. (→ Phase 4)

**Recommendation:** proceed — Failed: 0; all four decisions propagated to Phase 1 + Phase 4.

### Whole-Plan Consistency Sweep
Re-read `plan.md` + all 4 phase files after propagation. No stale terms: launchd fully replaced by
Docker sidecar in Phase 1; the "either (a)/(b)" go-live in Phase 4 replaced by the concrete
deregister→release sequence; Phase 4's "enough turns banked" baseline guidance replaced by
owner-signals-ready.
Embedder env/pin consistent across plan.md ↔ Phase 1. **No unresolved contradictions.**
