# Brainstorm — external catalogs as first-class residents (accepted design)

Date: 2026-08-23. Follows ADR-0031 (external catalog roots, search-only tier).
Status: **accepted design, ready for plan → cook.** Not yet implemented.

## The reframe (load-bearing)

The user's goal: a genuinely large skill catalog the agent invokes when needed,
without the per-turn context tax — externals promoted from "guest" (search-only)
to first-class.

Key evidence that reshaped the mechanism:
- The concierge does NOT make installed skills free — only their *descriptions*
  are on-demand; their *names* stay RESIDENT in every turn's skill listing.
  Today 373 entries resident (40 full-desc + 333 name-only), against a 3% listing
  budget (`skillListingBudgetFraction: 0.03`, settings.json).
- Mass-installing 1,928 externals → ~2,301 resident names → blows the 3% budget →
  Claude Code silently truncates the listing (skills dropped). This REINTRODUCES
  the exact tax the concierge exists to remove. **"Just like bundled" at scale is
  self-defeating.** (Rejected approach A.)
- BUT the enforcer's per-turn OFFER is a live Qdrant query (`_retrieve`), NOT
  resident. Externals can appear in the offer at ZERO resident cost. The single
  `must_not tier=external` filter (enforcer.py:537) is all that excludes them.

So "first-class" = first-class in the on-demand OFFER, consumed via `get_skill`
read-inline — NOT installed. This preserves the zero-resident-cost property that
makes a huge catalog viable.

## Contract

- **Outcome:** external skills participate first-class in the per-turn offer
  (not just explicit search), discovered by intent-match across a huge catalog,
  at near-zero resident cost; consumed via `get_skill` read-inline; the ones that
  earn it graduate to real installed skills by demonstrated usage.
- **Constraints:** (1) externals aren't Skill-tool-invocable (not registered) →
  read-inline consumption; (2) resident listing is budget-capped → resident names
  must not balloon (so: NO mass install); (3) unvetted third-party text → higher
  floor + provenance marking; (4) offer-composition change resets the telemetry
  epoch — window external metrics from ship.
- **Non-goals:** mass symlink-install of the catalog; per-project scoping;
  content auto-scanning/vetting; letting externals displace installed offers.
- **Acceptance:** for a real intent, the offer shows the installed top-k UNCHANGED
  plus ≤2 external annex rows (marked, only when ≥floor); no installed slot lost;
  listing budget untouched; telemetry attributes external offers/takes; a repeat-
  used external auto-promotes; enforcer selftest + doctor green.

## Accepted approach — B (offer-tier annex) + C (usage-promotion)

**Consumption:** read-inline via `get_skill`; a repeatedly-used external
auto-graduates to a real installed skill (organic curation).

**Dilution control — additive annex (NOT merged competition):**
1. One retrieval, `must_not tier=external` removed, larger limit (~12–16 groups).
2. Partition: **installed** → existing top-k path (floors, dominance, gates —
   byte-identical to today, zero displacement); **external** → top-N above the
   external floor, appended, marked `[external:<alias>]` + get_skill note.
3. Single Qdrant query, no extra round-trip → ~zero added hot-path latency.

**Accepted numbers (env-overridable):**
- `ENFORCER_EXTERNAL_SLOTS = 2` — max external annex rows.
- `ENFORCER_EXTERNAL_FLOOR = 0.40` — externals appear only on strong intent-match
  (vs installed ITEM_FLOOR 0.18); most turns show zero externals. Docker smoke
  test: c4-container 0.73, apple-container 0.68 — clear it; weak neighbors don't.

**Usage-promotion (C, fast-follow phase):** when a catalog skill's ledger
external-takes cross a conservative threshold, auto-symlink it into
`~/.claude/skills` (becomes Skill-tool-invocable, name-only budget). Resident set
grows only by *demonstrated* usage, never by mass install.

## Implementation outline (for the plan)

1. **Enforcer annex** (`hooks/scripts/enforcer.py`): drop the `must_not` filter in
   `_retrieve`, widen the limit, add `_partition_external()` (installed untouched;
   external top-N ≥ `ENFORCER_EXTERNAL_FLOOR`, capped at `ENFORCER_EXTERNAL_SLOTS`);
   render annex rows with `[external:<alias>]` + the get_skill consumption note in
   `_ranked_mandate`; keep the search-only exclusion available via a kill-switch
   (`ENFORCER_EXTERNAL_ANNEX=0` restores ADR-0031 behavior). New selftest case.
2. **Doctrine** (`hooks/doctrine/skill-first.md`): the offer can now carry external
   annex rows; `USING: <alias>:<skill>` = get_skill read-inline (already documented).
3. **Usage-promotion** (fast-follow): a SessionStart hook (or extend auto_reindex)
   reads the ledger external-takes, promotes those over threshold via catalogs.py
   promote logic; conservative threshold; log each promotion.
4. **Telemetry** (`scripts/analyze.py`): external offer→take conversion (distinct
   from the existing installed offer→take); epoch note.
5. **ADR-0032** supersedes ADR-0031's "search-only, promote later, measured" stance
   with the accepted annex + usage-promotion model; version bump 0.23.0; docs +
   openwiki + driftcheck; enforcer/doctor selftests; commit + push.

## Unresolved (for the plan phase, not blocking design)
- Usage-promotion threshold value (how many external-takes → promote) — set from
  early external-take data, conservative default (e.g. 3 distinct sessions).
- Whether the annex floor should be per-catalog (a trusted catalog lower, an
  unvetted one higher) — deferred; single global floor for v1.
- Epoch: the annex changes offer composition → all offer-conversion metrics reset
  at ship; the installed-only ranking is unchanged so installed metrics continue.
