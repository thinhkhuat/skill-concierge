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

## Dependencies

- **Predecessor:** `260626-1751-skill-first-semantic-fusion-impl` (completed — provides the live semantic index this plan improves).
- **Internal ordering:** P3 `blockedBy` P1 (re-calibrate after enrichment) and P4 (activation gate). P4 `blockedBy` P1 (measure after enrichment is live). P2 is independent (parallel track).
- **Constraints:** vendored engine `vendor/skill-search` is upstream-managed — touching its indexing path is significant (P1 weighs a vendored-edit vs a non-vendored overlay). Repo writes go via Bash (workbench Write-tool hook). No git ops (git/ dir state).
