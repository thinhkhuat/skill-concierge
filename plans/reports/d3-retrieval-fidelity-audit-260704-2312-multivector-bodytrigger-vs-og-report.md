# D3 — Retrieval-Fidelity Audit: Multi-vector MAX-pool + Body-triggers vs the OG single-vector

**Dimension:** D3 (retrieval fidelity) · **Date:** 2026-07-04 · **Constraint:** READ-ONLY (nothing modified)
**Question:** Did the fork's engine patches (ADR-0012 multi-vector MAX-pool + ADR-0016 body-derived
triggers) genuinely IMPROVE retrieval over the OG's single full-description vector, or add topical
noise/dilution — and is the improvement **measured** or **asserted**?

**One-line verdict:** SPLIT. The **description-trigger MAX-pool (ADR-0012) is MEASURED and better**
on the fork's own index; the **body-trigger layer (ADR-0016, the +60% growth the charter asks about)
is UNMEASURED** — its promised A/B was never run and is documented as non-meaningful on the current
eval universe.

---

## 1. The two retrieval paths, contrasted (file:line)

**OG (skill-search 0.1.0) — one vector per skill.** The vendored source builds a single
`kind="base"` point per skill from `name + description + body[:4000]`
(`vendor/skill-search/skill_search/server.py:296-298` `_skill_text`) and ranks with a plain top-k.
The multi-vector/body-trigger toggles exist in the vendored file but are **engine patches the fork
added** (documented in `vendor/skill-search/VENDORED.md`); with them off, the vendored code is the
OG single-vector retriever.

**Fork patched path — many points per skill, MAX-pooled.**
- `server.py:82` — `MULTIVECTOR` default ON: each skill gets one base point PLUS one `kind="trigger"`
  point per intent phrase.
- `server.py:88` — `SKILL_BODY_TRIGGERS` default ON: body decision-sections also become trigger points.
- `server.py:276-293` — `_trigger_phrases(s)`: description phrases first, then body phrases deduped
  against them, **capped COMBINED at `_TRIG_MAX`=12** (`server.py:254`). Description phrases occupy
  the first ≤12 slots; body phrases only fill leftover slots.
- `server.py:296-298` — `_skill_text` (the base vector) is **untouched**; body signal is added as
  SEPARATE points, never blended into the base vector.
- `server.py:441-443` — retrieval is `query_points_groups(group_by="name", group_size=1)`: each skill
  scored by its single BEST point (MAX-pool). On a single-vector index this is identical to plain top-k.
- Body extraction: `skills_discovery.py:75-104` `_extract_body_triggers(body)` mines only labeled
  decision-sections (`## When to Use`, `Triggers:`, `Use when:`, `Examples:` …), stops at the next
  header or a `Do NOT use` exclusion line so exclusions naming OTHER skills don't leak in; exposed as
  `body_triggers` (`skills_discovery.py:145`).

**Mechanism claim — MAX beats MEAN.** The fork's prior attempt (`scripts/enrich_index.py`) averaged
trigger embeddings INTO the one base vector (MEAN centroid). ADR-0012 records that a *"centroid
dilutes the one distinctive phrase"* and was not reindex-robust — superseded by scoring a skill by its
best phrase point (MAX), on **separate** points (`docs/adr/0012-multi-vector-max-pool-retrieval.md:7-14`).
This is the correct representational move: MAX-over-separate-points cannot be diluted the way a blended
mean is. Note: there is **no single head-to-head MAX-vs-MEAN results table** — the MEAN path was found
inferior/inert and retired; the measured A/B (below) is MAX-multivector vs bare single-vector.

---

## 2. What was actually MEASURED — and it's only the description layer

**ADR-0012 description-trigger A/B — REAL numbers, held-out, on the fork's mpnet-768 index.**
Source: `plans/reports/experiment-260630-multivector-max-pooling-vs-bare-ab-report.md:31-41`; corpus
`eval/scenarios/*.json` (14 skills, 168 authored positives, 70 near-miss negatives), engine =
paraphrase-multilingual-mpnet-base-v2. LIVE (bare single-vector) vs SHADOW (multi-vector), **held-out
column** (trigger phrases from descriptions, independent of the separately-authored scenario queries):

| metric | LIVE (bare) | SHADOW (multivector) | Δ |
|---|---:|---:|---:|
| correct rank-1 % | 11.3 | **25.0** | +13.7 (2.2×) |
| correct top-5 % | 26.2 | **46.4** | +20.2 (1.8×) |
| separation (pos−neg) | 0.049 | **0.105** | +0.056 (2.2×) |
| true-neg false-fire % | 1.4 | 1.4 | +0.0 (flat) |

(`experiment-…-report.md:33-41`.) Verdict in that report: *"Multi-vector MAX **beats** the bare
single-vector baseline on the recall lever … and does **not** raise false-fire on labeled negatives"*
(`:60-64`). The 4× offer-crowding it also showed was proven a **0.20-floor scale artifact**, re-tuned
away at the live floor 0.45 (crowd-median 11 vs bare 34) — floor sweep at `:73-81` and ADR-0012:26-28.
The corpus even carries Vietnamese positives (`eval/scenarios/tdd.json`), a legitimate exercise of the
fork's multilingual embedder.

**This is a genuine, honestly-run improvement over the OG single-vector — but on a 14-of-495 slice.**
`scripts/precision_eval.py` header states the 14-skill shadow was originally "un-measurable" and that
a full-495 apples-to-apples run is the intended gate. The measured win is on the fork's own
in-universe corpus, held out to avoid train==test leakage (`experiment-…-report.md:24-28`) — sound,
but narrow (14 skills, scenario-authored positives).

---

## 3. What was NOT measured — the body-trigger layer (the +60% patch the charter targets)

The A/B in §2 tested **description** triggers only. The experiment harness
`scripts/multivector_experiment.py` builds its shadow from `eval/triggers.json` (description-derived
phrases) + `eval/scenarios` positives (`multivector_experiment.py:14-18`) — it does **not** run
`_extract_body_triggers` and has **no body-trigger point kind**. So the body layer has zero A/B.

The fork's own docs concede this, three times:

1. **ADR-0016 "Open / to measure"** — *"Shadow-A/B: does adding body triggers raise rank-1/separation
   on the eval set, or add topical noise? (Phase 7.)"* and *"Extraction precision: how many bodies
   actually carry a cleanly labeled decision section vs. free prose (bounds the real coverage gain,
   not just point count)."* (`docs/adr/0016-body-derived-trigger-points.md:57-62`). The ADR promises
   the delta will be *"recorded in the Phase-7 validation report"* (`:48`).

2. **Journal, "Not yet run"** — *"the opus-validate pass and the shadow A/B on the body-trigger layer
   (rank-1 / separation delta) — both scoped into Phase 7, after this docs phase."*
   (`docs/journals/journal-2026-07-04-usefulness-rate-upgrades.md:82-85`).

3. **Implementation validation, explicitly non-meaningful** — *"the eval-universe caveat
   (AGENTS.md/`docs/caveats.md`) makes a quantitative body-trigger recall A/B non-meaningful here, as
   the task noted."* (`plans/reports/opus-validation-260704-0510-usefulness-rate-upgrades-implementation.md:108`).

**No Phase-7 validation report exists.** A search of `plans/reports/` finds no body-trigger A/B; the
promised "Phase-7 validation report" is not present. The only post-ship evidence for body-triggers is
the reindex point-count (`{"embedded":1339 … }`, total **2231 → 3570 (+60%)**,
`docs/adr/0016-…:41-46`) and two **qualitative** wild-run introspection reports — neither is a recall
measurement.

**Shipped default-ON against its own recommendation.** The design proposal recommended gating body
triggers behind a shadow-A/B before default-on; the operator overrode to default-ON immediately
(`docs/adr/0016-…:32-35`, decision log D1). So the +60% index growth is **live and unmeasured**, on
an operator override, with the validating A/B deferred and then declared non-meaningful.

---

## 4. Topical-noise / dilution risk — bounded by design, unquantified in fact

- **Dilution: correctly avoided.** Body signal is added as separate MAX-pool points, not blended into
  the base vector (`server.py:296-298` unchanged; verified `opus-validation-…-0510-…:24,58-59`). This
  sidesteps the exact MEAN-centroid dilution ADR-0012 measured as worse. Good.
- **Topical noise: real, acknowledged, capped, but not measured.** ADR-0012 already documents
  description-trigger topical collisions (*"'token format' pulls `design-system` via 'token
  architecture'"*, `docs/adr/0012-…:40-42`). Body triggers **extend that collision surface** —
  `_extract_body_triggers` pulls whole lines from labeled sections (`skills_discovery.py:100-104`),
  and because they only fill leftover slots under the COMBINED cap (`server.py:276-293`), they can
  only ADD firing phrases, never displace description phrases. The `Do NOT use` exclusion guard
  (`skills_discovery.py:92-93`) is a sensible precision safeguard, but its effectiveness is untested.
- **Bounded, not free.** The `_TRIG_MAX`=12 COMBINED cap keeps per-skill growth flat; the +60% total
  comes from body phrases filling empty slots (median description ~3/12), well under full-body
  chunking's 2–4× (`server.py:276-284`; `journal-…:58-64`, correcting an earlier "flat point-count"
  overclaim). So the growth is bounded and reversible (`SKILL_BODY_TRIGGERS=0` + reindex) — but
  whether a tangential body phrase surfaces a skill off-purpose is **unmeasured**. Extraction
  precision (how many of 488 bodies have a clean labeled section vs free prose) is an open question
  in both ADR-0016 (`:62`) and researcher-b (`researcher-b-…-report.md:150-153`).

---

## 5. The benchmark gap (charter item 4)

- **OG's 24-query eval is wrong-universe.** `vendor/skill-search/eval/{labeled_queries.jsonl,run_eval.py}`
  target the upstream author's skills (`gsd-*`, `superpowers:*`, built-in slash-commands) that this
  engine deliberately does NOT index (ADR-0001) → recall ≈ `0.00/0.08/0.08`, "measures the wrong
  universe" (`docs/caveats.md §1`). Not usable as a quality bar. The OG's shipped recall@1 0.67 was on
  **bge-small on the OG's own 117-skill universe** — never re-run on the fork's mpnet/excluded index.
- **The fork DOES have one valid in-universe measurement** — the `eval/scenarios` A/B in §2 (14 skills,
  mpnet-768, held-out, VN included). That is a real recall number on the fork's index. But it (a)
  covers 14/495 skills, and (b) measures the **description**-trigger layer, not body triggers.
- **For body triggers specifically: UNMEASURED, and the corpus to settle it does not exist.**

**What would settle it, and whether the materials exist in-repo:**

| Need | Exists in-repo? |
|---|---|
| A/B harness that scores two shadow collections | **Yes** — `scripts/multivector_experiment.py`, `scripts/precision_eval.py` (495-way recall + confusion + true-neg) |
| Live toggle to build BODY=1 vs BODY=0 indexes | **Yes** — `SKILL_BODY_TRIGGERS` + reindex (`server.py:88`) |
| In-universe query corpus (14 skills) | **Yes** — `eval/scenarios/*.json` |
| **Body-only-signal labeled corpus** — positive queries whose decisive phrase lives in a skill's BODY decision-section but NOT its description | **No** — must be built. This is the load-bearing gap: `eval/scenarios` positives were authored from descriptions, so they cannot demonstrate a body-only recall gain. Flagged unresolved in `researcher-b-…-report.md:150-153` ("No `eval/triggers.json`-equivalent labeled corpus exists yet for body-derived when-to-use extraction quality"). |
| Extraction-precision audit (labeled-section vs free-prose across 488 bodies) | **No** — must be built (ADR-0016:62) |

Minimal experiment to settle it: (1) reindex two collections `SKILL_BODY_TRIGGERS=1` and `=0`; (2)
run `precision_eval.py` on both against `eval/scenarios` — this shows whether body triggers HURT
precision/false-fire on the existing corpus (a cheap regression check, buildable today); (3) to prove
the *recall gain* the ADR claims, author a body-only-signal corpus (10–20 skills whose intent lives in
`## When to Use` but not the description) and A/B rank-1/separation there. Step 3's corpus is the only
missing material — everything else (harness, toggle, engine venv) is present.

---

## VERDICT

- **Description-trigger MAX-pool (ADR-0012): MEASURED · BETTER (narrowly).** rank-1 2.2×, separation
  2.2×, false-fire flat, on a held-out in-universe A/B (`experiment-260630-…:31-64`). Genuine
  improvement over OG single-vector — caveated by a 14/495-skill corpus with scenario-authored queries.
  The MAX-over-separate-points design also correctly avoids the MEAN-centroid dilution the fork earlier
  measured as worse.
- **Body-trigger layer (ADR-0016, +60% / 2231→3570): UNMEASURED.** The promised Phase-7 shadow A/B was
  never run and is documented as "non-meaningful" on the current eval universe
  (`opus-validation-…-0510-…:108`; `journal-…:82`). Shipped default-ON by operator override against the
  proposal's own gate-first recommendation. Dilution risk is soundly avoided (separate points, base
  vector untouched); **topical-noise risk is bounded by the `_TRIG_MAX`=12 cap and the exclusion guard
  but is not quantified.** The claim that body triggers improve retrieval is **asserted by mechanism
  analogy to ADR-0012, not measured.**

**Net for D3:** the fork's retrieval is **provably better than the OG for the description-trigger
mechanism on a narrow in-universe slice**, and **UNMEASURED for the specific body-trigger patch the
charter flags** — neither provably better nor provably worse. What would settle the body question: an
`SKILL_BODY_TRIGGERS=1`-vs-`=0` A/B via the existing `precision_eval.py`/`multivector_experiment.py`
harness (buildable now for a precision regression check) plus a **new body-only-signal labeled corpus**
(the one missing material) to demonstrate the recall gain the ADR asserts.

---

**Status:** DONE
**Summary:** Description-trigger MAX-pool is measured and better on the fork's index (rank-1/separation
2.2×, false-fire flat); the +60% body-trigger layer is UNMEASURED — its Phase-7 A/B never ran and is
declared non-meaningful, shipped default-ON on operator override.
**Verdict:** UNMEASURED for the body-trigger patch (better-but-narrow for the description layer). Settle
it with a `SKILL_BODY_TRIGGERS=1/0` A/B on the existing harness (present) + a new body-only-signal
corpus (missing, must be authored).
**Unresolved:** (1) No body-only-signal corpus exists in-repo — the load-bearing gap. (2) Extraction
precision across the 488 bodies never audited. (3) Even the measured description-layer win covers only
14/495 skills. (4) No live organic-adoption read for either layer (needs a post-deploy window).
