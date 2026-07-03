# ADR-0016 — Body-derived trigger points (Option 4)

Status: Accepted (2026-07-04)
Relates to: ADR-0012 (multi-vector MAX-pool trigger layer — this EXTENDS it), ADR-0002 (semantic
which+whether), ADR-0013 (engine freshness / copy-into-stable-venv). Source:
`plans/reports/proposal-260704-0244-…` (Opus-validated). Vendored-engine change: see `vendor/skill-search/VENDORED.md`.

## Context
ADR-0012 built the trigger layer from each skill's **description phrases only** (`_split_phrases(description)`).
But the decisive "when / how / which to use" signal usually lives in the skill **BODY**, not the one-line
description. Ground-truth check (`plans/reports/researcher-a-260704-0236-…`): the body IS already in the base
vector, but (a) the deployed embedder `paraphrase-multilingual-mpnet-base-v2` truncates at ~384 **tokens** —
looser than the 4000-**char** cap, so long bodies are silently cut — and (b) it is averaged into one blended
768-d vector, smearing the distinctive phrases. Adding MORE body text to the base vector repeats the exact
MEAN-centroid dilution ADR-0012 measured as WORSE. The fix is **representational**: mine the body's decision
sections as their own SEPARATE MAX-pool points, never blended.

## Decision
- **Extract (`vendor/skill-search/skill_search/skills_discovery.py`).** `_extract_body_triggers(body)` pulls
  SHORT phrases from the body's LABELED decision sections — `## When to Use`, `Triggers:`, `Use when:`,
  `Examples:`, `Also use`, `Use this skill` — never the whole body. A markdown header pulls its section until
  the next header OR a `Do NOT use`-style exclusion line (so exclusions, which often name OTHER skills, don't
  leak in as triggers for this one). Exposed as `body_triggers` on the parsed dict; `description`/`body`
  untouched. Extracted from the FULL body (not the 4000-char-capped copy) so a late section still refreshes.
- **Emit (`vendor/skill-search/skill_search/server.py`).** `_trigger_phrases(s)` takes description phrases
  first, then (if `SKILL_BODY_TRIGGERS`) body phrases deduped against the description, capped COMBINED at
  `_TRIG_MAX` (12). Fed through the SAME trigger-point path + stable per-(skill,slot) ids as ADR-0012 —
  incremental-reindex-safe, per-phrase content-hash so body edits refresh points. Query side unchanged.
- **Toggle:** `SKILL_BODY_TRIGGERS` (default ON). `=0` + reindex → description-only, byte-identical to before.
- **Base vectors are untouched** — no MEAN/centroid (that is the ADR-0012 anti-pattern).

## The all-ON override (operator decision, recorded)
The proposal recommended shipping this behind a shadow-A/B gate before default-on. The operator explicitly
directed it default-ON now (decision log D1). Honored; the A/B is run as a smoke in validation (Phase 7) and
recorded there rather than as a pre-ship gate. Kill-switch (`SKILL_BODY_TRIGGERS=0` + reindex) is the revert.

## Evidence
- Vendor unit gate: **29 passed** (1 pre-existing `integration` test deselected — see decision log D7). New
  tests cover header-section / inline-label / negative-exclusion / empty extraction, and dedup / flag-off /
  combined-cap emission.
- Live reindex (`skill-search --reindex`): `{"indexed":488, "embedded":1339, "skipped":2231, "deleted":0}` —
  **+1339 body-derived trigger points; total 2231 → 3570 (+60%)**. Doctor: `status: OK`, engine-freshness OK,
  multi-vector layer 3082 trigger points / 3570 total.
- Point-count note: the COMBINED cap bounds per-skill triggers at the same 12-slot ceiling as before, but the
  TOTAL rises because most skills left slots empty (median description ~3/12) — bounded growth, far under
  full-body chunking's 2-4× (this corrects an earlier "flat point-count" overclaim; decision log D8).
- Shadow-A/B rank-1/separation delta: recorded in the Phase-7 validation report.

## Consequences
- Body-only decision signal becomes retrievable via MAX-pool in BOTH the enforcer-hook and MCP paths, at the
  same query cost.
- Index grows ~+60% (bounded); acceptable and reversible.
- **Deploy dependency (ADR-0013):** the vendored engine must be re-copied into the stable venv
  (`pip install vendor/skill-search`) AND a reindex run for this to take effect — editing the vendor source
  alone does nothing. The persistent MCP process also runs the old code until it restarts.

## Open / to measure
- Shadow-A/B: does adding body triggers raise rank-1/separation on the eval set, or add topical noise? (Phase 7.)
- Does the COMBINED `_TRIG_MAX` cap starve verbose-description skills of any body phrases? Revisit the cap if
  the A/B or organic data shows it limiting (decision log D6).
- Extraction precision: how many bodies actually carry a cleanly labeled decision section vs. free prose
  (bounds the real coverage gain, not just point count).
