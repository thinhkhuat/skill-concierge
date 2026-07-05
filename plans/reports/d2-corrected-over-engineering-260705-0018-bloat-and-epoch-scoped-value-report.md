# D2 — CORRECTED OVER-ENGINEERING RE-AUDIT (ponytail / KISS lens)

**Type:** READ-ONLY re-audit · supersedes the DATA sections of `d2-over-engineering-audit-260704-2312-fork-bloat-delete-simplify-report.md`
**Date:** 2026-07-05 · **Author:** D2 auditor (first-hand file:line reads + windowed telemetry)
**Discipline applied:** epoch-scoped data rules from the corrected handover
(`from-corrected-analysis-to-audit-team-260705-0018-...`). Nothing modified.

Verdict key: **DELETE** (remove, no value) · **SIMPLIFY** (keep intent, cut machinery) ·
**REVERT/REOPEN** (return to data-backed operating point, owner-owned) · **KEEP** (earned).

**What changed from the 2312 pass:** the old report's headline — "63% embed_timeout,"
"the semantic stack delivers nothing most of the time," "net-negative" — was epoch-pooled
(≈15 config epochs stacked) and subagent-contaminated. It is **withdrawn**. Part A below
(the inert graveyard + never-armed binary facts + LOC) is config-INDEPENDENT and **stands,
re-confirmed at file:line**. Part B (any efficiency/value claim) is re-grounded to the
current epoch and lands on **INSUFFICIENT DATA**, not a negative verdict.

---

## PART A — CONFIG-INDEPENDENT (re-confirmed, still valid)

These rest on file-reads and a full-ledger binary scan, not on any rate. They do not depend
on which epoch you are in.

### A1. The DEFAULT-INERT graveyard — five features shipped/wired/tested but PROVABLY NEVER FIRED → **DELETE / SIMPLIFY**

| Feature | Wiring (file:line) | Carried cost while OFF | Ever armed? (evidence) |
|---|---|---|---|
| Per-skill τ | `enforcer.py:158-189` + call `512-514` + selftest `637-661` + `eval/thresholds.json` + `scripts/calibrate_thresholds.py` (240 LOC) | ~272 LOC + JSON corpus | **No.** `_load_per_skill_tau` returns `{}` unless `ENFORCER_PER_SKILL_TAU` set (`enforcer.py:173`); grep of `~/.claude/settings*.json` + shell + `hooks.json` = **flag absent**. Header (`:160-166`) admits arming it *lowers* the bar. |
| Deterministic routes | `enforcer.py:192-233` + call `505-507` + `config/deterministic-routes.json` (`"routes": []`) | ~50 LOC + empty config | **No.** Loader gated on `ENFORCER_DETERMINISTIC` (`:206`) — flag absent. **Full-ledger scan: 0 of 601 offer-events carried a score-1.0 (deterministic) hit.** Binary, epoch-independent. |
| Dominance collapse | `enforcer.py:236-245, 372-379` + call `534` | ~40 LOC | **No.** `DOMINANCE_RATIO=None` unless `ENFORCER_DOMINANCE_RATIO` set (`:241-245`) — flag absent. Header: fires only ~5%, "no evidence it improves conversion." |
| Keep-off suppression | `enforcer.py:130-155` + call `499-500` + `config/keep-off.json` (`"keep_off": []`) + `scripts/build_keep_off.py` (132 LOC) | ~170 LOC + empty config | **No.** **Full-ledger scan: 0 of 601 offer-events carried a `dropped` field; `dropped` is not even a key that appears anywhere in the 1,595-row ledger.** Generator ran once (2026-06-29), produced `[]`. |
| Legacy MEAN `enrich_index.py` | `scripts/enrich_index.py` (324 LOC) | 324 LOC, superseded | **Must-not-run.** Superseded by v0.12.0 body-triggers; its own header marks it a reverse-engineered Phase-1 MEAN recipe with a `--live` mutator footgun ("upsert → skills go dark → doctor FAILs"). |

**Binary facts confirmed this pass (epoch-INDEPENDENT):**
- Deterministic routes: **0/601** score-1.0 offer hits across the entire ledger.
- Keep-off: **0/601** `dropped` fields; the key never appears.
- No `ENFORCER_PER_SKILL_TAU` / `_DOMINANCE_RATIO` / `_DETERMINISTIC` in settings, local settings, or shell.

**Aggregate dead weight:** ~140 LOC of inert branches inside the 715-line enforcer (`wc -l
hooks/scripts/enforcer.py` = 715), plus ~700 LOC of supporting scripts (`calibrate_thresholds`
240 + `build_keep_off` 132 + `enrich_index` 324), two permanently-empty configs, and a
14-entry `thresholds.json`. None has moved a single production decision.

**Ranked disposition (unchanged, re-confirmed):**
- **DELETE now:** `enrich_index.py` (superseded `--live` footgun), `build_keep_off.py` +
  `config/keep-off.json` (never produced a non-empty set), the dominance-collapse branch.
- **SIMPLIFY:** fold per-skill-τ + deterministic-routes into a one-line ADR note ("levers
  considered, data said no — ADR-0009") and drop the code + `calibrate_thresholds.py` +
  `thresholds.json`. Keeping the *decision record* is cheap; keeping the *inert code* is not.

Honest counter-weight: every branch is fail-open and cannot break a turn
(`enforcer.py:139-144, 172-180`), and selftests pin them — so the graveyard is **inert, not
dangerous** (except `enrich_index --live`). But harmless dead code is still dead code. YAGNI
says delete, not gold-plate with tests.

### A2. Enforcer + governance layer — over-engineered ON ITS MERITS? (design/complexity only, value-agnostic)

Judged purely as design, independent of the unmeasurable value question:

- **Over-engineered on merits — YES, at the stage level.** `main()` threads keep-off → routes
  → per-skill floor → dominance in sequence (`enforcer.py:499-534`) — **four inert stages
  wired into the per-turn hot path**. A maintainer must read and reason about the interaction
  of four `if not os.environ.get(...)` branches that, by the authors' own headers, the data
  does not yet support. That is textbook premature abstraction regardless of whether the
  enforcer delivers value. This half is over-built on its own terms.
- **Sound on merits — the active core.** The contract itself is disciplined: **fail-silent,
  additive-only, stdlib-only** (`enforcer.py:12-16`) — it cannot block a turn. The live path
  (retrieve → floor gate → intent gate → emit MANDATE + append ledger) is a reasonable shape.
  The mpnet multilingual swap + VN imperative lexicon (`enforcer.py:114-123`, selftest
  `588-608`) fix a real EN-query→VN-skill recall miss — earned, not bloat.
- **Heavy-for-effect, but that is a data claim not a merit claim:** the actionability gate is a
  two-class kNN over a 912-prompt corpus + a `build_prompt_intent.py` generator (227 LOC) + a
  second Qdrant collection. As pure design that is a lot of apparatus for one veto; whether it
  earns its keep is a value question → Part B (currently unmeasurable).

**Merits verdict:** the enforcer is **half over-engineered (the four inert stages) and half
sound (the fail-silent active core + multilingual fix)**. The over-engineering is concentrated
in Part A's graveyard, not in the core contract. **SIMPLIFY** by deleting the inert stages;
**KEEP** the SKILL-FIRST core and the multilingual retrieval.

### A3. Two against-data gate knobs → **REOPEN with the owner** (decision smell, not a data claim)

Flagged as a design/decision smell, explicitly NOT a measured regression:

- **`GETAWAY_FLOOR = 0.45`** (`enforcer.py:66`). The inline comment itself records that
  "the ledger/corpus analysis argued AGAINST it (taken offers score LOWER than dodged, so a
  higher floor cuts the better-converting offers first)" and points to the data-backed
  alternative `0.40`. ADR-0009 is the record.
- **AUTHORIZED-SKIP getaway leg ON by default** (`enforcer.py:78`, `AUTHORIZED_SKIP=... != "0"`,
  ADR-0015). Ships ON against a proposal that recommended the getaway leg default-OFF pending
  a post-multi-vector re-measurement that ADR-0015's own "Open" section says is still open.

Both are **one-env-var reversible, fail-open, and owner-decided** (review-audit rule: don't
silently undo a user decision). The audit's job is only to say plainly: **the recorded data
points the other way.** Recommendation — **REOPEN** `GETAWAY_FLOOR` to 0.40, or at minimum
split `ENFORCER_AUTHORIZED_SKIP` per leg and turn the getaway leg OFF until the ADR-0015
prerequisite measurement is done. This is a flag-and-reopen, **not** a unilateral delete.

---

## PART B — DATA-DEPENDENT (corrected discipline) → **INSUFFICIENT DATA**

**Command:** `python3 scripts/analyze.py --since "2026-07-04 05:32"` (current epoch start;
v0.12.0 live, last metric-affecting commit `7a7da28`).

**Windowed result (87 events, 29 turn-windows, 27 offers):**
- offer bands: `{offer: 17, fallback: 8, negation: 1, getaway: 1}`
- fallback rate **9/27 (33%)**
- offered-turn conversion **5/17 (29%)** — *n=17*
- raw `embed_timeout` in window: **8 of 27 offers**

**Subagent/meta exclusion (per discipline step 2):** of those 8 `embed_timeout` events, **3
are `<task-notification>` subagent traffic** (session `360f2c2e`, prompts literally begin
`<task-notification><task-id>…`). Removing them leaves **5 genuine `embed_timeout`** over
~20 genuine offers → **≈25% (5/20)**. This matches the corrected handover's figure.

**Further caveat (self-session):** at least 3 of those 5 genuine timeouts are *self-session
meta* about skill-concierge itself ("YOU pooled the entire ledger…", "now that you've got the
idea of skill-concierge…", "this, and the way you cited data…"). Excluding self-referential
traffic, the genuine-external clean sample is **~14 offers** — even smaller.

### VERDICT — INSUFFICIENT DATA

- The genuine current-epoch `embed_timeout` is **≈25%, n≈20 (clean-external n≈14)**. That
  sample **cannot support a rate** and **cannot support any "net-negative" / "delivers nothing"
  claim.** The prior 63% / 29% figures are **withdrawn** as epoch-pooled + subagent-contaminated
  artifacts.
- The "is the enforcement layer worth its operational cost" question is, right now,
  **UNMEASURABLE** — not answered negatively, not answered positively.
- **Environmental context, NOT a config/design signal:** per-day `embed_timeout` ran 9–20%
  (06-27→07-01), then spiked to ~68% (07-02) and ~54% (07-04) — an onset **2 days before**
  v0.12.0 shipped ⇒ an **operational incident** (shim/Docker/load) to triage separately, not
  an enforcer-design property.

### What clean window would settle it
A single, controlled current-epoch window of **≥ ~60 genuine offered turns** (subagent- and
self-session-excluded, no config change mid-window) with the embed shim healthy — reporting
offered-turn conversion with a confidence interval — would move this from INSUFFICIENT DATA to
a real value verdict. Until then, the honest output is a measurement plan, not a score.

---

## SUMMARY TABLE (ranked, most-negative first)

| # | Thing | Cost | Verdict | Anchor |
|---|---|---|---|---|
| 1 | Inert graveyard (5 features, never fired) | ~140 LOC in enforcer + ~700 LOC scripts + 2 empty configs | **DELETE / SIMPLIFY** | `enforcer.py:130-245,499-534`; ledger 0/601 det-hits, 0/601 dropped |
| 2 | `enrich_index.py` `--live` MEAN footgun | 324 LOC, superseded | **DELETE** | `scripts/enrich_index.py` header |
| 3 | Four inert stages threaded into per-turn hot path | design/merits over-engineering | **SIMPLIFY** | `enforcer.py:499-534` |
| 4 | `GETAWAY_FLOOR=0.45` + authorized-skip getaway leg ON | 2 against-data hot-path knobs | **REOPEN w/ owner** | `enforcer.py:66,78`; ADR-0009 / ADR-0015 |
| — | Enforcement *value* question | (unmeasurable) | **INSUFFICIENT DATA** | `analyze.py --since 05:32`: 5/20 genuine embed_timeout |

**Earned, explicitly NOT bloat:** mpnet multilingual swap + VN imperative lexicon (real recall
fix), the fail-silent/additive/stdlib hook contract, the curated keep-on override, and the ADRs
(cheapest, highest-leverage artifact — every against-data knob is auditable only because they
exist).

---

## Unresolved / honest caveats
- **The value verdict is INSUFFICIENT DATA, full stop.** n≈14–20 clean offers. The prior
  "net-negative" conclusion is withdrawn.
- **Never-armed is proven** for the two ledger-observable features (routes 0/601 score-1.0;
  keep-off 0/601 `dropped`) and **inferred** for per-skill-τ / dominance (no persisted env flag
  anywhere). A one-off manual `export` in a past shell can't be ruled out but left no trace.
- **The against-data knobs (#4) are owner-owned** — flag-and-reopen, not unilateral delete.
- **The 07-02 embed_timeout onset is an operational incident**, to triage separately from
  enforcement design.

**Status:** DONE
