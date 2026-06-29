---
title: Retrieval enrichment rollout + compliance loop (post-fusion)
description: ''
status: in-progress
priority: P2
branch: main
tags: []
blockedBy: []
blocks: []
created: '2026-06-27T19:43:38.213Z'
createdBy: 'ck:plan'
source: skill
---

# Retrieval enrichment rollout + compliance loop (post-fusion)

## Overview

**Successor to** `260626-1751-skill-first-semantic-fusion-impl` (the v0.2.0 semantic fusion; shipped). This plan executes the post-fusion findings validated in-session 2026-06-28 (see `plans/reports/from-xia-bm25-routing-competitor-analysis-260628-0108-...-report.md`).

**The reframe that drives this plan.** The project assumed retrieval worked and *compliance* was the bottleneck (offered-turn dodge ≈ 92%). A per-skill threshold calibration (Phase D) disproved the threshold premise but surfaced the real cause: **for ~⅔ of skills the indexed vector doesn't separate the right skill from siblings** — 4/14 were *inverted* (negatives out-scored positives). A shadow PoC then proved the fix: **enriching a skill's indexed vector with trigger phrases lifts correct-skill rank-1 from 12% → 90%** (held-out, real 495-way retrieval), clears-floor 37% → 100%, for a small precision cost (self-on-own-negatives 1/70 → 5/70). So the dodge is **substantially a retrieval failure, not only compliance.**

**Sequencing rationale.** Phase 1 (enrichment) is the proven, dominant lever and the critical path — it likely shrinks the dodge directly and makes more skills calibratable. Phase 2 (doctrine re-injection) is orthogonal (compliance side) and runs in parallel. Phase 3 (threshold wiring) is now marginal and should run *after* Phase 1 re-calibration. Phase 4 (clean-window measurement) is the referee for every compliance claim and gates Phase 3's activation.

> **RED-TEAM 2026-06-28 — Phase 1 NO-GO as first drafted → GO-WITH-CHANGES (folded in below).** Two independent adversarial reviews (primary-source + live probes) found: (a) the recall lift is REAL and generalizes out-of-style (6%→88% on fresh prompts) — core method sound; BUT (b) the 'cheap parse-from-SKILL.md' trigger source re-adds text the engine ALREADY embeds (`name+description+when_to_use+body[:4000]`) — the proven lever was query-style *utterances*, i.e. the LLM path; (c) the 14-of-495 shadow structurally favors enriched skills — 57% of cross-domain control prompts spuriously rank-1 an enriched skill, so the 90%/precision numbers are unmeasurable until ALL 495 are enriched in shadow; (d) rank≠offer: centroid averaging shifts absolute cosine vs the hardcoded 0.20 floor, so floor re-tuning moves INTO Phase 1; (e) overlay mechanics need vector-only update (not payload-wiping upsert), fastembed-0.8.0 embed parity, a Qdrant snapshot for rollback, and an `enriched` marker. Direction confirmed; rollout is now staged and gated on a full-495 shadow + cross-skill precision.

## Current state (2026-06-28) — LIVE

Phase 1 **shipped live**. `claude_skills` swapped to prose-phrase enriched vectors (snapshot taken,
parity cos=1.0, payloads intact); `enforcer.py` GETAWAY_FLOOR 0.20→0.40. Verified: live rank-1
11.9→29.8%, clears-floor@0.40 79.2%, real queries fire with the right skill on top. ROLLBACK =
`enrich_index.py --revert` or restore the Qdrant snapshot + floor→0.20.

**RESOLVED:** the re-apply hook is built (`enrich_index.py --reapply`, wired into doctor `--fix` +
setup.sh), so reindex is now safe. Ran it: index 495→498 (86 embedded, 82 dead dropped, 412 kept
enriched), reapply re-enriched the 86 (parity cos=1.0), triggers.json pruned to 498. doctor now **status: OK** (was FAIL) — all checks green: Retrieval health ✓ (498 indexed, fresh),
Enrichment overlay ✓ (498/498), Duplicate MCP ✓. The earlier "Duplicate MCP" warning was a FALSE
POSITIVE (the repo's own `.mcp.json` template projecting an unexpanded `${CLAUDE_PLUGIN_ROOT}` entry
when CWD is the source repo); `check_dup_mcp` fixed to exclude template projections. Age-based
staleness cleared by a reindex (content unchanged: embedded 0 / skipped 498 → enrichment preserved,
reapply no-op).

**Other follow-ups:** utterance go/no-go (ordering gain, rank-1 31→67% on the 14; LLM-gen for new/481);
ITEM_FLOOR retune (left at 0.18, unmeasured); OOD recall on an independently-authored split.

## Phases

| Phase | Name | Status |
|-------|------|--------|
| 1 | [Enrichment rollout](./phase-01-enrichment-rollout.md) | LIVE (prose-phrase enriched + floor 0.40 shipped; utterance ceiling + index-staleness fix pending) |
| 2 | [Doctrine decay reinjection](./phase-02-doctrine-decay-reinjection.md) | Pending |
| 3 | [Per-skill threshold wiring](./phase-03-per-skill-threshold-wiring.md) | Pending |
| 4 | [Compliance measurement](./phase-04-compliance-measurement.md) | Pending |
| 5 | [Offer-suppression keep-off map](./phase-05-offer-suppression-keep-off.md) | Shipped INERT v0.9.0 — machinery deployed; suppresses nothing (keep_off:[]); activation still gated on P4 clean-window data |
| 6 | [Runner-up-gap menu collapse](./phase-06-runner-up-gap-collapse.md) | Shipped INERT v0.9.0 — default-off (ENFORCER_DOMINANCE_RATIO unset) |

## Dependencies

- **Predecessor:** `260626-1751-skill-first-semantic-fusion-impl` (completed — provides the live semantic index this plan improves).
- **Internal ordering:** P3 `blockedBy` P1 (re-calibrate after enrichment) and P4 (activation gate). P4 `blockedBy` P1 (measure after enrichment is live). P2 is independent (parallel track).
- **Added 2026-06-29 (Tier-0 offer gates, from smart-suggest study):** P5 (offer-suppression) `blockedBy` P4 — suppression must use the post-enrichment clean-window, NOT the pre-enrichment ledger (its never-taker counts are confounded). P6 (runner-up-gap collapse) is an independent display rule; its *measurement* uses P4. New ADR proposed (ADR-0011) for the suppression policy; no silent threshold flip (ADR-0009 score≠take lock). Rejected: porting smart-suggest's regex workflow rules (EFFORT already lives in the effort-gate plugin) and a Tier-2 'opportunistic' band (the ~93% offered-turn dodge means over-suggestion, not under).
- **Constraints:** vendored engine `vendor/skill-search` is upstream-managed — touching its indexing path is significant (P1 weighs a vendored-edit vs a non-vendored overlay). Repo writes go via Bash (workbench Write-tool hook). No git ops (git/ dir state).

## Validation Log

### Session 1 - 2026-06-29 (scope: Phase 5 + 6 only)

**Verification (Light tier, 2 phases):**
- Referenced files exist: config/keep-on.json, scripts/apply-overrides.py, scripts/analyze.py, driftcheck.json.
- Next ADR number = 0011 (highest on disk: 0010).
- FAILED -> Phase 6 mechanism: top-share over 186 real multi-candidate offers maxes at 0.285 (median 0.215); a %-share threshold (0.60/0.40/0.30) fires 0%. The share mechanism is unworkable in mpnet's compressed band -> redesigned to a top-vs-runner-up gap ratio.

**Decisions:**
1. Phase 6 -> collapse on top-vs-runner-up GAP (top/2nd >= ENFORCER_DOMINANCE_RATIO, default ~1.25), not %-share. Resolves the verification failure. Phase file renamed to phase-06-runner-up-gap-collapse.md.
2. Phase 5 suppression = HARD-DROP keep-off skills from the offered set (still search-reachable).
3. Phase 5 never-take threshold = take-rate <= 5% with a minimum offer count N (default 15); set in ADR-0011.
4. Phase 5 governance = AUTO-regen + auto-apply (operator choice over human-review). REQUIRED mitigations: regenerate from the Phase-4 clean-window only, enforce min N, keep keep-off reversible (revert path), and log the suppressed set on each regen.

**Propagation:** phase-05 + phase-06 updated (see file markers); phase-06 renamed.

**Whole-Plan Consistency Sweep:** plan.md table + dependencies note updated to the new Phase 6 name/mechanism; the old phase-06-dominant-share-collapse.md removed. No live claim still asserts a %-share threshold or "downweight". The %-share figures that remain (this log) are historical record of the rejected approach, not a live contradiction. No unresolved contradictions.

### Session 2 - 2026-06-29 (cook P5 + P6, inert; independent review)

**Built (staged in source; NOT committed / deployed):** ADR-0011, scripts/build_keep_off.py,
config/keep-off.json (keep_off: []), enforcer.py P5 hard-drop filter (fail-open) + P6
runner-up-gap collapse (default-off via ENFORCER_DOMINANCE_RATIO).

**Verified:** enforcer.py --selftest OK (+ keepoff-drop, gap-collapse, lone-render); analyze.py
--selftest OK; driftcheck IN SYNC; doctor WARN = pre-existing stale-index only (all change-relevant
checks green). Mechanism test reproduces the known never-takers on the full ledger.

**Key finding:** on the post-enrichment clean window (71 SHOWN-menu turns), 0 skills qualify for
suppression -> P5 ships INERT. The full-ledger never-takers were a pre-enrichment artifact; the
clean-window dependency prevented a wrong suppression.

**Independent review: SHIP-WITH-FIXES.** Merge-safe (inert). 6 fixes applied (see ADR-0011 Review):
corrected suppression denominator to band==offer (#1), P6 logs post-collapse (#2), --full overwrite
guard (#3), env parse guard (#4), intent_skip telemetry (#6), ADR re-entry wording (#5).

**Held at finalize (--auto high-risk + commit-needs-explicit-ask):** no commit, no version bump, no
phase-status flip — pending operator go.

**Deferred (operator decisions / activation):**
- Whether analyze.py adopts the band==offer denominator (changes the ~93% headline; ADR-0009-adjacent).
- Auto-regen wiring into doctor --fix / setup.sh (don't arm an unproven generator on a timer).
- Reindex for the stale-index WARN.
- "Enrichment overlay: not enriched" per doctor — investigate vs the plan's "enrichment shipped live".

### FINALIZE (2026-06-29 23:41) — cook close-out, completed late (see /come-clean)
v0.9.0 committed (8abcffd) + pushed + deployed (marketplace update + reload). Validated by TWO
independent verifiers -> GO (active=0.9.0, cache==source, --selftest OK, fail-open/fail-silent
confirmed, generator reproduces 6 never-takers, doctor WARN=stale-index only). P5/P6 phase status
synced above. Journal: docs/journals/2026-06-29-skill-concierge-090-offer-suppression.md. Handoff:
.handoff/handoff-2026-06-29-2341-skill-concierge-090-offer-suppression-shipped.md.
