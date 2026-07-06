---
phase: 6
title: "H4 Trigger Purity Lint"
status: pending
effort: "M"
---

# Phase 6: H4 Trigger Purity Lint

## Overview

Add a purity check to body-trigger extraction so workflow-summary phrases don't pollute the MAX-pool retrieval surface (a summary embeds near generic process-prose, not user intent, and burying it buries the skill). Ship **shadow-first** — log what it would drop, drop nothing, measure precision, then activate. Applies superpowers' SDO law (triggers must be pure trigger-conditions, `writing-skills/SKILL.md:152-158`). Depends on: Phase 1 (heuristic lock). Parallel with H5.

## Requirements

- Functional: a purity predicate rejecting process/workflow-summary phrases; SHADOW mode logs would-drops without removing; ACTIVE mode removes.
- Non-functional: `SKILL_TRIGGER_PURITY` (shadow→active→off); requires reindex + engine re-copy + MCP restart; vendor pytest green; `VENDORED.md` updated.

## Architecture (grounding-exact — note premise correction)

- Insert the predicate at **extraction**: `vendor/skill-search/skill_search/skills_discovery.py:100-103`, right before `phrases.append(line)` — the source-of-truth spot. (`_trigger_phrases` is in `server.py:276-293`, NOT `skills_discovery.py` — grounding correction; extraction-side is cleaner than the emission-side filter.)
- Keep `_BODY_SECTION_RE` (`skills_discovery.py:66-69`) and `server._LABEL_RE` (`server.py:252`) aligned — they are two hand-mirrored regexes (`:62-65` "kept in sync by hand"); the purity check touches label semantics.
- Purity heuristic v0 (Phase-1 lock): impure = leads with a process verb / numbered step / "runs|generates|produces|creates a … pipeline|workflow|report|steps"; pure = triggering condition ("use when …", task+domain noun phrase). SHADOW logs each would-drop as `(skill, phrase)` for precision review.
- **Reindex required** to take effect (ADR-0016 deploy dep, `docs/adr/0016...md:53-55`): `pip install vendor/skill-search` into the stable venv + reindex + MCP restart.
- **FULL reindex on activation [Red-Team F10, Med].** Per-phrase `content_hash` (`server.py:387`) makes reindex INCREMENTAL — correct for body edits, WRONG for a filter-logic change: unchanged skills keep their old (unfiltered) phrases → a MIXED-purity index. When the purity rule flips shadow→active, force a FULL re-extract of ALL skills (`--reindex --force` / bump an index schema token), never the incremental path.

## Related Code Files

- Modify: `vendor/skill-search/skill_search/skills_discovery.py` (purity predicate + `SKILL_TRIGGER_PURITY`)
- Modify: `vendor/skill-search/VENDORED.md` (document the layer change)
- Modify: `vendor/skill-search/tests/test_discovery.py`, `test_indexing.py` (purity cases)
- Create: `docs/adr/0023-trigger-purity-lint.md`

## Implementation Steps

1. Add `SKILL_TRIGGER_PURITY` (shadow|active|off) + the purity predicate at `skills_discovery.py:100-103`.
2. SHADOW mode: log would-drops `(skill, phrase)` — drop nothing.
3. Add tests: pure phrase kept; impure phrase flagged (shadow) / dropped (active).
4. Reindex in shadow; review the would-drop log for false-drops (precision) on the live corpus.
5. Flip to ACTIVE only if the false-drop rate is acceptable; re-copy engine + reindex + restart.
6. Update `VENDORED.md`; finalize ADR-0023.

## Success Criteria

- [ ] SHADOW mode logs would-drops without changing the index.
- [ ] Precision reviewed on the live corpus; false-drop rate recorded in the ADR.
- [ ] ACTIVE mode drops only impure phrases; vendor pytest green.
- [ ] `SKILL_TRIGGER_PURITY=off` → byte-identical to today.
- [ ] `VENDORED.md` + ADR-0023 written.

## Risk Assessment

- **HIGH (subjective heuristic): false-drops remove real triggers** → mitigate with shadow-first + a precision gate before activation. This is why H4 does NOT auto-activate at release.
- **Label-regex desync** (`skills_discovery` vs `server._LABEL_RE`) → keep both aligned; add a test asserting parity.
- **Vendored-layer honesty** → `VENDORED.md` must record the local patch.
