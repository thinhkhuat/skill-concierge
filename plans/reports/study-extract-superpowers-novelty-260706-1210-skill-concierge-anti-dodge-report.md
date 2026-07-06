# Superpowers → skill-concierge: Novelty Extraction (anti-dodge / skill-routing)

**Date:** 2026-07-06 · **Skill:** study-extract-integrate · **Mode:** extract + fit-rate + scope-gate (analysis; no code changed)
**Reference (read-only artifact):** superpowers v6.1.1 — Jesse Vincent / Prime Radiant — MIT — `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/CLONED/superpowers/6.1.1/`
**Evidence:** two delegated read-only agents (target framing `a2874a5a...`, reference study `ad2113e9...`). All `path:line` below are their cited reads; **not independently re-opened this turn** — re-verify target files at integration time (skill step 8 QA).

---

## Thesis (the reason this pairing works)

The two repos are **complementary opposites**:

- **skill-concierge = retrieve-precisely + enforce-in-generation.** Rich semantic layer (Qdrant + multilingual mpnet, MAX-pool fusion, body-derived triggers). But governance is *purely in-generation doctrine* — it deliberately rejected any post-hoc gate. Its own docs: *"Compliance is unmeasured, not solved. The doctrine is a design hypothesis; uptake lift is unproven"* (`skill-first-enforcement-mental-model.md:288`); *"the only lever is the doctrine's quality and constant presence"* (`:290-293`). Founding finding: model was offered good skills and still improvised — *"~14–18% uptake, flat before vs after a retrieval upgrade. Better candidates did not raise usage"* (`three-organs.md:23-24`).
- **superpowers = zero retrieval, doctrine-maximal.** No index, no embeddings, no search tool — *confirmed absence*. It bets everything on (1) a SessionStart hook injecting one meta-skill and (2) hand-tuned "Use when…" descriptions matched by the harness's native loader, backed by hard anti-skip doctrine.

**So:** concierge's weakest, highest-stakes layer (doctrine craft that stops the model dodging) is exactly the layer superpowers spent 100% of its engineering on. That is the harvest. We do **not** import superpowers' *discovery* model — concierge's is strictly better. We import its *anti-skip doctrine craft* and one measurement method.

This maps 1:1 onto your three asks: (1) right skill/right time → SDO trigger-purity; (2) reason about non-applicability on trivial tasks → Red Flags refutation craft; (3) stop dodging + fabricated skip rationale un-noticed → the TDD-the-doctrine loop.

---

## Target gaps this must serve (skill-concierge, self-admitted)

| # | Gap (concierge's own words) | Source |
|---|---|---|
| G1 | Compliance unmeasured; better candidates didn't raise usage | `mental-model.md:288`, `three-organs.md:23-24` |
| G2 | In-generation governance is the whole bet; **no fallback lever** — doctrine quality is the only knob | `mental-model.md:290-293` |
| G3 | Ledger contamination: subagent + meta traffic makes fusion lift **unmeasurable** on one shared ledger | `mental-model.md:164-167` |
| G4 | Anti-dodge is *self-attested only* — FALSE-REPORT ban has no in-turn detector; only an offline transcript audit catches false skips | `skill-first.md:38-39`, `audit_skill_usage.py:106-126` |
| G5 | Threshold tuning "out of road" — remaining lever is index **content**, not gates | `enforcer.py:161-164` |

---

## Fit table — extracted "goodies" rated against skill-concierge

Rated against concierge's audience/constraints, **not** against how good they are in superpowers.

### HIGH — portable, fits, slots into a specific existing unit

| Goodie (superpowers) | Evidence | Target unit in concierge | Net-new angle (what to actually add) |
|---|---|---|---|
| **H1. TDD-the-doctrine loop.** RED = run a pressure scenario on a subagent *without* the skill, capture the exact rationalizations *verbatim*; GREEN = write minimal doctrine that neutralizes *those* rationalizations. | `writing-skills/SKILL.md:558-567` | The measurement gap G1/G2/G4. concierge already owns both ends: FALSE-SKIPPING detector (`audit_skill_usage.py:106-126`) as the RED corpus, and the epoch-windowed transcript audit as the GREEN metric. | Wire concierge's *own* false-skip transcripts as the rationalization corpus; refine `skill-first.md` doctrine to name the captured excuses; re-measure on a clean window. Closes the "doctrine is the only lever but it's unmeasured" loop with infra concierge **already has**. |
| **H2. Red Flags rationalization table.** Symptom-indexed: each row = the agent's own skip-excuse → its refutation, so it fires at the moment of temptation. | `using-superpowers/SKILL.md:34-50` | `skill-first.md:52-56` (rule 6, "Refuse these standing rationalizations") + the enforcer `SKILL-CHECK:` line. | concierge lists rationalizations as *prose*; superpowers ships them as a tight *table* indexed by symptom. Convert concierge's prose to a symptom→refutation table; this is the concrete artifact H1's loop produces and sharpens. |
| **H3. `<SUBAGENT-STOP>` guard.** A dispatched subagent ignores the always-on meta-skill. | `using-superpowers/SKILL.md:6-8` | Directly attacks G3 (ledger contamination) + wasted enforcement on scoped subagents. concierge's `doctrine.py` injects at SessionStart unconditionally. | Detect subagent/meta sessions and skip (or tag) doctrine injection — cleans the measurement H1 depends on, and cuts effort spent enforcing on subagents that shouldn't route. Small, concrete, reversible. |
| **H4. SDO law — descriptions/triggers must be *pure triggers*, never workflow summaries.** Empirically: a workflow-summary in the description makes the agent follow the description and skip the skill body (observed: one review instead of two). | `writing-skills/SKILL.md:152-158` | ADR-0016 body-trigger extractor (`skills_discovery.py:66-69`, mines `Use when/Triggers/Examples`). | concierge mines decision-sections but has **no guard against workflow-summary pollution** in those sections. Add a trigger-purity lint to the extractor / a corpus-authoring rule → cleaner MAX-pool points → serves ask (1) "right skill at right time". |

### MEDIUM — worth deferring; seeds a future unit

| Goodie | Evidence | Why defer |
|---|---|---|
| M1. **"Update SDO for violation symptoms"** self-improvement loop — put the *symptom of about-to-violate* into the description so the skill re-surfaces at temptation. | `writing-skills/SKILL.md:544-549` | Depends on H1's harness existing first; then feed observed dodge-symptoms back into body-trigger points. Natural phase-2 of H1+H4. |
| M2. **Terminal-state routing** — a skill names its *only* legal successor, so the agent doesn't re-discover. | `brainstorming/SKILL.md:61` | Partly already solved by concierge's `SKILL-CHECK:` (stops re-running search to re-derive a verdict). A hard "next skill" over a ~500-skill corpus is brittle — offer as optional per-skill hint later. |
| M3. **Verification claim→proof gate table** ("Agent completed" → *VCS diff*, never self-report). | `verification-before-completion/SKILL.md:24-50` | Largely already covered by concierge's self-check footer (GROUNDED/LITERAL) + the separate effort-gate plugin. Marginal net-new. |

### LOW / NON-TRANSFER — flagged honestly (do NOT import)

| Rejected | Evidence | Why it does not transfer |
|---|---|---|
| N1. **The pure "1% rule" / no-discretion "always invoke".** | `using-superpowers/SKILL.md:11-13` | **Contradicts concierge's design.** concierge's library doctrine treats skip as a *lawful reasoned intent classification* (trivial errand vs real work) and even ships authorized-skip enforcer legs (ADR-0015). A blanket 1% "always invoke" over ~500 skills would raise the exact false-offers ADR-0009 tuned against, and override an operator decision. Carry the *framing* (name the temptation → H2); **drop the threshold**. |
| N2. **Description-matching-as-router / no-search discovery.** | `README.md:26`, superpowers has no index | concierge already has a strictly superior semantic layer. Importing superpowers' discovery model is a downgrade. Only H4 (description *craft*) transfers, not the dispatch model. |
| N3. Multi-harness scaffolding, zero-dep packaging, the brainstorming/verification *workflow* skills themselves. | `README.md:210-231` | Different domain — concierge is a governance plugin, not a dev-methodology suite. Out of scope. |

**Deliberately left out:** ~70% of superpowers by volume (the 14 workflow skills, multi-harness plugin code, git-worktree/plan-execution machinery). Reason: it's a *development methodology*; concierge is *skill-selection governance*. Only the anti-skip doctrine + one method transfer.

---

## Correction (do not propagate)

The tokens `máy-soi`, `A3⚠claim-no-tool`, `misselect⚠` from the tasking **do not exist in the skill-concierge repo** (full-repo search, agent `a2874a5a`). They live in your **global harness footer hook** (`~/.claude`), a separate layer. Notably: superpowers *also* has no live dodge-catcher — it too bets on in-generation doctrine + a SessionStart hook. So the extracted direction **reinforces concierge's existing bet (better doctrine), it does not argue for a new post-hoc gate** (which concierge explicitly rejected).

---

## Recommended scope — Bundle B: the anti-dodge loop (H3 → H1 → H2)

The three HIGH items form one coherent, self-contained loop that hits all three of your asks and respects concierge's "no post-hoc gate" bet:

```
H3 subagent-stop  →  cleans the ledger (G3) so numbers are trustworthy
H1 TDD-doctrine   →  measures real dodges, captures the verbatim rationalizations (G1/G4)
H2 Red Flags      →  encodes the refutations into skill-first.md doctrine (G2)  → re-measure
```

Low-risk, reversible, uses infrastructure concierge already owns. **H4 (SDO lint)** is orthogonal corpus-quality work touching all skill authoring — recommend as a *separate* Bundle C, not folded in.

**Deploy caveat (before any of this goes live):** a repo edit is inert until `plugin.json` + `marketplace.json` are bumped, pushed to GitHub, then `/plugin update` + restart (runtime reads a version-pinned cache). Governance-file edits are load-bearing + versioned — hence the scope gate below.

---

## Attribution

Ideas above adapted (not copied) from **superpowers v6.1.1 by Jesse Vincent (jesse@fsck.com) / Prime Radiant, MIT license** — `https://github.com/obra/superpowers`. Concepts carried into concierge's own voice/design; no text lifted.

## Deferred stubs (harvest recorded, not lost)

- **M1** self-improving trigger symptoms → phase-2 of H1+H4.
- **M2** terminal-state "next skill" hint → optional per-skill field, post-corpus.
- **M3** claim→proof gate table → only if footer/effort-gate coverage proves insufficient.
- **Bundle C / H4** SDO trigger-purity lint on the body-trigger extractor.

## Unresolved / honest status

1. Evidence is **agent-relayed**, not independently re-opened this turn — re-verify the exact target files (`skill-first.md`, `doctrine.py`, `skills_discovery.py`, `audit_skill_usage.py`) before editing.
2. concierge has **no live "did the skill help" metric** — H1's re-measure is a *compliance/dodge-rate* signal (epoch-windowed), not an outcome-quality signal. Don't overclaim usefulness lift.
3. Integration (skill step 6+) is **not started** — gated on the scope decision below.
