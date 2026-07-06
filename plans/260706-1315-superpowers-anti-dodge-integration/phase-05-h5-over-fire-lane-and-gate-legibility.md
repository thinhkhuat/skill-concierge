---
phase: 5
title: "H5 Over-fire Lane and Gate Legibility"
status: pending
effort: "M"
---

# Phase 5: H5 Over-fire Lane and Gate Legibility

## Overview

Add a narrow "explain-my-own-prior-output" authorized-skip lane so the gate stops forcing pointless searches on self-referential/trivial turns, and make the two `SKILL-CHECK` messages legible (state the WHY). This is the **over-fire** mirror the doctrine has no symmetric guard against — surfaced live this session (a trivial explain-turn was forced into a `search_skills` ritual). Depends on: Phase 1 (lane-semantics lock). Parallel with H4.

## Requirements

- Functional: (a) a new pre-gate lane detecting self-referential turns; (b) the cross-file contract update (unique anchor + selftest 2→3 + parity test). **Gate legibility (formerly item b) is DEFERRED [Red-Team F12]** — it is a separate hypothesis and, worse, rewording `GETAWAY_SKIP_MSG`/`INTENT_SKIP_MSG` risks breaking the audit's substring anchors (`audit:176-177`). Ship the lane only.
- Non-functional: default-ON `ENFORCER_SELFREF_SKIP` (one-var revert); **NARROW** detector; fail-open (error → normal routing, never a blanket skip).

## Architecture (grounding-exact)

- **Correct reference frame [Red-Team F1/F2, Critical].** The enforcer fires on `UserPromptSubmit` and sees ONLY the user's prompt (`enforcer.py:463`) — never the agent's self-narration. So the detector matches **user prompts that request an operation on the assistant's IMMEDIATELY-PRIOR message** — 2nd-person ("explain/expand/rephrase *your last answer / that point*"), deictic, with NO external object clause. (The agent-side "surely no skill" thought is an H2 doctrine row — Phase 4 — NOT a detector input; the enforcer can never see it.)
- **Whole-prompt task-verb veto [Red-Team F1, Critical].** `_is_imperative` (`:408-430`) checks only the LEADING token, so "explain your answer **and implement** the migration" escapes it. The lane MUST scan the ENTIRE prompt against `_IMPERATIVE_VERBS ∪ _VN_VERBS` and VETO on ANY hit. The self-referential phrase must be the whole semantic payload (short, no object). Anything with a task tail → fall through to normal routing (do NOT fire the lane, do NOT blanket-bless).
- Insert as a no-I/O pre-gate near `enforcer.py:468-478` — detect → `_authorized_skip_inject("selfref")` → `_append_offer(sid, "selfref_skip", ...)` → `return 0`.
- **Unique-signature message + parity test [Red-Team F8, High].** The 3rd message constant (beside `:314-324`) must carry a DISTINCTIVE, prose-unlikely signature phrase (like the two existing signatures). Add THAT phrase to the audit marker-match (`audit:176-178`); bump the selftest (`:694`) 2→3; ADD a parity selftest asserting the new anchor does NOT match the getaway/intent messages OR the H2 doctrine-table row (Phase 4) — else the audit miscounts real false-skips as authorized, masking dodges. Coordinate the Phase-4 table wording with this phrase.

## Related Code Files

- Modify: `hooks/scripts/enforcer.py` (new lane + flag + 3rd message + legibility + selftest 2→3)
- Modify: `skills/skill-usage-audit/scripts/audit_skill_usage.py` (new anchor substring at `:176-178`)
- Create: `docs/adr/0019-over-fire-lane-and-gate-legibility.md`

## Implementation Steps

1. Add `ENFORCER_SELFREF_SKIP` flag (default-ON) + the narrow self-referential pre-gate lane (outright-skip).
2. Add the 3rd `SKILL-CHECK` message constant (INTENT-style pre-authorize).
3. Update audit marker-match `:176-178` with the new anchor; bump selftest 2→3 + add a must-fire case.
4. Add legibility (the WHY) to the two existing messages + the ranked mandate.
5. `enforcer.py --selftest` green (incl. must-NOT-fire real-task fixtures); finalize ADR-0019.

## Success Criteria

- [ ] Purely self-referential (2nd-person, no task tail) turn → authorized-skip, flag ON.
- [ ] **Bypass fixtures must NOT fire** — "explain your answer and implement the migration", "rephrase your last answer as a working config", "clarify your point by writing the actual code" all route normally (whole-prompt task-verb veto works).
- [ ] `ENFORCER_SELFREF_SKIP=0` → old 2-lane behavior.
- [ ] Audit counts the new lane as `authorized_skip`, NOT false-skip; selftest asserts **3** injects, green.
- [ ] **Parity test green:** the new anchor does NOT match the getaway/intent messages or the H2 doctrine-table row.

## Risk Assessment

- **HIGHEST: a too-broad detector authorizes skips on real work** (the exact dodge the doctrine fights) → mitigate with a narrow regex + must-NOT-fire selftest fixtures + default-ON-with-revert.
- **Cross-file contract miss** (#1 hidden-scope trap) → checklist-gated in steps 3; both the audit anchor and the selftest count must move together.
