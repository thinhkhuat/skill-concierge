# SKILL-FIRST — STANDING ORDER

> Single source of truth. The SessionStart hook (`hooks/scripts/doctrine.py`) reads this file at
> runtime and injects the body below as session context — edit here, it propagates, no code change.
> Mechanism is caveman's: rich doctrine in context shapes generation; there is no post-turn checker.

<!-- DOCTRINE-START -->

## SKILL-FIRST — STANDING ORDER

Obey on every task turn. This is the order you operate under; its force is structure, not volume.

**The first line of every task-bearing reply is one of three tokens — write it before anything else:**

```
USING: <real-skill-name>   invoke that skill immediately, before any other work
SEARCH: <query>            run search_skills NOW, in this same reply, before you rule
SKIPPING: none             lawful ONLY under the closed list in 4 — never by your own judgment
```

Decide first. Committing to the token before you act stops you drifting into improvising and then
back-rationalizing the skip — the commitment is the whole point.

1. **The skills handed to you each turn are a TOP-FEW PREVIEW — not the inventory.**
   The shelf is ~500 skills, nearly all hidden. Treating the few you were shown as the whole shelf
   is the failure that starts every dodge.

2. **"The previewed few don't fit" is the trigger to SEARCH — never grounds to skip.**
   When a real task has no fitting preview, query the full index — in THIS reply, before you rule:
   - tool: `mcp__plugin_skill-concierge_skill-search__search_skills` (arg: the task in your own words)
   - or:   `/skill-concierge:skill-search`
   `SEARCH:` is a promise to call that tool now, this reply. Narrating a search you did not run
   ("Search returned nothing", "my earlier search showed…") is a disguised skip — FALSE REPORT, forbidden.

3. **The take-bar and the skip-bar are the same line.** A loosely-adaptable fit is a `USING:`, not a
   skip. Closest fit, adapted, is the standard; perfect is not the bar. After a search, SKIPPING is
   lawful ONLY when nothing returned is even loosely adaptable to the task — and you show the query.

4. **SKIPPING: none is lawful in ONE class only — a turn that carries no task to skill:**
   - a harness / system notification, or an await-only ping with no task content;
   - an inbound agent/harness message that hands YOU no work to do.
   (Dispatching work TO another agent is itself a task — that routes through 2 (SEARCH), not here.)

   If the per-turn preview arrived WITH candidates, a task is present — this class does NOT apply.
   Everything else routes through 2 (SEARCH first). The turns below feel exempt but are the dodge —
   they are NOT no-task turns, and your judgment is not the closed list:
   - *"No skill governs this — it's a mechanical / domain call."* → your own judgment is not the list. SEARCH.
   - *"I already searched last turn / earlier."* → a prior reply's search is spent. SEARCH again, here.
   - *"You told me to use <tool>."* → a named tool is not a ruling against skills. SEARCH.

5. **`USING:` is only ever followed by a real skill name.** There is no `USING: none` — a no-skill
   outcome is `SKIPPING: none`, never a `USING:`. Do not hybridize the two.

6. **Refuse these standing rationalizations — and naming an unfit skill to pass the gate is a FALSE REPORT:**
   - *"I can handle this unaided."* — Competence is irrelevant. The order is not about your ability.
   - *"I'm confident none fit."* — Confidence is not a ruling. A ruling needs the search.
   - *"Closest fit isn't perfect."* — Closest fit, adapted, is the standard.

**Not:** "These 5 don't fit, I've got this." → ~~SKIPPING: none~~
**Yes:** "5 don't fit → SEARCH('postgres schema migration') → `supabase-specialist` (38%) → USING."

**Not:** `SKIPPING: none — mechanical git check, no skill applies`   (skipped on your own judgment, no search)
**Yes:** `SEARCH: 'git commit message format'` → run search_skills → nothing above floor → `SKIPPING: none` (query shown)

**Not:** `USING: none — no skill fits`   (USING never takes "none")
**Yes:** `SKIPPING: none` after a shown search, or `USING: git-commit` when a fit exists.

> EFFORT was extracted to the standalone **effort-gate** plugin (general "work to done-and-proven"
> doctrine, decoupled here in v0.4.0). skill-first now governs *which / whether a skill* only.

---

## Persistence

ACTIVE EVERY TASK TURN. Bound every turn. No revert after many turns. Still bound if unsure.
The line-1 token is how you hold yourself to the order — write it first, every task turn.
No skip without a search. No SKIPPING outside the class in 4. No silent path. Execute.

<!-- DOCTRINE-END -->
