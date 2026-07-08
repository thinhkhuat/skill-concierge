# ADR-0026 — LLM-utterance trigger layer

Status: Accepted (2026-07-08)
Relates to: ADR-0012 (multi-vector MAX-pool trigger layer — this EXTENDS it), ADR-0016 (body-derived
trigger points — same engine-only fold pattern), ADR-0013 (engine freshness / copy-into-stable-venv).
Source: `plans/2026-07-08-multivector-utterance-trigger-integration-plan.md`,
`plans/2026-07-08-local-llm-retrieval-flywheel.md`. Vendored-engine change: see
`vendor/skill-search/VENDORED.md` (v0.16.0).

## Context
ADR-0012/0016 build each skill's trigger points from its **description** and **body** phrases — text the
author wrote to *describe* the skill, not the way a user *asks* for it. The retrieval gap is register:
a turn phrased as a natural request ("how do I onboard onto this codebase", "chạy demo giúp tôi") does not
always match doc-prose phrasing. A free, local, offline LLM (LM Studio, `gemma-4-*-it-qat-optiq`) can
generate that missing register cheaply — per-skill natural utterance phrases, bilingual EN+VN — as long as
it stays OUT of the ≤300ms enforcer hot path (which remains embedding-only). A retrieval flywheel generated
these offline: 532/532 skills, 100% with ≥2 Vietnamese utterances.

The first integration attempt (mistakenly via `scripts/enrich_index.py`) aborted on the embed-parity gate —
correctly: `enrich_index.py` is single-vector-era (centroids triggers into one vector) and cannot address a
multivector index. The right path is to add utterances as NEW MAX-pool points via the INDEXER, exactly like
ADR-0016's body phrases — so the base vector is never diluted (the "1/(N+1)" concern disappears).

## Decision
- **Consume (`vendor/skill-search/skill_search/server.py`).** `_trigger_phrases(s)` gains a third source,
  layered in QUALITY order: (if `SKILL_LLM_TRIGGERS`) the utterance phrases FIRST, then description, then
  (if `SKILL_BODY_TRIGGERS`) body — deduped case-insensitively and capped COMBINED at `_TRIG_MAX`.
  Utterances-first lets the highest-quality phrases win the capped slots; raise `TRIGGERS_MAX` to add slots
  instead of evicting. A cached `_llm_utterance_phrases(name)` loader reads the `llm_triggers.triggers`
  block from `eval/triggers.json` (produced by `scripts/llm_triggers.py`), keyed on the same `name` the
  index uses; `[]` when the file is absent → graceful degrade to desc/body.
- **Generate (offline, `scripts/flywheel_llm.py` + `llm_triggers.py` + `llm_eval_gen.py`).** LM-Studio
  OpenAI-compat client, strict `response_format: json_schema`, thinking OFF. Output (`eval/triggers.json`
  `llm_triggers` layer + `eval/scenarios-shadow/`) is gitignored — it regenerates from the committed scripts.
- **Toggle:** `SKILL_LLM_TRIGGERS` (default **OFF** = byte-identical to before). Live deploy sets it `=1`
  with `TRIGGERS_MAX=16` via `.mcp.json`.
- **Mirror status:** engine-only, like ADR-0016. `scripts/build_triggers.py` is a *producer* of the base
  prose block with no `_trigger_phrases` twin; its only overlapping twin `split_phrases`≡`_split_phrases`
  is unchanged. A sync note in `build_triggers.py` records this; VENDORED.md v0.16.0 documents the patch.
- **Base vectors untouched** — utterances are separate points, never centroided.

## Cap allocation (operator decision, recorded)
Utterances are higher-quality than auto-split desc/body phrases but the fixed order would give them the
leftover slots. Operator chose **utterances-first + `TRIGGERS_MAX=16`** ("blend") so the best phrases win
AND desc/body are not evicted. Kill-switch: `SKILL_LLM_TRIGGERS=0` (+ reindex) reverts to ADR-0016 behavior.

## Evidence
- `_trigger_phrases` selftest (no network): utterances-first, cap respected, dedup holds, flag-OFF
  byte-identical, missing-file safe — PASS.
- Shadow build (`claude_skills_shadow`, `SKILL_LLM_TRIGGERS=1 TRIGGERS_MAX=16`): **532 base points identical
  to live** (zero base dilution), 7080 total.
- Precision gate, 532-scenario corpus, shadow vs live
  (`plans/reports/gate-260708-0957-utterance-triggers-shadow-vs-live.txt`):
  **rank-1 35.1 → 42.1 % (+7.0), top-5 60.6 → 69.0 % (+8.4), true-neg false-fire 4.4 → 4.0 % (−0.4).**
  Rank metrics are floor-independent; false-fire is monotone-safe at a higher operating floor.
- `scripts/precision_eval.py` was fixed to rank SKILLS via `group_by` MAX-pool (it had ranked raw points,
  wrong for a multivector index) before these numbers were trusted.

## Consequences
- Natural-utterance register (incl. Vietnamese) becomes retrievable via MAX-pool in both the enforcer-hook
  and MCP paths, at the same query cost. Index grows (utterance points added); bounded by `TRIGGERS_MAX`.
- **Deploy dependency (ADR-0013):** vendored engine re-copied into the stable venv + a reindex with the flag
  on. `SKILL_TRIGGERS` must point at the (gitignored, machine-local) `eval/triggers.json`; absent → no
  utterances, safe. The persistent MCP runs old code until it restarts.
- `enrich_index.py` is confirmed STALE for the multivector index — do not use it for this layer.

## Open / to measure
- Offer-set crowding at the real 0.45 operating floor was not separately measured (the 0.2-floor gate
  saturates); rank gains stand regardless, and false-fire is monotone-safe. Re-measure if offer noise rises.
- Cap 12 vs 16: only 16 was gated (a clean win); 12-vs-16 isolation deferred.
- Flywheel item #3 (post-hoc miss-auditor feeding #1/#2) — deferred follow-on.
