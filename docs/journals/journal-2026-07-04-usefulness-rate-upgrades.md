# Journal — 2026-07-04 — Usefulness-rate upgrades (0.12.0)

## What & why
Two Opus-validated findings drove this arc, both from re-studying the enforcer's own behavior
rather than tuning thresholds again:

1. The enforcer already runs a real semantic retrieval over the full catalogue on **every**
   prompt, but on its two "no offer" verdicts — **getaway** (top score < floor) and
   **intent_skip** (conversational turn) — it returned nothing at all. The agent, bound by the
   SKILL-FIRST doctrine's "no skip without a search" rule, had no way to know the hook had
   already looked and cleared the turn, so it re-ran `search_skills` to re-derive a verdict that
   already existed. The perceived over-firing was the doctrine's blindness to a decision already
   made, not hook noise.
2. The multi-vector trigger layer (ADR-0012) built its MAX-pool phrases from each skill's
   one-line **description** only, but the decisive "when to use this" signal usually lives in
   the skill's **body** — `## When to Use`, `Triggers:`, `Use when:` sections. That signal was
   in the base vector already, but truncated (~384-token embedder limit) and blended into one
   mean-pooled vector, which dilutes rather than surfaces it.

Both fixes are documented in full in [ADR-0015](../adr/0015-authorized-skip-tier-and-library-doctrine.md)
(AUTHORIZED-SKIP tier + library doctrine) and [ADR-0016](../adr/0016-body-derived-trigger-points.md)
(body-derived trigger points).

## Sequence
`/plan` produced the Opus-validated proposal (`plans/reports/proposal-260704-0244-…`) →
sequential Sonnet-5 implementer sub-agents, one phase's files at a time, no worktree (parallel
edits to the same `enforcer.py` would have collided; sequential was the user's explicit call) →
deploy + reindex the live engine → this docs phase (Phase 6). Every fork faced during the run
is recorded standalone in
[`plans/260704-0415-usefulness-rate-upgrades/decisions-audit-log.md`](../../plans/260704-0415-usefulness-rate-upgrades/decisions-audit-log.md)
for later audit — decisions D0–D8, not re-litigated here.

## Decisions — the all-ON override (loudest one)
The proposal recommended shipping the **intent-margin leg** default-ON but the **getaway-floor
leg** and **all of body-trigger retrieval** default-OFF, gated behind a post-v0.10.0 score
re-measurement, because ADR-0009 showed cosine score is *anti-correlated* with adoption (taken
offers median 0.414 < dodged offers 0.457) — a bare score-floor skip fires exactly where
real-but-low-scoring work lives, risking under-gating.

**The operator explicitly overrode this and directed everything ON now** (decision log D1),
having been shown the tradeoff in those terms. This is honored, not silently softened. The
mitigations shipped alongside the override, not instead of it:
- Every feature gets an env kill-switch **defaulting ON** — `ENFORCER_AUTHORIZED_SKIP`,
  `SKILL_BODY_TRIGGERS` — so rollback is one env var, no code change.
- The getaway-leg message embeds the library-doctrine escalation (real/ambiguous work →
  `find-skills`, never a bare self-declared skip) — the feature firing is not equivalent to a
  blind skip.
- `audit_skill_usage.py` now tallies `authorized_skip` separately from `false_skip`, so any
  under-gating regression is measurable, not just felt.
- Prereq #4 (re-measuring score↔adoption on post-v0.10.0 multi-vector traffic before trusting
  `GETAWAY_FLOOR`) stays open, tracked in both ADRs and the handoff — it was not resolved, only
  deferred with the risk stated plainly.

## Two factual slips caught mid-flight
Both were caught by the operator reviewing the work in progress, not by a self-check the
implementer ran on its own — worth naming plainly:

- **The body-trigger point-count claim.** An early draft of the design note, a code comment, and
  `VENDORED.md` all asserted the COMBINED per-skill cap (`_TRIG_MAX`) keeps the total index point
  count "flat." The live reindex disproved that outright: points went **2231 → 3570 (+60%)**. The
  cap bounds per-skill triggers at 12 (vs. unbounded if body triggers got their own extra slots on
  top), but the *total* still rises because most skills' descriptions left slots empty (median
  ~3/12) that body phrases now fill. Corrected in the code comment, `VENDORED.md`, and the decision
  log (D8) to "bounded growth, not flat" — still far under full-body chunking's 2–4×, just not zero.
- **`VENDORED.md` missing the new engine patch.** The body-trigger extraction (`_extract_body_triggers`,
  `_trigger_phrases`) is a direct edit to the vendored engine source, which the project's own
  convention requires logging in `vendor/skill-search/VENDORED.md` (re-apply-on-re-vendor list).
  It was implemented without that entry; added afterward alongside the point-count correction.

Neither slip changed the shipped behavior — both were documentation catching up to what the code
already did — but both are the kind of drift the project's driftcheck/ADR discipline exists to
catch, so they're named here rather than folded silently into "docs updated."

## Validation status
- Vendor unit gate: **29 passed**, 1 pre-existing `@pytest.mark.integration` test deselected
  (`test_end_to_end_build_search_incremental` asserts `embedded == indexed`, false under the
  multi-vector layer, identical on `main` before this work — decision log D7, left as a documented
  pre-existing issue, not a regression from this arc).
- `enforcer.py --selftest` and `audit_skill_usage.py --selftest`: both green, ON and OFF.
- Live reindex: `{"indexed":488, "embedded":1339, "skipped":2231, "deleted":0}` — the +1339 body
  points landing as expected. `doctor` reports `status: OK`.
- **Not yet run:** the opus-validate pass and the shadow A/B on the body-trigger layer (rank-1 /
  separation delta) — both scoped into Phase 7, after this docs phase. Neither the enforcer tier
  nor the trigger layer has a live organic-traffic adoption read yet; that needs a post-deploy
  window (see the handoff's open follow-ups).

## Files touched this phase
Docs only — `README.md`, `AGENTS.md`, `CLAUDE.md` (the two new flags + ADR pointers), this
journal, and the companion handoff. No code, ADR, or CHANGELOG edits (those were already in place
before this phase started).
