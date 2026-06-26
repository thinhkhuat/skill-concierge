---
phase: 4
title: "Acceptance and Rollout"
status: done
priority: P1
effort: "0.5-1d"
dependencies: [1, 2, 3]
---

# Phase 4: Acceptance and Rollout

## Overview

Run the full P1 acceptance suite (`docs/plan.md:119-136`), review via `code-reviewer` + `tester`
subagents, dogfood on real transcripts, **snapshot the lexical baseline from the ledger**, then go
live by retiring the lexical hook and enabling the semantic enforcer — with a settings backup and a
rollback path. The baseline snapshot is the irreversible-if-skipped step: do it FIRST.

## Related Code Files

- Modify: `~/.claude/settings.json` — deregister the old lexical hook (BACK UP first).
- Reference: `scripts/analyze.py` (baseline vs after), `docs/plan.md` acceptance checklist,
  `config/keep-on.json` (do not let override regen clobber it — see Risks).

## Implementation Steps

1. **Snapshot the baseline FIRST** (before any go-live): run `analyze.py` on the current ledger and
   save the lexical-hook numbers (offer/uptake/hit@k/dodge/fallback). This is the "before" half;
   once the hook swaps it is **irrecoverable** (`docs/plan.md:135`). Go-live timing is
   **owner-gated**: the owner signals ready after inspecting `analyze.py` — no fixed window, no
   automated swap. <!-- Updated: Validation Session 1 - owner-signals-ready baseline -->
2. Run the full acceptance checklist (Success Criteria below) on dev-local.
3. **Dogfood on real transcripts:** replay representative prompts; eyeball that semantic candidates
   beat the old lexical picks, especially the EN→VN semantic-jump class.
4. Spawn `code-reviewer` + `tester` subagents on the shim + enforcer (same gate the ledger and
   reproduction-layer slices passed). Apply blockers/should-fixes; re-verify green.
5. **Back up `~/.claude/settings.json`.** Then, in order (Validation S1, owner): (i) **deregister the
   old lexical `skill_first_nudge.py`** from `~/.claude/settings.json`; (ii) cut a **marketplace
   release** and **full plugin install** so the new enforcer goes live via `hooks.json` — this also
   clears the 0.1.1→0.1.2 cache drift. <!-- Updated: Validation Session 1 - deregister then full install -->
6. Confirm exactly ONE enforcement hook fires post-swap (no double injection from old + new).
7. Let the ledger run a comparable window post-swap, then run `analyze.py` again → **measure** fusion
   lift (uptake up / dodge down) before-vs-after. Lift is measured, not asserted.
8. Wire logman with `RETENTION_DAYS=0` for the compounding ledger (default 90d DELETES data —
   `docs/plan.md:89-91`). Deferrable, but note the shape is already drop-in.

## Success Criteria (the P1 acceptance gate, `docs/plan.md:119-136`)

- [x] Per-turn hook latency within budget with the warm endpoint (≲150ms, measured).
- [x] Hard ~120ms embed timeout enforced (injected-delay test → mandate-only, turn ≲150ms).
- [x] Hook injects semantic top-k — an EN query surfaces a VN-described skill the lexical scorer missed.
- [x] Embed / Qdrant DOWN → mandate-only fallback (no silence, no crash).
- [x] `library.json` no longer read; one catalogue; counts reconcile to the index.
- [x] Safety contract intact: fail-silent, never-blocks, empty/slash suppressed.
- [x] Ledger logs offer + manual + auto + search (tagged by `ev`); manual distinct from auto.
- [x] `analyze.py` prints offer / uptake / hit@k / dodge / fallback + per-skill rollups.
- [ ] Ledger is ONE append-only compounding `.log`; logman-detectable; `RETENTION_DAYS=0` documented. *(PENDING: logman wiring deferred — step 8; ledger is already a single append-only `.log`.)*
- [x] Baseline captured on the lexical hook BEFORE the fusion landed (before/after comparable).
- [x] Old lexical hook retired; exactly one enforcement hook live. *(GO-LIVE EXECUTED 2026-06-26 on owner GO: committed+pushed `12b61de`, `skill_first_nudge.py` deregistered from `~/.claude/settings.json` (backup `settings.json.bak-260626-pre-fusion-golive`), plugin updated 0.1.2→0.2.0. Applies on next Claude Code restart; verify exactly one enforcement hook fires post-restart.)*

## Risk Assessment

- **Override-generator landmine (`docs/plan.md:177`).** `generate_overrides.py` targets
  `settings.local.json` (deleted) with a 2-item keep-on default → a rerun nukes the curated
  always-on set. Guard before ANY override regen during rollout; the curated set lives in
  `config/keep-on.json`.
- **Baseline timing is owner-gated** (no fixed window, Validation S1): the risk is swapping too early.
  The owner inspects `analyze.py` for a stable sample before signaling ready; the hook never auto-swaps.
- **Rollback:** keep the `settings.json` backup; reverting = restore the backup + re-enable the old
  hook + stop the enforcer. The semantic path degrades to mandate-only even if left half-wired, so a
  partial rollback is non-catastrophic.
