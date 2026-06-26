---
phase: 3
title: "Resilience and Budget"
status: done
priority: P1
effort: "0.5d"
dependencies: [2]
---

# Phase 3: Resilience and Budget

## Overview

Make the new hook safe under a **down** OR an **up-but-slow** embed endpoint. Add the load-bearing
hard ~120ms client-side embed timeout → mandate-only fallback, plus mandate-only fallback on embed/
Qdrant unreachable. The hook never silences and never crashes; it always returns within the ≲150ms
per-turn budget regardless of shim state.

## Related Code Files

- Modify: `hooks/scripts/enforcer.py` — add the timeout + the three fallback paths + `fallback` tagging.

## Implementation Steps

1. **Client-enforced timeout:** wrap the embed POST in a stdlib `urllib` request with a HARD socket
   timeout (~120ms, tunable constant). The timeout is enforced on the CLIENT so the hook returns in
   budget regardless of shim health.
2. **Fallback = inject the existing MANDATE-only text** (never silence, never crash) on ANY of:
   (a) embed endpoint unreachable, (b) Qdrant unreachable, (c) embed call exceeds the ~120ms timeout.
3. **(c) is the load-bearing add** (`docs/plan.md:60-65`): reachability checks miss an *up-but-slow*
   shim (GC pause, cold page, contention) that would otherwise silently tax every prompt with no
   trigger. The hard timeout converts "slow" into a clean fallback.
4. **Tag `fallback`** in the `offer` event when any fallback path fired, so `analyze.py` can compute
   fallback rate.
5. **Budget proof:** confirm total hook time stays ≲150ms = ~120ms embed cap + Qdrant ms + overhead.

## Success Criteria

- [x] Deliberately-slowed shim (injected delay >120ms) → hook falls through to mandate-only AND the
      turn completes ≲150ms (measured with the injected delay).
- [x] Embed endpoint down → mandate-only fallback fires (no silence, no crash).
- [x] Qdrant down → mandate-only fallback fires (no silence, no crash).
- [x] `fallback` flagged in the ledger for those turns; `analyze.py` reports fallback rate.

## Risk Assessment

- **Timeout tuning.** 120ms is a tunable constant. If real warm embeds run hotter, raise it but keep
  total ≲150ms; don't set it so tight that real candidates never make it through (that silently
  collapses the fusion back to mandate-only).
