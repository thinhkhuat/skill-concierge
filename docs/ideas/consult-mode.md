# consult-mode — a deliberation layer over the reflex layer

Status: design accepted 2026-08-29 (four decisions locked below); seed for ADR-0049.
Origin: evening session 2026-08-29, idea-refine dialogue. Owner: Thinh.

## Problem statement

How might we give the user an opt-in, reasoning-driven planning step — "consult the
best skill combo for this task" — where an agent deeply reads actual skill bodies
(installed + external) and composes a chain, as a counterweight to the cheap per-turn
embedding offer?

The per-turn enforcer offer is a **reflex**: it must be cheap because it fires every
turn, so it answers "which skill, fast" and can never read bodies or compose chains.
At ~500 skills, human curation is impossible. What is missing is **deliberation**:
opt-in, expensive-allowed, reasoning-driven.

## Recommended direction (locked 2026-08-29)

1. **Home:** new plugin skill `skill-concierge:consult`, absorbing the
   `which-skills` workflow and render (which-skills retires to a shim).
2. **Depth:** dossier layer (precomputed per-skill capsules) + live full-body reads
   for the ~10-15 finalists.
3. **Trigger:** explicit invocation + enforcer consult-intent phrase routing.
4. **Externals:** first-class picks marked `[external]`, promoted via
   `catalogs.py` only on explicit accept.

## Mechanism — a four-stage funnel

Embeddings stop being the decider and become the sieve:

```
task ─→ ① SIEVE      engine recall (installed + external, blocklist-aware,
                      multi-sub-goal queries) → ~20 candidates + capsules
     ─→ ② DEEP READ  analyst subagent (sonnet-class) reads FULL bodies of the
                      finalists (Read for installed, get_skill for externals)
                      → ranked fit/overlaps/gaps JSON, grounded in bodies
     ─→ ③ COMPOSE    main agent merges with session context → chain shape,
                      order, handoffs, promote list → RUN/⚠/ALSO card
     ─→ ④ COMPOUND   verdict + takes logged as ledger `consult` rows →
                      feeds mined chains (ADR-0040): the deliberate layer
                      trains the reflex layer
```

- **Dossier layer**: structured capsule per skill (identity, capabilities,
  inputs/outputs, overlaps, freshness). Generation rides the flywheel's
  bounded-parallel workers (ADR-0043 pattern — capsules are a second artifact type
  from the same machine); staleness rides the content-fingerprint detector
  (ADR-0024). Target ~150-300 tokens per capsule.
- **Bias guard for externals**: the analyst ranks on fit from bodies;
  installed-status is carried as logistics metadata, so origin cannot quietly win
  the ranking. The RUN card marks `[external]` rows and prints the one-command
  promote; promote fires only on explicit accept.
- **Enforcer routing**: a consult-intent phrase class ("which skills for X",
  "plan a skill strategy") makes the turn emit `USING: skill-concierge:consult`
  via the existing skill-first mandate machinery. Subagent sessions never route.
- **Cost model**: zero per-turn change — consult is opt-in; the enforcer offer
  logic is untouched except the routing class.

## Key assumptions to validate

- [ ] **Capsule signal** — a ~200-token LLM capsule beats metadata-only for
  shortlisting. Test: A/B on ~10 real tasks, human judges the ideal pick's rank.
- [ ] **Analyst context budget** — ~15 full bodies + capsules fit a 200K subagent
  with room to reason. Test: dry run with the largest skills on the shelf.
- [ ] **Routing precision** — replay recent real prompts against the
  consult-intent class; count false routes before shipping.
- [ ] **Flywheel endpoint budget** — ~500 capsules as one bounded run +
  incremental on body change; confirm provider tolerance.

## MVP scope (phased)

1. Capsule layer — schema + flywheel-worker generator + fingerprint staleness.
2. Sieve verb — engine call returning shortlist + capsules + external rows.
3. `skills/consult/SKILL.md` — funnel workflow, analyst template, composer,
   RUN/⚠/ALSO render, promote path.
4. Ledger `consult` events feeding mined chains.
5. Enforcer consult-intent routing (phase 2 — explicit invocation ships first).
6. ADR-0049 + version bump + docs sweep.

## Not doing (and why)

- No per-turn cost change — enforcer offer logic untouched except the routing class.
- No deliberation panel (multi-reader fan-out) — single analyst first; escalate
  only if proven weak.
- No auto-promote — externals promote only on explicit accept.
- No capsule consumption by the enforcer annex — future, separate ADR if wanted.
- No cross-harness subagent spawning in v1 — consult runs inline on harnesses
  without a spawn primitive (documented fallback).

## Open questions

- Default depth when enforcer-routed: `--fast` (capsules only) vs `--deep`?
- Capsule generation on the flywheel's existing provider or a dedicated lane?
- Keep the name `consult`, or preserve `which-skills` muscle memory in the alias?

## Practice-run findings (dogfood, 2026-08-29)

Ran the designed mechanism manually on this very build task: engine sieve →
sonnet analyst subagent with a deep-read mandate → compose. Analyst artifact:
`plans/reports/consult-analyst-260829-2230-consult-mode-fit.md` (11 full bodies
read, Status DONE, ~4 min wall clock).

1. **Sieve recall gap is real and load-bearing.** The #1-ranked fit
   (`developing-claude-code-plugins`) and three other top fits were **missed by
   the embedding sieve** and admitted manually — their descriptions lack the
   task's vocabulary. Capsules + a wider consult top_k are not optional polish;
   they are the fix for the exact failure observed.
2. **Deep reading kills false positives the sieve cannot.** External
   `antigravity:agents-md` scored 0.86 on the sieve and LOW on body-read
   (orthogonal content). One of three served externals was genuinely relevant
   (`tool-design`, high fit for the sieve-verb contract). Body-grounded judgment
   inverted two sieve verdicts — the strongest evidence yet for stage ②.
3. **Analyst context budget holds at this scale.** 11 bodies + 1 grounding ADR
   fit a sonnet subagent with room to reason; report landed clean. Assumption #2
   validated at funnel width ~11 (design says ~10-15 finalists).
4. **The which-skills JSON contract survives unchanged** — absorb
   ranked/overlaps/gaps/suspect as the analyst return schema.
5. **Composer session-context overrides mattered twice**: the harness-enforced
   `~/.claude/docs/claude-code-component-building.md` (mandatory companion, on
   no sieve) and the repo's own ADR convention (both generic ADR skills demoted
   to references). Design addition for `skills/consult/SKILL.md`: the compose
   step must explicitly instruct merging repo-internal authority — enforced
   docs, repo conventions, session history — over the analyst's ranked list.
6. **External consumption path works verbatim**: `get_skill("<alias>:<skill>")`
   read-only inline; no promote needed for single-build reference use.
