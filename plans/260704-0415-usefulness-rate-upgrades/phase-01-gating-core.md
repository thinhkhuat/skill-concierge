---
phase: 1
title: Gating core
status: completed
effort: M
---

# Phase 1: Gating core — AUTHORIZED-SKIP tier (both legs, default ON) + get_skill nudge

## Overview
Replace the enforcer's two SILENT verdict paths (getaway `top<floor`, intent_skip `conversational`) with an
injected one-line AUTHORIZED-SKIP authorization, so the agent no longer re-runs `search_skills` to
re-derive a verdict the hook already computed. Both legs ON by default, behind an ON-default kill-switch.

## Requirements
- Functional: on getaway + intent_skip, inject a SKILL-CHECK/AUTHORIZED-SKIP line (keep existing
  `_append_offer` telemetry). Silent behavior preserved when kill-switch off.
- Non-functional: hook stays **fail-silent + additive** — never raises, never blocks a turn (AGENTS.md
  guardrail). STDLIB-only, no new imports, no I/O on the trivial path.

## Related Code Files
- Modify: `hooks/scripts/enforcer.py` (ONLY file this phase owns)

## Architecture / anchors (verified 2026-07-04)
- Env-override pattern already used: `GETAWAY_FLOOR` (:66), `MAX_SHORT_WORDS` (:68). Mirror it.
- `MANDATE` constant (:242); `_inject(text)` (:288).
- Silent getaway return: `enforcer.py:473-477` (`_append_offer(sid,"getaway",...)`, `return 0`, no `_inject`).
- Silent intent_skip return: `enforcer.py:483-485` (`_append_offer(sid,"intent_skip",...)`, `return 0`).
- Fallback paths already `_inject(MANDATE)` at :433/441/445/453 — model the new injects on these.

## Implementation Steps
1. Add config near line 66: `AUTHORIZED_SKIP = os.environ.get("ENFORCER_AUTHORIZED_SKIP", "1") != "0"`.
   Add a shared marker constant `AUTHORIZED_SKIP_MARKER = "SKILL-CHECK:"` (Phase 3 audit joins on this exact
   string — keep them in sync; note the cross-file contract in a comment).
2. Build two message constants (concise, additive):
   - **getaway** (score below floor — possibly-real task): state full-catalogue retrieval ran and nothing
     cleared the floor; `SKIPPING: none` is pre-authorized ONLY if the turn is genuinely trivial/non-task;
     if it is real or ambiguous work, do **NOT** skip — **escalate to `find-skills`** (burden of proof on
     SKIP). Include a `get_skill(<name>)` nudge for when a surfaced candidate's fit is unclear from the short
     description slice.
   - **intent_skip** (classified conversational): state the intent-margin classifier judged this a
     conversational/non-task turn; `SKIPPING: none` pre-authorized, no further `search_skills` needed.
3. At the getaway path (:473-477): if `AUTHORIZED_SKIP`, `_inject(<getaway msg, may interpolate top/floor>)`
   before `return 0`; else keep silent (current behavior).
4. At the intent_skip path (:483-485): same pattern with the intent_skip msg.
5. Keep both wrapped so any exception is swallowed (reuse the module's existing fail-silent structure).
6. Extend the module `--selftest`: assert both legs inject when flag on, and stay silent when
   `ENFORCER_AUTHORIZED_SKIP=0`.

## Success Criteria
- [ ] getaway + intent_skip inject an AUTHORIZED-SKIP line by default; silent when `ENFORCER_AUTHORIZED_SKIP=0`.
- [ ] getaway message carries the library-doctrine `find-skills` escalation (burden on SKIP) + `get_skill` nudge.
- [ ] `AUTHORIZED_SKIP_MARKER` constant present and documented as the audit join key.
- [ ] `python3 hooks/scripts/enforcer.py --selftest` passes; hook never raises (fail-silent preserved).

## Risk Assessment
- Over-authorizing skips on real-but-low-scoring tasks (getaway leg). Mitigated by the escalation text in the
  message + ON-default kill-switch + the audit metric (Phase 3). User-directed all-ON (see decisions-audit D1).
