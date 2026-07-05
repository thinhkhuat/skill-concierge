# OpenSpace → skill-concierge: fit-rated innovation harvest (synthesis)

- **Date:** 2026-07-04 23:31 (Asia/Saigon)
- **Method:** `study-extract-integrate` — mine an external reference for material to fold into the user's own project, by *adapting, never copying*. Fit-rated against skill-concierge's actual constraints, not against how good the idea is in OpenSpace.
- **Reference:** [HKUDS/OpenSpace](https://github.com/HKUDS/OpenSpace) — self-evolving skill engine, **MIT**-licensed. Studied read-only as an inert artifact.
- **Target:** skill-concierge — a skill-**governance** layer over Claude Code (Retrieve + Enforce + Ledger).
- **Team:** 4 parallel specialists, one per subsystem; each cited `file:line` on both sides. Individual reports: `lane-1..4-*.md` in this directory.
- **Status:** analysis complete; no code integrated yet.

> ⚠ **EPOCH-VALIDITY CAVEAT** — added 2026-07-05; supersedes any current-state reading of the ledger figures in this report.
>
> **Corrected mental model:** *In a system whose configuration changes almost daily, its telemetry is a sequence of short epochs, not one dataset — a metric is only valid for the config epoch it was collected under; pool across epochs and you measure a system that never existed.*
>
> Every ledger/telemetry figure cited here — offer→take, "~94% dodge", cosine 0.414 vs 0.457, any conversion/fallback rate — is **epoch-specific**, mostly **ADR-0009-era (v0.6.1, 2026-06-29)**, and must NOT be read as current-state. skill-concierge shipped ~8 config epochs in 8 days, including the **v0.10.0 multi-vector retrieval swap** whose own CHANGELOG says *"re-measure before reuse"* — so pooling across, or carrying a number past, an epoch boundary is invalid. The only valid read is per-epoch (`analyze.py --since/--until` at version-bump commit timestamps); the current epoch (v0.12.0) has N≈15 surfaced offers — **insufficient for any rate**. Corrected per-epoch figures accompany these reports in this directory.

---

## The one through-line

Every lane converged on the same gap:

> **skill-concierge measures whether a skill was *offered and used*; OpenSpace's entire advantage is that it observes whether a skill *actually helped* — and feeds that back into retrieval, selection, and curation.**

The unlock, verified in code: OpenSpace's per-skill effectiveness is **not** the execution telemetry you'd assume a selection-only tool could never obtain. `skill_applied` is an **LLM judgment over the transcript** (`skill_engine/types.py:171-179`) — and skill-concierge *already owns a transcript reader* (`skill-usage-audit`). That single fact is what makes most of the harvest portable.

So the meaningful upgrade is **not** "copy the evolution engine" (Lane 4: ~85–90% of it — authoring, executing, versioning skills — is out of scope by design). It is: **close the loop from "used" to "helped," then let retrieval / enforcement / curation act on that signal.**

---

## Tier 1 — HIGH value, fits skill-concierge's axioms

| # | Port | From (OpenSpace) | Into (skill-concierge) | Role | Lane |
|---|------|------------------|------------------------|------|------|
| **1** | **Follow-through judge** — split today's offer→take into *took-and-followed* vs *took-and-ignored* via an LLM pass over the transcript | `types.py:171-179`, `store.py:573` | `scripts/analyze.py:112-132` | the **sensor** the system lacks | 2 |
| **2** | **WORKFLOW-vs-REFERENCE consumption framing** — mandate tells the model *how to consume* the skill: "if it has step-by-step commands, **follow them — they are verified workflows**" | `registry.py:614-629` | `hooks/doctrine/` + enforcer mandate | cheapest attack on false-SKIPPING | 3 |
| **3** | **BM25 lexical fusion into the dense MAX-pool ranker** (fuse via RRF/max-blend, do **not** copy the cascade) | `skill_ranker.py:264-312`, `search_tools.py:404-425` | `vendor/.../server.py:431-462` | top LLM-free recall lever | 1 |
| **4** | **Graduated telemetry prior + description-repair flag** — soften ADR-0011's hard drop into a soft rank penalty; surface chronic never-take skills as "your description mis-sells this → repair," not a silent drop | ranking prior `registry.py:382-407`; health diagnosis `evolver.py:1573-1579` | ADR-0011 offer-suppression + the ranker | the **actuator** for #1's signal | 1 + 4 |

### Why these four, in plain terms

- **#1 (sensor).** Today `offer→take` proves a skill *fired*, not that it *helped* — ADR-0009 even found the current proxy anti-correlated with adoption. An LLM pass over the same transcript turn, asking "did the agent's actions track the SKILL.md steps or invoke-and-ignore?", turns gate-compliance data into a real usefulness signal. Needs nothing new: the transcript reader and the post-hoc cadence both already exist.
- **#2 (cheapest win).** Pure in-generation text, zero hook cost. Agents emit `USING` then wing it partly because the mandate says *use a skill*, never *execute its steps*. A consumption instruction converts the token from a label into a committed action.
- **#3 (recall).** Dense mpnet "measures topic, not intent" and under-scores exact tokens / rare API names / acronyms (`supabase`, `k6`, `WCAG`). A BM25 signal over the same corpus rescues them — LLM-free, ~ms at this catalogue size. Critical adaptation: **fuse** so lexical can *promote* rank; don't copy OpenSpace's cascade, whose "cosine decides final order" throws the benefit away.
- **#4 (actuator).** The response to #1's signal: down-rank *softly* (with a new-skill grace floor) and *tell the author why*, upgrading ADR-0011's binary cliff into a graduated signal + a fix suggestion.

### Dependency & sequence

**#1 is the sensor; #4 is the actuator.** #4 only beats today's behavior if #1 lands first — otherwise it re-uses the same weak `offer→take` proxy ADR-0009 already flagged. **#2 and #3 are independent, cheap, parallel wins.**

Recommended order: **#2 (text, instant) → #3 (retrieval A/B) → #1 (judge) → #4 (act on the judge).**

---

## Tier 2 — worth it, deferred or conditional

- **Bind the `USING /x` token to a named first action** ("USING /officecli — first running its xlsx step"). Cheap; pairs with #2. A bare token is trivially faked; a named action is self-coherent with doing it. (`registry.py:688-704`, Lane 3)
- **Single decisive pick over shop-from-5** — when one candidate clears a high margin, inject *that one* with workflow framing instead of a rejectable menu (closes the "none of these five fit → skip" dodge). Adopt **only** when the margin is decisive, else keep the menu. (`registry.py:340-504`, Lane 3)
- **Retrievability linter** — promote `build_triggers.py`'s existing empty-trigger detection (`:99-112`) into a first-class "this description is too thin to retrieve" signal. (Lane 4)

---

## Explicitly rejected — what does NOT transfer (the honest column)

| Rejected | Why | Lane |
|---|---|---|
| **Post-hoc analyzer / Stop-gate** | *is* the behavioral-compliance solver but it's post-hoc — skill-concierge deliberately rejected this as **anti-caveman** ("lets the dodge complete, spends the tokens, then catches it," `mental-model.md:168-176`). Adopting it reverses the owner's design call. | 3 |
| **Skill execution / delegation to a grounding agent** | violates the no-execution axiom. It's *why* OpenSpace has no false-SKIPPING (removes agent discretion by executing) — but skill-concierge must buy compliance with in-generation commitment instead. | 3 |
| **`completion_rate` / `task_completed` + all tool telemetry** (success rate, latency, failure streaks) | **impossible** — needs task-success ground truth from an execution harness skill-concierge doesn't have. Honest metric stops at "offered → followed," never "→ succeeded." | 2, 4 |
| **"When in doubt, leave it out" cost polarity** (`registry.py:696`) | **inverted** for skill-concierge. OpenSpace burdens the *select* because a wrong pick derails a 20-iteration auto-run; skill-concierge only *offers*, so a wrong **skip** is its top-severity failure. Copying this breaks its burden-of-proof-on-SKIP doctrine (ADR-0015). | 3 |
| **Full FIX/DERIVE/CAPTURE evolver + patch engine, fuzzy-match, cloud sharing, LLM-in-the-hot-path** (plan-then-select, query expansion) | out of scope by design or by the cheap-hook axiom. | 1, 4 |

Roughly **85–90% of OpenSpace's evolution engine is deliberately left out** — it authors/executes/versions skills, which a selection-only governance layer does not do. The residual value is a **signal/suggestion layer**, never an evolution loop.

---

## Caveats / unresolved

- **#3's magnitude is reasoned, not measured** — it wants a shadow A/B on skill-concierge's own eval (same harness as ADR-0012) before shipping default-on.
- **#1/#4 precision ceiling** — both lean on the `offer→take` family ADR-0009 flagged as a weak/anti-correlated proxy; the follow-through judge is a *new reading* of it, so it inherits that signal's quality until validated on a live transcript sample.
- **Lane 4 row 2 (quality scorer)** is a README claim with no verified implementation — directional inspiration only.
- Subagents did not read `enforcer.py`/`ledger.py` in full (grep-scoped by instruction); the follow-through / abandon-rate designs are grounded proposals, not verified against a live transcript sample.

## Attribution

Ideas mined from [HKUDS/OpenSpace](https://github.com/HKUDS/OpenSpace) (MIT). Concepts were re-interpreted for skill-concierge's selection-only design — **adapted, not copied**; no OpenSpace source was transcribed into the target.
