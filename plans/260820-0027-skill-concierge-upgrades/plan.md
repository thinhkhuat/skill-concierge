# Plan — skill-concierge pragmatic upgrades (agent/harness value)

## Why stale was incremental-only
- disk hash 2686bd87 != manifest 2a366ad4, same count 389
- one file changed post-index: vn-news-coverage-tracker (00:12, +17.4m)
- incremental: re-embed 1 skill (688 pts, 5146 skipped) vs rebuild 389 skills — same outcome, ~8x cheaper. Verified: `{"embedded":688,"skipped":5146}` and doctor now green on retrieval health.

## Phase 1 — P0 instrumentation & timeout (P0.1 + P0.3 bite)
- [ ] Add embed_ms/qdrant_ms + fallback_reason timing to ledger offer events (enforcer.py)
- [ ] Bump EMBED_TIMEOUT_S 0.20 -> 0.35 (enforcer.py:63)
- [ ] Add --latency flag to analyze.py histogram
- [ ] Verify: curl enforcer selftest, analyze --since window

## Phase 2 — Flywheel robustness (gateway confirmed permanent)
- [ ] Raise max_tokens 2000->4000 in flywheel_llm.py / llm_triggers.py (finish_reason=length x22)
- [ ] Verify triggers path unification already correct (SKILL_TRIGGERS -> durable home) — no move needed, just guard
- [ ] Throttle: don't stamp on length-error (auto_flywheel.py)

## Phase 3 — Menu + thresholds (P1.4/P1.5)
- [ ] Align SKILL_TOP_K 10->6 in .mcp.json (code default is 6)
- [ ] Keep GETAWAY_FLOOR 0.45 but expose per-skill tau toggle (no flip yet — measure first)

## Phase 4 — Chain hints (P2.7)
- [ ] Seed 3 next-skills: verify-as-claimed->session-handoff, skill-concierge:doctor->skill-concierge:flywheel, ak:plan->ak:cook

## Phase 5 — Overrides drift
- [ ] Run apply-overrides to clear -24 stale

## Verification
- [ ] doctor.py status WARN->OK (only overrides remains)
- [ ] enforcer.py --selftest OK
- [ ] analyze.py fallback rate measured post-change (epoch-windowed)
