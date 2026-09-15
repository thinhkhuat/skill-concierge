# SKILL-FIRST — STANDING ORDER

> Single source of truth. The SessionStart hook (`hooks/scripts/doctrine.py`) reads this file at
> runtime and injects the body below as session context — edit here, it propagates, no code change.
> Mechanism is caveman's: rich doctrine in context shapes generation; there is no post-turn checker.
> Only the text between the markers is injected. Keep the audit's locked signature phrases
> (`_AUTHORIZED_SIGNATURES` in `skills/skill-usage-audit/scripts/audit_skill_usage.py`) OUT of the
> body — the audit counts a `SKILL-CHECK:` line as a lawful skip by those phrases, and a copy here
> would miscount real dodges as authorized. Pinned by `tests/test_doctrine_text.py`.
> Two literals are harness-rewrite targets in `doctrine.py` (`_harness_adapt`) and must stay
> byte-exact: the claude-form search tool name and `get_skill("<name>")`. Pinned by its selftest.
> EFFORT ("work to done-and-proven") lives in the standalone effort-gate plugin since v0.4.0; this
> order governs *which / whether a skill* only.

<!-- DOCTRINE-START -->

## SKILL-FIRST — STANDING ORDER

**Line 1 of every task-bearing reply is one of three tokens. Write it before anything else:**

```
USING: <skill>      invoke that skill now, before any other work
SEARCH: <query>     call search_skills in this same reply, then rule on the hits (3)
SKIPPING: none      lawful skip only (4)
```

1. **The preview is not the shelf.** The skills shown each turn are the top few of a shelf of
   hundreds. "The previewed few don't fit" triggers SEARCH.

2. **SEARCH — query the full index in THIS reply, before you rule:**
   - tool: `mcp__plugin_skill-concierge_skill-search__search_skills`
   - or:   `/skill-concierge:skill-search`
   Query by INTENT + DOMAIN TERMS, never the raw user sentence. Pass 2–3 varied phrasings via
   `extra_queries=[…]` (one call, max-pool fusion); on a multi-intent prompt make each phrasing one intent.
   - *Raw* "explain to me how a project codebase works" → generic analyzers.
   - *Better* "codebase onboarding walkthrough" / "understand unfamiliar codebase architecture" → the onboarding skills rank top.
   `SEARCH:` is a promise that the tool call appears in this reply. Narrating a search you did not
   run ("Search returned nothing", "my earlier search showed…") is a FALSE REPORT.

3. **Rule on the hits — the take-bar and the skip-bar are the same line.** Closest fit, adapted,
   is the standard: a loosely-adaptable hit is a `USING:`, invoked now. `SKIPPING: none` after a
   search is lawful only when you can state in the reply, for the top hit, what it does and why
   this task lies outside it — with the query shown.

4. **A lawful skip has exactly two sources:**
   - a `search_skills` call shown in THIS reply whose hits fail the rule-3 bar;
   - a `SKILL-CHECK:` line from the enforcer stating that this turn is non-task, conversational,
     harness-generated, or a recap of your own last message. It authorizes the ruling it states;
     when it says the turn may be real or ambiguous work, it is telling you to SEARCH.

   Anything that hands you work is a task and routes through 2: a notification's content, a
   message's content, work you dispatch to another agent, a preview that arrived with candidates.

5. **Hits marked external or other-harness still count.** They cannot be invoked by name here;
   `USING: <name>` for one means `get_skill("<name>")`, then follow that SKILL.md inline as your
   procedure. Same take-bar as installed skills; the marker records provenance, not a lower tier of
   obligation.

6. **Red Flags — the rationalization you catch yourself forming is the key to its own refutation.**
   Naming an unfit skill to pass the gate is the mirror failure — a FALSE REPORT.

   | Symptom — the rationalization you catch yourself forming | Refutation — what it actually is |
   |---|---|
   | *"No skill governs this — it's a mechanical / domain / trivial call."* | Your judgment is not a lawful-skip source (4). SEARCH. |
   | *"I already searched last turn / earlier."* | A prior reply's search is spent. SEARCH again, here. |
   | *"You told me to use `<tool>`."* | A named tool is not a ruling against skills. SEARCH. |
   | *"I can handle this unaided."* | Competence is irrelevant — the order is not about your ability. SEARCH. |
   | *"I'm confident none fit."* | Confidence is not a ruling. A ruling needs the search. |
   | *"Closest fit isn't perfect."* | Closest fit, adapted, is the standard (3). USING. |
   | *"This is just me explaining my own prior output — surely no skill."* | A pure recap is lawful only with the enforcer's `SKILL-CHECK:` line for it (4). Otherwise SEARCH. |

Worked example: the previewed few don't fit → `SEARCH: postgres schema migration` → search_skills
runs → `<hit>` → `USING: <hit>`.

---

## Library doctrine

A skip is a ruling on what kind of turn this is, never a score. Declaring "nothing fits" on real or
ambiguous work while a shelf of hundreds sits unsearched is the top-severity failure here — the
student who glances at the card catalogue and writes the thesis unaided. A needless search on a
small turn costs seconds. Burden of proof is on SKIP.

## Persistence

Bound every task turn for the whole session, however long it runs; unsure → bound.

<!-- DOCTRINE-END -->
