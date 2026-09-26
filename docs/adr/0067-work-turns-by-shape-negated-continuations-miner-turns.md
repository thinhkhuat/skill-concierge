# ADR-0067 — Work turns by prompt shape; negated continuations; the miner ends a turn at a new stimulus

Status: Accepted (2026-09-26)
Amends: ADR-0066 decisions 1, 2 and 4 (the work-turn test, continuation parsing, the prompt-intent
miner). ADR-0066 is accepted and left as written.
Evidence: `plans/reports/code-reviewer-260926-2155-v0524-diff.md` (review of 0.52.4: 3 Medium, 5 Low);
store census and old-vs-new runs of 2026-09-26 22:37.

## Context

The 0.52.4 work-turn test dropped every prompt opening `<` or `[`. The store holds 461 slash commands
with arguments (`/vn-canu-reporting …`, `/ak:cook …` — the only copy of the request), 43 chat messages
relayed from Telegram (`[TG DM] …`), 9 `<pasted_content>` prompts and 11 pasted HTML comments, all real
work. It also counted 123 plain `/compact` records as work. Typed prompts stored as a list of text and
image blocks (about 210) never opened a turn at all.

The widened continuation reader read any parenthetical that mentions "continu…", including a negation —
"(new task, not continuing x)" is exactly what an agent obeying the red-flags row writes. Requiring the
colon also lost the bare `USING <name> (continuing)` form that `_USING` still reads.

The prompt-intent miner skipped cross-session messages, scheduled tasks and notifications without ending
the turn, so the tool calls they triggered labelled the typed prompt before them.

## Decision

1. **A work turn is decided by the prompt's shape.** Work: typed text, a relayed chat message, pasted
   content (`<pasted_content>`, a pasted `<!-- … -->`), a slash command with arguments, and a typed prompt
   stored as a list of text and image blocks. Not work: `isMeta` and compaction records, every other
   `<tag>` record (notifications, local-command output, `!` shell echoes, teammate messages), a slash
   command without arguments or a session builtin (`/compact`, `/plugin`, `/model`, `/theme`, `/add-dir`,
   `/effort`, `/cd`, `/export`, `/clear`, `/config`, `/fast`, `/reload-plugins`, `/resume`), the
   bracketed notices of the enforcer's harness lane plus `[Scheduled Task`, a cross-session message, a
   plain `/compact`, and a list-form record opening `<` or `[`. The dead "Stop hook" and "This session is
   being continued" heads are gone (those records are `isMeta` / `isCompactSummary`).
2. **A list-form typed prompt opens a verdict turn** too; every string-content user record still does,
   so the verdict segmentation stays comparable.
3. **Duplicates.** A record line the store wrote twice in one file is read once, for every count (0.52.4
   deduplicated continuation units only). A resumed session's file repeats the records it continues from;
   for a continuation unit, the copy in the session's own file wins, whichever file is read first.
4. **Continuations.** A parenthetical with `not`, `no`, `never`, `new task` or `new work` before the
   continuation word is a fresh ruling. The bare form reads in capitals only (`USING x (continuing)`;
   "Using rg (continuing …)" is prose). After a comma, a part names a skill only when it is one name after
   filler ("then ak-git"), so "then run the tests" is not read.
5. **The prompt-intent miner** ends the current turn, unlabelled, at a stimulus that hands the agent work
   without being a typed prompt: a cross-session or teammate message, an idle notice, a system or task
   notification, a scheduled task, a slash command. A compaction summary does not end it — an
   auto-compaction lands inside the prompt's own work.

## Consequences

- Measured 2026-09-26 22:37, 0.52.4 reader vs 0.52.5 reader, same minute. Since 2026-09-19: identical.
  Since 2026-07-04: skip-ruling turns 954 → 967 (+17 from list-form prompts opening turns, −4 from
  duplicated lines), false 602 → 612, search-backed 74 → 76, hook-authorized 278 → 279; enforcer-run
  310/659 → 318/670; USING declarations 1,937 → 1,929, skip rulings 1,010 → 1,004, `/slash` 540 → 538
  (duplicated lines). Continuations 98, re-read 8 → 7, no earlier use 11 → 10, stale 1 (organic 74:
  3/9/1 → 2/8/1); four units' gaps moved because a list-form prompt now opens a turn. The resumed-session
  rule changes no unit in either window today.
- Prompt-intent labels (read-only `mine()`, not a rebuild): 3,848 → 3,758 rows; 138 actionable rows drop
  out (their turn ended before a clear signal), 48 conversational rows appear, and 35 prompts flip
  actionable → conversational — 34 of them had no tool call of their own and three or more after a
  scheduled task (12), a task notification (8), a slash command (9) or a cross-session message (5). The live `prompt_intent` collection is not rebuilt by this release; a
  rebuild changes the enforcer's actionability gate and is its own epoch.
- Left as they are: one fresh `USING: session-handoff (… for seamless continuation)` still reads as a
  continuation (2026-07-02, outside both windows; not a negation); "then search" after a comma still reads
  `search`, a real skill name here; 49 automated "Meanwhile, Heartbeat…" prompts from one project count as
  work (a project's own text, not a harness shape).
- No standing-order change, so no new trail epoch for the rulings. The verdict and continuation counts
  across the 0.52.4 → 0.52.5 readers are not comparable for windows that hold list-form prompts or
  duplicated lines.
- Revert: `git revert` of the release commit.
