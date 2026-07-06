---
phase: 1
title: "Spikes and Design Locks"
status: pending
effort: "S"
---

# Phase 1: Spikes and Design Locks

## Overview

Resolve the 3 grounding unknowns and lock the design decisions **before** any code, so later phases build on facts, not guesses. Doc-gated (the H3 spike needs live Claude Code hook docs). No production code changes; output is decisions + ADR stubs. Depends on: none.

## Requirements

- Functional: (a) determine whether a plugin SessionStart hook can detect a subagent/dispatched session; (b) lock H5 lane semantics; (c) lock H4 purity heuristic + shadow-first rollout; (d) reserve ADR numbers on `main`.
- Non-functional: no runtime behavior change; decisions recorded as `Proposed` ADR stubs.

## Architecture (decisions to lock)

- **H3 spike (doc-gated).** Invoke `/working-with-claude-code` (refs `hooks.md`, `plugins-reference.md`): does the SessionStart payload carry `source` and any subagent/dispatch marker? Do Task-dispatched subagents even fire a *plugin* SessionStart hook? Pick the mechanism per result:
  1. subagent signal present in payload → `doctrine.py` reads stdin, gates injection on it;
  2. no payload signal → dispatch-time env marker set when spawning subagents, read by `doctrine.py`;
  3. subagents don't fire plugin SessionStart at all → H3 collapses to **audit-side exclusion only** (no `doctrine.py` change).
- **[SPIKE RESOLVED — live official docs, 2026-07-06] The subagent signal EXISTS: `agent_id`.** SessionStart's `source` is only `startup|resume|clear|compact` (no subagent value) — BUT the COMMON hook input fields include **`agent_id`**: *"Present only when the hook fires inside a subagent call. Use this to distinguish subagent hook calls from main-thread calls"* ([code.claude.com/docs/en/hooks](https://code.claude.com/docs/en/hooks)). So `doctrine.py` CAN scope injection by `agent_id` — this **corrects Red-Team F3(b)**, which checked only SessionStart-specific fields and missed the common `agent_id`. doctrine.py is FEASIBLE, not audit-only. (`/working-with-claude-code` was NOT used — stale; resolved via live WebFetch. See workbench-rule flag.) Invariant for ADR-0020: *a top-level user session must NEVER lose the doctrine — key on `agent_id` present (positive subagent proof); fail TOWARD injection.*
- **H5 lane semantics — LOCK:** the self-referential lane authorizes an **outright skip** (mirror `INTENT_SKIP_MSG`, `enforcer.py:321-324`), **NOT** getaway-style `find-skills` escalation — these turns genuinely need no skill; escalating would recreate the ritual. Detector must be NARROW: scoped to "explain/expand/rephrase/clarify my own prior output/answer/points" with no new task verb.
- **H4 purity — LOCK:** ship **SHADOW-first** — log the phrases the lint *would* drop, drop nothing, measure precision on the live corpus, flip to active only after the false-drop rate is acceptable. Heuristic v0: a body-trigger phrase is *impure* if it reads as process/workflow-summary (leads with a process verb / numbered step / "runs|generates|produces|creates a … pipeline|workflow|report|steps") rather than a triggering condition ("use when …", task+domain noun phrase).
- **ADR reservation:** confirm next-free number on `main` before claiming 0019-0023 (the archived bge-m3 plan created a `0019` on `feat/bge-m3-ollama-migration`, not main — verify no collision).

## Related Code Files

- Create: `docs/adr/0019-...md` … `docs/adr/0023-...md` (skeletons only, Status: Proposed)
- Modify: none

## Implementation Steps

1. `/working-with-claude-code` → read the SessionStart hook payload schema; answer H3 detectability with a verbatim citation.
2. `ls docs/adr/` on `main` → confirm next-free ADR number(s), accounting for the feat-branch `0019`.
3. Write ADR stubs 0019 (H5), 0020 (H3), 0021 (H1), 0022 (H2), 0023 (H4) — Status: Proposed, with the locked decisions + kill-switch flag named.
4. Record the three design locks (H5 outright-skip; H4 shadow-first; H3 mechanism-per-spike) in the ADR stubs.

## Success Criteria

- [ ] SessionStart subagent-detectability answered with a doc citation (Rule B honored).
- [ ] Next-free ADR numbers confirmed on `main` (no bge-m3 `0019` collision).
- [ ] 5 ADR stubs written (Proposed) with kill-switch flags named.
- [ ] H5 / H4 / H3 design decisions recorded.

## Risk Assessment

- **Spike may find subagents don't fire plugin SessionStart** → H3 becomes audit-only (smaller than a `doctrine.py` edit). Acceptable — record and adjust Phase 2 scope.
- **ADR-number collision** with the feat-branch bge-m3 `0019` → mitigated by the explicit `main`-side check in step 2.
