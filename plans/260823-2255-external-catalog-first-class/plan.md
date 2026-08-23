# Plan — external catalogs first-class in the concierge offer (ADR-0032, v0.23.0)

Authority: accepted brainstorm
`plans/reports/brainstorm-260823-2255-external-catalog-first-class.md`.
Supersedes ADR-0031's "search-only, promote later, measured" stance.

## Outcome
External catalog skills participate first-class in the per-turn enforcer offer
(not just explicit `search_skills`), as an **additive annex** that never displaces
the installed top-k, at near-zero resident cost, consumed via `get_skill`
read-inline. Repeat-used externals auto-graduate to real installed skills.

## Grounding (enforcer.py, read this session)
- `_retrieve` (`:525-542`): single Qdrant `query/groups`, currently
  `must_not tier=external` (`:534-539`), returns `[(name, desc, score)]` — no tier.
- `main` offer path (`:725-762`): embed → `_retrieve` → keepoff → deterministic
  hits → getaway floor → intent gate → `shown = [c ≥ ITEM_FLOOR]` → dominance →
  `_ranked_mandate(shown) + _chain_hint` → `_append_offer`.
- `_ranked_mandate` (`:555-576`): renders `• name (pct%) — desc` lines.
- Ledger `offer` event (`_append_offer`) + `get_skill` event (ADR-0031, `ledger.py`).
- `catalogs.py promote` (symlink into `~/.claude/skills`, collision-refusing).

## Accepted parameters (env-overridable)
- `ENFORCER_EXTERNAL_ANNEX` default `1` (kill-switch `0` = ADR-0031 search-only).
- `ENFORCER_EXTERNAL_SLOTS` default `2`.
- `ENFORCER_EXTERNAL_FLOOR` default `0.40`.
- `PROMOTE_MIN_TAKES` (Phase 3) default `3` distinct sessions.

## Phases
1. **Enforcer external annex** — `phase-01-enforcer-annex.md`. The core: the installed
   query is unchanged; a SEPARATE `_retrieve_external` query supplies ≤SLOTS externals
   ≥FLOOR marked with the get_skill note; installed path byte-identical; kill-switch;
   selftest. (As-built uses two queries, not one widened query — see the phase file.)
2. **Telemetry — external offer→take** — `phase-02-telemetry.md`. Distinguish
   external-annex offers in the ledger; `analyze.py` reports external offer→take
   conversion, epoch-noted.
3. **Usage-promotion (fast-follow)** — `phase-03-usage-promotion.md`. A SessionStart
   hook reads ledger external-takes; a skill over `PROMOTE_MIN_TAKES` distinct
   sessions auto-promotes via `catalogs.py` promote logic; conservative, logged,
   idempotent, kill-switchable.
4. **ADR-0032 + docs + ship** — `phase-04-adr-docs-ship.md`. ADR-0032 supersedes
   ADR-0031's search-only stance; README/CHANGELOG/AGENTS/openwiki; version 0.23.0;
   driftcheck; blind validation; commit + push.

## Acceptance (whole-plan)
- Docker-intent smoke: offer shows installed top-k UNCHANGED + ≤2 external annex
  rows marked `[external:<alias>]` with get_skill note, only when ≥0.40; a
  below-floor intent shows zero externals; kill-switch restores ADR-0031.
- No installed offer slot lost to an external (separate-query design; installed offer
  byte-identical ON vs OFF proven live + selftest case 10).
- Ledger attributes external offers + takes; analyze reports external conversion.
- Usage-promotion promotes a skill past threshold, idempotent, and the promoted
  twin is suppressed by the ADR-0031 realpath dedup (no double-listing).
- enforcer/ledger/catalogs/analyze selftests + full engine suite green; doctor OK
  (modulo restart-gated drift); driftcheck exit 0.

## Non-goals
Mass symlink-install; per-project catalog scoping; content auto-scanning;
per-catalog floors (single global floor v1); letting externals displace installed.

## Risks
- **Latency:** the annex adds ONE small extra Qdrant call (`limit=SLOTS`) on
  installed-offer turns. Signal: enforcer offer p95 in `analyze --latency` rises >
  budget. Response: the intent gate already issues 2 Qdrant calls on some turns, so
  one more small one is within budget; the external query is best-effort.
- **Dilution via annex noise:** floor 0.40 keeps most turns external-free. Signal:
  external offer→take ≪ installed. Response: raise `ENFORCER_EXTERNAL_FLOOR`.
- **Promotion runaway:** conservative threshold + idempotency + kill-switch.
  Signal: unexpected `~/.claude/skills` growth. Response: `PROMOTE_ENABLED=0`.
