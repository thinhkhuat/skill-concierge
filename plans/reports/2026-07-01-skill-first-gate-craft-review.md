# SKILL-FIRST Prompt-Gate — Craft Review (DISCOVER → DIAGNOSE)

> Method: optimize-prompt consultant pass. This report covers **DISCOVER** and **DIAGNOSE** only.
> OPTIMIZE/VALIDATE happen later with the controller. Nothing in the live system was edited.
> The DRAFT surfaces below are **proposals, not applied.**

---

## Discovery Summary

- **Platform.** Claude Code hook-injected context. Two delivery halves (caveman split):
  - `skill-first.md` — full standing order, injected **once at SessionStart** by `doctrine.py`.
  - `enforcer.py` — injected **every turn** (UserPromptSubmit). Two strings the model actually sees:
    `MANDATE` (embed/Qdrant-down fallback, lines 242–250) and `_ranked_mandate()` (normal path with the
    candidate preview + %-share, lines 343–370).
  - `docs/skill-first-enforcement-mental-model.md` is **design philosophy** (honored, not rewritten).
- **Model.** Cross-Claude, primary Opus 4.8. Opus over-engineering lens applied (it satisfices under a
  pile of absolute orders; it lawyers vague self-judged terms).
- **Goal.** Make Claude reliably CONSIDER + USE a fitting skill, while (a) not over-firing on trivial /
  conversational turns and (b) not rewarding ritual (empty SEARCH, naming an unfit skill, declaring
  USING then not invoking).
- **Design constraints to keep (from the philosophy doc).** Prevention-not-policing; in-generation
  governance; **no post-turn detector** (§8, §11 — owner-set, do not propose a Stop/PostToolUse gate);
  caveman split (rich-once + cheap-per-turn); structure-over-volume (§5); per-turn budget **~44 tok**
  (§6, §10.3).
- **Coexistence reality (given).** Two OTHER session-start standing orders share the reply with this
  one: an **EFFORT** order and a **self-check FOOTER** spec. skill-first's "first line = token, no
  reply without it" competes for the opening; the footer competes for the close.

---

## Score: 72 / 100

| Dimension | Score | Note |
|---|---|---|
| Structural design (forced token, pre-commitment, named dodges, Not/Yes) | 9/10 | genuinely strong; caveman levers applied well |
| Output-format clarity (line-1 token) | 7/10 | clear shape, but the trivial-turn case has no lawful value |
| Contradiction-freedom | 5/10 | doctrine ("every reply, no exception") contradicts the enforcer's own getaway/actionability gate |
| Incentive alignment (ritual vs substance) | 6/10 | dodges named, but "usable" + retrospective SEARCH tense leave gameable seams |
| Token efficiency (per-turn) | 6/10 | per-turn injection runs ~2× the design's own 44-tok budget |
| Robustness across the 3 stacked orders | 6/10 | three absolute orders = the §2.5 intensifier-spam failure at system scale |
| Testability / falsifiability | 8/10 | selftest pins refusal + render; behavior still unmeasured (acknowledged) |

The foundation is well-engineered. The 28-point gap is concentrated in **one logic hole** (the
trivial-turn bind), **one budget regression** (per-turn overshoot), and **a few gameable seams**
(tense, "usable", %-share-as-confidence).

---

## Issues Found

### ISSUE 1 — The trivial / pure-chat turn has NO lawful first-line token [HIGH]

**Current** (`skill-first.md:13–19`, and the absolute close `:55`):
```
**First line of every reply — no exception — is one of three tokens:**
USING: <skill>      invoke it before anything else
SEARCH: <query>     you queried the FULL index this turn; ruling pending
SKIPPING: none      lawful only after a search returned nothing usable (see 4)
...
No first-line token = no reply. No skip without a search. No silent path. Execute.
```

**Problem.** On a turn with no task at all ("thanks, that worked", "good morning", "what did you mean
by that?"), all three tokens are unlawful or absurd:
- `USING` — there is no skill.
- `SEARCH` — searching the 500-index for "thanks" is pure theater (the exact ritual the goal forbids).
- `SKIPPING: none` — explicitly **unlawful** without a prior search.

So the doctrine, read literally, forces one of: a theatrical search to legitimize a skip, an *unlawful*
SKIPPING (which teaches the model the lawfulness clause is ignorable — corroding every other clause),
or no reply. **Worse, it contradicts the enforcer itself:** the getaway floor (`enforcer.py:481`) and
the actionability gate (`:491`) already decide "this turn needs no skill" and stay silent — yet the
SessionStart doctrine (still in context) says "every reply, no exception." The two halves disagree
about whether trivial turns need a token. This is the single biggest craft defect: it manufactures
ritual on exactly the turns the goal says to leave alone.

**Fix.** Gate the obligation on *a task being present*, matching what the enforcer already does
mechanically. Make a bare `SKIPPING: none` lawful on a genuine no-task turn **without** a search; keep
the search-before-skip discipline only where there IS a task but no previewed skill fits:
```
SKIPPING: none   — lawful in two cases only:
                   (a) no task this turn (pure chat / acknowledgement), or
                   (b) you SEARCHED the full index for a real task and nothing was even
                       loosely adaptable — show the query.
```
**Philosophy-risk (named):** this re-opens a sliver of the "self-judged trivial loophole" the redesign
killed (§2 failure #2). Mitigation: the judgment shrinks from the abusable *"will a skill help?"* to the
narrow *"is there a task at all?"*, and the enforcer's gate is the mechanical backstop — when the
per-turn trigger fired **with candidates**, a task is present and (a) does not apply. State that link
explicitly so the model can't smuggle a real task into "no task." The conservative alternative (keep the
absolute rule, accept theater on trivial turns) is strictly worse against the stated goal; recommend the
task-gated fix.

---

### ISSUE 2 — Per-turn injection runs ~2× the design's own 44-token budget [HIGH]

**Current** (`enforcer.py:343–370`, the every-turn `_ranked_mandate` fixed text):
```
"SKILL-FIRST — line 1 of your reply = one of: USING <skill> | SEARCH <query> | SKIPPING none.\n"
"Top-few PREVIEW for this request (NOT the full ~500-skill shelf):\n"
... candidates ...
"None fit? That is not a skip — SEARCH the full index (search_skills) before any SKIPPING; show the
 query. Closest fit, adapted, is the standard; perfect is not the bar. [full standing order: session start]"
```
and `MANDATE` (`:242–250`) is similarly ~80 tok.

**Problem.** The design's own split (`mental-model §6`, §10.3) sets the per-turn trigger at **~44 tok**
and the rich version at SessionStart. Both injected strings restate the full rule + the "closest fit"
clause + the dodge framing **every turn** — ~90–110 tok of fixed text before candidates. That is the
rich half leaking into the cheap half, paid on every prompt, against the doc's "cut prose, keep on the
half paid once" discipline (§6). The full reasoning already lives at SessionStart; per-turn only needs
the token shape + the "preview, search before skip" reminder + the candidate list.

**Fix.** Trim per-turn to the §10.3 spec; let the SessionStart doctrine carry the argument:
```
SKILL-FIRST · line 1 = USING <skill> | SEARCH <query> | SKIPPING none.
Preview for this task (NOT the full ~500 shelf):
  • <name> (58%) — <desc>
None fit → SEARCH the full index (search_skills) before SKIPPING; show the query. [full order: session start]
```
(Full drafts below.) The "closest fit, adapted, is the standard / perfect is not the bar" line moves to
SessionStart-only — it is reasoning, not a per-turn trigger.

---

### ISSUE 3 — The SEARCH token is written in the past tense, breaking pre-commitment [MED]

**Current** (`skill-first.md:18`; identical in `mental-model §10.1:228`):
```
SEARCH: <query>     you queried the FULL index this turn; ruling pending
```

**Problem.** Line 1 is written **before** the model acts ("Deciding first stops you drifting…", `:21`).
At the instant it writes `SEARCH: <query>`, it has **not** queried yet. "you queried … this turn"
asserts a past act that hasn't happened, which muddies the very pre-commitment the gate is built on
(§3: "decide *before* acting"). A model that notices the tense mismatch can read the token as a
post-hoc label rather than a commitment to act — the opening for SEARCH-as-theater.

**Fix.** Make it prospective — the token is a promise, not a receipt:
```
SEARCH: <query>     querying the full index now; ruling after the results
```

---

### ISSUE 4 — "nothing usable" re-imports the self-judged loophole at the post-search step [MED]

**Current** (`skill-first.md:18` & `:34`):
```
SKIPPING: none      lawful only after a search returned nothing usable
3. **SKIPPING is lawful ONLY after a full-index search returns nothing usable...**
```

**Problem.** "Usable" is self-judged, and it sits directly against `:41` *"Closest fit, adapted, is the
standard; perfect is not the bar."* The two pull opposite ways: one says take even a loose fit, the other
lets the model declare results "not usable." A motivated model runs the search (satisfying the letter),
then rules everything "not usable" — the §2 "self-judged loophole," just relocated from before the search
to after it. The gate moved the confidence-judgment; it didn't bound it.

**Fix.** Bind the skip bar to the same standard as the take bar — no daylight between them:
```
SKIPPING is lawful after a search ONLY when nothing returned is even LOOSELY adaptable to the task.
If any result could be adapted, that is a USING, not a skip. "Not a perfect fit" is never a skip.
```

---

### ISSUE 5 — %-share reads as confidence on a compressed, low-signal band [MED]

**Current** (`enforcer.py:343–361`):
```
pct = f" ({round(score / total * 100)}%)" if multi else ""
...
note = "\nMultiple candidates — pick the one matching the actual intent." if multi else ""
```

**Problem.** Share-of-mass disambiguates *which* among several (its stated purpose, and it does help).
But on the compressed mpnet band it can actively **mislead about whether to engage at all**: a weak
0.30 over a weak 0.18 renders as **62% vs 38%**, which reads like "fairly confident in #1" when the true
signal is "both weak, #1 merely less weak." The percentage encodes RANK but masks ABSOLUTE weakness, and
nothing in the wording tells the model the share is relative-only. The "pick the one matching the actual
intent" note helps with selection but not with the engage/skip read.

**Fix.** Keep the share (it earns its place for selection) but **label it relative**, so it can't be read
as confidence:
```
note = "\nShares are RELATIVE rank among these few (all merely above the noise floor), not confidence —
pick the one matching the actual intent, or SEARCH if none do." if multi else ""
```
Low-cost wording change; no engineering. (A deeper option — suppress share when top-share < a spread
threshold — is an OPTIMIZE-phase engineering call, not craft.)

---

### ISSUE 6 — "No first-line token = no reply" states a consequence no hook can deliver [MED]

**Current** (`skill-first.md:55`):
```
No first-line token = no reply. No skip without a search. No silent path. Execute.
```

**Problem.** By design there is **no post-turn checker** (§8, §11) — nothing blocks a reply that omits
the token. The doctrine asserts a system consequence ("= no reply") the architecture intentionally does
not implement. A model that infers the threat is empty discounts the whole order's credibility; and this
exact line is the one that collides hardest with the EFFORT order and the FOOTER spec for control of the
reply's opening. Stating an unbacked consequence is also a small honesty/consistency defect in a doctrine
whose force is supposed to come from *structure, not bluff* (§5).

**Fix.** Frame it as a self-imposed protocol (true to the in-generation bet), not a gate that fires:
```
The line-1 token is the first thing you write, every task turn — it is how you hold yourself to the
order. No skip without a search. No silent path. Execute.
```

---

### ISSUE 7 — Three absolute standing orders = the §2.5 intensifier-spam failure, at system scale [LOW]

**Current** (`skill-first.md:11` + `:54`): *"This is not advice. This is the order you operate under."* /
*"ACTIVE EVERY RESPONSE. Bound every turn."* — stacked with an EFFORT order and a FOOTER order, each
equally maximal.

**Problem.** §2 failure #5 and §5 both warn that volume habituates and **structure carries the force**.
Three coexisting "every turn, no exception, this-is-an-order" doctrines are precisely that failure
re-created one level up: when everything is maximum-priority, the model satisfices across them. skill-first
cannot fix the other two, but its own meta-absolutism ("no reply without it", "this is not advice")
adds to the pile without adding structural force.

**Fix.** skill-first keeps its *structural* forcing (the token, the search-before-skip, the named dodges)
and sheds *rhetorical* absolutism (Issue 6 already removes the empty threat). Flag to the controller that
the three session-start orders should be **harmonized into one opening contract** (token at top → work to
done → footer at close) rather than three independent "I own the reply" claims. Out of scope to fix here;
in scope to name.

---

### ISSUE 8 — The caveman parallel is oversold: here, token ≠ behavior [LOW / honest-limit]

**Problem.** caveman works because **format == behavior** — the terse output *is* the compliance, so the
forced pattern is self-enforcing. skill-first's token and the desired act are **decoupled**: writing
`USING: x` does not invoke x; writing `SEARCH: q` does not run the search. The doc's claim that
self-coherence bridges this (§3, `mental-model:61`) is real but **weaker** than caveman's identity of
form and behavior — which is exactly why the gate is gameable in ways caveman is not. Not a fix, a limit
to keep honest: lean on the one place form and behavior DO couple — `USING: <skill>` immediately followed
by the invocation in the same turn (`:16` "invoke it before anything else" — keep and harden this; it is
the strongest lever the gate has).

---

## DRAFT — Optimized Surface 1: `skill-first.md` (SessionStart, rich) — PROPOSAL, not applied

```markdown
## SKILL-FIRST — STANDING ORDER

Obey on every task turn. This is the order you operate under; its force is structure, not volume.

**First line of every task-bearing reply is one of three tokens — write it before anything else:**

    USING: <skill>      invoke it immediately, before any other work
    SEARCH: <query>     querying the full index now; ruling after the results
    SKIPPING: none      lawful in only two cases — see 3

Decide first. Committing to the token before you act stops you drifting into improvising and then
back-rationalizing the skip — the commitment is the whole point.

1. **The skills handed to you each turn are a TOP-FEW PREVIEW — not the inventory.**
   The shelf is ~500 skills, nearly all hidden. Treating the few you were shown as the whole shelf
   is the failure that starts every dodge.

2. **"The previewed few don't fit" is the trigger to SEARCH — never grounds to skip.**
   When a real task has no fitting preview, query the full index before any skip:
   - tool: `mcp__plugin_skill-concierge_skill-search__search_skills` (arg: the task in your own words)
   - or:   `/skill-concierge:skill-search`
   Read the ranked results. THEN rule.

3. **SKIPPING: none is lawful in exactly two cases:**
   (a) **No task this turn** — pure chat, an acknowledgement, a clarifying question. No search needed.
   (b) **A real task, searched, nothing adaptable** — you ran the full-index search and nothing
       returned is even LOOSELY adaptable to the task. Show the query as proof.
   If the per-turn preview arrived WITH candidates, a task is present — (a) does not apply.

4. **The take-bar and the skip-bar are the same line. A loosely-adaptable fit is a USING, not a skip.**
   Closest fit, adapted, is the standard; perfect is not the bar. "Not a perfect fit" is never a skip.

5. **These are not exemptions. They are the dodge, named — refuse each:**
   - *"I can handle this unaided."* — Competence is irrelevant. The order is not about your ability.
   - *"I'm confident none fit."* — Confidence is not a ruling. A ruling needs the search.
   - *"The few don't fit — move on."* — → SEARCH. Never skip.
   - *"Closest fit isn't perfect."* — Closest fit, adapted, is the standard.
   - Naming an unfit skill just to pass the gate is a FALSE REPORT. Forbidden.

**Not:** "These 5 don't fit, I've got this." → ~~SKIPPING none~~
**Yes:** "5 don't fit → SEARCH('postgres schema migration') → `supabase-specialist` (0.38) → USING."

## Persistence
ACTIVE EVERY TASK TURN. Bound every turn. No revert after many turns. Still bound if unsure.
The line-1 token is how you hold yourself to the order. No skip without a search on a real task.
No silent path. Execute.
```

**Why this is still in-philosophy:** no post-turn detector added; same caveman split; structure-first; the
only philosophy concession is the *task-gated* trivial exit (Issue 1), which is argued and backstopped by
the enforcer's existing gate.

---

## DRAFT — Optimized Surface 2: `MANDATE` (per-turn fallback, embed/Qdrant down) — PROPOSAL

```python
MANDATE = (
    "SKILL-FIRST · reply line 1 = USING <skill> | SEARCH <query> | SKIPPING none.\n"
    "Shown skills are a top-few PREVIEW of ~500, not all. On a real task, "
    "\"few don't fit\" / \"I'm confident\" → SEARCH (search_skills) before any SKIPPING; show the query. "
    "No task (pure chat) → SKIPPING none, no search. "
    "[full order: session start]"
)
```
*Trimmed toward the §10.3 budget; adds the no-task clause (Issue 1); drops the restated reasoning the
SessionStart doctrine already carries (Issue 2).*

---

## DRAFT — Optimized Surface 3: `_ranked_mandate()` (per-turn, normal path) — PROPOSAL

```python
def _ranked_mandate(cands: list) -> str:
    total = sum(s for (_n, _d, s) in cands) or 1.0
    multi = len(cands) > 1
    lines = []
    for name, desc, score in cands:
        blurb = _clean(desc)
        if len(blurb) > _DESC_CHARS:
            blurb = blurb[:_DESC_CHARS].rsplit(" ", 1)[0] + "…"
        pct = f" ({round(score / total * 100)}%)" if multi else ""
        lines.append(f"  • {name}{pct} — {blurb}")
    note = ("\nShares are RELATIVE rank among these few (all merely above the noise floor), not "
            "confidence — pick the one matching the actual intent, or SEARCH if none do.") if multi else ""
    return (
        "SKILL-FIRST · reply line 1 = USING <skill> | SEARCH <query> | SKIPPING none.\n"
        "Preview for this task (NOT the full ~500 shelf):\n"
        + "\n".join(lines) + note + "\n"
        "None fit → SEARCH the full index (search_skills) before SKIPPING; show the query. "
        "[full order: session start]"
    )
```
*Changes: relative-rank label on the share (Issue 5); "closest fit, perfect is not the bar" reasoning
moves to SessionStart-only (Issue 2); trigger trimmed toward budget. Note: the existing `--selftest`
asserts the literal strings `"(75%)"`, `"(25%)"`, and `"Multiple candidates"` (`enforcer.py:535–538`) —
**this draft changes the note text, so that selftest must be updated in the OPTIMIZE phase** or it will
fail. Flagging so it isn't missed.*

---

## Changes Made (proposal-level, nothing applied)

- **Task-gated the obligation** so trivial/pure-chat turns get a lawful bare `SKIPPING: none` with no
  theatrical search, resolving the doctrine↔enforcer contradiction (Issue 1).
- **Made SEARCH prospective** ("querying now") to restore pre-commitment (Issue 3).
- **Welded the skip-bar to the take-bar** ("loosely adaptable") to close the post-search "not usable"
  loophole (Issue 4).
- **Labeled %-share as relative rank**, not confidence (Issue 5).
- **Removed the unbacked "= no reply" consequence**; reframed as a self-imposed protocol (Issue 6).
- **Trimmed both per-turn strings** back toward the design's ~44-tok budget by moving reasoning to the
  paid-once SessionStart half (Issue 2).
- **Flagged** the three-stacked-orders harmonization (Issue 7) and the token≠behavior limit (Issue 8) as
  out-of-scope-to-fix-here but named.
- **Flagged a test dependency:** the proposed `_ranked_mandate` note breaks the literal-string selftest
  assertions — update in OPTIMIZE.

## Open questions for the controller (OPTIMIZE/VALIDATE)

1. Accept the task-gated trivial exit (Issue 1), or hold the absolute rule and accept ritual on trivial
   turns? This is the one philosophy concession and needs the owner's call.
2. Is the EFFORT/FOOTER harmonization (Issue 7) in scope for this pass, or a separate workstream?
3. %-share: wording-only label (proposed) vs. a spread-threshold suppression (engineering)?

---

## FINAL — apply-ready

> OPTIMIZE phase output. Controller decisions locked: D1 task-gate + a TIGHT, CLOSED exempt-turn
> taxonomy ACCEPTED; transcript-data findings D1–D4 merged with craft Issues 2/3/4/5/6. Philosophy held:
> no post-turn detector, caveman split (rich-once / cheap-per-turn), structure-over-volume. The
> `_ranked_mandate` render and the updated selftest assertions in §4 below were **executed and pass**
> (scratch run, output captured) — not asserted.

### 1. `hooks/doctrine/skill-first.md` — full body (paste between `<!-- DOCTRINE-START -->` and `<!-- DOCTRINE-END -->`)

````markdown
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
   - an agent-to-agent dispatch that hands you no work to do.

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

## Persistence

ACTIVE EVERY TASK TURN. Bound every turn. No revert after many turns. Still bound if unsure.
The line-1 token is how you hold yourself to the order — write it first, every task turn.
No skip without a search. No SKIPPING outside the class in 4. No silent path. Execute.
````

**What changed vs. the draft / original doctrine, and which finding it closes:**
- Point 4 rewritten into a **closed, single-class** exemption (harness/system notice, await-only ping,
  no-task agent dispatch) with the **three dodge-classes named as still-forbidden** (self-confident
  domain judgment ~40%, prior-session search ~20%, user-named-a-tool ~15%) and the **"candidates present
  → task present → exemption void"** link stated. Closes **D1** (the 68% false-SKIPPING, #1 defect).
- Point 2 + the SEARCH token line now **require the `search_skills` call in the same reply**; narrated /
  imagined search = disguised SKIPPING. Closes **D4** (16% ritual SEARCH) and folds in **Issue 3**
  (prospective tense — "run … NOW", not "you queried").
- New point 5 + a Not/Yes **prohibit `USING: none`**. Closes **D3** (13 hybridization occurrences).
- New second Not/Yes pair targets the **self-confident skip** specifically (caveman show-don't-tell). **D2**.
- Point 3 **welds skip-bar to take-bar** (Issue 4). The unbacked "= no reply" is gone; persistence is a
  **self-imposed protocol** (Issue 6).

### 2. `enforcer.py` — `MANDATE` (per-turn fallback, embed/Qdrant down)

```python
MANDATE = (
    "SKILL-FIRST · reply line 1 = USING <skill> | SEARCH <query> | SKIPPING none.\n"
    "Shown skills are a PREVIEW of ~500, not all. \"Few don't fit\" / \"I'm confident\" / "
    "\"you named a tool\" are NOT skips — run search_skills THIS reply before any SKIPPING (show the "
    "query). SKIPPING is lawful only on a no-task turn, or after a search finds nothing adaptable. "
    "USING never takes \"none\". [full order: session start]"
)
```
*Trimmed; reasoning lives at SessionStart (Issue 2). Carries the D1/D3/D4 spine as terse reminders.
~60 tok — slightly above the §10.3 44-tok target because this is the **no-candidate fallback** and must
stand alone; the candidate-bearing path (§3) is leaner.*

### 3. `enforcer.py` — `_ranked_mandate()` (per-turn, normal path)

```python
def _ranked_mandate(cands: list) -> str:
    # %-SHARE is RELATIVE rank among the shown few, NOT absolute confidence — raw mpnet cosines
    # (~0.18-0.40) read as noise; share disambiguates WHICH fits. Shown only with 2+ candidates
    # (a lone candidate is always 100% → meaningless). Raw scores still logged to the ledger.
    total = sum(s for (_n, _d, s) in cands) or 1.0
    multi = len(cands) > 1
    lines = []
    for name, desc, score in cands:
        blurb = _clean(desc)
        if len(blurb) > _DESC_CHARS:
            blurb = blurb[:_DESC_CHARS].rsplit(" ", 1)[0] + "…"
        pct = f" ({round(score / total * 100)}%)" if multi else ""
        lines.append(f"  • {name}{pct} — {blurb}")
    note = ("\nShares are RELATIVE rank among these few (all above the noise floor), not confidence — "
            "pick the one matching the intent.") if multi else ""
    return (
        "SKILL-FIRST · reply line 1 = USING <skill> | SEARCH <query> | SKIPPING none.\n"
        "Preview for this task (NOT the full ~500 shelf):\n"
        + "\n".join(lines) + note + "\n"
        "None fit → run search_skills THIS reply before any SKIPPING; show the query. "
        "A loosely-adaptable fit is a USING. [full order: session start]"
    )
```
*Issue 5 (share labeled RELATIVE, not confidence), Issue 4 ("loosely-adaptable fit is a USING"), Issue 2
(reasoning moved out), D4 ("run search_skills THIS reply"). The %-share **computation is unchanged**, so
the existing `(75%)` / `(25%)` assertions stay valid.*

### 4. `enforcer.py` `--selftest` — EXACT assertion updates (because the note text changed)

The share math is unchanged, so `(75%)` / `(25%)` checks stay. Only the **note phrase** moved from
`"Multiple candidates"` → `"RELATIVE rank"`, in **three** places (two in block (2) ~lines 537–541, one in
block (5) ~line 596). All four edits below; with them, `python3 enforcer.py --selftest` stays green
(proven on a scratch replica — output captured).

**(2a) ~line 537–538** — the multi note check:
```python
    # BEFORE
    if "Multiple candidates" not in multi:
        bad.append("ranked_mandate: missing disambiguation note for 2+ candidates")
    # AFTER
    if "RELATIVE rank" not in multi:
        bad.append("ranked_mandate: missing relative-rank note for 2+ candidates")
```

**(2b) ~line 539–541** — the lone-candidate check:
```python
    # BEFORE
    lone = _ranked_mandate([("alpha", "desc alpha", 0.25)])
    if "%" in lone or "Multiple candidates" in lone:
        bad.append("ranked_mandate: lone candidate must show no share and no note")
    # AFTER
    lone = _ranked_mandate([("alpha", "desc alpha", 0.25)])
    if "%" in lone or "RELATIVE rank" in lone:
        bad.append("ranked_mandate: lone candidate must show no share and no note")
```

**(5) ~line 595–597** — the collapsed-render check (same phrase, must move too for the check to mean anything):
```python
    # BEFORE
    lone_collapsed = _ranked_mandate([("a", "da", 0.30)])
    if "%" in lone_collapsed or "Multiple candidates" in lone_collapsed:
        bad.append("collapsed render must be lone (no %-share / note)")
    # AFTER
    lone_collapsed = _ranked_mandate([("a", "da", 0.30)])
    if "%" in lone_collapsed or "RELATIVE rank" in lone_collapsed:
        bad.append("collapsed render must be lone (no %-share / note)")
```

(The `(75%)` / `(25%)` assertion at ~line 535–536 is **unchanged** — keep it.)

**Verification run (scratch replica of the proposed render + assertions):**
```
OK: all proposed selftest assertions pass
  • alpha (75%) — desc alpha     ← share preserved
  • beta (25%) — desc beta
Shares are RELATIVE rank among these few ...   ← new note, "RELATIVE rank" present
[lone render contains no "%" and no note]      ← lone/collapsed checks pass
```

### Carry-over flags (PROMPT scope done; these are for the controller's D2-full-scope owners)
- **Issue 7** (three stacked absolute session-start orders — skill-first / effort / footer — = §2.5
  intensifier-spam at system scale): NOT a prompt-text fix inside skill-first; needs the three harmonized
  into one opening contract. Out of my surface scope; flagged.
- **Issue 8** (token ≠ behavior, unlike caveman's format == behavior): honest design limit; the strongest
  coupling lever — `USING: <skill>` immediately followed by the invocation — is kept and hardened in
  point-line 1 and point 5.
```
