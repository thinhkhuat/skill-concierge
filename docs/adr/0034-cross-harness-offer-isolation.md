# ADR-0034: Cross-harness offer isolation — the installed offer holds only invocable skills

| | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-08-24 |
| **Supersedes** | none |
| **Amends** | ADR-0033 (narrows its "offer across the union" clause to the per-turn offer) |

## Context

ADR-0033 folded Codex's skill universe into the one shared Qdrant collection under distinct
`codex-*` scopes, and stated the consequence plainly: *"the enforcer, chain hints, and search
offer across the union."* For search and chain hints that is right. For the **per-turn offer**
it is not.

`enforcer._retrieve` queried Qdrant with a single `must_not tier=external` condition and no
scope filter, so in a Claude session the Codex plugin cache competed for the `TOP_K` (8)
installed slots on equal terms. Measured live on 2026-08-24 over six prompts, counting only
rows this harness genuinely cannot invoke: **18 of 48 offer rows** (0–5 per prompt) were
non-invocable. The mirror holds in a Codex session for Claude's `plugin` scope.

An offer row the agent cannot act on is strictly worse than no row. It burns a slot that an
invocable skill would have taken, and it invites a `USING:` the harness will then refuse —
turning the concierge's own preview into a source of false routing.

## Decision

**Keep foreign-harness skills out of the installed offer, then re-surface them as a separate
marked annex.** This is the ADR-0032 external-annex shape applied one layer up.

- `enforcer._retrieve` over-fetches to `RETRIEVE_LIMIT` (`TOP_K * 5`), drops rows this harness
  cannot invoke, and trims back to `TOP_K`. The multiplier is **headroom, not a guarantee**: in a
  domain the sibling harness dominates, more than `RETRIEVE_LIMIT - TOP_K` of the top groups can
  be foreign and the menu comes back short. Measured: at `TOP_K * 3`, two of thirty probes
  under-filled (5 and 7 rows, needing 30 and 25 groups); at `TOP_K * 4`, one of sixty still did
  (*"vercel edge config feature flags"*, 7 rows, 35 groups needed); at `TOP_K * 5`, every case
  observed so far fills. A shorter menu of invocable rows beats a full one padded with rows the
  agent cannot act on, so under-fill remains the accepted degradation, not a bug to pad around.
- `enforcer._retrieve_foreign` issues a **separate** query filtered to the foreign scope set,
  keeping the top `ENFORCER_FOREIGN_SLOTS` (2) rows scoring >= `ENFORCER_FOREIGN_FLOOR` (0.40).
  A dedicated query, never a partition of a widened one, is what makes displacement
  structurally impossible — the same hard invariant ADR-0032 rests on.
- `_ranked_mandate` renders them as a **third block**, distinct from the external-catalog block
  so provenance stays legible ("installed under the sibling harness" is not "in a search-only
  catalog"), marked `[codex]` / `[claude]`, carrying the `get_skill` read-inline instruction.
- The floor is deliberately the external floor's height (0.40), not `ITEM_FLOOR` (0.18): a row
  the agent cannot invoke earns its place only on strong intent-match.

### Why a post-filter and not a Qdrant `must_not scope`

**Scope records where a skill's indexed copy lives. That is not the same question as "can this
harness invoke it."** A query-side scope filter conflates the two, and the first implementation
of this ADR did exactly that. It was wrong on real data.

Claude Code resolves plugin enablement by **layering** settings files — user, then project,
then project-local, last writer wins. `skills_discovery._installed_plugin_roots()` reads the
**user** file only. So a plugin disabled globally but enabled for one project (on the dev
machine: `agent-skills@addy-agent-skills`, `False` in `~/.claude/settings.json`, `True` in the
repo's `.claude/settings.local.json`) is dropped from discovery, its Codex twin wins the name
in dedup, and the point carries `scope: codex-plugin` for **24 skills Claude invokes fine**.
A pre-filter silently deleted all 24 from the offer and printed them under *"NOT invocable here
— do not use the Skill tool"*: the exact false routing this ADR exists to prevent, inverted.

The post-filter tests each row with `_invocable_twin()`: a foreign-scoped row whose plugin is
**installed on this side and not switched off** in this session's merged settings is invocable
anyway and stays in the offer. `_retrieve_foreign` skips the same rows, so a twin never appears
in both blocks. Three details are load-bearing and each was a defect before it was a rule:

- **Installation is checked, not just enablement.** A plugin switched on in settings whose cache
  is absent is not invocable; treating it as a twin would keep a genuinely dead row.
- **A key absent from `enabledPlugins` means ENABLED**, matching Claude Code and
  `skills_discovery._installed_plugin_roots`. Collecting only explicit-`true` keys would make an
  enabled-by-default plugin permanently unrescuable.
- **Marketplace collisions resolve by union.** Skill names carry only the bare plugin id, so if
  any `<id>@<marketplace>` copy is installed and on, the id is invocable. Keying on the bare id
  with last-writer-wins silently lost the enabled copy on JSON key order.

**Unknown must filter nothing.** When `installed_plugins.json` cannot be read, the twin test
cannot be made, so `_invocable_plugin_ids()` returns `None` and `_retrieve` drops **no** rows.
The first version of this post-filter got that backwards — `_invocable_twin` returned `False` on
unknown and the caller dropped on `not _invocable_twin(...)`, so an unreadable or
`enabledPlugins`-less settings file silently reinstated the exact mislabelling the post-filter
had just replaced. The drop is now conditioned on positive knowledge, and the selftest pins it.

That resolution belongs in the **hook**, not in discovery. The index is machine-global and
shared across concurrent sessions; baking a cwd-scoped view into it would make sessions fight
over each other's points — the ADR-0028 / v0.19.1 hazard. The enforcer already runs per
session with the right cwd, so it is the only correct place to ask a per-project question.
When no settings file can be read the twin test returns "unknown" and filters **nothing**,
failing toward ADR-0033's union — merely noisy, and already shipped — never toward telling the
agent a skill it can invoke is unusable.

Dropping the query-side condition also keeps an unindexed keyword filter off the installed
query's hot path.

### Which scopes are foreign

Not "everything belonging to the other harness". The set is derived per harness:

- **From Claude:** `codex-plugin` and `codex-personal`. The latter is populated *only* when
  `~/.codex/skills` and `~/.claude/skills` are different directories, and then its skills are
  genuinely unreachable from Claude. Where the operator has symlinked them, discovery dedups
  everything into one `personal` scope and the entry matches nothing.
- **From Codex:** `plugin` only. Claude's plugin cache is not on Codex's load path at all, so
  that one is unconditional. `personal` is deliberately **not** foreign here, even though the
  mirror argument looks symmetric. It is not symmetric: `SKILL_DIRS` walks the Claude personal
  root first regardless of harness, so a skill present in *both* personal roots is tagged
  `personal` — and Codex can invoke it via `~/.codex/skills`. With the twin rescue unavailable
  on that side, excluding `personal` would drop exactly those skills and label them
  uninvocable: the same defect, mirrored. Keeping them costs at most some Claude-only personal
  rows in a Codex offer — the pre-ADR-0034 noise, which is the direction to fail in.
- `project:` scopes are cwd-derived and shared by construction. Never foreign.

### Harness detection

Path-derived, not a new env var. Both harnesses run the same `hooks/hooks.json` and expand the
same `${CLAUDE_PLUGIN_ROOT}`, so the discriminator is where the plugin was installed —
`~/.codex/plugins/cache/**` vs `~/.claude/**`. `enforcer.py` uses **precedence**: the env var
decides whenever it is set; only an unset or empty one falls through to the hook's own resolved
`__file__`, which covers a wiring by absolute path. A falsy candidate is skipped, never
resolved — `Path("").resolve()` returns `os.getcwd()`, which would turn the check into a silent
CWD probe and **invert** the filter for any session whose cwd sits under `~/.codex/`, making a
Claude session exclude Claude's own plugin skills. The selftest pins that case.

**One-var revert.** `ENFORCER_CROSS_HARNESS=0` restores ADR-0033's union: the pre-change
request shape (limit `TOP_K`, no `scope` payload), no annex query, no annex block.

**Telemetry.** The `offer` ledger event gains an `xh` field mirroring ADR-0032's `ext`, and
`analyze.py._cross_harness_annex_stats` consumes it. Conversion is keyed on the **exact** name
a session was offered, not on a prefix: cross-harness rows carry a plugin namespace, not a
catalog alias.

## Consequences

- The installed offer in either harness is now exactly the top-k skills that harness can
  invoke. Cross-harness skills stay discoverable — via the annex on strong matches, and via
  `search_skills` unrestricted — but invocability is never implied.
- `search_skills` and chain hints are untouched: ADR-0033's union still governs there, where a
  non-invocable result is a legitimate answer rather than a routing instruction. A chain hint
  can still name a `codex-plugin` skill without a marker; deliberate, and low-impact today
  (11 of 625 sidecar entries carry successors).
- **Both annex queries moved past the gates.** They were issued immediately after `_retrieve`,
  ahead of the getaway and actionability gates, so a suppressed turn paid for them and threw
  the result away. With this ADR adding a third round-trip inside a hard per-turn budget, both
  now run just before the inject. Rendered output is unchanged.
- **`scope` and `tier` gained keyword payload indexes** (`server._ensure_collection`). Only
  `name` was indexed, so every enforcer query's `tier` condition — and the new annex query's
  `scope` condition — was a linear scan over ~25k points inside a hard 100 ms cap where a
  timeout costs the whole offer. `_ensure_collection` is called only from `build_index()`, so
  **the indexes appear at the next reindex, not at deploy**; creating them on an existing
  populated collection is safe and idempotent, and the SessionStart auto-reindex self-heals it.
  Note the vendored tests cannot prove the indexes are built — they run against local Qdrant,
  which warns that payload indexes have no effect there — only that the call does not raise.
- **Ledger epoch note.** This changes what `offered` contains. Any offer-composition metric
  (hit@k, conversion, fallback) pooled across the v0.25.0 boundary describes two different
  configs. Window it: `analyze.py --since <this release's commit>`.
- Companion fix in the same release: `_plugin_paths()` now globs both caches at
  `skills/<skill>/` **and** `skills/<category>/<skill>/`. The single-star glob had silently
  missed 35 installed, invocable `mattpocock-skills` skills. Without it, filtering the foreign
  plugin scope would have narrowed the Claude offer while a real Claude blind spot stayed open.
- **Known residual:** `_installed_plugin_roots()` still reads only the user settings file, so
  the *index* keeps mislabelling a project-enabled plugin's scope. The enforcer now compensates
  at query time, which is where a per-project question belongs, but `search_skills` results and
  the provenance shown for such a skill remain cosmetically wrong. Fixing it in discovery
  requires deciding how a machine-global index should represent a per-project fact — out of
  scope here.

## Validation

- `enforcer.py --selftest` case (12) pins: a non-invocable foreign row is dropped from the
  installed offer while the offer still refills to `TOP_K`; an **invocable twin stays** in the
  installed offer and is **not** repeated in the annex; scope is never a query condition; the
  annex query matches the foreign scope *set*, applies the floor, renders the harness marker
  plus the `get_skill` instruction, and never joins the installed %-share pool; an empty
  `CLAUDE_PLUGIN_ROOT` falls through to `__file__` instead of resolving to the cwd; and the
  kill-switch restores the pre-ADR-0034 request shape and output.
- `analyze.py --selftest` pins the `xh` stats, including that a pull of a *different* foreign
  skill does not count as a conversion and that subagent rows are excluded.
- `vendor/skill-search` suite green including three new discovery tests: category-nested plugin
  skills are found and namespaced correctly, a SKILL.md inside a real skill's own subdirectory
  is **not** minted as a phantom skill, and the Codex cache gets identical two-depth treatment.
- Live discovery: 2541 skills (2506 + exactly the 35 previously-missed `mattpocock-skills`),
  zero duplicate paths, zero phantoms.
- Live offer probe, flag OFF vs ON, counting only rows this harness cannot invoke. Six prompts
  — *"debug this failing test"*, *"review my code changes"*, *"docker build is broken"*, *"write
  a plan for a new feature"*, *"audit the security of this endpoint"*, *"help me plan a database
  migration"* — went **18 of 48 -> 0**. A 20-prompt sweep including Vercel/Next/Cloudflare
  queries (the domains where the Codex cache is densest) returned **160 rows, 0 non-invocable,
  8 rows every time**; re-run at `TOP_K * 5` including the pass-3 counterexample, 21 of 21 full,
  168 rows, 0 non-invocable. Every foreign-scoped row kept in
  the offer was an invocable twin (`agent-skills:*`); the annex held only genuinely
  non-invocable skills (`superpowers:*`, `vercel:*`, `omo:*`, `supabase:*`, `cloudflare:*`).
  Warm latency: installed query 14-20 ms, annex query 8-18 ms, against the 100 ms cap.
- Two independent adversarial validation passes, both returning FAIL on the implementation as it
  stood:
  - **Pass 1** (`plans/reports/validator-260824-1545-adr0034-cross-harness.md`) — the
    scope-vs-invocability premise, and `Path("")`-resolves-to-cwd inverting harness detection.
  - **Pass 2** (`plans/reports/validator-260824-1720-adr0034-pass2.md`) — a regression introduced
    by the pass-1 fix: `Path.cwd()` at module scope broke the fail-silent contract (a deleted
    working directory turned every turn into a traceback, where the pre-change code returned a
    full offer); plus the unknown-twin path failing toward the harm it was built to prevent,
    offer under-fill at `TOP_K * 3`, and the Codex `personal` mirror.
  Every finding above is fixed and the two blocking ones are pinned by selftest case (12) — a
  deleted-cwd import that must not raise, and an unknown manifest that must filter nothing.
  - **Pass 3** (`plans/reports/validator-260824-1745-adr0034-pass3.md`) — PASS, no blockers.
    Its three advisories (a stale README sentence, residual under-fill at `TOP_K * 4`, and an
    unguarded `Path.cwd()` in `_visible_sidecar_names` that would silently cost the whole offer
    on the chain-hint path) are all fixed too; the last one is pre-existing rather than from this
    work, but having decided the deleted-cwd case is worth guarding, guarding half of it was not
    defensible.
  All three passes are worth reading; the first two each caught a defect whose selftests were
  already green, because the tests pinned the mechanism while the bug was in the premise.
