# Anti-dodge integration (v0.14.0) — design, decision arc & caveats

**Status:** Planned for **v0.14.0** · **Owner decision:** Option B locked **2026-07-06** · **Base:** 0.13.1
**Plan:** [`plans/260706-1315-superpowers-anti-dodge-integration/plan.md`](../plans/260706-1315-superpowers-anti-dodge-integration/plan.md)
**Source study:** [`plans/reports/study-extract-superpowers-novelty-260706-1210-skill-concierge-anti-dodge-report.md`](../plans/reports/study-extract-superpowers-novelty-260706-1210-skill-concierge-anti-dodge-report.md)
**Reference (adapted, not copied):** superpowers v6.1.1 — Jesse Vincent / Prime Radiant — MIT — https://github.com/obra/superpowers

This is the **loud, single source of truth** for why skill-concierge is growing five anti-dodge
mechanisms at once, what each is, what we knowingly accepted, and where the traps are. Read it before
touching `enforcer.py`, `doctrine.py`, `skill-first.md`, the vendored engine, or the audit script.

---

## 1. The thesis (why this exists)

skill-concierge is **retrieval-strong, doctrine-underinvested.** The repo's own docs are blunt about it:

- *"Compliance is unmeasured, not solved … uptake lift is unproven"* — `skill-first-enforcement-mental-model.md:288`.
- *"the only lever is the doctrine's quality and constant presence"* — `:290-293`.
- The founding finding: the model was offered **genuinely-good** skills and still improvised — *"~14-18% uptake, flat before vs after a retrieval upgrade. Better candidates did not raise usage"* — `openwiki/architecture/three-organs.md:23-24`.

Superpowers is the mirror image: **zero retrieval**, all craft spent on anti-skip doctrine. So it is the
ideal donor for exactly the layer skill-concierge admits is its weakest and highest-stakes. We take its
**doctrine craft and one measurement method**, not its discovery model (ours is strictly better).

---

## 2. The five ideas (the original analysis — assessed valuable, kept in full)

The core loop is **H3 → H1 → H2**: clean the measurement, measure the dodges + harvest the real
excuses, encode the refutations, re-measure. **H5** and **H4** are parallel tracks.

| # | Idea | What it does | Target gap it closes |
|---|------|--------------|----------------------|
| **H1** | **Rationalization-harvest loop** | Turns the existing false-skip *detector* (`audit_skill_usage.py`) into a *harvester*: capture the verbatim `SKIPPING:` excuses agents actually used, feed them into doctrine, re-measure. | "Doctrine is the only lever but compliance is unmeasured." Uses infra concierge already owns. |
| **H2** | **Red Flags table** | Converts the prose rationalizations in `skill-first.md` into a symptom→refutation *table* that fires at the moment of temptation — the agent's own excuse is the key that retrieves the counter. | Prose read once at session-start blurs; a symptom-indexed table pattern-matches at the point of dodge. |
| **H3** | **Subagent session-scoping** | Stops injecting the doctrine into subagent/self/meta sessions and excludes them from the usage denominator. | Ledger contamination (a meta session alone swung uptake 17%→14%) + wasted enforcement on scoped workers. |
| **H4** | **Trigger-purity lint** | Rejects workflow-summary phrases from the MAX-pool trigger surface (a summary embeds near generic process-prose, not user intent → buries the skill). Ships shadow-first. | Applies superpowers' SDO law: triggers must be pure trigger-conditions, never workflow summaries. |
| **H5** | **Over-fire lane + gate legibility** | A narrow "explain-my-own-prior-output" authorized-skip lane so the gate stops forcing pointless searches on trivially self-referential turns. | The *over-fire* failure the doctrine has no symmetric guard against (see §3). |

Full fit-rating, non-transfers (the "1% rule" was rejected — it contradicts concierge's reasoned-skip
doctrine), and attribution: the **source study report** linked at the top.

---

## 3. The decision arc (how we got here)

1. **Study** superpowers v6.1.1 → extract the five above, fit-rated against concierge's real gaps.
2. **The live dogfood that birthed H5.** Mid-session, the enforcer gave two near-identical "explain the
   next item" turns opposite verdicts — one auto-authorized skip, one *forced a pointless `search_skills`*
   on a turn that obviously needed none. That is the **over-fire** mirror of a dodge: the gate guards hard
   against *under-firing* (skipping too easily) and has **no guard against ritualizing the trivial**. The
   severity model prices a needless search as "cheap," ignoring that every pointless search erodes the
   agent's trust in the gate exactly where real work needs it. H5 was added from this first-hand evidence.
3. **Plan** the 7-phase integration, grounded in the exact code anchors.
4. **Red-team** — 4 hostile reviewers, code-verified. Anchors held; they found real design bugs in the 3
   core mechanisms + argued for a smaller MVP (see §4, §5).
5. **Owner decision — Option B (2026-07-06):** ship all 5 in v0.14.0 with every *correctness* fix applied;
   overrule the *scope-cut* recommendation.

**Owner rationale (recorded, not paraphrased away):** rich lived experience with how this plugin actually
behaves outweighs 4 stateless, cold-boot reviewers on the *scope/value* call. The reviewers' *correctness*
findings are accepted and applied in full; only their instinct to defer H1/H2-v2/H4 to a later version is
overruled. Fixing all five is judged the higher-value path.

---

## 4. Red-team correctness fixes — APPLIED (the compass: more governance, not less)

All four reviewers converged: the three core bugs pointed *away* from the plan's own "burden of proof on
SKIP" doctrine. Every fix below is folded into the plan phases.

- **H5 was a bypass [Critical].** The enforcer sees only the *user* prompt (`enforcer.py:463`); "explain
  your answer **and implement X**" slipped the lead-token-only imperative check (`:408-430`), and an
  outright-skip would be scored *authorized* — invisible to H1. **Fix:** correct 2nd-person reference frame
  (user prompt operating on the assistant's prior message), **whole-prompt task-verb veto**, a **unique
  signature anchor + parity test**, and legibility deferred (it risked the audit's substring contract).
- **H3 failed the wrong way [Critical].** `doctrine.py` is fail-*silent* (`except→return 0` = **suppress**),
  and the SessionStart payload carries **no** subagent signal. **Fix:** audit-side exclusion is the primary
  deliverable; any `doctrine.py` edit fails *toward* injection (a top-level session must never lose the doctrine).
- **H1's "clean denominator" was impossible [Critical].** Turn dicts carry no `sid`; false-skips are counted
  before `meta_sessions` exists. Plus the capture read a stale `txt`, and the harvest leaked verbatim
  transcript text. **Fix:** `sid`-join promoted to first-class, capture at the match-site, gitignored +
  scrubbed sink, and an honest split of harvest (keep) vs re-measure (may be unmeasurable — see §5).

---

## 5. Caveats — accepted KNOWINGLY (the loud part)

These are the costs Option B takes on with eyes open. They are **not** open bugs; they are documented,
owner-accepted trade-offs. Anyone implementing or deploying must respect them.

1. **The re-measure leg may be "insufficient data" this epoch.** Per [`AGENTS.md` → Guardrails](../AGENTS.md),
   the ledger is a *sequence of short config epochs*; shipping v0.14.0 opens a **new** epoch, and this repo
   changes ledger inputs almost daily. The **harvest** leg of H1 is epoch-independent and keeps its value;
   the **re-measure** leg is contingent on a config-freeze window and may not close before the next change.
   Do NOT author H2-v2 from an unclean or too-small window; say **"insufficient data"** rather than pool.
2. **Reindex sits on the critical deploy path (H4).** Activating the purity lint needs the vendored engine
   re-copied into the stable venv + a **FULL** reindex (not incremental — a filter-logic change leaves a
   mixed-purity index otherwise) + MCP restart. H4 ships **shadow-first / off** at release; it activates only
   after its false-drop precision is measured on the live corpus.
3. **H4's purity heuristic is subjective.** "Workflow-summary vs trigger-condition" has no pre-existing
   ground truth. Shadow-first mitigates (log would-drops, drop nothing, review) but does not *prove* the spec
   is definable — watch for dropping legitimate "generate a report"-style triggers.
4. **Cross-plan coordination is a hard precondition.** `260628-0215-retrieval-enrichment-rollout` (in-progress)
   also does clean-window compliance measurement and touches `GETAWAY_FLOOR`. **Only one config-touching plan
   ships per epoch** — two overlapping T0 windows on the shared ledger produce an unattributable delta (its
   own red-team already caught this). Confirm before the H1 re-measure.
5. **The stale-engine trap gates release.** H2/H5 go live on `/plugin update` (cache path); the MCP runs the
   OLD venv engine until `setup.sh` reruns. `doctor "Engine venv ✓"` proves existence, not currency
   ([`caveats.md`](caveats.md) §11). Engine-freshness by content-hash (ADR-0013) is a **hard** release gate.

---

## 6. Guardrails specific to this work

- **Every new mechanism ships default-ON behind a one-var revert** (mirrors `ENFORCER_AUTHORIZED_SKIP` /
  `SKILL_BODY_TRIGGERS`): `SKILL_SUBAGENT_STOP` (H3), `ENFORCER_SELFREF_SKIP` (H5), `SKILL_TRIGGER_PURITY` (H4).
- **The `SKILL-CHECK:` cross-file contract is a literal, three-way coupling.** The enforcer emits a marker +
  *distinctive substring*; the audit matches that substring (NOT the bare marker); the selftest asserts the
  inject count. H5's 3rd lane must add a **unique** signature phrase to all three and a parity test — a generic
  anchor collides with the H2 doctrine-table row and miscounts real dodges as authorized.
- **Per-decision ADRs 0019-0023** (over-fire lane, subagent-scoping, harvest loop, Red Flags table, trigger
  purity) are authored in **Phase 1** of implementation and become the immutable record; this design doc is
  the narrative arc that links them.
- **Deploy = triple-bump** `plugin.json` + `marketplace.json` + `CHANGELOG.md` → 0.14.0, MINOR (additive).

---

## 7. Related

- Plan (7 phases, all fixes applied): [`plans/260706-1315-superpowers-anti-dodge-integration/`](../plans/260706-1315-superpowers-anti-dodge-integration/plan.md)
- Original 5-point study + fit table: [`plans/reports/study-extract-superpowers-novelty-260706-1210-…-report.md`](../plans/reports/study-extract-superpowers-novelty-260706-1210-skill-concierge-anti-dodge-report.md)
- The layer this hardens: [`skill-first-enforcement-mental-model.md`](skill-first-enforcement-mental-model.md), [`openwiki/architecture/enforcement-gate.md`](../openwiki/architecture/enforcement-gate.md)
- Operational landmines: [`caveats.md`](caveats.md) · Epoch rule: [`AGENTS.md` → Guardrails](../AGENTS.md)
- ADRs (forthcoming, Phase 1): `docs/adr/0019`–`0023`
