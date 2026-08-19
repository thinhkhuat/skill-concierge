# Over-engineering audit — ADR-0029 / ADR-0030 (engine skill chaining)

Auditor: adr-scope-auditor (read-only) · 2026-08-19 · Scope: `docs/adr/0029-*`, `docs/adr/0030-*`,
`plans/260819-2218-engine-skill-chaining/plan.md`.

## Verdict

The plan builds a soft hint and a menu regrouping with the ceremony of a subsystem: 2 ADRs, 5 phases,
2 flags, 2 new state files, a vendored-engine patch, and a lint. One ADR's worth of mechanism
(ADR-0029, slimmed) earns its keep; ADR-0030 should be cut entirely, and ADR-0029 loses roughly half
its surface with no capability the owner actually asked for being lost. Recommended shape:
**1 ADR, 1 phase, 1 flag, 1 new file** — still v0.21.0.

## What I verified (all claims below are source-read, not recalled)

- Doctrine already forces per-turn re-SEARCH — `hooks/doctrine/skill-first.md:63` ("A prior reply's
  search is spent. SEARCH again, here.") and rule 2 (`:28-39`), including the mandate to issue
  2–3 varied phrasings via `extra_queries` (`:30`, `:33`).
- `get_skill` returns the **full SKILL.md text** including frontmatter (`vendor/skill-search/skill_search/server.py:692-710`)
  — so any `next-skills:` frontmatter is *already delivered to the agent* at deep-pull time, today,
  with zero code.
- `search_skills` output renders only `{name, command, description, score}` — `_fuse_ranked`
  hardcodes those keys (`server.py:637-648`, `:681`). A `next-skills` Qdrant payload field would
  have **no renderer** anywhere today.
- The ledger already records every skill use with `{t, sid, name}` — `auto` for tool invocations
  (`hooks/scripts/ledger.py:83-84`) *and* `manual` for user-typed slash skills (`ledger.py:60-63`).
  Live ledger ≈ 4.7k lines — a tail read is microseconds.
- The repo already carries three default-inert mechanisms: per-skill-tau (shipped off 2026-06-30,
  `enforcer.py:188-196`, still un-armed in any settings), deterministic routes (`enforcer.py:222-247`),
  dominance collapse (`enforcer.py:268-277`).
- `_mcp_env` exists (`hooks/scripts/auto_reindex.py:40`) — the ADR's forwarding target is real.
- Shelf: `~/.claude/skills/agent-skill-stack/SKILL.md` — planning-time, upfront multi-skill set
  assembly, including dynamic workflow decomposition (its §2). Different lifecycle than a per-turn
  hook; does not substitute for W1, but overlaps heavily with W2's decomposition idea.

---

## Q1 — W1 surface: frontmatter + sidecar + chain-state + enforcer line

### The three options at ~500 skills

| Option | Surface | What works | What breaks at ~500 skills |
|---|---|---|---|
| (b) Pure doctrine (bodies name successors + one doctrine row) | ~2 lines | Successor names enter context the moment skill A is invoked (SKILL.md auto-loads); agent re-SEARCHes next turn anyway | Nothing *breaks* — but successors die at **context compaction** (body summarized away) and never reach the *enforcer's* menu on a vague turn |
| (a) Ride `get_skill`/`search_skills` output | ~0 lines | Already true for `get_skill` (full text returned, `server.py:703`); search output would need a `_fuse_ranked` key | Same as (b); the preview menu still can't show successors |
| W1 as designed | 2 files + flag + patch + lint + doctrine row | Above, **plus** hint survives compaction (re-injected from disk each turn) | No scale problem — sidecar is an O(1) dict lookup |

The discriminator is not scale — it is **turn-class conversion**. W1's machinery exists to catch the
vague follow-up turn ("go ahead", "now the docs"). Two facts undercut that target population:

1. **The hint inherits the actionability gate.** On a non-imperative vague turn, the enforcer
   suppresses the offer at `enforcer.py:605-608` — the ranked mandate (to which CHAIN-HINT appends)
   never renders. "now the docs" opens with filler + a noun → non-imperative → the kNN gate decides.
   W1's reach into its *own* target class is partial by construction.
2. This repo's own ledger analysis found taken offers score *lower* than dodged ones
   (`enforcer.py:66`) — the offered-on-vague-turn population is the worst-converting one.

So the honest case for engine-side is narrow: **hint survival across compaction**. That case is real
(this is a long-session tool) and the owner already chose engine-side scoping — but it justifies the
*slimmest* engine, not the designed one.

### Two files — is one too many? Yes, and the answer is zero new state files

- `next-skills.json` (sidecar): **keep**. It is the only zero-network way for the enforcer to map
  name→successors (a Qdrant point-retrieve would be a new network call — banned by the hot-path
  constraint, `enforcer.py:18-24`).
- `chain-state.json`: **cut**. It is a materialized view of data the ledger already persists
  (`ledger.py:63,83-84`). The enforcer can tail-read the ledger (fixed 64KB seek-back, filter
  `ev in ("auto","manual")` by sid within TTL) in ~12 lines. DRY: don't materialize what you can read.
- The lead's "one merged file" idea: **worse than either** — the sidecar is regenerated wholesale at
  index time while chain state mutates per invocation; merging forces read-modify-write of the
  sidecar on every skill use and creates a reindex-vs-state clobber bug.

**Bonus defect the cut fixes:** the proposed chain-state seeds only from PostToolUse(Skill) (`auto`)
— ADR-0029 "Decision" bullet 3. Slash-invoked skills log `manual` (`ledger.py:60-63`) and would
**never seed a chain** under the designed mechanism. The ledger-tail reader sees both event kinds
naturally.

### Further W1 trims

- **Cut the Qdrant payload carriage.** `_fuse_ranked` hardcodes its output keys (`server.py:648`);
  `get_skill` returns the full file anyway. The payload field is dead data today and only fattens the
  vendored patch (ADR-0016 re-vendor friction). Sidecar only.
- **Cut the flag forwarding through `auto_reindex._mcp_env()`.** Make the sidecar write
  *unconditional*; let `ENFORCER_CHAIN_HINT` gate only the enforcer read. An unread sidecar is inert;
  the whole producer/consumer config-drift class (the ADR-0027 bug family the ADR itself cites)
  evaporates when the producer's config never varies.

## Q2 — TTL / sid-scope / dangling lint: which earns its complexity

| Guard | Cost | Misfire it prevents | Keep? |
|---|---|---|---|
| sid-scoping | ~2 lines | concurrent session's skill use hinting in this one | **Keep** |
| 15-min TTL | ~3 lines | yesterday's stale chain hinting today | **Keep** |
| Dangling-name lint | reindex code + fixture + docs | a typo'd successor renders in an advisory line | **Cut first** |

The lint polices a *soft-text* channel that already self-labels "candidates, fit still required" and
self-heals at the agent (search, find nothing, move on — fail-open everywhere else in this hook).
It is the only one of the three guarding a failure mode with no downstream consequence. The E2E
fixture (P1) already exercises authored names; that is enough warning until a real typo shows up.

## Q3 — W2 ships inert: discipline or dead code?

**For keeping W2 as designed:** it follows the house pattern (per-skill-tau precedent,
`enforcer.py:188-196`); mechanism-ships-inert-with-selftest is how this repo stages risky levers;
the lexical splitter is deterministic and stdlib-only; the flag is a clean revert.

**For cutting W2:**
1. **The repo's own precedent is the counter-example.** Per-skill-tau shipped inert 2026-06-30 and
   is still un-armed; no settings arm deterministic routes or dominance either. Default-off
   mechanisms here stay off. W2 would be the **fourth inert limb** — code with a selftest tax that
   no production turn ever executes, drifting silently against the evolving embed shim.
2. **The capability already exists at the tool layer.** ADR-0030's own Context concedes
   across-turn recovery via forced re-SEARCH. For the *first* menu, the doctrine already orders
   2–3 varied phrasings through `extra_queries` (`skill-first.md:30,33`) — and MAX-pool over query
   variants (`server.py:670-681`) **is** per-intent retrieval when the agent phrases one query per
   intent. W2 rebuilds, inside the hardest-to-test layer (a 300ms hook), what the primary tool
   already exposes via its documented interface.
3. **Decomposition intelligence already lives on the shelf** — `agent-skill-stack` §2 derives
   workflows dynamically. A comma/`và` splitter is the dumbest possible version of a problem the
   user already owns a smart version of.
4. The comma false-split risk is admitted by the ADR itself (Consequences) — presentation-only
   blast, yes, but it is blast with zero measured upside.

**Pick: cut W2 from v0.21.0 entirely.** Residue: **one doctrine sentence** — "a multi-intent prompt
is searched one phrasing per intent via `extra_queries`" (~1 line in `skill-first.md` rule 2).
Withdraw ADR-0030; if the decision trail matters, record it as a rejected-alternative paragraph
inside ADR-0029's Context rather than as its own ADR. Saves: 1 ADR, 1 flag (+ its CLAUDE.md and
AGENTS.md lines + its own auto_reindex forwarding), the P3 phase, the latency probe, and an
estimated 100–150 lines (EN+VN connector lexicons, parallel-embed executor, grouped renderer,
union-dedup, selftests — estimate, not measured). Lost capability: a legible grouped first-menu
*if ever armed* — recoverable later by re-proposing when ledger data shows multi-intent first menus
actually converting poorly.

## Q4 — W3: one metric is enough

Ship **`--chains` only**; defer hint-follow. `--chains` is a pure read-side view over `auto`
events the ledger already records — zero new data, and it alone answers the origin question
("does skill-concierge support daisy-chaining?") with real bigrams. Hint-follow measures an
intervention that may not survive its first epoch; add it only when a demotion decision actually
needs the number (~20–30 lines on top of `--chains` at that point). Saves one metric's worth of
epoch bookkeeping and analyzer surface now.

## Q5 — Proportionality: the 1-phase version

A soft hint plus a menu regrouping does not need 5 phases and 2 ADRs. The 1-phase version:

| | Designed plan | 1-phase version |
|---|---|---|
| ADRs | 2 (0029 + 0030) | 1 (0029 slimmed; 0030 withdrawn → rejected-alt note) |
| Phases | P0–P4 | 1 (impl + docs + ship in one arc; `--chains` folded in or dropped to a follow-up) |
| Flags | 2 | 1 (`ENFORCER_CHAIN_HINT`, default ON, consumer-side only) |
| New state files | 2 | 1 (sidecar only; chain state read from ledger tail) |
| Vendored patch | parse + payload + sidecar | parse + sidecar only |
| Lint / probe / forwarding | yes / yes / yes | no / no / no |

P1's gates in the plan are already the right ones (selftest, E2E hint, byte-identity); they survive
unchanged. Version 0.21.0 minor bump is correct either way (new user-visible behavior + flag).

Note the designed P2→P1 dependency dissolves: with hint-follow deferred, nothing depends on
anything — one commit arc, one validation pass.

## Cut list (summary)

| # | Cut | Saves | Capability lost | Does the loss matter? |
|---|---|---|---|---|
| 1 | ADR-0030 / W2 entirely (+1 doctrine sentence) | 1 ADR, 1 flag, 1 phase, ~100–150 lines, latency probe | grouped first-menu, only if ever armed | No — `extra_queries` MAX-pool + forced re-SEARCH already cover it; repo precedent says it would stay off |
| 2 | `chain-state.json` → ledger tail read | 1 state file, ledger.py write path, a two-truths drift class | none | No — and it *fixes* the slash-invocation seeding gap |
| 3 | Qdrant payload carriage | vendored-patch size (ADR-0016 friction) | none today (no renderer; `get_skill` returns full text) | No |
| 4 | `_mcp_env` flag forwarding (write sidecar unconditionally) | forwarding code + the ADR-0027 drift class | none (unread sidecar is inert) | No |
| 5 | Dangling-successor lint | reindex code + fixture | early typo warning | Marginal — soft-text channel, self-healing |
| 6 | Hint-follow metric (keep `--chains`) | ~20–30 lines + epoch bookkeeping | hint-efficacy number on day 1 | No — add it when a demotion decision needs it |

**Kept (irreducible core of "skills can say 'after me, X' and the engine honors it one turn
later"):** frontmatter authoring, parse patch → sidecar, enforcer hint from ledger-tail + sidecar
with TTL + sid-scoping, `ENFORCER_CHAIN_HINT` default ON, one doctrine row, selftest, VENDORED.md
entry, version bump. Roughly half the designed diff.

## Defects / inconsistencies found in the proposals (independent of cuts)

1. **Approval-state contradiction:** both ADRs say "Source: …plan.md (owner-approved 2026-08-19)"
   (`docs/adr/0029-…:8`, `0030-…:8`) while the plan itself says "Status: DRAFT — awaiting owner
   approval" (`plans/260819-2218-…/plan.md:3`). One of the two is stale; fix before P0 sign-off.
2. **Slash-invocation seeding gap** (detailed in Q1): chain-state on the `auto` path only never
   chains from `/skill:name` invocations.
3. **Hint reach is gate-limited** (detailed in Q1): the actionability gate suppresses the mandate on
   the vaguest non-imperative turns — the ADR's motivating population. Worth one sentence of honest
   scope in ADR-0029's Consequences either way.

## Unresolved questions (owner calls, not mine)

- Whether the compaction-survival argument is worth *any* engine surface, or pure doctrine (option
  b) suffices — the owner already scoped engine-side, so I audited the smallest engine version, but
  option b remains the true zero-surface alternative.
- Whether `--chains` ships in the same arc or as a follow-up (pure read-side; no dependency either
  way once hint-follow is deferred).
