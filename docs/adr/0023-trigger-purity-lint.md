# ADR-0023 — Trigger-purity lint (H4)

Status: Accepted (2026-07-06) — ships **shadow-first**, NOT activated at release.
Relates to: ADR-0016 (body-derived trigger points — this filters what that extracts), ADR-0012
(multi-vector MAX-pool trigger layer), ADR-0002 (semantic which+whether). Source:
`docs/anti-dodge-integration-v0.14.md` (H4), `plans/260706-1315-superpowers-anti-dodge-integration/phase-06-h4-trigger-purity-lint.md`.
Vendored-engine change: see `vendor/skill-search/VENDORED.md`.

## Context
ADR-0016 mines each skill's BODY labeled decision-sections (`## When to Use`, `Triggers:`, …) for extra
MAX-pool trigger points. But those sections mix two kinds of line: genuine triggering CONDITIONS ("use
when the user wants X", task+domain noun phrases) and workflow SUMMARIES — process narration ("Runs the
plan→cook→test pipeline"), numbered steps ("1. Scaffold the project"). A summary embeds near generic
process-prose rather than user intent, so indexing it as a trigger point pulls the skill toward the wrong
queries and buries it under its own noise. Superpowers' SDO law states the rule directly: a trigger must
be a trigger-CONDITION, never a workflow summary (`writing-skills/SKILL.md:152-158`).

## Decision
- **Predicate at EXTRACTION (`vendor/skill-search/skill_search/skills_discovery.py`).** `_is_impure_trigger`
  flags a phrase as a workflow-summary when it (1) leads with a numbered step (`1.`, `2)`, `Step 3 …`) OR
  (2) leads with a doing-verb whose object is a summary noun — `runs|generates|produces|creates … pipeline|workflow|report|steps`.
  Both the verb AND the summary noun must be present for signal (2), so a use-condition that merely mentions
  "report" ("When the user wants to generate a report …") is NOT flagged. The check runs at the source-of-truth
  extraction site (right before a phrase is appended to `body_triggers`), not the `server.py` emission side.
- **Three-state flag `SKILL_TRIGGER_PURITY` (default `shadow`).**
  - `shadow` — LOG would-drops `(skill, phrase)`, drop nothing. The index is **byte-identical** to pre-H4
    (measurement only). This is the release state.
  - `active` — drop impure phrases from the trigger surface.
  - `off` — predicate never runs; also byte-identical to pre-H4.
- **Conservative by design.** Only unambiguous summaries flag; genuine conditions stay. The heuristic is
  subjective (see Risk), so it ships shadow-first and its false-drop precision is reviewed on the live
  corpus before anyone flips it to `active`.
- **Label-regex parity preserved.** `skills_discovery._BODY_SECTION_RE` and `server._LABEL_RE` are two
  hand-mirrored label vocabularies; a parity test now pins them (server's set ⊆ the body set; the one
  body-only extra is `when to use`, which only ever appears as a header).

## ACTIVATION requires a FULL reindex (not incremental) — Red-Team F10
The per-phrase `content_hash` reindex (`server.py:387`) is INCREMENTAL: it re-embeds only skills whose text
changed. That is correct for a body EDIT but WRONG for a filter-LOGIC change — when `SKILL_TRIGGER_PURITY`
flips `shadow`→`active`, unchanged skills keep their old (unfiltered) phrases, leaving a MIXED-purity index.
Activation must therefore force a FULL re-extract of ALL skills (`--reindex --force`), plus the standard
ADR-0016 deploy dependency: re-copy the vendored engine into the stable venv (`pip install vendor/skill-search`)
+ reindex + MCP restart. Editing the vendor source alone changes nothing live.

## Evidence
- Vendor unit gate: **25 passed, 1 deselected** (`python3 -m pytest tests/test_discovery.py tests/test_indexing.py -m "not integration"`).
  New tests: shadow keeps-all + logs `(skill, phrase)`; `active` drops the two impure kinds and keeps the
  pure condition; `off` byte-identical; a conservative "generate a report" use-condition is NOT flagged;
  and a `_BODY_SECTION_RE` ↔ `server._LABEL_RE` parity assertion.
- The pre-existing `@integration` test in `test_indexing.py` (`test_end_to_end_build_search_incremental`)
  is deselected by the standard marker and is stale under the multi-vector layer (its `embedded == indexed`
  assertion predates ADR-0012/0016 trigger points); it runs only against an isolated temp store, never the
  live index. Out of H4's scope — flagged to the release owner.
- Live shadow precision (false-drop rate on the real corpus): **to be measured in Phase 7** before any
  activation decision — recorded there, not here.

## Consequences
- At the release default (`shadow`), retrieval is unchanged — zero risk shipped, measurement gained.
- Activating `active` narrows the trigger surface to pure conditions, at the cost of a mandatory FULL
  reindex and the false-drop risk below.
- The flag is a one-var revert (`SKILL_TRIGGER_PURITY=off` + reindex), mirroring `SKILL_BODY_TRIGGERS`.

## Open / to measure (before activation)
- **HIGH — subjective heuristic.** "Workflow-summary vs trigger-condition" has no pre-existing ground truth.
  Shadow-first mitigates (log, drop nothing, review) but does not PROVE the rule is cleanly definable. Watch
  for dropping legitimate "generate a report"-style triggers; the conservative verb+noun conjunction is the
  first guard, the live shadow log is the second.
- False-drop precision on the live corpus — the gate that must pass before `shadow`→`active`.
- **The process-verb branch (`_IMPURE_PROCESS_RE`) is corpus-SILENT today.** A shadow scan of the live
  corpus fires only the numbered-step signal (~82 would-drops, all genuine steps); zero phrases hit the
  verb+summary-noun path. So its false-positive rate is UNMEASURED — Phase 7 must not read "no drops seen"
  as "no FP risk" for this branch. Its known FP class is terse verb-LEAD bullets ("generate a report …");
  grep the shadow log for those explicitly, not just numbered steps.
