# ADR-0083: owner reputation badges on the menu, with a pull-in for ranked skills Jev placed lower

- **Status:** Accepted (2026-10-07, shipped in 0.61.0 on the owner's order "ship it, along with the
  supporting skills to manage, and suggest skills for each tier as well as maintaining the tiers").
  Built on the order "all 3 badges now - #b it is. work on implementation now".
- **Keeps:** Jev's order and its five rows (ADR-0061, ADR-0062), every gate, the doctrine text.
  **Adds:** badges, a legend line, a pull-in block, two ledger fields, the `reputation` skill.

## Context

The owner wants his own judgement of skills to count on the menu, the way a restaurant marks its
best dishes, and to keep that judgement in a list he curates, like keep-on.

Measured before deciding (2026-10-07, cached Jev answers, catalogue `f65af73783c60a68`, 313 real
turns where the agent used a skill; `plans/261007-1813-jev-turn-type-gate-replay/`):

- **Reordering by source loses.** Putting a reputable tier (ak-*, pstack, Matt Pocock) first cut
  "the used skill ranked first" from 100 to 37 and "in the five-row menu" from 177 to 151 (2 gained,
  28 lost). A +0.10 boost lost 9 for 2 gained. The measure rewards past agent choices, so it favours
  today's order; it still rules out a hard reorder.
- **A ranked skill Jev places sixth or lower is invisible.** The used skill sat in Jev's ranks 6-10
  on 13 of the 313 turns. Appending badged rows from ranks 6-10 when Jev's own `fits` clears a bar
  (`pull_in_sim.py`, the three families standing in for the owner's list): bar 0.5 added 0.44 rows a
  turn and caught 0 of the 13; bar 0.3 added 0.76 rows and caught 1. The owner's list will be far
  narrower than three families, so these are upper bounds on noise.
- **🔥 data exists.** The ledger's invocation rows give distinct sessions per skill: in the last 30
  days 169 skills were used across 123 sessions; 28 reached 5 sessions, 11 reached 8.

## Decision

1. **Badges, next to the name, never moving a row.** ❤️ house favourite and ⭐ trusted come from
   `~/.claude/skill-concierge/reputation.json` (`{"heart": [...], "star": [...]}`), exact names or
   `fnmatch` patterns (`pstack:*`). An exact entry beats every pattern; between two matches of one
   kind, ❤️ wins. 🔥 proven = invoked (Skill tool, auto or manual, subagents excluded) in at least 5
   distinct sessions in the last 30 days, written to `proven.json` by `auto_promote.py` at session
   start (throttled, fail-open); a use under a personal skill's frontmatter name (`ak:cook`) counts for
   its directory name (`ak-cook`), the name the menu shows. Badges render on installed and pulled rows only: external-catalogue
   and other-harness rows are not the owner's installed skills, and a pattern such as `*:*` would
   otherwise match `antigravity:` and `vercel:` rows (externals keep their own `used N×` mark).
2. **The choosing rule rides with the badges, not the doctrine.** A one-line legend appears only when
   a ❤️ or ⭐ row is shown: choose in two passes — mark every row that does the task's job as its
   main purpose; among those take ❤️, then ⭐, then the rest, and inside each group prefer 🔥, then the
   higher row (unbadged rows are the last group). When only 🔥 is on the menu, which is common because
   🔥 is automatic, a one-line 🔥 legend replaces it (about a quarter of the length).
   The doctrine's 900-character growth cap (`tests/test_doctrine_text.py`) would not fit the rule, and
   a turn without badges should pay nothing for it.
3. **Pull-in (owner's pick of the wider option, 2026-10-07).** A ❤️ or ⭐ skill in Jev's ranks 6-10
   whose own `fits` is at least 0.5 is shown under the five rows, in an "On the owner's list" block,
   at most two. Jev's five rows never move and their shares are unchanged. Whole-shelf turns only:
   preview turns have no Jev `fits` to judge by.
4. **Ledger.** Offer events gain `badges` (`{name: marks}` for every shown or pulled row) and `pulled`
   (`[[name, probability]]`); the Jev event gains `pulled` names. Additive keys.
5. **Management.** `scripts/reputation.py` (`list`, `add heart|star`, `remove`, `why`, `suggest
   [--apply]`; `suggest` is the owner's maintenance pass, its rules in the script's docstring, and
   `--apply` was the owner's choice over suggestions-only; it never removes a ❤️, because the log
   misses rule-driven use such as intent briefs written under the owner's rules, so a ❤️ with no
   recorded use prints as a review line only; bad input fails closed — no removal from an incomplete
   installed view or for another harness's plugin, no review from a log shorter than 90 days) and the
   `skill-concierge:reputation` skill. Adding a name to one tier moves it out of the other. `why`
   restates the hook's rule; a test holds the two to the same answers.

Switches: `SKILL_REPUTATION=0` turns every badge, the legend, pull-in and the 🔥 digest off.
`SKILL_REPUTATION_PULL_MAX` (2; `0` keeps badges, drops pull-in), `SKILL_REPUTATION_PULL_FIT` (0.5),
`SKILL_REPUTATION_PULL_DEPTH` (10), `SKILL_PROVEN_MIN_SESSIONS` (5), `SKILL_PROVEN_WINDOW_DAYS` (30).
Seams: `SKILL_CONCIERGE_REPUTATION`, `SKILL_CONCIERGE_PROVEN`. Query-time and hook-side, so none is in
`ENGINE_ENV_KEYS`.

## Alternatives rejected

- **Reorder the menu by tier.** Lost on the replay above.
- **Badge as a tie-break only.** The agent cannot measure "fit about equally", and same-job twins
  rarely tie (a 45 % `code-review` against an 11 % `ak-code-review`), so the badge would almost never
  decide; the owner's judgement is quality, which Jev's topical fit cannot see.
- **Narrow pull-in (❤️ only, fit ≥ 0.7, one row).** Recommended on noise grounds; the owner chose
  the wider form. Revert path below.
- **🔥 above the owner's tiers.** Usage feeds on itself (a skill offered gets used, then badged, then
  picked more), so 🔥 only orders rows inside one group.

## Consequences

- A badged row lower on the menu can now win over row 1, by design. The risk moves to the agent's
  first pass: stretching "does this task's job" to admit a badged row. W41 watches it.
- A ranked skill Jev never shortlists stays invisible; that is a findability problem, fixed with a
  curated trigger phrase (`triggers-curated.json`), not a badge.
- 🔥 counts Claude Code, Codex and the other harnesses' ledger rows together, the same ledger the
  external `used N×` mark reads.

## Owner's list as first written (2026-10-07)

The owner ordered: "every plugin:skill should be added to the reputation list, along with ak-*
family, matt-pocock's skills too, and those in the keep-on list". The tier mapping question went
unanswered for 10 minutes, so the recommended default was applied and logged: the 54 keep-on skills
as ❤️ (exact names, so they win over every pattern); `*:*` (every plugin skill, including plugins
installed later), `ak-*` and Matt Pocock's 34 personal skills as ⭐. One command moves any of them.
Consequence: most menu rows carry a badge, and the owner's personal skills outside keep-on (most
`tk-*`, many `vn-*`) are the unbadged group. Pull-in will fire more often than the three-family
simulation; W41's 0.5-rows-per-turn trigger watches it.

## Revert

`SKILL_REPUTATION=0` (everything) or `SKILL_REPUTATION_PULL_MAX=0` (keep badges, drop pull-in), in
`~/.config/harness-env.sh` so every harness sees it; or raise `SKILL_REPUTATION_PULL_FIT` to 0.7 for
the narrow form. An empty `reputation.json` shows only 🔥.
