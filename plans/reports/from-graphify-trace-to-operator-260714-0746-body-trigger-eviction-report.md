# Body-trigger eviction by the utterance layer — measured, undocumented

**Date:** 2026-07-14 07:46 · **Constraint:** READ-ONLY (nothing modified; operator chose log-only)
**Origin:** graphify trace of the highest-betweenness bridge node, `D3 (CORRECTED RE-AUDIT) — Retrieval Fidelity`
**Prior report:** `d3-corrected-retrieval-fidelity-260705-0018-multivector-bodytrigger-status-report.md`

---

## 1. Finding

Under the **live** config (`SKILL_LLM_TRIGGERS=1`, `TRIGGERS_MAX=16`, `SKILL_BODY_TRIGGERS` unset → default ON),
the ADR-0026 utterance layer **evicts** the ADR-0016 body layer from the combined trigger cap. Both
`AGENTS.md` and ADR-0026 state the opposite.

`vendor/skill-search/skill_search/server.py:314-337` — `_trigger_phrases()` appends in quality order
(utterances → description → body), dedups, then truncates: `return phrases[:_TRIG_MAX]`. Body is last,
so it absorbs the whole truncation.

## 2. Measurement (435 discovered skills, live flags)

| | skills |
|---|---|
| have body triggers | 233 |
| body **fully** evicted (0 body phrases indexed) | 30 |
| body **partially** evicted | 129 |
| body fully survives | 63 |
| **body phrases dropped** | **933** |

159/233 body-bearing skills (68%) lose some or all of their body layer.

Slot arithmetic (skills with body triggers):

| source | median | mean | max |
|---|---|---|---|
| utterance phrases | 10 | 9.1 | 10 |
| description phrases | 3 | 3.5 | 16 |
| utt+desc, pre-body | 12 | 12.6 | 26 |

Median skill has ~3-4 of 16 slots left when body is consulted. 30/233 (13%) have utt+desc alone
filling or overflowing the cap — body gets zero.

Examples: `business-report` (16 slots taken, 16 body phrases → 0 indexed); `archon` (26 taken, 16 → 0);
`tavily-dynamic-search` (16 taken, 4 → 0).

## 3. The contradiction

- `AGENTS.md:64` — "live deploy uses `16` so utterances **add slots rather than evict**". FALSE on live config.
- `docs/adr/0026-llm-utterance-trigger-layer.md:44-45` — "Operator chose utterances-first + `TRIGGERS_MAX=16`
  ('blend') so the best phrases win **AND desc/body are not evicted**." FALSE on live config.
- `docs/adr/0016-body-derived-trigger-points.md:59` — predicted exactly this ("Does the COMBINED `_TRIG_MAX`
  cap starve verbose-description skills of any body phrases?"). Open question was closed by **assertion**,
  never measured.

Pre-ADR-0026, description alone took ~3 slots → body had ~13 → effectively no eviction. The utterance
layer caused the eviction; its own decision log denies it.

## 4. D3's verdict re-verified against current code (all HOLD, 9 days on)

| D3 claim | Re-verified 2026-07-14 |
|---|---|
| `SKILL_BODY_TRIGGERS` default ON | ✅ `server.py:89` |
| `SKILL_MULTIVECTOR` default ON | ✅ `server.py:83` |
| Harness has **no** body-trigger point kind | ✅ no `body_trigger` in `multivector_experiment.py` / `precision_eval.py` |
| **No Phase-7 body-trigger report exists** | ✅ still absent from `plans/reports/` |

So: the layer is still UNMEASURED, still default-ON, **and now also substantially discarded** — a state
worse than D3 recorded, because the shipped +60% index-growth rationale no longer describes the live index.

## 5. What would settle it (unchanged from D3 §3, still buildable today)

Shadow-collection precision regression: reindex `SKILL_BODY_TRIGGERS=1` vs `=0`, score both on
`eval/scenarios` via `precision_eval.py`. Harness, toggle, engine venv all exist. Does not touch the
live collection. Answers whether the 933 evicted phrases are a loss or a mercy.

Still missing (the load-bearing gap D3 named): a **body-only-signal labeled corpus** — 10-20 skills whose
decisive intent lives in a `## When to Use` section but NOT the description. Without it, no recall GAIN
for body triggers can be demonstrated, only a precision non-regression.

## 6. Status

**Operator decision (2026-07-14): log only.** No code, config, or doc changed. `TRIGGERS_MAX` remains 16;
the false "not evicted" lines in `AGENTS.md:64` and ADR-0026:44-45 remain in place, knowingly.

## Unresolved

1. Whether body triggers earn their slots at all — UNMEASURED, and the harness still cannot measure recall
   gain without corpus (b).
2. Whether utterances-first ordering is correct — asserted as "quality order", never A/B'd against
   description-first or body-first.
3. `AGENTS.md:64` and ADR-0026:44-45 remain factually false about the live config until the cap is raised
   or the text corrected.
4. Extraction precision across ~488 skill bodies never audited (`ADR-0016:62`).
