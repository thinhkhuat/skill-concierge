---
phase: 3
title: "Enforcer per-session enablement gate"
status: completed
priority: P1
effort: "2h"
dependencies: [2]
---

# Phase 3: Enforcer session gate

## Overview

The enforcer already computes `INVOCABLE_PLUGIN_IDS` from the fully merged user+project+local layers. Extend the offer-side filtering so Claude sessions demand membership for `plugin`-scope rows (today only FOREIGN_SCOPES rows are gated), and sweep the other offer-adjacent lanes (annex rows, chain-hint/ROUTE successor names) with the same predicate.

## Requirements
- Functional: a `plugin:skill` row whose plugin is disabled in THIS session's merged layers is never offered/hinted/routed here; enabled rows are unaffected; `INVOCABLE_PLUGIN_IDS is None` (unreadable manifests) filters nothing (fail-open, ADR-0034 contract).
- Non-functional: one-var revert `ENFORCER_PLUGIN_GATE=0`; no new network or file I/O on the hot path beyond what `_invocable_plugin_ids()` already does at import; OMP/ZCode/DSH/Cline lanes untouched.

## Architecture

- In the `_retrieve` post-filter (`hooks/scripts/enforcer.py` ~`:1302`), add a Claude-only leg: `RUNNING_HARNESS == "claude"` and `scope == "plugin"` and gate flag on → require `name.split(":", 1)[0] in INVOCABLE_PLUGIN_IDS`. Docstring cites the layering asymmetry and points at ADR-0052.
- Annex rows (~`:1392`) and `_visible_sidecar_names()`/ROUTE successor filtering get the same predicate so no lane leaks a session-disabled plugin skill (fix-the-generator-then-sweep-the-class).
- `_selftest()` gains cases: enabled plugin row survives; disabled dropped; None → no drop; flag-off → no drop. Selftest output carries the `plugin-enablement gate` marker (G3 greps it).

## Related Code Files
- Modify: `hooks/scripts/enforcer.py`

## Implementation Steps
1. Add the gate predicate + flag; wire into `_retrieve` post-filter, annex, hint/ROUTE name filters.
2. Extend `_selftest` with the four cases and the output marker.
3. Run selftest; run the dev-engine discovery probe to confirm the offer-facing universe (advisory only — offers are enforcer-side).

## Success Criteria
- [ ] G3: selftest OK with the plugin-enablement gate marker

## Risk Assessment
- Over-gating: a plugin enabled but whose registry entry is malformed → dropped offer. Mitigation: the existing union-not-last-writer rule and the None-means-UNKNOWN contract are preserved verbatim.
- Epoch: this changes offer-composition measurement — record the epoch boundary in ADR-0052 + CHANGELOG; no rate claims across it.
