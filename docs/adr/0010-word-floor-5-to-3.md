# ADR-0010: Word floor 5→3 — let the language-aware imperative-veto see 4–5-word commands

**Status:** Accepted — operator decision; supersedes the word-floor portion of ADR-0009. Reversible (see "Revert").
**Date:** 2026-06-29
**Deciders:** owner (thinhkhuat)
**Supersedes:** ADR-0009 (word floor only; its score floor 0.45 stays in force)

## Context

ADR-0009 set `MAX_SHORT_WORDS = 5` — a prompt with ≤5 words gets a silent getaway BEFORE any embed and BEFORE the imperative-veto (`_is_imperative`) runs. Since then the veto was made language-aware: it now recognizes Vietnamese task prompts, not just English (commit 0b065e0).

That exposed a gap. The veto exists to protect short commands from suppression, but at `MAX_SHORT_WORDS = 5` no ≤5-word prompt ever reaches it — they are dropped at the word floor first. So the protection (English, and the new Vietnamese) only ever engaged for >5-word prompts; the short commands it was built for were dropped upstream regardless.

## Decision

Set `MAX_SHORT_WORDS = 3` (lowered from 5). Prompts of 4–5 words now reach embed + the gate, where the language-aware veto protects genuine commands. Prompts of ≤3 words (ultra-short trivia — "thanks", "ok cool", "yes please") stay on the silent getaway.

Rationale:
- ADR-0009's own analysis found the 3–5-word band is ~2.0:1 actionable:conversational — admitting the 4–5w slice favors real commands, and the veto (now incl. Vietnamese) shields them from the intent gate.
- The data-backed floor was 2; the operator chose 3 as the middle point — admit 4–5w commands while still filtering the ≤3w trivia perceived as noise.
- Blast radius bounded: the enforcer is additive + fail-open; a suppressed offer never blocks work. More 4–5w prompts now hit embed (minor cost); the getaway/score floors + intent gate still filter noise.

## Known boundary

3-word commands (e.g. Vietnamese "sửa lỗi này") are STILL dropped at the word floor. Full short-command coverage would require `MAX_SHORT_WORDS = 2` (the data-backed value) — a further operator call, not made here.

## Revert

- `hooks/scripts/enforcer.py`: set `MAX_SHORT_WORDS = 5` to restore ADR-0009, or `2` for the data-backed floor.
- The word floor is a literal, not env-backed — a code edit is required.
- Per convention, supersede this with a new ADR rather than editing it.

## Verification

- `enforcer.py --selftest` — refusal guard + ranked-mandate + imperative-veto pass (touches no tested contract).
- End-to-end through `main()`: a 4-word prompt now reaches the gate (was dropped at 5); a 3-word prompt still gets the getaway.
- `driftcheck.py` — IN SYNC.

## Related

- ADR-0009 (the decision this supersedes for the word floor).
- The Vietnamese imperative-veto change (commit 0b065e0) that motivated lowering the floor.
