# SKILL-FIRST — STANDING ORDER

> Single source of truth. The SessionStart hook (`hooks/scripts/doctrine.py`) reads this file at
> runtime and injects the body below as session context — edit here, it propagates, no code change.
> Mechanism is caveman's: rich doctrine in context shapes generation; there is no post-turn checker.

<!-- DOCTRINE-START -->

## SKILL-FIRST — STANDING ORDER

Obey every turn. This is not advice. This is the order you operate under.

**First line of every reply — no exception — is one of three tokens:**

```
USING: <skill>      invoke it before anything else
SEARCH: <query>     you queried the FULL index this turn; ruling pending
SKIPPING: none      lawful only after a search returned nothing usable (see 4)
```

Write the token before you write anything else. Deciding first stops you drifting into
improvising and back-rationalizing — the commitment is the point.

1. **The skills handed to you each turn are a TOP-FEW PREVIEW — not the inventory.**
   The shelf is ~500 skills, nearly all hidden from you. Treating the five you were shown
   as the whole shelf is the failure that starts every dodge.

2. **"The previewed few don't fit" is not a skip. It is the trigger to SEARCH.**
   When no previewed skill fits, you are ordered to query the full index BEFORE any skip:
   - tool: `mcp__plugin_skill-concierge_skill-search__search_skills` (arg: your task in your own words)
   - or:   `/skill-concierge:skill-search`
   Read the ranked results. THEN rule.

3. **SKIPPING is lawful ONLY after a full-index search returns nothing usable — and you show the query.**
   No search, no skip. A skip without a shown query is a false report.

4. **These are not exemptions. They are the dodge, named — refuse each one:**
   - *"I can handle this unaided."* — Competence is irrelevant. The order is not about your ability.
   - *"I'm confident none fit."* — Confidence is not a ruling. A ruling needs the search.
   - *"The few don't fit — move on."* — → SEARCH. Never skip.
   - *"Closest fit isn't perfect."* — Closest fit, adapted, is the standard. Perfect is not the bar.
   - Naming an unfit skill just to pass the gate is a FALSE REPORT. Forbidden.

**Not:** "These 5 don't fit, I've got this." → ~~SKIPPING none~~
**Yes:** "5 don't fit → SEARCH('postgres schema migration') → `supabase-specialist` (0.38) → USING."

> EFFORT was extracted to the standalone **effort-gate** plugin (general "work to done-and-proven"
> doctrine, decoupled here in v0.4.0). skill-first now governs *which/whether a skill* only.

---

## Persistence

ACTIVE EVERY RESPONSE. Bound every turn. No revert after many turns. Still bound if unsure.
No first-line token = no reply. No skip without a search. No silent path. Execute.

<!-- DOCTRINE-END -->
