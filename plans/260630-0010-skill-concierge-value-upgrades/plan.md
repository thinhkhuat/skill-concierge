# Plan — skill-concierge value upgrades (BM25-doc missed novelty + close-out)

**Created:** 2026-06-30 · **Driver:** `/ck:cook` "all actionable mechanisms" + close-out
**Status:** DONE (pending final code-review + commit) — see Outcome
**Branch:** main

## Goal
Implement the genuinely-missed novelty from the BM25-routing doc + the owner-approved
close-out items, providing measurable value/quality to the plugin — finished to a clean stop.

## Scope (user-approved via AskUserQuestion, 2026-06-30)
IN: multi-vector MAX-pooling experiment (shadow) · per-skill τ wiring · deterministic
enforcement tier · corpus-health report · reindex · report correction · analyze.py
denominator fix · commit close-out docs.
OUT: keep-off auto-regen wiring (explicit "don't arm yet") · P5 activation (gated downstream).

## Grounding evidence (scout, this session)
- doctor: index stale ~5h; **enrichment overlay NOT live** (bare single-vector index); 500 serving.
- `eval/thresholds.json`: 14 skills, 5 `ok`, **all 5 τ ≤ 0.45** (live floor) — one negative.
- `calibrate_thresholds.py` own note: lever for weak/no-signal is "index content/embedding, not calibration".
- enforcer: single global `GETAWAY_FLOOR=0.45`; `_retrieve` top-5, stdlib REST, fail-silent.
- `precision_eval.py`: LIVE-vs-SHADOW A/B harness; ranks by POINT (needs group-by-skill-max for multi-vector).

## Key design decision (grounded disagreement)
Per-skill τ and the deterministic tier touch LIVE routing on a system the owner tuned
conservatively (false-offers dominate the dodge). The data shows arming τ live now would
LOWER bars and ADD false offers. So both mechanisms ship **default-INERT behind env flags
with selftests** (matching the project's `DOMINANCE_RATIO` / keep-off-auto-regen pattern) —
implemented + verifiable, not silently regressing live routing. Multi-vector is measured on
shadow; it is the substrate lever that could later justify arming τ.

## Phases

### P0 — Safe wins (ship live)
1. **Reindex** live (`skill-search --reindex` / engine) — clear stale, refresh offers.
2. **analyze.py denominator fix** — dodge headline → band=="offer" denominator (ADR-0009 number revised; owner-approved). Update ADR-0011 Open→Resolved note.
3. **Report correction** — fix "enrichment shipped live" overstatement in `plans/reports/analysis-260629-2342-bm25-doc-missed-novelty-report.md` (doctor proves not-enriched; reframe MEAN-vs-MAX as bare-vs-MAX).
4. **doctor corpus-health check** — read `eval/thresholds.json`, report ok/weak/no-signal counts + fix hint. Additive, fail-open.
- Acceptance: doctor green/warn unchanged except new line; analyze.py selftest (if any) + manual run sane; report internally consistent.

### P1 — Multi-vector MAX-pooling experiment (shadow; DELEGATED)
1. Build `claude_skills_shadow` = base skill vectors + per-trigger/scenario points (payload name=skill), reindex-robust (real points).
2. Adapt eval to group-by-skill-MAX before ranking (fair multi-vector scoring).
3. Run LIVE (bare single-vector) vs SHADOW (multi-vector MAX): rank-1%, top-5%, clears-floor%, true-neg false-fire%, offer-crowding, separation delta.
- Acceptance: metrics table returned. DECISION GATE: multi-vector live-wiring proposed ONLY if it beats baseline on recall AND does not blow up true-neg/crowding. Else shelve-with-data.

### P2 — Mechanisms in enforcer (default-inert, tested)
1. **Per-skill τ wiring** — `ENFORCER_PER_SKILL_TAU` (default off). When on: load `eval/thresholds.json`, for `ok`-status skills use per-skill τ as that candidate's floor; global floor otherwise. Raise-only safety note. Selftest pins behavior + default-inert.
2. **Deterministic enforcement tier** — tiny high-precision exact-pattern→skill map, `ENFORCER_DETERMINISTIC` (default off). Selftest pins patterns + default-inert + additive (never blocks).
- Acceptance: `enforcer.py --selftest` passes incl. new cases; both default-inert (no live behavior change unless flag set).

### P3 — Finalize (MANDATORY subagents)
1. `code-reviewer` subagent — acceptance/regression/contracts/patterns/lint across all touched files.
2. `tester` subagent — run all `--selftest`s + any repo tests; 100% pass.
3. project-management sync (this plan + the retrieval-enrichment plan.md status), docs-manager (if warranted), `/ck:journal`.
4. Commit close-out docs + this work via git-manager (owner-approved).

## Risks / rollback
- enforcer changes: default-inert → zero live behavior change; rollback = unset flags / revert file.
- shadow build: isolated collection; never touches `claude_skills`.
- reindex: 500 already serving; standard op.

## Outcome (2026-06-30)
- **P0 shipped:** reindex (stale cleared); analyze.py band=="offer" denominator (ADR-0011 Open→Resolved; build_keep_off regression caught + fixed); report enrichment-is-live correction; doctor Corpus-health check. doctor `status: OK`.
- **P1 validated + WIRED LIVE (user chose full send):** multi-vector MAX-pool — rank-1 2.2x, top-5 1.8x, separation 2.2x, flat false-fire (shadow held-out). Floor sweep → KEEP 0.45 (no flood there). Live index migrated 500→2312 points (500 base + 1812 trigger); retrieval rewritten to Qdrant groups/MAX in search_skills + enforcer; latency ~2ms. ADR-0012.
- **P2 shipped default-INERT (data-backed):** per-skill τ (`ENFORCER_PER_SKILL_TAU`) + deterministic routes (`ENFORCER_DETERMINISTIC`, config/deterministic-routes.json) — wired + selftested, OFF by default (all 5 ok-τ < 0.45 floor → arming would add false offers; arm τ only after recalibrating vs multi-vector scores).
- **Your-call:** analyze.py denominator fix adopted; close-out docs to be committed at finalize.

## Activation caveat
The persistent skill-search MCP runs old single-vector code until it restarts → its `search_skills`
returns duplicate points on the multi-vector index until reload. Enforcer (per-prompt subprocess) is
already on the new code. **Restart the MCP / reconnect to fully activate.** Revert: `SKILL_MULTIVECTOR=0`
+ reindex.

## Resolved questions
- Multi-vector beats bare enough? YES (2.2x, validated). Wired live.
- Arm inert flags now? NO — per-skill τ/deterministic stay inert (data shows arming τ now regresses);
  measure real adoption (analyze.py offered-turn conv) over a traffic window first.
