# Semantic Fusion Implementation: Embed Timeout & Score Band Tuning

**Date**: 2026-06-26 14:00  
**Severity**: High  
**Component**: skill-concierge hook enforcement + semantic candidate ranking  
**Status**: Resolved (Phases 1-4) / Blocked on owner approval (Phase 5)

## What Happened

Completed the skill-first × skill-search semantic fusion per plan 260626-1751. Deployed warm fastembed mpnet-768 Docker sidecar (scripts/embed_server.py, 127.0.0.1:6363), rewrote the lexical UserPromptSubmit hook into a semantic enforcer.py, and repointed scripts/analyze.py catalogue to run live hit@k / fallback-rate / band telemetry from the Qdrant index.

Code reviewer passed 0 blockers, 6/6 acceptance criteria. Tester: 11/11 PASS. Fixed two valid review findings: telemetry join broke on whitespace in prompts (ledger logged unstripped, enforcer logged stripped), and stale 120ms docstrings.

## The Brutal Truth

The embed timeout decision felt arbitrary at first — the plan said 120ms, it's a nice round number. But live measurement crushed that: Python cold-start takes ~50ms, so 120ms cap pushed the slow-path to ~180ms total, blowing the ≲150ms per-turn budget. Had to re-calibrate to 90ms. The painful part: nobody guesses this without instrumentation. A developer shipping this without measuring latency components would break the budget silently.

The score band insight was humbling. mpnet multilingual cosines are narrow and overlapping — pure trivia sits at ~0.11, real task queries at ~0.22-0.40, but noisy trivia ("what's 2+2") creeps to ~0.24. A single threshold can't separate them. Resolution was cheap: low floor (0.20), pre-gate shallow queries, always rank-order above the floor. But that's only clean in hindsight. The urge to find a "magic number" threshold had to die first.

## Technical Details

**Embed latency tuning:**
- Cold-start (Python interpreter): ~50ms
- Network to Qdrant: ~10ms warm, ~20ms p95
- p95 observed: 24ms warm
- 120ms cap → slow-path total ≲180ms (exceeds budget by 30ms)
- 90ms cap → slow-path total ≲140ms (20ms headroom, 3.75x over warm p95)
- **Decision:** 90ms threshold for per-turn hook latency budget

**Score band compression:**
- Cosine similarity range: 0.11 (noise) to 0.40 (strong real signal)
- Overlap zone critical: 0.22-0.24 contains both modest real queries and random trivia
- Single threshold fails (high false-positive rate in overlap)
- **Resolution:** Low getaway floor (0.20), show all top-k above floor, use rank (not absolute score) as signal; mandate's own getaway clause neutralizes occasional low-confidence fires

**Verification metrics:**
- mpnet cosine parity vs deployed engine index: 1.000000 on EN + Vietnamese
- Warm POST latency: 13.8ms median (well under 90ms budget)
- Telemetry: offer↔turn join now idempotent on whitespace variations

## What We Tried

1. **120ms cap (plan nominal):** Measured 180ms slow-path total; rejected.
2. **Single absolute threshold (0.35):** High false-positive on trivia overlap zone; rejected.
3. **Threshold + query-length gate:** Worked but required heuristics; replaced with rank-ordering + floor.
4. **Ledger logging with original prompt:** Whitespace broke join with enforcer's stripped version; fixed by logging stripped form consistently.

## Root Cause Analysis

**Embed timeout:** Budget was end-to-end (turn latency), not just the network call. Plan writers estimated the network round-trip only; interpreter cold-start was not in the model. Lesson: per-turn hooks are different from batch workloads.

**Score band:** mpnet's compression is inherent to the model; multilingual pretrain trades off precision in the similarity space for coverage. No amount of tuning fixes that. The right response is to stop looking for a threshold and lean into rank-ordering instead.

**Plan inaccuracies:** Two bugs caught during build: (1) library.json read was in analyze.py, not ledger.py as stated; (2) plan listed both a host launcher AND Docker sidecar without clarifying the distinction (sidecar = deployed runtime, launcher = host/dev + parity-testing). Both were low-severity but required real interpretation during execution.

## Lessons Learned

1. **Latency budgets must account for cold-start.** A per-turn hook lives in the critical path. Measure the full stack (interpreter, network, db query) before setting thresholds. Plan-nominal estimates are dangerous when they omit a dominant component.

2. **Score overlap is a design signal, not a tuning problem.** When two categories compress into the same band, a single threshold cannot separate them. Pivot to rank-ordering or multi-signal classification.

3. **Plans need implementation clarity on dual modes.** Stating both a host launcher and a Docker sidecar without marking which is deployed/dev created ambiguity. Write plans as "sidecar deploys to production; launcher used for host/dev parity testing" not just "add sidecar + launcher."

4. **Join on the cleansed form, not the original.** Ledger and enforcer must log the same normalized input. Unstripped whitespace in prompts breaks telemetry joins silently (low hit@k) unless you catch it in review.

## Next Steps

> **Update (same session, 2026-06-26): go-live EXECUTED on owner GO.** Shipped as v0.2.0
> (commit `12b61de`), lexical hook deregistered from `~/.claude/settings.json` (backup kept),
> plugin updated 0.1.2→0.2.0, applied via `/reload-plugins`. Verified live: one enforcement
> hook fires, `band=offer` with candidates when settled. The "owner must approve" note below
> was the state at journal-write time. See `docs/plan.md` status header.

**Phase 5 (go-live) is HIGH-RISK and owner-gated:**
- Deregister lexical `skill_first_nudge.py` from ~/.claude/settings.json
- Bump marketplace version + install semantic enforcer
- Risk: Double-injection if cache still has the old lexical hook; requires cache flush + verification

**Owner must approve before proceeding.** No automated go-live; this is a manual handoff. The build is done and verified, but the deployment cuts over the skill-first enforcement model live. That decision is not ours.

**Future: Baseline metrics.**
Once live (with approval), establish baseline hit@k by skill, fallback rate, and latency p95 by offer band. Use that to inform future threshold tuning without guesswork.

---

**Status**: DONE  
**Summary**: Semantic fusion build complete (phases 1-4), verified 11/11 tests; phase 5 deployment blocked pending owner approval due to high-risk live cutover.
