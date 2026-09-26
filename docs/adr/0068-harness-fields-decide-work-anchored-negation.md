# ADR-0068 — The harness's own fields decide work; the continuation negation is anchored to the word

Status: Accepted (2026-09-26)
Amends: ADR-0067 decisions 1, 3, 4 and 5 (work turns, file order, negated continuations, the
prompt-intent miner). Corrects ADR-0067's Consequences, which is accepted and left as written.
Evidence: `plans/reports/code-reviewer-260926-2245-v0525-diff.md` (review of 0.52.5: 3 Medium, 5 Low);
store census and runs of the 0.52.4, 0.52.5 and 0.52.6 readers, launched together at 2026-09-26 23:28:54.

## Context

ADR-0067 let a typed prompt stored as a list of text blocks open a turn and count as work. The rule
also let in a team runner's inbox relays and scaffolding (`## New Messages …`, `## Team Governance`,
`## Turn Context`, `Team: "…"`), 66 records with no origin fields of their own. Of the 29 skip turns a
list-form record opened since 2026-07-04, 24 were team records, 4 were SDK prompts and 1 was typed by a
person. So the false-skip rise ADR-0067 credited to typed prompts came from team relays. The harness
already marks most records itself: `origin.kind` (`human`, `task-notification`, `auto-continuation`),
`promptSource` (`typed`, `queued`, `suggestion_accepted`, `system`, `sdk`) and `entrypoint`. Of the
SDK prompts, 1,083 come from programs (`sdk-ts`, `sdk-cli`: conversation-summary templates, "reply OK"
probes, eval prompts) and 19 from people (Claude Desktop, VS Code). 31 plain-text notices ("N background
agents were stopped") carry `origin.kind` task-notification but no `<task-notification>` tag.

The negation guard rejected a note carrying any "no", "not" or "never" before the continuation word.
That lost continuations that justify themselves in the doctrine's own words ("same task, no new search —
continuing"), and it missed "instead of / rather than / without continuing".

## Decision

1. **The harness's fields decide first.** An `origin.kind` other than `human`, a `system` prompt, or an
   SDK prompt from a program (entrypoint `sdk-…`) is not work and, in list form, opens no turn. A
   typed prompt (`origin.kind` human, or a typed/queued/accepted-suggestion source) passes the list-form
   guard, so "[Image #1] what is this" reads; its text still goes through ADR-0067's head rules. The
   four team-runner heads are not work. An empty prompt is not work.
2. **Verdict turns.** A string-content user record still opens a turn (unchanged since before 0.52.5);
   a list-form record opens one only when it hands over work. Team relays in list form no longer open
   turns.
3. **Negation anchored to the word.** A continuation note is a fresh ruling when the continuation word
   itself is negated (`not/no/never [a] continu…`, `…n't continu…`, `instead of / rather than / without
   continu…`) or when it names a new task or new work that is not itself negated ("not a new task —
   continuing" still reads). After a comma, a part also names a skill when it opens with a hyphenated or
   namespaced name ("+ ak-git for the commit").
4. **Fixed file order.** The audit reads transcript files in sorted order. A resumed session usually
   rewrites the copied records' session id (8,788 of 8,958 cross-file copies), so both copies claim
   their own session and the order decides; ADR-0067's "whichever file is read first" held only for the
   copies that keep the original id, where the session's own file still wins.
5. **The prompt-intent miner** applies the same field rules: it skips records with a non-human origin, a
   system prompt, a program's SDK prompt and the team heads, and a plain-text notification or a team relay
   ends the current turn. Its selftest runs the turn-end sequence once per stimulus head, from a literal
   list.

## Consequences

- Audit, same minute (0.52.4 / 0.52.5 / 0.52.6 readers). Since 2026-07-04: skip-ruling turns
  970 / 983 / 967; false 604 / 614 / 601; search-backed 74 / 76 / 74; hook-authorized 292 / 293 / 292;
  enforcer-run turns 310 of 673 / 318 of 684 / 308 of 671. Continuations 99 in all three; 0.52.5 and
  0.52.6 both read re-read 8, no earlier use 10, stale 1 (0.52.4: 9 / 11 / 1); organic 74, 2 / 8 / 1.
  The continuation listings of 0.52.5 and 0.52.6 are identical in both windows. Since 2026-09-19 the
  headline is identical in all three readers.
- Prompt-intent labels (read-only `mine()`): 3,763 → 3,506 rows (−257: 164 conversational, 93 actionable;
  no new row). The skipped prompts are 229 programmatic SDK prompts (152 `sdk-ts`, 77 `sdk-cli`), 66 team
  relays, 31 plain-text notices and 1 auto-continuation. Balanced, the corpus is now 440 + 440 (0.52.5:
  604 + 604). The live `prompt_intent` collection is still not rebuilt (owner: held until after the
  Track B switch-over).
- **Corrections to ADR-0067's Consequences:**
  - Its "+17 from list-form prompts" were list-form records, but not typed prompts: the reviewer measured
    13 of the 17 turns, and all of the false-skip rise (602 → 612), as team relays. On this minute's run
    the 0.52.6 reader, which also drops SDK and notification records, gives 983 → 967 turns and 614 → 601
    false against 0.52.5.
  - Of the "four units' gaps moved because a list-form prompt now opens a turn", only one (`1505d811`) moved for that reason. The other three moved
    because a bracketed typed prompt, a `<pasted_content>` prompt and a plain `/compact` changed class
    (each verified by switching its rule off).
  - "Since 2026-09-19: identical" held for the headline; one listed unit (`07a53743`) moved from gap 0 to 1.
  - Its "138 actionable rows drop out, 48 conversational rows appear" were net label changes that already
    held the flips, and its "35 prompts flip" came from a text-keyed comparison that does not reproduce;
    the reviewer found 43 flips by transcript position (31 distinct texts), all of prompts with no tool
    call of their own.
- Left as they are: a list-form record carrying the literal text `"tool_result"` is dropped by the raw
  pre-filter unless another marker is on the line (not measured); "then search" after a comma still reads
  `search`, a real skill name here.
- No standing-order change, so no new trail epoch.
- Revert: `git revert` of the release commit.
