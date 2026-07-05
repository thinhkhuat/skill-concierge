# Opus Adversarial Validation — Final Syntheses (skill-concierge direction)

**Date:** 2026-07-04 · **Mode:** READ-ONLY, adversarial reproduction (independently re-ran every
load-bearing number; nothing applied) · **Model:** Opus 4.8
**Subjects:** (1) integrated-final direction report [PRIMARY]; (2) OG-vs-fork audit synthesis;
(3) OpenSpace transferable-innovations synthesis.

## VERDICT: PASS (with 4 advisories — one material)

Every thesis-critical claim SURVIVED independent reproduction. The verdict is not FAIL or PARTIAL
because no reproduced number was found to be fabricated, and no advisory flips a roadmap decision. The
one material advisory (the 63% headline blends subagent burst traffic) *sharpens* the number without
overturning the conclusion, and the report itself already names its root cause as the top gap.

---

## Thesis-critical claims: what survived, what bent

| Claim | Reproduced? | Verdict |
|---|---|---|
| Dodge ~62-63% (global) | 389/624 = 62% | CONFIRMED |
| Offered-turn conversion 10% / dodge 90% | 34/316 = 11% / 89% | CONFIRMED (11%, rounds to the reported 10%) |
| Recent bypass "63% embed_timeout" | recent-150 = 66% (fallback field) / 61% (band) | CONFIRMED as ~60-66%, but see A1 |
| "embed_timeout" is the literal fallback reason | `fallback:"embed_timeout"` in ledger rows | CONFIRMED |
| Worsening trend (recent >> lifetime) | lifetime 34% → recent 54-66% | CONFIRMED (trend even stronger than reported) |
| ~840 LOC inert graveyard, never fired | configs empty; 0 route/keep-off hits ever | CONFIRMED (2 of 5 proven, 3 inferred — as disclosed) |
| Engine novelties KEPT (warning/health/dark-stale) | present in `server.py` | CONFIRMED |
| OpenSpace closed loop real: 226 skills, gen 0-3 | gdpval DB = 226, gen 0/1/2/3 = 159/37/23/7 | CONFIRMED exactly |
| Description-trigger A/B measured (11.3→25.0%) | real held-out experiment, 14 skills mpnet | CONFIRMED |
| Body-trigger A/B never ran | no Phase-7 report; harness has no body kind | CONFIRMED |

---

## Findings

### [ADVISORY — MATERIAL] A1. The "63%" headline blends subagent burst traffic at 94% fallback
- **Claim:** "63% of recent turns hit `embed_timeout` → the semantic stack is bypassed most of the time"
  (primary line 45; D2 line 34, scoped to "recent-150 offer events").
- **What I did:** Loaded the raw ledger (`~/.claude/skill-telemetry/logs/skill-invocation-ledger.log`,
  1566 lines, 592 offer events). Recent-150 fallback = 99/150 = **66%** by fallback-field, 91/150 =
  **61%** by `band=="fallback"`. Split the traffic by prompt type: `<task-notification>` offers
  (subagent fan-out completions) run at **60/64 = 94% fallback**; normal prompts at **141/528 = 27%**.
  Inside recent-150, task-notifications are 38 rows at 100% fallback; **normal-only recent fallback is
  61/112 = 54%** (last-150 normal-only offers = 55%).
- **Verdict:** CONFIRMED-BUT-INFLATED. The 63% headline mixes two populations. Subagent burst traffic
  (concurrent embed load → timeout) is 11% of lifetime offers and ~25% of the recent window, and it
  fires at 94% fallback — mechanically inflating the headline. The honest "recent *genuine-turn*
  bypass" is ~54-55%. **Still a majority, still sharply up from 27% lifetime-normal** — so the thesis
  ("majority of recent real turns bypass the stack; worsening") holds. But "63%" is not the rate a
  single interactive user should expect; it is a load-contended, multi-agent-session number. The report
  partially self-protects: its #1 recommendation names the root cause as "uninstrumented … the shim
  under contention" — which is exactly this. Recommend the reports restate the headline as
  "~55% of recent genuine turns (≈63% including subagent burst traffic)".
- **Evidence:** `enforcer.py:466` pre-gates only `/`-prefixed prompts; task-notifications pass through
  and are logged as turns. Daily fallback: 06-27 12%, 06-28 10%, 07-01 36%, 07-02 78%, 07-04 58% — the
  spike spans 3 days / 8+ sessions (not one session), correlating with heavy multi-agent days.

### [ADVISORY] A2. Lifetime fallback is 34%, not the reported "29%"
- **Claim:** D2 line 34: "lifetime 29%".
- **What I did:** 201/592 offer events carry a truthy fallback = **34.0%** lifetime.
- **Verdict:** MINOR FACTUAL SLIP, direction-safe. The real lifetime baseline is *higher* than stated,
  so the "worsening" delta the report leans on is understated (conservative). No decision impact.

### [ADVISORY] A3. "10% conversion = enforcement net-negative" partly conflates false-offer noise
- **Claim:** "when it runs, 10% conversion / 90% dodge … Added machinery = measured net-negative-to-flat."
- **What I did:** Reproduced 34/316 = 11%. Read `_offer_conversion` (`analyze.py:112-132`): the 90%
  "dodge" counts every `band=="offer"` turn where the agent took none of the ≤5 offered skills. The
  per-skill table shows near-zero-take offers (skill-search 0/20, hooks-audit 0/20,
  agentmemory:session-history 0/33) — i.e. a large share of the 90% is *correctly-ignored tangential
  offers*, not non-compliance. The report's own D2 note (`deterministic-routes.json`) states "this
  system's dodge is dominated by FALSE offers."
- **Verdict:** DEFENSIBLE-BUT-OVERTIGHT. The number is real; the "net-negative" framing is fair for the
  *infrastructure cost/benefit* reading (heavy stack delivers "OG-plus-nothing" most turns) but would
  be an overclaim if read as "agents ignore good offers 90% of the time." The integrated final hedges
  correctly by sequencing ("enforcement is unjudgeable while its retrieval is bypassed", line 78), so
  this is a framing caveat, not a broken claim.

### [ADVISORY] A4. Delete-safety of the graveyard is proven for 2 of 5, inferred for 3 — as disclosed
- **Claim:** roadmap #2 "DELETE the inert graveyard … zero behavior change (they never fired)."
- **What I did:** `config/deterministic-routes.json` → `"routes":[]`; `config/keep-off.json` →
  `"keep_off":[]`. Ledger: 0 offers with a score-1.0 signature, 0 `dropped` fields ever (the 4 grep
  hits are the words "dropped"/"deterministic" inside user *prompt text*, not events). `enforcer.py`
  gates routes on `ENFORCER_DETERMINISTIC` (L206), tau default-INERT (L158), dominance default-inert
  (L372). enrich_index.py (324 LOC) is a standalone legacy script.
- **Verdict:** CONFIRMED SAFE on default config. Per-skill-τ and dominance-collapse "never armed" is
  *inferred* from "no env flag set anywhere" (a negative), not a positive ledger signal — the reports
  label this precisely (D2 line 192; primary Gaps "proven for only 2 of 5"). Honest hedging intact.

---

## Secondary confirmations (no defect)
- **Engine novelties kept:** `server.py` has `_staleness_warning()` (L150), `health()` with
  `dark_skills`/`stale_points` (L498-528), disk-vs-index drift manifest (L89-159). Not broken by the
  multivector/body-trigger patches. CONFIRMED.
- **OpenSpace closed loop:** gdpval_bench DB = **226 skill_records**, lineage_generation 0-3
  (159/37/23/7), 132 `skill_judgments` over 90 `execution_analyses` ("did each skill help?"), 45
  `derived` + 141 `captured` origins. The self-rewrite lineage is real and shipped. The REJECT of
  auto-*generation* is evidence-plausible (226 records with 141 captured = sprawl vs a curated
  catalogue); the ADOPT of auto-*improvement* (derived/generation progression) is the working half.
  CONFIRMED. (showcase DB is a smaller 77-record instance — same schema, same mechanism.)
- **Body-trigger UNMEASURED:** `multivector_experiment.py` builds its shadow from description-derived
  `eval/triggers.json` and has no body-trigger point kind (D3 line 82-85); no Phase-7 validation report
  exists in `plans/reports/`. Note `phase-07-validation.md` is `status: completed` yet its "A/B smoke
  run" checkbox is unchecked — corroborates "never ran." Reports hedge this correctly as UNMEASURED.
- **Description-trigger MEASURED:** rank-1 11.3→25.0% traces to a real held-out A/B (14 skills, 168
  positives / 70 negatives, mpnet-768) — `d3` §2. Correctly caveated "14 of 495 skills."

---

## What did NOT survive cleanly
Nothing was refuted outright. Two numbers bent under scrutiny, both in the report's favor's *opposite*
direction (i.e., honest-to-conservative): the "63%" is inflated by subagent traffic (real genuine-turn
rate ~55%, A1), and the "29% lifetime" is actually 34% (A2, understating their own trend). Neither
flips a recommendation.

## UNVERIFIABLE
- **"Will closing the loop lift OUR conversion?"** — correctly labeled UNMEASURED/extrapolated by the
  reports; I cannot verify a future counterfactual. Honest hedge stands.
- **OpenSpace "duplicate families" sprawl claim** — I confirmed 226 records and derived lineage but did
  not enumerate duplicate skill *families*; the sprawl magnitude is supported, the "duplicate" adjective
  is not independently verified here.

## Internal consistency across the 3 reports
Consistent. The integrated final's STRONG/MODERATE/UNMEASURED tiers match the underlying D-reports'
evidence strength. STRONG claims (engine kept, graveyard inert, stack bypassed, OpenSpace loop real) all
reproduced. UNMEASURED items (body-trigger lift, loop-lifts-our-conversion) are correctly fenced off
from the STRONG ones. The evidence-strength labels are honestly applied — no STRONG claim was found to
rest on UNMEASURED ground.

---

## THE SINGLE MOST IMPORTANT THING TO FIX BEFORE ANY BUILD DECISION
**Disaggregate the "63%" before it drives the roadmap.** The number that anchors the entire "stop adding
machinery, fix the bypass" thesis is a blend of (a) genuine user turns bypassing at ~55% and (b)
subagent task-notification burst traffic bypassing at 94% under concurrent embed load. These are two
different problems with two different fixes: (a) is a shim/contention regression worth instrumenting;
(b) may be as simple as gating `<task-notification>` prompts out of the enforcer entirely (they are
subagent-completion echoes, not a user asking for work — the same reason `/`-prefixed prompts are
pre-gated at `enforcer.py:466`). Roadmap step #1 ("INSTRUMENT + FIX the 63% embed_timeout regression")
is correctly sequenced FIRST, but its own framing should split these two populations, or the fix will
chase a contention artifact that partly self-resolves once subagent traffic is gated. Everything
downstream (judging enforcement, sizing the feedback-loop investment) inherits this number's honesty.
