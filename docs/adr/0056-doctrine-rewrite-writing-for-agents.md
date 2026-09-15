# ADR-0056 — SKILL-FIRST doctrine and enforcer strings rewritten under the writing-for-agents levers

Status: Accepted (2026-09-15, owner order: "audit every writing in the doctrine … strengthen and correct")
Relates to: ADR-0015 (library doctrine — its escalation clause is superseded here), ADR-0019 (self-recap lane), ADR-0054 (harness lane), ADR-0055 (the env trial that exposed the non-hermetic selftest), ADR-0042 (OMP deploy doctrine — installer fix).
Evidence: `plans/reports/audit-260915-1125-doctrine-writing-audit.md` (line-by-line findings), `plans/reports/review-260915-doctrine-writing-for-agents.md` (independent review, two passes).

## Context

The doctrine body is injected into every session on every harness; five enforcer strings ride on
top of it per turn. Both grew by accretion since v0.3.0 (ADR-0015 added the library doctrine, the
anti-dodge integration added rule 4's closed list and the Red Flags table, later ADRs added rows
and clauses). Auditing every line against the writing-for-agents reference, then handing the
rewrite to an independent reviewer, found four classes of defect:

1. **The one question the order exists to settle was answered in five places, three ways.** The
   token line, rule 4, Red-Flags row 7, the library section and the Persistence line each defined
   when `SKIPPING: none` is lawful; rule 4 said "one class — no task", the library section let a
   "positively-reasoned trivial" turn skip without a search, row 7 added a self-recap class, and
   the getaway leg's `SKILL-CHECK:` line pre-authorized "trivial" turns. A trivial errand is a
   task. An agent that wants to skip reads whichever clause is softest.
2. **A phantom pointer.** Doctrine and the getaway leg escalated real-or-ambiguous work to
   `find-skills`. No skill of that name is installed on any harness here (`ak:find-skills` exists
   on this machine and discovers skills to *install* from registries — a different job). The
   escalation the situation needs is a term-rich re-query of `search_skills`, because the getaway
   leg fires precisely when the raw prompt scored below the floor.
3. **Stale caches, labels and harness names in agent-facing text.** "~500 skills" (live index
   2,714 points); an ADR number; a v0.4.0 plugin-history note; "the Skill tool" (a Claude Code
   name) in a body read by five harnesses; a row-grouping parenthetical written for a 7-row table
   that had grown to 8; two token spellings (`USING <skill>` per turn, `USING: <skill>` in the body).
4. **Load without behaviour.** Meanings stated three times ("USING never takes none", "in THIS
   reply"), Not/Yes pairs that spelled the banned outputs into context, rationale sentences the
   agent cannot act on, and `MANDATE` claiming "shown skills are a preview" on the two code paths
   that show none.

Two mechanisms failed alongside the text: `doctrine.py`'s OMP rewrite of the consumption hint was
a byte-exact string replace whose selftest ran on a fixture, so rewording the body silently
detached it; and the OMP installer's fast path trusted the registry's version record while the
cache it pointed at still held the previous release's content.

## Decision

- **A lawful skip is defined once, in rule 4, with exactly two sources**: a `search_skills` call
  shown in this reply whose hits are not even loosely adaptable, or an enforcer `SKILL-CHECK:` line
  that itself states the turn is non-task, conversational, harness-generated, or a recap of the
  agent's own last message. The line authorizes the ruling it states; a line that says the turn
  may be real work is an order to SEARCH. Every other mention (token line, row 7, library section)
  points at rule 4. "Trivial" is removed from the getaway leg; the doctrine's own cost argument
  (a needless search on a small turn costs seconds) is the reason.
- **The skip criterion after a search is checkable**: the agent must be able to state, for the top
  hit, what it does and why the task lies outside it, with the query shown.
- **Escalation target is `search_skills` with 2–3 intent+domain phrasings** in the doctrine,
  `MANDATE` and the getaway leg; `get_skill` when a hit's fit is unclear. ADR-0015's `find-skills`
  clause is superseded.
- **Rule 5 covers every hit marked external or other-harness**, worded harness-neutrally ("cannot
  be invoked by name here"); the concrete call `get_skill("<name>")` stays because `doctrine.py`
  rewrites it per harness (OMP → `read("skill://<name>")`), and that selftest now adapts the live
  body so the coupling cannot detach silently again.
- **Pruned**: catalogue count → "a shelf of hundreds"; ADR/version labels; EFFORT note (file
  header only); Not/Yes pairs → one worked example with placeholders; CHAIN-HINT row (the per-turn
  line carries the caveat); no-op sentences. Body 8,074 → 4,238 chars.
- **Enforcer strings**: colons unified; `MANDATE` says "No preview this turn"; intent and selfref
  legs carry the harness leg's "if it hands you work, route it" tail; harness leg drops its
  maintainer taxonomy; `CONSULT_MANDATE` drops the ADR label, funnel exposition and operator
  kill-switch footer. Locked signatures untouched; `tests/test_doctrine_text.py` pins their
  absence from the body, the absence of phantom pointers, and the absence of cached counts.
- **Selftest 0041 pins its flags ON locally**, so `--selftest` is hermetic under the ADR-0055 env.
- **OMP installer** compares the cache manifest, not the registry record, before declaring the
  deploy current.

## Consequences

- New **trail-side** epoch (epoch-watch v0.47.1): retrieval, gates, bands and ledger schema are
  unchanged, so v0.47.0's ledger watches continue; USING/SEARCH/false-SKIPPING shares and the
  `authorized_skip` tally re-baseline from this deploy. W7 watches getaway follow-through — the one
  claim the text alone cannot prove.
- Trivial questions that reach a preview or a getaway line now cost a search before the answer.
  That is the library doctrine's own trade (seconds against the top-severity failure) applied
  consistently; if the trail shows it hurting, the fix is the getaway leg's wording, not a new
  skip class.
- The doctrine reads about 1,000 tokens shorter per session on every harness.
- Revert path: `git revert` of the release commit restores body, strings and installer; no config
  or data migration is involved.
