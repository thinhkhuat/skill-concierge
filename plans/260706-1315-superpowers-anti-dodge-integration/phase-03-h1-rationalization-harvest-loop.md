---
phase: 3
title: "H1 Rationalization Harvest Loop"
status: pending
effort: "M"
---

# Phase 3: H1 Rationalization Harvest Loop

## Overview

Turn the existing false-skip **detector** into a **harvester**: capture the verbatim `SKIPPING:` rationalizations for false-skip turns, feed them into doctrine authoring (H2), and re-measure the false-skip rate on a clean epoch window. This closes concierge's #1 admitted gap ("doctrine is the only lever, but compliance is unmeasured") using measurement machinery it already owns. Mirrors superpowers' RED-step (capture verbatim rationalizations, `writing-skills/SKILL.md:558-567`). Depends on: Phase 2 (clean measurement).

## Requirements

- Functional: for each false-skip turn (declared `SKIPPING`, no `search_skills`, no `SKILL-CHECK` marker), capture the offending assistant text; emit a deduped rationalization corpus; exclude meta/self/subagent turns; support windowed re-measure.
- Non-functional: keep `_skip_verdicts` **pure** (the selftest pins it) — do all text capture in the file-walk loop.
- **Data-safety [Red-Team F7, High].** The harvest EMITS verbatim assistant text, which often quotes the user's task (paths, project names, pasted secrets). Sink = a gitignored scratch path (`logs/` or `.ijfw/`, already ignored); cap emitted text to the `SKIPPING:` clause only (not surrounding task text); run a minimal secret/path scrub before write; ADR states local-only, never committed, never linked from an ADR. Add the harvest glob to `.gitignore` in THIS phase, not Phase 7.

## Architecture (grounding-exact)

- **Capture at the MATCH site, NOT the flush [Red-Team F5, High].** `txt` is loop-local to the inner `for blk in msg["content"]` loop (`:205`, assigned `:220`); at the flush points (`:157`, `:235`) it holds a stale/unbound value. So capture WHERE `_SKIPPING.search(txt)` fires (`:232`): do `cur["skip_text"] = txt` (or the matched `SKIPPING:` line) right there while `txt` is valid, then thread the already-populated `cur["skip_text"]` through the flush.
- **Thread `sid` onto every turn dict — first-class, not "extra plumbing" [Red-Team F4, Critical].** The turn dicts (`:158-159`, `:236-237`) carry NO `sid`; `false_skip` is computed (`:240`) BEFORE `meta_sessions` exists (`:247`) → there is no key to exclude meta/subagent at turn granularity. Fix: thread session identity onto the turn dict at both flush points; make the harvest sibling session-aware. Keep `_skip_verdicts` itself pure (do the filter in a wrapper).
- **IMPLEMENTED CORRECTION [telemetry-dev, 2026-07-06] — subagent exclusion is per-FILE, NOT per-sid.** Grounding: subagent transcripts carry the PARENT's `sessionId` (980 files; 572 under `subagents/`; 558 `isSidechain:true`; 0 mixed) — so a sid-set exclusion would wrongly drop the parent's ORGANIC turns. Correct design: a per-file `sub` flag (from the `subagents/` path + `isSidechain`) threaded onto each turn, plus a raw-line phrase match for dispatched-teammate sessions (3 high-precision phrases; dodges the 400-char `sess_text` cap). See ADR-0021.
- The marker-match fails SAFE toward over-flagging (`:170-178`): re-verify each captured item against the enforcer's LIVE `GETAWAY_SKIP_MSG` / `INTENT_SKIP_MSG` / the H5 `SELFREF` message so lawfully-authorized skips (incl. H5's new lane) are NOT harvested as rationalizations — else H2 would refute the excuse H5 just authorized (self-contradicting doctrine, Red-Team F4/F8).
- **Split the loop [Red-Team F6, Critical].** HARVEST (capture verbatim → feed H2) is epoch-independent — keep it. RE-MEASURE is contingent on a config-freeze window: `scripts/analyze.py --since/--until` (repo root, `:233-235`/`:90` — NOT `:248-254`, NOT the audit dir). Per `AGENTS.md:84`, a fresh post-deploy epoch may be "insufficient data"; do NOT author H2-v2 from an unclean or too-small window.

## Related Code Files

- Modify: `skills/skill-usage-audit/scripts/audit_skill_usage.py` (capture + `--harvest` + `--selftest` case)
- Create: `docs/adr/0021-rationalization-harvest-loop.md`

## Implementation Steps

1. Capture verbatim `SKIPPING:` text for false-skip turns in the file-walk loop; keep `_skip_verdicts` pure.
2. Join to meta/self/subagent exclusion; emit a deduped rationalization corpus (`--harvest` mode → output file/stdout).
3. Re-verify captured items against the live enforcer message strings before treating them as rationalizations.
4. Extend `--selftest` with a synthetic false-skip turn carrying a rationalization string.
5. Document the clean-window re-measure protocol (epoch = deploy commit; exclude meta/subagent).
6. Finalize ADR-0021.

## Success Criteria

- [ ] `--harvest` emits verbatim rationalizations for false-skip turns ONLY.
- [ ] meta/self/subagent turns excluded from the corpus.
- [ ] `_skip_verdicts` still pure; `--selftest` green with the new case.
- [ ] Re-measure runs windowed on an epoch boundary; protocol documented.

## Risk Assessment

- **Turn segmentation is line-heuristic** (`:151-156`, substring-sniffs raw JSONL) → a rationalization spanning multiple text blocks may split. Accept for v1; name the ceiling in the ADR.
- **Over-flag contamination** (marker drift → authorized skips captured as rationalizations) → mitigated by the live-string re-verification against ALL three enforcer messages.
- **Metric is compliance/dodge-rate, not outcome-quality — AND may be unmeasurable this epoch** [Red-Team F6]. The ADR must state both: no usefulness-lift claim, and the re-measure leg is deferred until a config-freeze window exists (define minimum-n + freeze duration, or split re-measure out of v0.14.0).
