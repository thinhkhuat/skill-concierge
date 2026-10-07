# SKILL-FIRST — STANDING ORDER

> Single source of truth. The SessionStart hook (`hooks/scripts/doctrine.py`) reads this file at
> runtime and injects the body below as session context — edit here, it propagates, no code change.
> Mechanism is caveman's: rich doctrine in context shapes generation; there is no post-turn checker.
> Only the text between the markers is injected. Keep the audit's locked signature phrases
> (`_AUTHORIZED_SIGNATURES` in `skills/skill-usage-audit/scripts/audit_skill_usage.py`) OUT of the
> body — the audit counts a `SKILL-CHECK:` line as a lawful skip by those phrases, and a copy here
> would miscount real dodges as authorized. Pinned by `tests/test_doctrine_text.py`.
> The claude-form search tool name (and the slash forms) are harness-rewrite targets in
> `doctrine.py` (`_harness_adapt`) and must stay byte-exact. `get_skill("<name>")` is rewritten by
> no harness; it appears exactly once, in rule 5 (the count is pinned by `tests/test_doctrine_text.py`;
> the doctrine selftest checks it is present, in the OMP rendering too).
> EFFORT ("work to done-and-proven") lives in the standalone effort-gate plugin since v0.4.0; this
> order governs *which / whether a skill* only.
> The skip ruling is `NO SKILL: <why>` since v0.52.0 (ADR-0062); it replaced the older `SKIPPING` token.
> The audit and the label extractor read both forms, so older transcripts stay comparable.
> A whole-shelf ranking is the third skip source since ADR-0082: `NO SKILL: whole-shelf —`
> naming the ranking's top row. The audit counts it lawful only when that name matches row 1.

<!-- DOCTRINE-START -->

## SKILL-FIRST — STANDING ORDER

**Line 1 of every task-bearing reply is a ruling. Write it before anything else:**

```
USING: <skill>        invoke that skill now, before any other work
SEARCH: <query>       call search_skills in this same reply, then rule on the hits (3)
NO SKILL: <why>       a lawful skip (4), its reason on the same line
```

1. **Know which offer you hold.** A *whole-shelf ranking* judged every skill you can use for this turn;
   a *preview* is the top few of a far larger shelf. A row that fits, even loosely adapted (3), is a
   `USING:` now. When no row of a whole-shelf ranking fits even loosely, rule out its top row by name
   and the rows below it in the same reason:
   `NO SKILL: whole-shelf — <top row>: <what it does>; <why this task lies outside it and the rows below>` — or rule
   `SEARCH:` with terms the ranking may have missed (a tool, a file type, a domain name) when you
   expect a skill it did not show. When no row of a preview fits, rule `SEARCH:`.

2. **SEARCH in THIS reply, before you rule:**
   - tool: `mcp__plugin_skill-concierge_skill-search__search_skills`
   - or:   `/skill-concierge:skill-search`
   Query by intent and domain terms ("codebase onboarding walkthrough", for "explain how this
   codebase works"), 2–3 phrasings in `extra_queries=[…]`, one per intent. `SEARCH:` promises the
   call is in this reply; narrating a search you did not run is a FALSE REPORT.

3. **Rule on the hits — the take-bar and the skip-bar are the same line.** Closest fit, adapted, is
   the standard: a loosely-adaptable hit is a `USING:`, invoked now. `NO SKILL:` after a search
   states the query and, for the top hit, what it does and why this task lies outside it.

   **Picking outside the hits.** For a skill that is not among this reply's hits or this turn's offer, the route is: line 1 `SEARCH:` → the search → load its body → quote the line that covers this task → `USING: <name>` on its own line.

   **A loaded body that excludes the task** — a hit's or not — is re-ruled in the same reply: a new `USING:` or `SEARCH:` line ending `(re-rule: <old>)`, quoting the excluding line — and tell the user you switched.

   **Continuing a skill.** To keep following a skill you invoked earlier this session when this turn's offer does not list it and the new work is the same task: line 1 `USING: <name> (continuing)`, then re-read its body in this reply with `get_skill` (rule 5) — your harness's skill tool only when that call is unavailable or cannot find the skill — before other work. The re-read stands in for the search; a body that excludes the new work is re-ruled as above.

4. **A lawful skip has exactly three sources**, and `NO SKILL:` names which one: a search shown in this
   reply whose hits fail the rule-3 bar; a whole-shelf ranking whose top row you rule out by name (1);
   or a `SKILL-CHECK:` line from the enforcer saying this turn
   is non-task, conversational, harness-generated, a recap of your last message, or that no
   installed skill does what it asks. That line
   authorizes only the ruling it states (write `NO SKILL: hook-cleared — <its reason>`); when it
   says the turn may be real work, SEARCH. Anything that hands you work is a task — a
   notification's content, a message's content, work you dispatch. Burden of proof is on the skip.

5. **A hit your harness does not list still counts** while it stays switched on for you — a hit
   whose `disabled_in` names your harness, or that your harness has switched off, is off.
   `USING: <name>` then means `get_skill("<name>")` and following that SKILL.md inline. Same
   take-bar as installed skills.

6. **Red flags — a thought that skips without a source (4). Rule instead** (under a whole-shelf
   ranking, ruling out its top row by name (1) also answers each):

   | The thought | The ruling |
   |---|---|
   | "No skill governs this — it's mechanical / trivial / I can handle it unaided / I'm confident none fit." | Your judgment is not a skip source: SEARCH. |
   | "I searched earlier." | That search is spent: SEARCH here. |
   | "I'm still in <skill> — continuing." | Only for the same task; new work: SEARCH (3). |
   | "You told me to use `<tool>`." | A named tool is not a ruling against skills: SEARCH. |
   | "The name matches." | A name is a label: load the body and quote the covering line (3). |

   Naming an unfit skill to pass the gate is the mirror failure — a FALSE REPORT.

Worked examples. Preview, no row fits → `SEARCH: postgres schema migration` → `<hit>` → `USING: <hit>`.
Whole-shelf ranking led by `tui-fundamentals`, task edits a web page's default language →
`NO SKILL: whole-shelf — tui-fundamentals: builds terminal UIs; this task edits one web page setting, and no row below covers that`.

This order binds every task turn for the whole session; unsure → it binds.

<!-- DOCTRINE-END -->
