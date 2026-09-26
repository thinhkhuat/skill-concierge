# ADR-0062 — `NO SKILL: <why>` ruling, whole-shelf offers, and a shorter standing order

Status: Accepted (2026-09-26)
Supersedes: the standing-order text of ADR-0056 (rules 1, 4, 6, the library and persistence sections)
and the `SKIPPING: none` token everywhere agents are told it. Keeps: ADR-0022's red-flags table
(now four rows), ADR-0058's off-list route and re-rule duty, ADR-0015/0054/0061's `SKILL-CHECK:` legs
and their locked signature phrases.
Evidence: `plans/260926-1514-standing-order-rewrite/` (draft revisions, notes, label patch, gates);
reviews `plans/reports/validator-260926-1515-concierge-advice.md`,
`plans/reports/overeng-audit-260926-1515-concierge-advice.md`,
`plans/reports/validator-260926-1520-standing-order-draft.md`.

## Context

The owner asked whether the concierge is "friction, a burden bolted on" and whether the session-start
standing order should shrink. Three facts came out of the measurement and three independent reviews:

1. On an English turn since v0.51.0 the offer is a ranking of the whole invocable catalogue (ADR-0061),
   but the offer and the standing order both told the agent it held "the top few of a shelf of hundreds,
   not the shelf" — the agent was misinformed about what it held.
2. The skip token `SKIPPING: none` read as "skipping nothing" and carried no reason (owner, 15:18).
3. The standing order was 853 injected words (~1.3k tokens, once per session and after each compact);
   parts restated each other (library doctrine vs rule 4; red-flag rows vs rules 3/4).

A proposed third lawful skip source ("rule directly on a whole-shelf ranking, no search") was withdrawn:
its evidence was confounded (17 of the 18 "needless" searches followed an embedding menu that lacked
the skill) and it would be the new skip class ADR-0056 rules out.

## Decision

1. **The skip ruling is `NO SKILL: <why>`** — the action and its reason on line 1:
   `NO SKILL: hook-cleared — <reason>` or the search and its top hit. Owner's choice (AskUserQuestion,
   2026-09-26 15:20) over `SKIPPING SKILLS:` and `SKILL: none`. Every enforcer string that names the
   token says it; the locked `SKILL-CHECK:` signature phrases are byte-identical.
2. **Two offer kinds, taught once and labelled every turn.** Rule 1 defines a *whole-shelf ranking*
   (every skill you can use judged for this turn) and a *preview* (the top few of a far larger shelf);
   the router's offer is headed "Whole-shelf ranking for this task (every skill you can use judged):"
   and, when none fits, asks for a search with terms the ranking may have missed; embedding, fallback
   and non-English offers keep "Preview … not the shelf". The router is not named in agent-facing text:
   the name carries no meaning for a model and the label stays true if the router changes (owner,
   15:23). Per-turn facts live on the turn's own output, not in the session-wide order.
3. **The standing order drops to 614 words (−28 %).** Library doctrine → one clause of rule 4;
   persistence → one line ("unsure → it binds"); the red-flags table stays a table (ADR-0022) with four
   rows — the live excuses "mechanical", "trivial", "I can handle it unaided" and "I'm confident none
   fit" stay named; the recap case lives in rule 4. Kept: the line-1 ruling, SEARCH as a promise of a
   real call, take-bar = skip-bar, the off-list route, the visible re-rule, the `SKILL-CHECK:` source
   ("authorizes only the ruling it states"), `disabled_in`, the same take-bar for non-listed hits.
4. **Readers accept both forms and trust only the enforcer's own output.** The usage audit and the
   label extractor read `NO SKILL:` (any case, colon required — prose opening "No skill…" is not a
   ruling), the old `SKIPPING` (months of transcripts), and rulings wrapped in markdown. Both count a
   `SKILL-CHECK:` authorization only through one shared check, `_enforcer_output`: a UserPromptSubmit
   `hook_additional_context` attachment whose text starts with the enforcer's own head (`SKILL-FIRST`,
   `SKILL-CHECK:`, `CONSULT-ROUTE`). The agent's text, tool results, file echoes, memory and
   instructions attachments, other hooks and the session-start standing order can all quote the line;
   none counts, so the `NO SKILL: hook-cleared` wording cannot be self-authorized by copying a hook
   line. (A first cut trusted any hook attachment or `isMeta` record; review measured 142 real records
   of other kinds that carried the line, several reachable by the agent — reading or editing a file.)
   Re-measured 2026-09-26 19:05 against the 0.51.1 reader: the last 7 days are unchanged (130 skip
   turns, 11 false, 107 authorized); since 2026-07-04 hook-authorized goes 270 → 265, while 25 more
   markdown-wrapped or lower-case rulings are read.

## Consequences

- A new trail epoch: ruling shares (USING / SEARCH / skip) before and after v0.52.0 are not pooled.
- Proof is measured only on turns where the enforcer ran (a per-turn offer, a consult route or a
  `SKILL-CHECK:` line was injected): 7 of the 11 recent false skips were replies to Stop-hook
  feedback, where the enforcer never runs — 6 of them in one session — so an all-turns before/after
  would track Stop-hook frequency, not this change. The baseline is thin (4/123, 4 events).
- "Every skill you can use judged" is the label's exact claim: the router's catalogue is every
  installed skill this session can invoke, minus keep-off and blocklisted ones (`_jev_catalog`).
- Rule 4 names the router's own skip ground ("no installed skill does what it asks") beside the other
  `SKILL-CHECK:` grounds, so a literal reader neither discounts that authorization nor learns the list
  is open-ended.
- Revert: one `git revert` of the release commit restores the ADR-0056 text, the old token and the
  single offer label; the parsers keep reading both forms either way.
