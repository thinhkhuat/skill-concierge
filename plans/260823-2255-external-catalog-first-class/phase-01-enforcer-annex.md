---
phase: 1
title: "Enforcer external annex"
status: completed
priority: P1
effort: "3h"
dependencies: []
---

# Phase 1: Enforcer external annex

## Overview
Make external catalog skills appear as an additive annex in the per-turn offer,
without displacing the installed top-k.

## Requirements
- Functional: one retrieval returns both tiers; installed path byte-identical to
  today; up to `ENFORCER_EXTERNAL_SLOTS` (2) externals scoring ≥
  `ENFORCER_EXTERNAL_FLOOR` (0.40) are appended, marked `[external:<alias>]` with
  the get_skill consumption note. `ENFORCER_EXTERNAL_ANNEX=0` restores ADR-0031.
- Non-functional: no extra Qdrant round-trip; hot-path latency unchanged.

## Architecture (as-built — two-query, revised from the initial single-query sketch)
- `_retrieve` stays UNCHANGED (must_not tier=external, limit TOP_K, 3-tuples) so the
  installed offer is byte-identical whether the annex is on or off.
- NEW `_retrieve_external(vector)`: a SEPARATE query (must tier=external, limit
  EXTERNAL_SLOTS), applies EXTERNAL_FLOOR, returns `[(name, desc, score, alias)]`.
  **Why two queries, not one widened query:** a single widened query would drop
  installed skills out of the limit window whenever externals ranked high in it —
  silently displacing the curated shelf. Two small queries hold the zero-displacement
  invariant. The external query is best-effort (try/except → no-annex on failure).
- `main`: the installed `cands` pipeline (keepoff, deterministic, getaway, intent,
  ITEM_FLOOR, dominance) is untouched and NEVER sees external tuples. `_external =
  _retrieve_external(vector)` (guarded); `_ranked_mandate(shown, annex=_external)`
  renders the installed block then a distinct annex block.
- Alias derived from the external point's `scope` (`catalog:<alias>` → `<alias>`).

## Related Code Files
- Modify: `hooks/scripts/enforcer.py` (`_retrieve`, `_ranked_mandate`, `main`, new
  `_partition`, new env constants, selftest case 11).

## Implementation Steps
1. Add env: `EXTERNAL_ANNEX`, `EXTERNAL_SLOTS`, `EXTERNAL_FLOOR`.
2. `_retrieve`: conditional filter + widened limit + `scope` payload + 4-tuple.
   Keep back-compat: callers that unpack 3-tuple updated.
3. `_partition` + wire into `main` after retrieve; installed keeps the whole
   existing pipeline; external computed separately, never enters keepoff/getaway/
   intent/dominance (annex is context-only, like chain hints).
4. `_ranked_mandate`: optional `annex` param → append
   `• <alias>:<name> [external:<alias>] — <desc> (read via get_skill)` lines +
   one guidance line.
5. Ledger: `_append_offer` records external annex names (Phase 2 consumes).
6. Selftest case 11: partition correctness (installed untouched, external ≥ floor,
   ≤ slots, annex rendered, kill-switch off → no externals, request-shape when
   annex on has NO must_not).

## Success Criteria
- [x] `enforcer.py --selftest` green incl. case 11.
- [x] Live: docker prompt → installed offer unchanged + `antigravity:*` annex
  (≤2, marked, get_skill note); sub-0.40 intent → zero externals.
- [x] `ENFORCER_EXTERNAL_ANNEX=0` → byte-identical to ADR-0031 (must_not present).

## Risk Assessment
- Widened limit adds Qdrant work: signal = latency histogram rise; response =
  shrink buffer. External partition is O(k), negligible.
- 4-tuple breaks an unseen caller: grep `_retrieve(` — sole caller is `main`.
