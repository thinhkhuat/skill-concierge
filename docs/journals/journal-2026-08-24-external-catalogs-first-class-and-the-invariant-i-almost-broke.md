# External catalogs, first-class — and the invariant I almost broke

2026-08-24 · skill-concierge · v0.22.0 → v0.23.0 · follows the always-on-allowlist arc

The session began with a modest-sounding ask — "let skill-concierge search a second skills
collection that lives outside `~/.claude/skills`, without importing it" — and ended two ADRs
and three releases later with external catalogs sitting first-class in the per-turn offer. The
interesting part was not the plumbing. It was a reframe the owner had right from the start and a
fidelity bug I built, caught, and tore out before it shipped.

## The plumbing (ADR-0031, v0.22.0)

Discovery roots were hardcoded to two paths. Adding a third class of root — an operator-owned
`catalog-roots.json` mapping an alias to a local directory — was mechanical once the scout mapped
the engine: names mint as `<alias>:<name>`, points carry a `catalog:<alias>` scope and a
`tier: external` payload, and the ADR-0028 scope filter (built to be extended exactly this way)
keeps a reindex from pruning them. The one non-obvious call was the consumption path: an external
skill is not registered with Claude Code, so the `Skill` tool cannot invoke it. `get_skill`
already returns a body from the indexed path, so "read the SKILL.md inline and follow it" became
the consumption model — no install, zero registration. The first catalog (`antigravity`, ~1,900
skills) went in search-only: retrievable via `search_skills`, deliberately excluded from the
per-turn offer with a single `must_not tier=external` filter.

The autonomous run that shipped it also taught the recurring lesson again: a blind validator
caught that the test suite was reading the operator's *live* catalog config and failing two
count-exact tests on the very machine that ran them. The fix belonged in the generator —
`conftest.py` now pins `SKILL_CONCIERGE_CATALOG_ROOTS` to a nonexistent path — not in the tests.

## The reframe (ADR-0032, v0.23.0)

Then the real ask: promote externals from guest to first-class, "like the bundled catalog." My
first instinct was to reach for promotion — symlink the catalog into `~/.claude/skills` so the
skills become real. The owner's instinct was better, and the evidence settled it. The concierge
makes *descriptions* on-demand, but *names* stay resident in every turn's skill listing. Today 373
names sit resident against a 3% listing budget. Mass-installing 1,928 externals would put ~2,301
names resident, blow the budget, and make Claude Code silently truncate the listing — reintroducing
the exact tax the concierge exists to remove. "First-class like bundled," taken literally, is
self-defeating at catalog scale.

The unlock was noticing that the per-turn *offer* is a live Qdrant query, not the resident listing.
Externals can be first-class *in the offer* at zero resident cost. First-class is about how the
offering mechanism treats them, not about OS-level registration. The owner had meant exactly this
all along; I just had to catch up to it.

## The invariant I almost broke

The design promised a hard invariant: the annex is *additive* — the installed offer must be
untouched, zero displacement. My first implementation removed the `must_not` filter and widened the
single retrieval to `TOP_K + SLOTS + buffer`, then partitioned installed vs external from that one
window. Clean, one query, low latency. It passed the selftest.

Then I ran it live and the installed offer for the docker prompt had shrunk from eight skills to
four. The widened window was the bug: when externals rank high, they consume slots in the limit
window, and installed skills that *would* have been in the filtered top-8 fall outside it and
vanish. The single-query optimization silently displaced the curated shelf — the precise thing the
invariant forbade.

The fix was to stop optimizing and run two queries: the installed query unchanged (byte-identical
to search-only), plus a separate tiny `must tier=external` query for the annex. One extra ~20ms
Qdrant call buys a guarantee that no widened window can. The proof is a hash: the installed offer is
identical (`1b51bb67`) with the annex on versus off. I would have shipped the one-query version if I
hadn't looked at the actual output — the selftest was green on a case that didn't exercise the
displacement.

## What shipped

Two small queries, an annex of at most two externals scoring ≥0.40 (higher than installed's 0.18,
so most turns show none and unvetted third-party text earns airtime only on strong intent-match),
rendered as a distinct `[external:<alias>]` block with the get_skill instruction. Plus
usage-promotion: an external used across three distinct sessions auto-graduates to a real installed
skill — the resident set grows only by demonstrated use, which is the organic version of the
mass-install I almost reached for. Kill-switch restores search-only. An independent validator passed
it with zero blocking findings; the deployed 0.23.0 smokes are green, and the annex now fires on
real turns.

## Decision
Externals are first-class in the offer via an additive annex sourced from a *separate* query
(never a widened shared query), consumed via `get_skill`, with usage-promotion for the proven-used
few. Recorded in ADR-0032; ADR-0031's search-only stance is superseded in part.

## Next steps
Two fast-follows are recorded and deliberately unbuilt (owner-scoped): an annex on
installed-getaway turns, and per-catalog floors. The `PROMOTE_MIN_TAKES=3` threshold is a first
guess to tune from live external-take data. Epoch-window all offer-composition metrics from
2026-08-23.
