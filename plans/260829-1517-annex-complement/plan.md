# Plan — Complement annex: gap-gated + usage-ranked externals (ADR-0048, v0.41.0)

Owner order (2026-08-29): "make the external catalogs, while staying as annex, far more
helpful and serve as a valuable mechanism along with the builtin." Design fork resolved by
owner pick: gap-gate + usage ranking; thin-intent bar reuses GETAWAY_FLOOR.

## Evidence (live ledger, 2026-08-29)

- 2,656 offers, 410 carried externals; **6 external pulls ever** — take-rate ≪1%. The
  annex is noise-dominated: it fires on ~15% of turns and is almost never consumed.
- The 6 pulls are all genuine builtin gaps (multi-source-search, apple-container,
  pdf-conversion-router, active-directory-attacks) — when externals win, they win where
  the builtin has nothing.
- Same-day observation: a plugin-design task drew 4 design-system/Azure external rows —
  echoes of a well-served intent (installed top 0.75+).

## Decision

The annex becomes the builtin's **complement**, not its echo.

1. **Gap/beat gate** (`_retrieve_external`): when the installed top ≥ `GETAWAY_FLOOR`
   (0.45, reused — the owner-tuned "builtin answers this" bar), an external must BEAT the
   installed top by `ENFORCER_ANNEX_BEAT` (default 0.04) to earn a slot. When the top is
   below it (thin intent), the annex widens to cap at the plain `EXTERNAL_FLOOR` (0.32).
   The ADR-0036 margin rule (top − 0.08) no longer applies to the EXTERNAL annex — it
   keeps governing the FOREIGN annex (ADR-0034), unchanged.
2. **Usage ranking**: `auto_promote.py` — which already walks the ledger counting external
   get_skill pulls per session for promotion — dumps the counts to a durable digest
   `~/.claude/skill-concierge/external-takes.json` ({name: distinct-session count}). The
   enforcer reads it live (blocklist pattern, tiny file, fail-open): taken-before externals
   float first (takes desc, then score desc) and render `used N×`. Gate stays score-based
   for all rows — provenness reorders, never admits below the gate.
3. **Kill-switch**: `ENFORCER_ANNEX_COMPLEMENT=0` restores the ADR-0047 margin-rule annex
   byte-identically. EPOCH v0.41.0 (offer composition changes).

## Non-goals

- No displacement, no primary-pool merging (settled ADR-0047).
- No chain-hint/ROUTE admission of externals (reverted, stays reverted).
- No floor relaxation for proven externals (reorder + marker only — KISS).
- No catalog-content curation; blocklist unchanged.

## Steps

1. G1 this plan + GATES.md.
2. G2 enforcer: `_annex_gate()` + ranking + marker; selftest case pins (beat/thin/rank/
   marker/kill-switch).
3. G3 auto_promote digest write + enforcer live-read; both selftests green.
4. G4 docs: ADR-0048, README, AGENTS.md, CLAUDE.md, openwiki (enforcement-gate,
   quickstart flag), CHANGELOG, manifests+package.json → 0.41.0; driftcheck exit 0.
5. G5 live probes: well-served intent → annex silent/beat-only; thin intent → annex fills;
   proven row floats; venv re-copy.
6. G6 independent blind validator; fix findings.
7. G7 commit + push, clean tree.

## Risk / rollback

- Beat-comparability across tiers assumes the shared embedder makes scores comparable —
  true (same collection, same embedder, ADR-0045 substrate).
- If the beat gate starves legit complements (score compression), lower
  `ENFORCER_ANNEX_BEAT` or flip `ENFORCER_ANNEX_COMPLEMENT=0` — one env var, no re-release.
- Digest is advisory-only: absent/corrupt file = unranked annex (fail-open), never a
  failed offer.
