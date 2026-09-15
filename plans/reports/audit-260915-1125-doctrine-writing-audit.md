# Audit — SKILL-FIRST doctrine + enforcer strings under the writing-for-agents levers

Date: 2026-09-15 · Skill used: `writing-for-agents` (levers: context pointers, two loads, information hierarchy, completion criteria, leading words, negation, pruning) · Scope: `hooks/doctrine/skill-first.md` injected body (every line) and every agent-facing string in `hooks/scripts/enforcer.py` (MANDATE, ranked-mandate render, four `SKILL-CHECK:` legs, CONSULT_MANDATE, CHAIN-HINT, ROUTE, annex/foreign blocks). Shipped as v0.47.1 / ADR-0056. Independent review (two passes, fresh agent): `review-260915-doctrine-writing-for-agents.md`.

Line numbers in the first table are the pre-rewrite file (`git show 3ac8ca9:hooks/doctrine/skill-first.md`).

## Doctrine body — author's pass, by line

| Lines | Lever | Defect | Action |
|---|---|---|---|
| 11 | no-op | "its force is structure, not volume" describes the document to itself | cut |
| 18, 21–22 | negation / no-op | token block + "stops you drifting into improvising and then back-rationalizing the skip" | cut (reviewer: rationale, not behaviour) |
| 24–26 | cache vs environment | "~500 skills" — live index 2,714 points, ~720 installed | "a shelf of hundreds" |
| 29, 38, 17 | duplication | "in THIS reply, before you rule" ×3 | once, in rule 2 |
| 30 vs 40–41 | duplication | `extra_queries` explained twice | one sentence |
| 36 | pointer | `codebase-onboarding` named as if a skill; none installed | generic example |
| 38–39 | negation (hard guardrail) | FALSE REPORT clause needed | kept, paired with the positive promise |
| 49 | relevance | "— ADR-0054" label in agent-facing text | cut |
| 55–57 | duplication | rule 4 previews the Red Flags table | cut |
| 59–60, 87–88 | duplication / negation | "USING never takes none" ×3 + Not/Yes pairs spelling banned outputs | rule 5 → the obligation only; pairs → one worked example |
| 62–66 | branch completeness | only `[external: <alias>]` covered; enforcer also renders an other-harness block | "hits marked external or other-harness" |
| 68 | stale | row grouping for a 7-row table that had 8 rows | cut |
| 79 | duplication | row 8 restates the CHAIN-HINT line's own caveat | cut |
| 90–91 | relevance | EFFORT / v0.4.0 history note injected every session | file header, outside the markers |
| 100–113 | pointer | `find-skills` — no such installed skill | term-rich `search_skills` re-query |
| 105–108 | **contradiction (HIGH)** | "positively-reasoned trivial/unambiguous earns a no-search skip" vs rule 4 "ONE class — no task" | see reviewer F2 below: one definition, two sources |
| 119–121 | negation / duplication | four "No …" clauses restating rules 2–4 | one line |

## Independent review — findings and disposition

| # | Sev | Finding (reviewer) | Disposition |
|---|---|---|---|
| F1 | HIGH | Rule 5's reworded `get_skill("<name>")` detached `doctrine.py`'s OMP rewrite (`get_skill("<alias>:<skill>")` → `read("skill://…")`); the selftest ran on a fixture and kept passing | FIXED — rewrite re-targeted; selftest now adapts the live body and asserts the claude-form tool + hint are present |
| F2 | HIGH | Lawful-skip set stated in five places with three contents; getaway leg admits "trivial", which rule 4 and row 1 refute | FIXED — rule 4 = two sources (reviewer's wording); token line, row 7, library, persistence point at it; "trivial" removed from the getaway leg |
| F3 | MED | Two token spellings (`USING <skill>` per turn vs `USING: <skill>` in body) | FIXED — colons in MANDATE + ranked header |
| F4 | MED | "Skill tool" is a Claude Code name in a five-harness body and in annex/foreign blocks | FIXED — "cannot be invoked by name here" / "consume via get_skill" |
| F5 | MED | "route it through 2" ×4 in rule 4 | FIXED — one sentence |
| F6 | MED | Not/Yes pairs restate rules 3–5 and spell the banned outputs | FIXED — one worked example |
| F7 | MED | Library + Persistence mostly restatement | FIXED — reviewer's compact wording |
| F8 | MED | Rule 5 ¶2 duplicates the per-turn annex/foreign footer | PARTIAL — shortened to the obligation + the call; the call stays because the OMP rewrite targets it (F1) |
| F9 | MED | Steps and reference interleaved; skip criterion fuzzy | FIXED (criterion: "state, for the top hit, what it does and why this task lies outside it"); structure kept as one numbered list, ordered steps-first, since the per-turn strings point at rule numbers |
| F10 | LOW | Row 8 duplicates the CHAIN-HINT caveat | FIXED — deleted |
| F11 | LOW | Example skill names don't resolve | FIXED — `<hit>` placeholders |
| F12 | LOW | `[external: <alias>]` spelling ≠ rendered `[external:alias]` | FIXED — described generically |
| F13 | LOW | Harness leg taxonomy is maintainer-facing; CONSULT footer is operator-facing | FIXED — both removed (selftest inverted for the footer) |
| — | — | No-ops: "Obey on every task turn", "Match the symptom…", "Execute.", token rationale, retrieval "why" | FIXED — deleted |

Second-pass verdict: see the review file's "Second pass" section.

## Enforcer strings — final state

| String | Change |
|---|---|
| `MANDATE` (refusal guard + retrieval fallback) | "No preview this turn"; term-rich search order; SKIPPING only after that search finds nothing adaptable; colons |
| ranked-mandate header/footer | colons; "the top few of a shelf of hundreds" |
| `GETAWAY_SKIP_MSG` | "non-task or conversational" (no "trivial"); `search_skills` re-query with 2–3 intent+domain phrasings; `get_skill` when a hit's fit is unclear; signature unchanged |
| `INTENT_SKIP_MSG`, `SELFREF_SKIP_MSG` | + "if the turn hands you work, route it (SEARCH/USING)"; signatures unchanged |
| `HARNESS_SKIP_MSG` | taxonomy parenthetical dropped; signature unchanged |
| annex / foreign blocks | "NOT installed here — consume via get_skill" |
| `CONSULT_MANDATE` | ADR label, funnel exposition and operator footer dropped |
| CHAIN-HINT, ROUTE, note | unchanged |

## Verification

- `enforcer.py --selftest` OK under `ENFORCER_MULTI_INTENT=0`, `=1` and `ENFORCER_CHAIN_PROJECTION=0` (case 0041 now pins its flags ON locally — it failed on HEAD under the ADR-0055 env before this fix).
- `doctrine.py --selftest` OK on the live body for OMP / Command Code / Codex / DSH / Cline branches; per-harness render check: only OMP carries `skill://`, every other harness keeps `get_skill(`.
- `audit_skill_usage.py --selftest` OK (four signatures). `tests/test_doctrine_text.py` (new, 3 tests) + full suite 24 passed.
- Live probes off the ledger (`SKILL_CONCIERGE_LOG=/tmp/sc_audit/ledger`): intent, harness, selfref legs, consult route, ranked preview, and the 1 ms-embed-timeout fallback each rendered the new text.
- Body: 8,074 → 4,238 chars (≈2,018 → 1,059 tokens per session, every harness).

## Out of scope, flagged for the owner

- **The nine `skills/*/SKILL.md` descriptions** are always-loaded context pointers of 400–700 chars each with long trigger-phrase lists. The writing-for-agents rule ("one trigger per branch, cut identity the body carries") would halve them — but this plugin's own retriever indexes those descriptions plus flywheel utterances, so pruning trades per-turn context load against recall of the concierge's own skills. Owner's call; unchanged.
- The enforcer has no OMP rewrite for the per-turn annex/foreign `get_skill` footer (reviewer side observation). `get_skill` exists as an MCP tool under OMP too (`skill-concierge:skill-search/get_skill`), so the line is usable there; the `skill://` form is OMP's preferred path for ledger capture. Left as is.
- `docs/skill-first-enforcement-mental-model.md` quotes the v0.3.0 doctrine draft ("~500", old numbering). Dated design record (2026-06-27), not evergreen; left as history. ADR-0015 and CHANGELOG 0.12.0 keep "escalate to `find-skills`" as the record; ADR-0015 carries a status note pointing at ADR-0056.

## Unresolved

- None blocking. Epoch-watch W7 measures whether the reworded getaway leg is followed by a search on real work — the only claim the text alone cannot prove.
