---
phase: 2
title: "H3 Subagent Session Scoping"
status: pending
effort: "M"
---

# Phase 2: H3 Subagent Session Scoping

## Overview

Stop injecting the skill-first doctrine into subagent / self / meta sessions, and exclude them from the real-usage denominator. This cleans the shared ledger so H1's numbers mean something, and stops nagging scoped workers that can't act on the doctrine. Mirrors superpowers' `<SUBAGENT-STOP>` (`using-superpowers/SKILL.md:6-8`). Depends on: Phase 1 (mechanism lock).

## Requirements

- Functional: **audit-side exclusion** of subagent/self/meta sessions from the real-usage denominator (telemetry-dev) **AND** `doctrine.py` injection-scoping keyed on the `agent_id` hook-input field (enforcer-dev) — both confirmed feasible by the live-docs spike (2026-07-06).
- Non-functional: default-ON `SKILL_SUBAGENT_STOP` (one-var revert); **fail TOWARD injection** — on ANY detection/parse error the doctrine MUST still be injected. NB [Red-Team F3]: `doctrine.py`'s existing idiom is `except → return 0`, which for an *injector* means SUPPRESS (fail-closed). A naive `try/except: return 0` wrapper therefore drops the doctrine on real sessions — the opposite of intended.

## Architecture

- **Audit side (PRIMARY).** `audit_skill_usage.py` already computes `meta_sessions` (`:247-248`, keywords `:39-41`) to separate dogfood/self traffic. Extend it to also flag subagent/dispatched sessions (content-keyword or a dispatch marker), and ensure the real-usage denominator excludes them. This is offline over transcripts — it does NOT need any live hook signal, so it works regardless of the Phase-1 spike outcome.
- **`doctrine.py` side — CONFIRMED FEASIBLE via `agent_id` (live-docs spike 2026-07-06).** `doctrine.py:main()` (`:49-63`) today reads only `DOCTRINE_PATH`, never `sys.stdin`. Implement: read the SessionStart payload from stdin; if the common field **`agent_id`** is present (= running inside a subagent call) AND `SKILL_SUBAGENT_STOP` on → skip injection; else inject. Key on `agent_id`, NOT `agent_type` (`agent_type` also appears for top-level `--agent`/persona sessions, which SHOULD still get the doctrine). Source: [code.claude.com/docs/en/hooks](https://code.claude.com/docs/en/hooks). This corrects Red-Team F3(b).
- **Fail-direction [Red-Team F3, Critical].** The existing top-level `except → return 0` (`:61-62`) = SUPPRESS. Any new detection must sit in an INNER `try` that, on error, sets `should_inject = True` and FALLS THROUGH to the existing inject block — NEVER `return 0`. Suppression fires only on a positive subagent proof.

## Related Code Files

- Modify: `hooks/scripts/doctrine.py` (conditional injection + `SKILL_SUBAGENT_STOP`)
- Modify (if needed): `skills/skill-usage-audit/scripts/audit_skill_usage.py` (subagent exclusion)
- Create: `docs/adr/0020-subagent-session-scoping.md`

## Implementation Steps

1. Implement stdin payload read + subagent detection in `doctrine.py` per the Phase-1 mechanism.
2. Add `SKILL_SUBAGENT_STOP` env flag (default-ON, `!= "0"`), one-var revert, fail-open wrapper.
3. Verify the audit excludes subagent sessions from the real-usage denominator; extend `meta_sessions` if subagent turns slip through.
4. Add a `doctrine.py` selftest/smoke: subagent payload → assert no injection; top-level payload → assert injection; malformed stdin → assert still injects (fail-open).
5. Finalize ADR-0020 (Accepted).

## Success Criteria

- [ ] Subagent/dispatched SessionStart → no doctrine injected (flag ON).
- [ ] Top-level user session → doctrine injected, unchanged.
- [ ] `SKILL_SUBAGENT_STOP=0` → old unconditional behavior (byte-identical injection).
- [ ] Malformed/empty stdin → still injects (fail-open), never errors.
- [ ] Audit real-usage denominator excludes subagent/self/meta.

## Risk Assessment

- **Fail-closed regression [Red-Team F3, Critical]** — a detection bug that mislabels a real top-level session as subagent silently drops the doctrine (no error to catch). Mitigate: fail TOWARD injection (inner-try, never `return 0`); suppression requires positive subagent proof (whitelist, not heuristic-absence); malformed-stdin selftest asserts `additionalContext` IS present.
- **Spike outcome 3** (subagents don't fire plugin SessionStart) → `doctrine.py` untouched; H3 = audit-side exclusion only (the primary deliverable regardless). Note this *reduces* how much measurement-cleaning H3 delivers to H1 — re-justify H1's value if so.
