---
phase: 6
title: Documentation
status: completed
effort: M
---

# Phase 6: Documentation — the full historical trail (MANDATORY, maximal)

## Overview
Produce the loud, thorough documentation the user demanded: future readers must be able to reconstruct the
exact sequence, decisions, and rationale of how these features got built. This is a first-class deliverable,
not an afterthought.

## Requirements
- Every architectural change gets an ADR; user-visible behavior + flags reach README/AGENTS/CLAUDE/CHANGELOG;
  the vendored change is in VENDORED.md (Phase 4); a handoff + a journal capture the run; the all-ON override
  and its risk are stated LOUDLY everywhere relevant, cross-linked to the decisions-audit log.

## Related Code Files
- Create: `docs/adr/0015-authorized-skip-tier-and-library-doctrine.md`
- Create: `docs/adr/0016-body-derived-trigger-points.md`
- Create: `docs/journals/journal-2026-07-04-usefulness-rate-upgrades.md` (or the repo's journal convention)
- Create: `.handoff/handoff-2026-07-04-usefulness-rate-upgrades.md`
- Modify: `README.md` (three-organs / Retrieve + Enforce sections; new flags)
- Modify: `AGENTS.md` (guardrails, env flags, VENDORED note)
- Modify: `CLAUDE.md` (quick-reference: new flags + go-live reminder if relevant)
- Modify: `CHANGELOG.md` (`[Unreleased]` → will finalize to `[0.12.0]` in Phase 8)
- Update: `plans/260704-0415-usefulness-rate-upgrades/decisions-audit-log.md` (append any new forks)

## Implementation Steps
1. **ADR-0015** — AUTHORIZED-SKIP tier + library doctrine: context (silent getaway/intent_skip → agent
   re-searches), decision (surface the verdict; both legs ON), the ADR-0009 tension + the user all-ON
   override (link decisions-audit D1), the `ENFORCER_AUTHORIZED_SKIP` flag, consequences, and that the
   getaway leg is knowingly ON against the data-backed caution.
2. **ADR-0016** — body-derived trigger points: context (body signal invisible to the description-only trigger
   layer), decision (extract labeled decision-sections into the MAX-pool layer, Option 4), the
   `SKILL_BODY_TRIGGERS` flag, the 384-token consideration, the skipped shadow-A/B (deferred to smoke, D1),
   consequences, supersedes-nothing (extends ADR-0012).
3. **README / AGENTS / CLAUDE** — reflect: new enforcer tier, new retrieval signal, the two flags (both
   default-ON), the library doctrine. Keep README's "three organs" framing accurate.
4. **CHANGELOG** — `[Unreleased] → Added/Changed` entries for all three moves + audit patch, referencing
   ADR-0015/0016. (Phase 8 renames to `[0.12.0] — 2026-07-04`.)
5. **Journal** — concise technical journal of the run (what/why/sequence/decisions/validation outcome).
6. **Handoff** — next-session handoff: what shipped, flags, the held push + exact go-live commands, open
   follow-ups (prereq #4 score re-measurement, A/B result).
7. Cross-link ADRs ↔ README/AGENTS; ensure the all-ON risk is stated where an implementer would look.

## Success Criteria
- [ ] ADR-0015 + ADR-0016 created (correct sequential numbers, repo ADR format).
- [ ] README, AGENTS.md, CLAUDE.md, CHANGELOG updated + consistent with the code.
- [ ] Journal + handoff written; decisions-audit current.
- [ ] The all-ON override + residual risk appear in ADR-0015/0016 + CHANGELOG (loud, not buried).

## Risk Assessment
- Doc/code drift. Mitigate: write docs AFTER code phases land; cross-reference exact flag names + ADR numbers;
  Phase 7 opus-validate cross-checks docs against the diff.
