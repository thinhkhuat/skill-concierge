# Skill-First Enforcement — Mental Model & Doctrine (caveman-anchored)

> **Status:** canonical reference, 2026-06-27. **Built & shipped v0.3.0** (caveman-only, in-generation
> governance, **no post-hoc detection gate** — the earlier P2 Stop/PostToolUse idea was rejected by the
> owner; §8 records why). Captures the complete mental model from the enforcement-redesign session.
> **Self-contained** — a future agent should be able to read only this file and hold the entire model,
> the gate artifacts, the open questions, and the next steps.
> **Scope:** the *Enforce* organ of skill-concierge (whether the agent uses a skill), not retrieval.
> **Role-model:** the `caveman` plugin — a proven, battle-tested governance plugin (tens of thousands
> of GitHub stars) whose mechanisms we anchor to. File cites below are real, read at the source.

---

## TL;DR (read this first)

skill-concierge fuses three organs: **Retrieve** (which skill — semantic Qdrant search), **Enforce**
(whether the model uses one — a per-turn UserPromptSubmit hook), **Ledger** (what got used —
telemetry). The fusion shipped (v0.2.1): the semantic enforcer replaced the old lexical hook;
retrieval quality and latency are **solved**. The hard truth the telemetry exposed: **retrieval was
never the bottleneck — compliance is.** The agent gets offered genuinely-good skills and still
improvises (uptake ~14–18%, flat before vs after; hit@k n/a — not one offered-and-used turn). The
binding constraint is **"whether," not "which."** Therefore the lever is the *enforcement message
itself, governing generation* — not more retrieval tuning, and **not a post-hoc gate.** The redesign
turns the message from **persuasion into a GATE**: a forced first-line decision token, no silent skip,
and — the key architectural fix — **a skip is only lawful after the agent searches the full ~500-skill
index**, because the per-turn offer is a *preview*, not the inventory. caveman proves the delivery
architecture: **rich doctrine injected once at SessionStart + a cheap trigger per turn**, and proves
the boundary — **caveman has no Stop hook, no post-turn check.** Governance is in-generation: the
doctrine shapes the write because it is in context as the model writes. A detection layer that catches
the dodge *after* the turn (Stop/PostToolUse) is the anti-caveman — it polices spent tokens instead of
shaping the disposition, and is **rejected by design** (see §3, §8, §11). **Shipped v0.3.0** (caveman-
only, no detection): `doctrine.py` (SessionStart) + the reworded `enforcer.py` trigger (per turn).

---

## 1. The problem, precisely

- **Three organs.** Retrieve (semantic, mpnet-768 over Qdrant), Enforce (the hook), Ledger (append-only telemetry → data-backed always-on curation).
- **Shipped state (v0.2.1, live):** lexical `skill_first_nudge.py` deregistered; semantic `enforcer.py` live via the plugin's `hooks.json`; warm embed shim (Docker sidecar, `fastembed==0.8.0` pinned for index parity) on `127.0.0.1:6363`; embed timeout tuned 120→90→**200ms**, shim threaded (`ThreadingHTTPServer`) after dogfooding showed ~60% `embed_timeout` fallback under contention. Retrieval coherent (an EN "janky UI on mobile" query surfaces `responsive-design` — a jump the lexical scorer could never make). Latency ~70ms warm.
- **The insight (verified from the ledger):** uptake **14–18%**, dodge **82–86%**, **hit@k = n/a** (zero offered-and-used turns). Better candidates did **not** raise usage. The constraint is the agent *choosing not to invoke a good offer*, then rationalizing it. Retrieval/latency tuning has hit diminishing returns; the unsolved half is **compliance**.

---

## 2. Why the original nudge under-binds (the cause, not the consequence)

The original message was **persuasion with a loud voice**. Five failures, each a compliance leak:

1. **It argues its case** ("skills encode a better approach…"). A justification invites evaluation; if the model judges a skill won't help *this time*, the message's own reasoning licenses the skip. Laws don't explain themselves.
2. **Self-judged loophole wider than the rule** ("trivial… a pure conversational reply…"). Motivated reasoning files almost anything under it.
3. **No forced action / no observable token.** "Scan your catalogue" is invisible and unverifiable.
4. **Skipping is silent and free.** "Announce the skill you're using" fires only *if* using — not-using has no required output, so the default path (improvise) is frictionless.
5. **Intensifier-spam** (MUST / not optional). Models are saturated with MUST/CRITICAL; volume habituates. Structure binds; loudness doesn't.

---

## 3. The doctrine: a GATE, not advice

Reframe from *disposition* ("you should prefer skills") to a **precondition on proceeding**.

**The compliance levers (model-agnostic — exploit format-adherence + pre-commitment priors, no vendor tricks):**
- **Output-forcing** — require an *emitted* first-line token, not an internal disposition. Its force is in-generation: having written `SEARCH: <query>` as line 1, the model is far likelier to actually run the search (self-coherence), the way caveman's forced terse pattern makes the next sentence terse. The value is the commitment it induces, **not** a token a downstream hook can grep — there is no such hook.
- **Pre-commitment** — decide *before* acting, so the model can't drift into improvising then back-rationalize.
- **No argument to win** — state the obligation; delete justification.
- **Invert the default** — make skipping the effortful, *recorded* path.
- **Name the exact rationalizations** — pre-empt the literal phrases the network emits.
- **Cost asymmetry** — a skip must carry a falsifiable reason (expensive); invoking is cheap.

**The architectural gap (the heart of it — surfaced by the user):**
The per-turn enforcer offers a **top-k PREVIEW (5), not the inventory (~500, nearly all hidden).** The
real dodge is **not lying** — the agent genuinely, correctly reasons "these few don't fit my task"
and **stops**, never escalating to the full-index search, because the token-economy instinct says
"I'm confident, none fit, stay efficient, move on." So the gate must make **"the previewed few don't
fit" a trigger to SEARCH the full index, never grounds to skip.** A skip is lawful *only after* a
full-index search returns nothing usable, with the query shown as proof.

**The "doubt" correction:** an LLM does not feel doubt — it follows the mean, confidently. So do **not**
write "resolve doubt to invoke." Instead **ban confidence/competence as an exemption**: "Competence is
irrelevant; the order is not about your ability. Confidence is not a ruling — a ruling needs the search."

**The "wrong skill beats no skill" trap (removed):** it invited gate-gaming (name any skill to pass).
Replaced with: *closest-fit-adapted is the standard; naming an unfit skill to pass the gate is a FALSE REPORT, forbidden.*

---

## 4. The EFFORT companion (drop trained token-thrift)

> **Extracted (v0.4.0):** EFFORT is now the standalone **effort-gate** plugin
> (`github.com/thinhkhuat/effort-gate`), decoupled from skill-concierge — it is universal, not
> skill-bound. The design below is preserved as rationale/history; the live doctrine ships in
> effort-gate (same caveman split: SessionStart full + per-turn re-assert, no detection).

Models are trained (length/effort penalties) to minimize tokens — and will **silently cut WORK** to feel
economical: skip a skill, a tool call, a search, a verification; do one call where three are needed;
"good enough" to wrap early. This is the hidden incentive that makes the SKILL gate's *skip* tempting.

**The trap to avoid:** "drop token-saving" does **not** mean "be verbose." It means **kill thrift on
WORK; keep thrift on WORDS.** The motto: **"Cut prose, never effort."** Forbidden: cutting work to
"save tokens," concluding "no skill fits" without a full-index search, stopping at "I'm confident I
can handle it." Less work is the user's call alone — name the cut, halt, await clearance; never cut by
silence.

---

## 5. Register: military — but the structure carries the force

Orders compel by **deleting the decision space and the justification**, not by volume. Imperative,
verb-first, no hedges ("when in doubt/prefer/try" → absolutes), enumerated forbidden moves, a named
consequence ("no line-1 decision = no reply"). **Honest caveat:** military *tone* without the
structural gate (forced token, killed rationalizations, no-silent-path) is **theater**. The power is
the gate; the register only strips the last softeners.

---

## 6. Token economics: the split (this reconciles two true things)

The order is **injected every turn, forever** — per-turn cost compounds, and the order is itself
**prose** (so "cut prose" applies to it). Measured: the full military GATE 1 ≈ **~400 tok/turn**;
compressed ≈ 115; a per-turn-minimal trigger ≈ **~44 tok**.

**But** caveman's activation hook carries a hard-won counter-lesson (`src/hooks/caveman-activate.js:31–33`):
> *"The old 2-sentence summary was too weak — models drifted back to verbose mid-conversation,
> especially after context compression pruned it away. Full rules with examples anchor behavior much
> more reliably."*

**Resolution — the split (caveman already does this):**
- **SessionStart, once:** the **full, rich, example-laden** doctrine. Not minimized — richness is what
  survives compaction and stops drift. Paid once, so richness is ~free.
- **UserPromptSubmit, per turn:** only the **~44-tok forced trigger + the candidate list.**

Your token point and caveman's anti-drift lesson are *both right* — they live on different halves of
the split. (Context: a prior name-only curation reclaimed ~38k tok/turn ≈ 19% of a 200k window; the
discipline that won that back is the same discipline that refuses to re-bloat the per-turn injection.)

---

## 7. caveman as the role-model (the proven case)

**How it GOVERNS** (from `skills/caveman/SKILL.md` + `src/hooks/caveman-activate.js`):

| Lever | What caveman does | Cite |
|---|---|---|
| Show, don't tell | every rule paired with `Not: …` / `Yes: …` + worked examples | `SKILL.md:29–30, 43–56` |
| Full rules > summary | over-summarized rules drift, esp. post-compaction | `activate.js:31–33` |
| Doctrine once + cheap per-turn | SessionStart full ruleset; per-turn tracker re-asserts `"(mode)."` | `activate.js:42–45, 91` |
| Anti-drift persistence | `ACTIVE EVERY RESPONSE. No revert after many turns. Still active if unsure.` | `SKILL.md:13–15` |
| Single source of truth | hook **reads SKILL.md at runtime**; no hardcoded copy | `activate.js:50–58` |
| Exceptions enumerated, not judged | "Auto-Clarity": a concrete closed list of when to drop the mode | `SKILL.md:58–67` |
| No self-reference | never announce the style; output the mode only | `SKILL.md:25` |

**How it SPREADS** (from `README.md` — the star engine): meme tagline ("why use many token when few do
trick"); a 2-second before/after (69→19 tok, same fix); **honest measured proof** (benchmarked vs
`"Answer concisely."` not the verbose default, so the delta is honest, `README:154`); one-line
`curl|bash` install; statusline gamification (`[CAVEMAN] ⛏ 12.4k` saved); explicit "Star This Repo"
ask; and it **embodies its own thesis** (the README is written in caveman).

**Two to steal first:** (1) **Not/Yes contrastive examples** — biggest single enforcement upgrade;
models obey a *demonstrated* pattern far more than a described one. (2) **"Still active if unsure"** —
a cleaner fix for the "doubt" problem than any rewrite.

---

## 8. Measurement reality (read before trusting any number)

- **The ledger is contaminated:** one global ledger, multiple concurrent agent sessions, an
  advisory/meta workload (review/handoff turns where *not* invoking a skill is correct), lexical+
  semantic eras mixed, n tiny. Proof of contamination: an adversarial-review session moved uptake
  17%→14% just by adding meta-turns. **The fusion lift is currently unmeasurable on this ledger.**
- **Why no post-hoc gate (design decision, owner-set):** a Stop/PostToolUse "P2 hard gate" that
  checks *if line 1 is `SKIPPING`, was `search_skills` called?* and rejects on omission was considered
  and **rejected.** It is the anti-caveman: it lets the dodge complete, spends the tokens, then catches
  it after the turn and forces a redo — whack-a-mole on output that already happened. Ask what caveman
  would be if a Stop hook caught your verbose paragraph and made you rewrite it: absurd, and not why
  caveman works. caveman has **no Stop hook and no PostToolUse enforcement** — verified in source
  (`src/hooks/`: only `caveman-activate.js` at SessionStart + `caveman-mode-tracker.js` at
  UserPromptSubmit). Governance is in-generation: the doctrine shapes the write because it is present
  in context *as the model writes*, never policed afterward. A UserPromptSubmit hook "only orders, can't
  force" — true — but the answer is a **richer, ever-present order** (the SessionStart doctrine half,
  which skill-concierge was missing), not a detection layer. Compliance is therefore moved by the
  quality and presence of the injected doctrine, and measured honestly on a clean window — not coerced
  at stop-time.
- **Stale index breaks "dig broader":** the semantic index goes stale as skills change on disk;
  `search_skills` then *misses known skills* (observed: it missed `rules-distill`, ranked analytics
  skills over the real hook skill). **Run `reindex()`** before relying on full-index search. Even
  fresh, semantic recall has a ceiling — when you suspect a skill exists *by name*, also check the
  by-name catalogue; search-before-skip is necessary, not sufficient.

---

## 9. The build: what shipped (v0.3.0)

**Binding authority:** `~/.claude/docs/claude-code-component-building.md` — **ENFORCED**; load it the
moment a CC component is touched. Rule B (latest docs) satisfied via `/plugin-scaffold` +
`/working-with-claude-code` (`hooks.md` SessionStart contract). Rule A (local-first) honored: built in
the dev repo, propagated to the install only on explicit owner go-live. **Proof:** `scripts/analyze.py`
(the honest before/after — caveman's credibility move; our telemetry already produces it).

**Shipped — four artifacts, pure run-time, zero detection (caveman-mirrored split):**
1. `hooks/doctrine/skill-first.md` → the rich standing order (SKILL-FIRST + EFFORT) with **Not/Yes
   examples** + a **persistence clause**. A plain doctrine markdown, **not** an invocable `SKILL.md`:
   the doctrine is hook-injected, never user-invoked, and packaging it as an indexed skill would
   pollute its own candidate list. (Divergence from the earlier plan's `skill-creator` step, for that
   reason — `skill-creator` authors invocable skills.)
2. `hooks/scripts/doctrine.py` → **SessionStart** hook, reads that file *at runtime* and injects the
   full doctrine (mirrors `caveman-activate.js`: single source of truth, fail-silent, additive-only).
3. `hooks/scripts/enforcer.py` → **UserPromptSubmit** message reworded from soft persuasion to the
   cheap **gate trigger** (forced line-1 token; "few don't fit → SEARCH, not skip"); all retrieval,
   fallback, and telemetry machinery untouched.
4. `hooks/hooks.json` → `SessionStart` wired in (`matcher:"*"`, `${CLAUDE_PLUGIN_ROOT}`).

**No P2 / Stop gate** — rejected by design (see §8). **Next:** `analyze.py` on a *clean* workload
window; never claim lift on the contaminated ledger. To compare windows, use
`analyze.py --since WHEN` / `--until WHEN` (epoch or local ISO time) around the boundary —
e.g. a fix/go-live commit time — instead of hand-splitting the ledger.

---

## 10. The gate artifacts (copy-ready, current best)

These are the **SessionStart doctrine** form (rich). The per-turn hook injects only the trigger in §10.3.

### 10.1 SKILL-FIRST — STANDING ORDER
```
SKILL-FIRST — STANDING ORDER. Obey every turn. This is not advice.

1. First line of every reply, no exception — one of:
      USING: <skill>     invoke it before all else
      SEARCH: <query>    you queried the FULL index this turn (line 3); ruling pending
      SKIPPING: none     lawful only per line 4, with the search result shown as proof

2. The skills handed to you each turn are a TOP-FEW PREVIEW — not the inventory.
   The inventory is ~500 skills, nearly all hidden from you. Treating the preview
   as the whole shelf is the failure.

3. If no previewed skill fits, you are ORDERED to query the full index BEFORE any skip:
      tool: mcp__plugin_skill-concierge_skill-search__search_skills  (arg: query)
      or:   /skill-concierge:skill-search
   Query with the task in your own words. Read the ranked results. THEN rule.

4. SKIPPING is lawful ONLY after line 3 returns nothing usable — and you show the query.
   "The previewed few don't fit" is NOT a skip. It is the trigger to SEARCH.

5. These are not exemptions. They are the failure, named:
      "I can handle this unaided."  Competence is irrelevant. Not about your ability.
      "I'm confident."              Confidence is not a ruling. A ruling needs the search.
      "The few don't fit — move on." → SEARCH. Never skip.
      "Closest fit isn't perfect."  Closest fit, adapted, is the standard. Perfect is not the bar.
   Naming an unfit skill to pass the gate is a FALSE REPORT. Forbidden.

Persistence: bound every turn, no drift after many turns, still bound if unsure.
No first-line decision = no reply. No skip without a search. No silent path. Execute.

Not: "These 5 don't fit, I've got this." → SKIPPING none.
Yes: "5 don't fit → SEARCH('postgres schema migration') → supabase-specialist (0.38) → USING."
```

### 10.2 EFFORT — STANDING ORDER
*(Extracted to the standalone effort-gate plugin in v0.4.0 — see §4. Kept here as the origin artifact.)*
```
EFFORT — STANDING ORDER. Obey every turn. This is not advice.

Your training pulls you to spend less — tokens, calls, steps. That pull is overridden here.

1. Do every step the task demands. Run the tool. Run the verification. Read the whole file.
2. Forbidden — and forbidden in silence:
      - cutting a skill/search/tool call/check to "save tokens" or because "I can just answer"
      - one call where three are required; a sample where a full read is ordered
      - concluding "no skill fits" from the previewed few WITHOUT a full-index search
      - "good enough", thinned reasoning, early wrap
      - any "to save context/time/effort" excuse for less work
3. Done means done and proven — never cheap.
4. Terse words. Full work. Cut prose, never effort.

Less work is the user's order alone: name the cut, halt, await clearance. Never cut by silence. Execute.
```

### 10.3 Per-turn trigger (cheap, UserPromptSubmit — ~44 tok)
```
SKILL-FIRST: reply line 1 = USING <skill> | SEARCH <query> | SKIPPING none.
"Few don't fit" / "confident" / "I can do this" → SEARCH (search_skills) before any SKIP; show the query.
Full work, not the cheap stop.  [full doctrine: session-start]
```
*(plus the candidate list the enforcer already injects)*

---

## 11. Open / unproven (do not paper over)

- **Compliance is unmeasured, not solved.** The doctrine is a *design* hypothesis; uptake lift is
  unproven and unmeasurable on the current contaminated ledger. Needs a clean workload window.
- **In-generation governance is the bet, and the whole bet** — a post-hoc enforcement gate is rejected
  by design (§8), so the only lever is the doctrine's quality and constant presence (the caveman wager).
  If a clean-window measurement shows the doctrine doesn't move compliance, the answer is a *richer or
  better-placed doctrine*, not a Stop-hook — adding detection would be reversing the owner's design call.
- **The split shipped (v0.3.0)** — doctrine@SessionStart (`doctrine.py` ← `hooks/doctrine/skill-first.md`)
  + trigger@per-turn (`enforcer.py`). Live once propagated to the install.
- **Stale-index hygiene** must be wired (a reindex trigger / the `skill-concierge:doctor` skill) or
  "dig broader" silently degrades.
- **Semantic recall ceiling** — even reindexed, search can miss a perfectly-named skill; the gate needs
  the "also check by-name" companion.
- **Caveman's virality levers** (honest measured proof, statusline, meme identity) are noted but not yet
  applied to skill-concierge if it ever goes public.
