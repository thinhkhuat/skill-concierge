# ADR-0082: a whole-shelf ranking is a lawful skip source when the agent rules out its top row

- **Status:** Accepted (2026-10-07, shipped in 0.60.0 on the owner's order: "ship it now, with what
  we've got. then we'd work on the audit and assessment after." A second round of forked review of the
  revised draft was waived by that order and runs after release.)
- **Reopens:** ADR-0062's withdrawn third skip source, and ADR-0056's "not a new skip class", on new
  evidence (below). **Amends:** doctrine rules 1 and 4 and red-flag row 1 (ADR-0062, ADR-0056); the
  whole-shelf offer's closing line (ADR-0062 decision 2). **Keeps:** the preview's forced search, the
  `SKILL-CHECK:` legs and their locked signatures, the post-search skip bar (rule 3).

## Context

The owner asked (2026-10-07) why conversational turns and one-line edits were forced through a
`search_skills` call after the router had already ranked the whole shelf. Restated decision under
review: on 2026-09-26 ADR-0062 withdrew "rule directly on a whole-shelf ranking, no search" because
17 of the 18 needless searches it counted followed an embedding preview, not a whole-shelf ranking,
and because ADR-0056 traded a few seconds of search for protection against skipping a needed skill,
adding that "if the trail shows it hurting, the fix is the getaway leg's wording, not a new skip
class".

New evidence, unconfounded: `plans/reports/analysis-261007-2024-forced-search-value-after-whole-shelf.md`
(lever `plans/261007-2024-search-value-after-whole-shelf/search_value.py`, transcript store, epoch from
the 0.52.3 doctrine commit; independently validated, `plans/reports/validator-261007-2024-forced-search-value.md`).
On 305 organic work turns that received a whole-shelf ranking:

- Agents searched on 22. In none did the search return a skill, absent from the ranking, that the
  agent then used (0 of 22; the 95 % upper bound is about 13 %, and the searched turns chose
  themselves). Across all sessions, including skill-concierge's own, that happened on 3 of 46
  searched turns, all in skill-concierge sessions.
- Agents already skipped without a search on 36 turns (11.8 %), mostly status and chat.
- 65 % of search hits were external-catalogue rows (epochs pooled).

The protection the forced search was meant to buy did not show up in the trail; its cost did. The
sample is thin, so W40 watches the change live instead of treating this as proof.

## Decision

1. **Third skip source.** Under a whole-shelf ranking whose rows do not fit even loosely adapted (the
   rule-3 take-bar, now stated on this path too), `NO SKILL: whole-shelf — <top row>: <what it does>;
   <why this task lies outside it and the rows below>` is a lawful skip. The reason covers the rows
   below because agents take a row-2..5 skill on 60 of the 160 offer-taken whole-shelf turns (fork B
   review, `plans/reports/fork-b-261007-2058-adr-0082-mechanism-review.md`). The ruling names the
   ranking's first row, which keeps it checkable: the same bar rule 3 sets after a search (name the top hit, what it does,
   why the task lies outside it). Owner's choice of form (AskUserQuestion 2026-10-07: "The top-ranked
   skill" over "Any listed skill").
2. **The search stays available, not forced.** The doctrine and the offer line both tell the agent to
   search with terms the ranking may have missed when it expects a skill the ranking did not show.
3. **Previews keep the forced search.** The embedding path's "Preview" offer is a few rows of a far
   larger shelf; nothing in this evidence covers it.
4. **The audit counts the new source separately.** `audit_skill_usage.py` tallies `shelf_skip` only
   when the latest enforcer output that turn (`_enforcer_output`) carried the "Whole-shelf ranking"
   head and the ruling's one named skill, the name right after `whole-shelf —`, is that ranking's first
   row (with or without its plugin prefix), followed by a reason. A copied ranking in the agent's text,
   another row's name (also one that contains the top row's, `ak-git` for `git`), the top row named
   only inside the reason, a name with no reason, or a preview that arrives later in the turn stays
   false. `_skip_verdicts` returns four counts; the false-skip report names the three sources.

## Alternatives rejected

- **Fix the getaway wording (ADR-0056's suggested route) or raise the fit floor.** The getaway wording
  never reaches a whole-shelf turn: there the router's top 5 replace the embedding menu and the
  getaway and actionability gates (`AGENTS.md:70`, ADR-0061). The router's fit score measures topical
  match, not need: the session's own conversational turns scored 0.48-0.82,
  and on the calibration corpus a 0.50 floor loses 10.2 % of real skill turns
  (`plans/reports/diagnosis-261007-1752-hoivu-default-vi-routing-misfires.md`). No wording or floor on
  the hook side separates them.
- **A Jev "work or conversation?" gate.** Replayed on 628 turns: safe only at about 0.3 % of traffic,
  and it adds nothing on top of the fit floor
  (`plans/reports/analysis-261007-1814-jev-turn-type-gate-and-reputation-tiers.md`).
- **Any row, not the top row.** Owner chose the top row: one name the audit can check.

The ranking can be wrong (the HOIVU turn's top row was a terminal-UI skill for a web page edit). That
is the case this source fits best: the agent rules the wrong row out in one line, with its reason on
record.

## Consequences

- Turns like the 2026-10-07 HOIVU one-liner and design discussions end with one ruling line instead
  of a search round. The 36 search-free skips seen on whole-shelf turns become lawful when they name
  the top row; those that do not stay false in the audit.
- Risk: a skill the ranking missed goes unused. Measured at 0 of 22 organic searched turns and 3 of 46
  overall; epoch-watch W40 watches it on live traffic.
- Doctrine body grows by 708 characters, 4,135 to 4,843, mostly the second worked example (cap pinned in `tests/test_doctrine_text.py`).
- New trail-side epoch at go-live: false-skip and shelf-skip shares re-baseline from the release.
- **Price shift.** The rule makes skipping cheaper on every whole-shelf turn, including the 160 of 305
  (52.5 %) where agents now take a skill from the offer; how many would drop to the one-line skip is
  invisible in the pre-change trail. W40 carries a baseline and trigger for it.
- **The search was measured degraded.** 65 % of hits were external-catalogue rows and the index
  reported itself stale, so part of the 0 of 22 measures a weak search, not the value of searching.
  Open item: search-hit quality; W40's offline search replay runs only after a reindex.
- Reach: since 2026-09-26 the ledger shows whole-shelf rankings on Claude Code (519) and OMP (44), 1 on
  Codex, none on Command Code or DSH (their 1.6 s Jev budget keeps the preview and its forced search).
- Known gaps: the ruling addresses row 1 only, so on multi-intent offers (default ON outside this
  machine's Claude Code) the leads of other intents are never ruled out by name; the annex rows
  (external, other-harness) are not addressed either. The label extractor still names a search-free
  skip `false_skip_no_search` (`scripts/extract_turn_labels.py:340`, label UNLABELLABLE); renaming it
  would relabel the private calibration corpus, so it stays. W40 reads Claude Code transcripts only.
- Revert path: `git revert` of the release commit restores the doctrine, the offer line and the audit;
  no config or data migration.

## Reviews

- Analysis validation: `plans/reports/validator-261007-2024-forced-search-value.md` (numbers reproduce;
  corrections applied).
- Draft review: `plans/reports/validator-261007-2045-adr-0082-draft-review.md` (audit matcher, private data,
  later-preview rule, doctrine table; all applied).
- Two forked reviews with the full session context: evidence,
  `plans/reports/fork-a-261007-2058-adr-0082-evidence-review.md` (ship with changes: price-shift watch,
  `AGENTS.md:70`, search quality; applied); behaviour,
  `plans/reports/fork-b-261007-2058-adr-0082-mechanism-review.md` (ship with changes: loose-fit bar and
  rows-below reason; applied).
