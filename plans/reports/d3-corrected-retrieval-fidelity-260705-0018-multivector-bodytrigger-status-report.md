# D3 (CORRECTED RE-AUDIT) — Retrieval Fidelity: Multi-vector MAX-pool + Body-triggers vs the OG single-vector

**Dimension:** D3 (retrieval fidelity) · **Date:** 2026-07-05 00:18 · **Constraint:** READ-ONLY (nothing modified)
**Charter:** `from-corrected-analysis-to-audit-team-260705-0018-epoch-scoped-baseline-report.md`
**Prior report:** `d3-retrieval-fidelity-audit-260704-2312-multivector-bodytrigger-vs-og-report.md`

---

## 0. Why the epoch-pooling correction does NOT touch this dimension (stated explicitly)

The corrected charter re-ran the audit because the prior pass mis-read the **invocation ledger** —
it pooled ~15 config epochs and read the aggregate as a current-state rate. D3 never used the
ledger. Retrieval quality here is measured by **held-out offline A/B experiments** on an authored
corpus (`SKILL_BODY_TRIGGERS`/multivector `=1` vs `=0`, scored on `eval/scenarios`), which are
independent of any invocation-time telemetry and independent of the config epoch. Concretely:

- The one MEASURED number (rank-1 11.3→25.0) comes from `precision_eval.py`/`multivector_experiment.py`
  run on a fixed authored corpus — not offer/conversion/fallback rates from the ledger.
- The UNMEASURED verdict on body-triggers rests on **file concessions + the absence of a Phase-7
  report** — again, no ledger rate involved.

So the 5-step epoch discipline changes nothing here. **Every D3 claim below is grounded in a
file:line or an offline experiment table; none is an epoch-pooled ledger rate.** The prior D3
verdict stands verbatim — I re-verified each load-bearing citation this pass (results below).

---

## 1. Re-verification log (file:line, re-read this pass — all HOLD)

| Claim | Citation | Re-verified? |
|---|---|---|
| OG = one vector per skill (`name+description+body`) | `vendor/skill-search/skill_search/server.py:296-298` `_skill_text` | ✅ text unchanged, single string |
| Fork `MULTIVECTOR` default ON | `server.py:82` | ✅ `os.environ.get("SKILL_MULTIVECTOR","1") != "0"` |
| Fork `SKILL_BODY_TRIGGERS` default ON | `server.py:88` | ✅ default `"1"`; "No effect when MULTIVECTOR is off" |
| Combined trigger cap = 12 | `server.py:254` `_TRIG_MAX` (env `TRIGGERS_MAX`, default 12) | ✅ |
| Retrieval = MAX-pool `group_by="name", group_size=1` | `server.py:441-443` | ✅ comment confirms "single-vector index → identical to top-k; multi-vector → best-matching phrase point" |
| Body extraction mines labeled decision-sections, stops at next header / `Do NOT use` exclusion | `skills_discovery.py:75-79`, exposed at `:145` `body_triggers` | ✅ |
| Description A/B held-out: rank-1 11.3→**25.0**, top-5 26.2→**46.4**, separation 0.049→**0.105**, false-fire 1.4→1.4 flat | `experiment-260630-multivector-max-pooling-vs-bare-ab-report.md:31-41` | ✅ exact match (rank-1 counts 19→42; false-neg fires 1→1) |
| Body A/B never run; deferred to Phase 7 | `docs/adr/0016-body-derived-trigger-points.md:47,57-58` ("Open / to measure", "recorded in the Phase-7 validation report") | ✅ |
| Shipped default-ON on operator override against the proposal's gate-first recommendation | `docs/adr/0016-…:32-34` (decision log D1) | ✅ |
| Body A/B declared **non-meaningful** on current eval universe | `opus-validation-260704-0510-usefulness-rate-upgrades-implementation.md:108` | ✅ verbatim ("makes a quantitative body-trigger recall A/B non-meaningful here") |
| +60% index growth (2231→3570, +1339 body points) | `docs/adr/0016-…:41-43` | ✅ |
| **No Phase-7 body-trigger report exists** | `ls plans/reports/` → only the prior D3 audit matches `body-trigger`; no Phase-7 report | ✅ CONFIRMED ABSENT |
| Experiment harness builds shadow from `eval/triggers.json` (description-derived) + `eval/scenarios` — no body-trigger point kind | `scripts/multivector_experiment.py:14-18,52` | ✅ `trigger` = `eval/triggers.json`, `scenario` = `eval/scenarios`; **no `body_triggers` reference anywhere in the harness** |

Every citation from the prior report re-reads clean. Line numbers are stable.

---

## 2. Verdict per layer (unchanged from prior pass, re-confirmed)

**Layer 1 — Description-trigger MAX-pool (ADR-0012): MEASURED · BETTER (narrowly).**
Real held-out A/B on the fork's own mpnet-768 index (14 skills, 168 authored positives, 70 near-miss
negatives, VN positives included): rank-1 **+13.7 pts (2.2×)**, top-5 **+20.2 pts (1.8×)**, separation
**2.2×**, false-fire **flat** (`experiment-…:31-64`). The held-out column is independent of the
scenario queries (trigger phrases come from descriptions), so this is not train==test leakage. The
MAX-over-separate-points design correctly avoids the MEAN-centroid dilution ADR-0012 earlier measured
as worse. **Caveat: 14/495-skill slice, scenario-authored positives.** This is a genuine improvement
over the OG single-vector retriever — and it is a real recall measurement, not a ledger artifact.

**Layer 2 — Body-derived trigger points (ADR-0016, the +60% / 2231→3570 growth): UNMEASURED.**
The promised Phase-7 shadow A/B **never ran** (no report on disk), the harness has **no body-trigger
point kind** to run it with (`multivector_experiment.py` uses description-derived `eval/triggers.json`
only), and the repo itself declares a quantitative body-trigger recall A/B **"non-meaningful"** on the
current eval universe (`opus-validation-…:108`). Shipped **default-ON by operator override** against
the proposal's own gate-first recommendation (`ADR-0016:32-34`). Dilution risk is soundly avoided
(body signal added as separate MAX-pool points; base vector `_skill_text` untouched). Topical-noise
risk is **bounded** by the `_TRIG_MAX`=12 combined cap and the `Do NOT use` exclusion guard, but is
**not quantified**. The claim that body triggers improve retrieval is **asserted by mechanism analogy
to ADR-0012, not measured.**

---

## 3. Charter items 3 & 4 (re-confirmed)

**Item 3 — Body-trigger layer still UNMEASURED (Phase-7 A/B never ran)?** ✅ **CONFIRMED.** No
Phase-7 report exists; the harness cannot produce one without a body-trigger point kind; the ADR/journal/
opus-validation all concede the delta is unrun and "non-meaningful" on the current corpus.

**Item 4 — No valid recall number on the fork's mpnet/excluded universe?** ✅ **CONFIRMED with one
nuance.** The OG's shipped recall@1 0.67 was on **bge-small over the OG's 117-skill universe** — never
re-run on the fork's mpnet-768/excluded index. The OG's 24-query eval targets skills this engine
deliberately does NOT index (recall ≈ 0.00–0.08, "wrong universe", `docs/caveats.md §1`) — unusable as
a bar. The fork's **one** valid in-universe recall number is the §2 Layer-1 A/B (14/495 skills,
description layer). **For body-triggers specifically: no valid recall number exists.**

**What would settle the unmeasured layer:** (a) a cheap, buildable-today precision regression check —
reindex two collections `SKILL_BODY_TRIGGERS=1` vs `=0`, run `precision_eval.py` on both against
`eval/scenarios`, showing whether body triggers HURT false-fire/precision; PLUS (b) the load-bearing
missing material — a **body-only-signal labeled corpus** (10–20 skills whose decisive intent lives in a
`## When to Use` section but NOT the description), to demonstrate the recall GAIN the ADR asserts.
Harness, toggle, and engine venv all exist; only corpus (b) must be authored. Extraction precision
across the ~488 bodies (labeled-section vs free-prose) is a second open question (`ADR-0016:62`).

---

**Status:** DONE
**Summary:** D3 is config/ledger-independent — the epoch-pooling correction does not touch it; every
citation re-verified clean. Verdict unchanged: description-trigger MAX-pool is MEASURED & better
(rank-1/separation 2.2×, false-fire flat, on a 14/495 held-out slice); the +60% body-trigger layer is
UNMEASURED (Phase-7 A/B never ran, harness can't run it, repo calls it "non-meaningful", shipped
default-ON on operator override).
**Verdict:** Layer 1 (description MAX-pool) = BETTER-but-narrow, MEASURED. Layer 2 (body-triggers) =
UNMEASURED — settle with a `SKILL_BODY_TRIGGERS=1/0` precision check on the existing harness (buildable
now) + a new body-only-signal labeled corpus (the one missing material).
**Unresolved:** (1) No body-only-signal corpus in-repo — the load-bearing gap. (2) Extraction precision
across ~488 bodies never audited. (3) Even the measured description win covers only 14/495 skills.
(4) No live organic-adoption read for either layer — and note that read, when done, must obey the
corrected epoch discipline (window to current config, exclude subagent/harness traffic) or it is UNMEASURED.
