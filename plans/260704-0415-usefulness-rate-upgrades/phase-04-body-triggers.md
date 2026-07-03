---
phase: 4
title: Body triggers
status: completed
effort: M
---

# Phase 4: Body-trigger retrieval (Option 4) + char→token awareness

## Overview
Feed each skill BODY's decision-sections ("when to use" / "Triggers:" / "Use when:") into the existing
MAX-pool trigger layer — which today is built ONLY from `description` phrases. This is the validated recall
fix (proposal Option 4): separate trigger points, MAX-pooled, no dilution of the base vector. ON by default
behind an ON-default kill-switch.

## Requirements
- Functional: when `SKILL_BODY_TRIGGERS` is on (default), each skill's body decision-sections yield extra
  trigger points (same mechanism/point-id scheme as description triggers). Off → description-only (today's
  behavior, exact).
- Non-functional: extracted phrases stay short (well under the model's 384-token cap); vendored engine change
  recorded in VENDORED.md; must not break incremental reindex, content-hash change detection, or the
  hook/MCP parity.

## Related Code Files
- Modify: `vendor/skill-search/skill_search/skills_discovery.py` (body extraction helper)
- Modify: `vendor/skill-search/skill_search/server.py` (emit body-derived trigger points)
- Modify: `vendor/skill-search/VENDORED.md` (record the customization — AGENTS.md guardrail)
- Modify (if present): vendor tests under `vendor/skill-search/tests/`

## Architecture / anchors (verified 2026-07-04)
- `skills_discovery.py:79-91`: parses `description` (+`when_to_use`) and `body.strip()[:4000]`.
- `server.py` `_split_phrases(s["description"])` at ~:358 builds description trigger points; `_LABEL_RE`
  (~:245-267) already matches `triggers?|examples?|use when|also use|use this skill` — reuse it for body
  sections. `_TRIG_MAX=12` (~:248) caps per-source phrase count.
- Deployed model truncates at 384 **tokens** (mpnet-768); the 4000-**char** body cap is looser than that.
  Keep body-derived phrases short so each point embeds fully.

## Implementation Steps
1. `skills_discovery.py`: add a helper that extracts the body's labeled decision-sections (reuse/mirror the
   `_LABEL_RE` labels) — return short phrases, not the whole body. Expose them on the parsed skill dict
   (e.g. `body_triggers`), leaving `description`/`body` untouched.
2. `server.py`: add `SKILL_BODY_TRIGGERS = os.environ.get("SKILL_BODY_TRIGGERS","1") != "0"`. In the trigger
   generation, when on, ALSO run the extracted body phrases through the same `_split_phrases` → trigger-point
   path (respect `_TRIG_MAX`, dedupe against description phrases to avoid double-count). Same MAX-pool query
   side — no change needed there.
3. Ensure stable per-(skill,slot) point ids + content-hash change detection still hold (bodies edit more often
   than descriptions — the hash must include body-trigger source so reindex refreshes them).
4. Record the change in `VENDORED.md`: what/why/where, the flag, and that it must be re-copied + reindexed.
5. Add/extend a vendor test asserting body decision-sections produce trigger points when the flag is on and
   none when off.

## Success Criteria
- [ ] Body decision-sections become trigger points when `SKILL_BODY_TRIGGERS` on; identical to today when off.
- [ ] Phrases short (no per-point token overflow); dedupe vs description phrases; `_TRIG_MAX` respected.
- [ ] `VENDORED.md` records the customization; vendor tests pass; a local reindex builds without error.

## Risk Assessment
- Dilution/noise from body prose. Mitigate: only LABELED sections, short phrases, separate points (never
  blended). Ships without shadow-A/B per user all-ON (D1) — A/B smoke recorded in Phase 7; kill-switch allows
  instant rollback.
- Vendored divergence. Mitigate: VENDORED.md entry + Phase 5 re-copy/reindex.
