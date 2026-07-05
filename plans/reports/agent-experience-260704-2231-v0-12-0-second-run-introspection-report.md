# Agent Experience Report — Second Run Under v0.12.0 (Introspection)

**Date:** 2026-07-04 22:31 (Asia/Saigon) · **Author:** operating agent, first-person
**Scope:** what the shipped v0.12.0 governance layer actually did to me on *this* introspection
session, grounded in same-turn tool output. Not a spec summary — a lived-run account. Companion to
the 05:54 first-wild-run report; where that ran a `/briefing → what-next` work arc, this one is a
cold read-and-report turn, which stresses a *different* corner of the layer (a slash-command entry
the enforcer pre-gates out entirely).

## 1. Proof I am actually governed right now (grounded, this turn)

**SessionStart injection — primary evidence.** My SessionStart context carries the full SKILL-FIRST
standing order AND the library-doctrine block. Verbatim tells present in my own context this session:

- *"**Burden of proof is on SKIP.** Only a positively-reasoned 'this turn is trivial/unambiguous'
  earns a no-search skip."*
- *"If the enforcer hands you a `SKILL-CHECK:` line (its AUTHORIZED-SKIP tier), you may go straight to
  `SKIPPING: none` ONLY when the line marks the turn genuinely trivial/conversational."*

Both strings are v0.12.0-specific (library doctrine + AUTHORIZED-SKIP framing, ADR-0015). Their
presence in my injected context is direct proof this session runs under the layer.

**Installed version — read, not recalled.** Live install path
`~/.claude/plugins/marketplaces/skill-concierge/.claude-plugin/plugin.json` line 3 → `"version": "0.12.0"`.
Note the trap: `find` under `~/.claude/plugins` surfaced **22 cached copies** (`cache/skill-concierge/.../0.1.0 … 0.12.0`)
each with its own version line — the *cache* is version-pinned history, the *marketplace* path is the
live one. Read the marketplace copy, not a stale cache hit. Confirmed 0.12.0.

**Health surface —** `python3 scripts/doctor.py` verbatim:
- `status: OK`
- `Retrieval health  488 skills indexed; embedder + qdrant reachable (indexed 15m ago)`
- `Multi-vector layer  3082 trigger points (+ base) of 3570 total — MAX-pooled retrieval`
- `Actionability gate  912 labelled prompts in 'prompt_intent'`
- `Settings overrides  32 on / 470 name-only`

Contrast worth logging: the 05:54 run got **WARN** (index stale, 488 serving vs 3570 total). This run
is **OK** with `indexed 15m ago` — the SessionStart `auto_reindex` self-heal (ADR-0014) evidently
closed the gap between the two sessions. I did not trigger it; it had already run.

## 2. How the layer acted on THIS very turn

**Line-1 token: `SEARCH`.** This is real reporting work; the enforcer surfaced no preview for it
(see below), so per the doctrine I could not self-declare a skip — I committed to `SEARCH` and ran
`search_skills` in that same reply. It returned six hits, top `plugin-dev:Skill Development` **0.588**
— a *skill-authoring* skill, off-intent for "introspect a live governance layer and write a grounded
account." Nothing returned was even loosely adaptable. Lawful outcome (rule 2/3): query shown →
nothing fits → proceed under the command's own procedure. Not a self-declared bare skip; a
search-proven one.

**Did the per-turn enforcer preview surface anything? No — and that is the interesting part.** No
5-candidate `SKILL-FIRST · Preview for this task` block appeared in my context for this turn.
`enforcer.py` L466–467 explains it: `if not prompt or prompt.startswith("/"): return 0` — a
slash-command entry (`/experience-skill-concierge`) is pre-gated out before any embed, retrieve,
floor, or offer runs. So the enforcer contributed **zero** retrieval to this turn; the only
skill-first pressure was the SessionStart doctrine + my own manual `search_skills`. (I mark the
"this exact turn hit L466" step as *reasoned from code*, not directly observed — I cannot see the
hook's stdin — but the observable absence of any preview is consistent with it.)

## 3. First-person account across each governance surface

**1. Library doctrine / skip classification — no loose-fit win this turn (honest gap).**
The exemplar's headline win was `what-next` at 18% getting *taken* where old behavior would skip.
This turn produced **no such take**: my search's best hit (0.588) was genuinely off-intent, so the
doctrine's correct output here was "proceed unaided, having *proven* it by search" — not "adapt a
loose fit." The doctrine still shaped me (it forced the search instead of a bare skip), but it did
not convert a marginal skill into a `USING:` because none existed. Reporting the null result as
loudly as the exemplar reported its win.

**2. AUTHORIZED-SKIP tier (`SKILL-CHECK`) — did NOT fire on me. The most-common gap, again.**
No `SKILL-CHECK:` line appeared in my context this turn. It could not: the turn entered as a slash
command and was pre-gated at L466 *before* the enforcer reaches either silent leg (getaway
score-floor / conversational intent-skip). So the D1-risk change — the getaway leg shipped ON
against ADR-0009's data — got **zero live pressure** here, exactly as in the 05:54 run. I saw its
`--selftest` contract pass in the code (L663–697 pin inject-on / silent-off) but never saw it act.
I will deliberately route trivial turns later to force it (see §4).

**3. Body-derived trigger points (ADR-0016) — present, not isolable.** doctor confirms the layer is
live: `3082 trigger points of 3570 total`, and ADR-0016's own evidence records the body-mining added
`+1339` points (2231 → 3570). But from a single session I cannot attribute any specific rank to the
body layer vs. the description layer — my one search returned no adaptable fit at all, so there is
nothing to credit or blame it for here. Correct honest stance: mechanism confirmed live, contribution
un-isolable.

**4. The friction — a self-imposed tax this turn, not an injected one.** Normally the tax is the
line-1 token + a 5-candidate preview to parse every turn. This turn the preview was *absent*
(slash-command pre-gate), so the only cost I paid was the one the doctrine made me pay myself: a
`search_skills` call that returned nothing usable. Cost = one tool call + one parse. Bought = a
*proven* "nothing fits" instead of an *asserted* one. That is the asymmetric-cost bet ADR-0015 makes
explicit — a cheap needless search vs. the top-severity failure of a false "nothing fits" on real
work. This turn it cost seconds and bought honesty; I felt both sides.

**5. The boundary — what the layer does NOT touch.** It governs skill *selection*. It does nothing
for **the correctness of this report's claims**. Nothing in the retrieve/enforce/ledger stack checks
whether my quoted version is right, whether my grep lied, or whether my "L466 pre-gated this turn"
inference holds. A confidently-wrong introspection report would pass every gate the layer owns. That
verification is a *different* apparatus (the self-check footer / a validator), not this one. The
05:54 run hit the same wall from the input side (stale handoff fed to a correctly-chosen skill); I
hit it from the output side (unverifiable claims flowing through a correctly-null skill search).

**6. My own process — graded at the bar I'd hold another agent to.** Reasonably clean this turn, with
two honest soft spots: (a) I state the enforcer pre-gated *this specific turn* at L466 — that is a
code-grounded inference, not an observation, and I flagged it as such rather than dressing it as
lived fact; (b) my version check had to step around 22 cache copies to find the one live path — I got
it right, but a lazier read would have grabbed a cache hit and reported a wrong "live" version. The
layer would not have caught either mistake; I had to.

## 4. Standing lens for the rest of this session

I keep watching the layer act on me. After ≥3 more real task-turns I append a **LIVE ADDENDUM**, and
I will **deliberately route at least one trivial / conversational turn** (a short non-imperative, >3
words so it clears the `MAX_SHORT_WORDS` pre-gate and actually reaches the enforcer's intent-margin
leg) — this is the single surface both this run and the 05:54 run failed to exercise, and the one the
D1 override most needs live pressure on. If a `SKILL-CHECK:` line fires, I quote it verbatim.

## Unresolved

- **AUTHORIZED-SKIP legs — still zero live exercise.** Both this run and 05:54 never tripped either
  silent leg. Needs the deliberate trivial-turn routing in §4, plus the ~50–100 organic offered-turn
  `skill-usage-audit` window ADR-0015 calls for.
- **Slash-command blind spot.** Turns that enter as `/command` bypass the enforcer entirely (L466), so
  the *only* governance on them is the SessionStart doctrine + agent discipline. Not a defect (the
  user already chose a route), but worth naming: a meaningful class of task-turns gets no per-turn
  retrieval at all.
- **Body-trigger contribution** — un-isolable from one session; real measure is organic adoption via
  `analyze.py`, not the wrong-universe vendored `eval/`.
- **"L466 pre-gated this turn"** — inferred from code, not observed from the hook's stdin; consistent
  with the observed absence of a preview but not directly proven.
