# ADR-0032 — External catalogs first-class in the offer (additive annex + usage-promotion)

Status: Accepted + implemented (2026-08-23).
Supersedes in part: [ADR-0031](0031-external-catalog-roots.md) — the "search-only tier,
promote to preview later, measured" stance (its Decision 5). ADR-0031's substrate
(catalog-roots config, `catalog:<alias>` scope, `tier: external` payload, get_skill
read-inline, symlink promotion) is unchanged and load-bearing here.
Source: owner design session 2026-08-23; brainstorm
`plans/reports/brainstorm-260823-2255-external-catalog-first-class.md`; plan
`plans/260823-2255-external-catalog-first-class/`.

## Context

ADR-0031 shipped external catalogs as a **search-only tier**: retrievable via explicit
`search_skills`, excluded from the per-turn enforcer offer (`must_not tier=external`).
The owner's goal is broader: a genuinely large catalog the agent *discovers and uses by
intent-match*, first-class in the concierge's own offering mechanism — the depth a bundled
catalogue omits because a harness loads every description every turn.

The reframe that shaped the mechanism (evidence, this session):
- The concierge makes *descriptions* on-demand, NOT *names*: an installed skill's name is
  resident in every turn's listing. Today 373 entries resident against a 3% listing budget.
  **Mass-installing 1,928 externals → ~2,301 resident names → blows the budget → Claude Code
  silently truncates the listing.** "First-class = install like bundled" is self-defeating
  at catalog scale.
- BUT the enforcer *offer* is an on-demand Qdrant query (`_retrieve`), not resident. Externals
  can be first-class **in the offer** at zero resident cost. First-class means *how the offer
  treats them*, not OS-level registration.

## Decision

**External catalog skills become first-class in the per-turn offer as an ADDITIVE ANNEX,
consumed via `get_skill` read-inline, with proven-used ones auto-graduating to installed.**

1. **Additive annex, zero displacement (hard invariant).** The installed offer is produced by
   the UNCHANGED `_retrieve` (still `must_not tier=external`, limit `TOP_K`) — byte-identical
   whether the annex is on or off. A SEPARATE `_retrieve_external` query (`must tier=external`,
   limit `ENFORCER_EXTERNAL_SLOTS`) supplies the annex. **Two small queries, not one widened
   query** — a widened single query would drop installed skills out of the limit window
   whenever externals ranked high in it, silently displacing the curated shelf. The extra
   query is best-effort: a failure degrades to no-annex, never breaks the installed offer.
2. **Quota + floor (dilution + injection safeguard).** At most `ENFORCER_EXTERNAL_SLOTS`
   (default 2) externals annex, and only those scoring ≥ `ENFORCER_EXTERNAL_FLOOR` (default
   0.40 — deliberately higher than the installed `ITEM_FLOOR` 0.18). Most turns show zero
   externals; the annex appears only on strong intent-match. The higher bar is the safeguard
   against unvetted third-party text getting cheap airtime.
3. **Render as a distinct block.** The annex is rendered below the installed offer, marked
   `[external:<alias>]`, with the instruction `USING: <name>` → `get_skill("<name>")` +
   follow inline (the Skill tool cannot invoke it — not registered). Externals never share the
   installed %-share pool.
4. **Rides only the main offer path.** A getaway/intent-skip turn (no installed offer) injects
   no annex — deliberate v1 scope. A strong external on an installed-getaway turn is a recorded
   fast-follow, not built here.
5. **Usage-promotion (organic curation).** A SessionStart hook (`auto_promote.py`) counts each
   external skill's `get_skill` takes across DISTINCT sessions; one over `PROMOTE_MIN_TAKES`
   (default 3) auto-promotes via `catalogs.py promote` (symlink into `~/.claude/skills`),
   becoming a real installed, Skill-tool-invocable skill under the name-only budget. The
   resident set grows only by *demonstrated* usage. Idempotent (collision-refused),
   throttled, kill-switch `PROMOTE_ENABLED=0`.
6. **Telemetry.** The `offer` ledger event gains `ext` (annex names); `analyze.py` reports
   external annex offers and external offer→take session-conversion, distinct from installed
   (installed ranking is unchanged). Epoch-scoped — window from ship.
7. **Kill-switch.** `ENFORCER_EXTERNAL_ANNEX=0` restores ADR-0031 search-only exactly (the
   installed query already carries `must_not tier=external`; the external query is not issued).

## Consequences

- The offer path issues one extra small Qdrant query on installed-offer turns when the annex
  is on. Signal: `analyze --latency` p95 rise; response: the external query is `limit=SLOTS`,
  cheap, and the intent gate already issues 2 Qdrant queries on some turns — within budget.
- New epoch for OFFER-composition metrics at ship; installed offer→take is unaffected
  (installed ranking byte-identical) and continues across.
- A promoted external exists once (installed) — the ADR-0031 realpath dedup suppresses the
  catalog twin at the next reindex; auto_overrides gives it a name-only budget entry.
- Open (fast-follow, recorded not built): annex on getaway turns; per-catalog floors;
  `PROMOTE_MIN_TAKES` tuning from live external-take data.

## Evidence

Implemented + verified 2026-08-23:
- `enforcer.py --selftest` cases 10 (installed query byte-identical: `must_not tier=external`,
  limit `TOP_K`) + 11 (external annex: separate `must tier=external` query, floor+slots,
  alias, render block with get_skill instruction, kill-switch → no query/[]). Green.
- **Live invariant proof:** for the docker intent, the installed offer is byte-identical with
  `ENFORCER_EXTERNAL_ANNEX=1` vs `=0` (same 8 skills, same %-shares) — zero displacement — with
  2 externals annexed only when on, marked `[external:antigravity]`, with the get_skill
  instruction. (The exact annexed skill names track the live catalog, which the owner pulls;
  at ship time `antigravity:github-actions-templates` was the strongest docker match — the
  invariant, not any specific example, is what the proof establishes.)
- `auto_promote.py --selftest` (distinct-session tally, threshold, subagent-row exclusion) +
  end-to-end: 3-session takes → symlink promoted, re-run idempotent, logged.
- `analyze.py --selftest` external annex offer→take case; live line renders.
- `ledger.py`/`catalogs.py` selftests green.
