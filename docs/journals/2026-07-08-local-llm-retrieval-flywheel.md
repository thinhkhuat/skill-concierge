# Local LLM Retrieval Flywheel: JSON Wars, Model Bake-Off, and a Stale Path Caught

**Date**: 2026-07-08 03:00–09:00
**Severity**: High (architectural discovery, near-miss to index corruption)
**Component**: Skill retrieval (flywheel generation + multivector indexing)
**Status**: Resolved (generation complete; integration blocked pending operator decisions)

## What Happened

Attempted to build a retrieval flywheel using LM Studio (free local model at `localhost:4310`) — two objectives: (1) generate a dense eval corpus (532 skills × 12 positive scenarios + 4-6 negatives each), and (2) generate utterance-style triggers to lift recall. Everything offline, never touching the ≲300ms enforcer hot path. Ran autonomously overnight. Hit a hard blocker on enrichment that revealed a stale code path was about to corrupt the live index; safety gates caught it. All generated data is valid.

## The Brutal Truth

This session was a tangle of technical debt, model compatibility gotchas, and one near-miss that made me grateful we run gates. Spent ~6 hours chasing qwen's reasoning mode only to prove it's completely broken for this job. Built three generators, stress-tested them, and then watched the enrichment step abort — correctly — on a parity check that exposed that the live index had evolved to multivector while the enrichment script was still single-vector-era. That's the kind of silent data corruption that ships at 3am.

The real punch: `enrich_index.py` would have happily written to production with a fundamentally broken model. The gate worked. Gates are worth the friction.

## Technical Details

**JSON reliability:** Original prompt strategy used unquoted keys (`{"key": value}` vs `key: value`). Ollama's `format:"json"` (loose constraint) accepted it 40% of the time; LM Studio rejects it outright. Fix: moved to strict `response_format: json_schema` (grammar-constrained decoder on LM Studio). This killed unquoted-key errors completely and is load-bearing for production.

**Qwen thinking dead-end:** Invested 90 minutes testing whether qwen3.5-9b's reasoning mode could close a 32% Vietnamese gap. Result: every path fails.
- `strict json_schema` + `reasoning_effort: "medium"` → content empty, reasoning filled 29 chars, finish_reason=stop
- `json_object` mode → server error, no choices
- Schema-less on trivial prompt → works fine
- Schema-less on the real generation prompt (long skill desc + "12 positives ≥3 Vietnamese, 4-6 negatives") → reasoning burns entire token budget, content empty, timeout

The grammar-constrained decoder and the reasoning token path do not coexist on this LM Studio build. Walking away was the right call; gemma-4-12b-it-optiq already hits 100% Vietnamese without any of this.

**Model selection metrics:**
- gemma-4-12b-it-qat-optiq: 100% VN, boundary-aware negatives (e.g. "speech" → "transcribe audio", "voice clone" — near-misses, not trivia). Winner.
- gemma-4-e4b-it-qat-optiq: 100% VN, ~2× faster, softer negatives. Fine for triggers (no negatives used).
- qwen3.5-9b: 32% VN (thinking-off), thinking-on breaks JSON (above).
- gpt-oss-20b: truncates at 4096 tokens even with `max_tokens=4096`, ~67s/skill. Dropped.
- Critical insight: quant recovery (qat+optiq) ≤ base model capability. A 4B quantized model will never produce 12B-quality negatives.

**Autonomous run reliability:**
- Harness killed the `run_in_background` tasks twice (not OOM — 56% memory free, LM Studio responsive, no system jetsam log).
- Root cause: harness reaper catches session-tracked background tasks. Fix: `nohup caffeinate -is bash ...&` creates an OS process outside harness tracking. Driver made resume-safe (cache + file-exists check fills only the gap, never wipes completed work).
- Result: 532/532 scenarios + 532/532 triggers, 100% Vietnamese, quality-verified. Finished ~05:56 after surviving two external kills.

**The architecture blocker — and the lesson:**
- `enrich_index.py:87 scroll_live` iterates live index points, keys by `name`, and dict-overwrites when duplicates are found. Single-vector era: it would centroid triggers into one vector.
- Live index is **multivector**: `come-clean` = 13 points: exactly 1 base @ cos 1.000 + 12 trigger points @ 0.25–0.55, MAX-pooled.
- `scroll_live` dict-overwrite = keeps an arbitrary trigger point (cos 0.329).
- Parity gate compares full-text embed vs this trigger point → cos 0.329 < 0.999 → ABORT.
- Gate was **correct**. `enrich_index.py` is **stale** (single-vector logic, wrong for multivector index). Would have silently diluted the base.

Doctor confirms "Enrichment overlay: not enriched" — this path was never used on this index before. A deploy would have corrupted production retrieval without warning.

## What We Tried

1. **Qwen thinking for Vietnamese coverage** — 90-minute investigation into whether reasoning mode could close the 32% gap. Tried per-request (`reasoning_effort`), tried server-side config, tried schema-less fallback. Every path failed. Abandoned; gemma coverage already sufficient and proven.

2. **Enrich → live** — ran `enrich_index.py --shadow` expecting a smooth enrichment flow. Hit the parity gate and stopped, correctly. Only then diagnosed that the enrichment script's model (single-vector centroid) doesn't match the live index's architecture (multivector MAX-pool).

3. **Precision gate on enriched shadow** — gate logged "OK", but the shadow was never built (enrichment aborted), so the numbers were junk. This is why we verify *before* trusting.

## Root Cause Analysis

Three separate causes, three separate fixes:

**1. JSON reliability:** Ollama's loose `format` constraint and Qwen's unquoted-key prompt example created a 60% failure rate. LM Studio's strict `response_format: json_schema` grammar-constrains the decoder and kills the class of errors entirely. This is correct; move on.

**2. Qwen thinking incompatibility:** The reasoning token path and the grammar-constrained decoder share the same token budget on this LM Studio build and do not play well together. Turning reasoning on **empties the content**. This is a hard limit of the current setup, not a workaround-able problem. Qwen reasoning is not usable for this job.

**3. Stale enrichment path:** `enrich_index.py` was written for a single-vector index. The live index evolved to multivector (individual trigger points, MAX-pooled). The centroid model is fundamentally wrong and would dilute the base. The correct path is to add utterances as *new points via the multivector indexer* + reindex, not via the enrich script. The indexer (`server.py:283 _trigger_phrases`) must be extended to read the llm-utterance layer.

The third one is the real lesson: **architecture drift**. Code path and data model diverged silently. Gate caught it; without the gate, we ship corrupted retrieval.

## Lessons Learned

1. **Safety gates earn their friction.** The 10-skill smoke caught 60% garbage JSON before a 90-minute run. The embed-parity gate caught a stale enrichment path before it corrupted production. Every gate we ship is a "nope, nice try" that saves a 3am debugging session. Keep them. They slow nothing down.

2. **Measure, don't assert.** Every model claim — Vietnamese coverage, negative sharpness, speed — was measured on real skill data. The qwen thinking investment looked promising on intuition alone; measurement killed it fast. Delegate-then-measure.

3. **Verify-before-trust is non-negotiable.** The precision gate logged "OK" on a shadow that never existed. Precision numbers were junk. Good thing we didn't go live. Always run the gate against actual data; logging confidence is not the same as data correctness.

4. **Multivector changes everything.** The "1/(N+1) description dilution" code-review concern evaporates when utterances are separate points instead of centroided into the base. The architecture became more sophisticated silently (MAX-pool over trigger points), and old enrich code no longer fits. Document these changes or they bite you.

5. **Autonomous overnight runs need escape hatches.** The harness reaper killed the background tasks twice, correctly (they hung). A fully detached process (outside session tracking) survives. Resume-safety (cache + file-exists) is not a nice-to-have; it's load-bearing for unattended work.

## Next Steps

1. **Operator decides** (3 questions in integration plan):
   - OK to edit vendored `server.py _trigger_phrases`?
   - Cap allocation: utterances-first at 12 (recommended) or raise to 16?
   - Shadow reindex acceptable for the gate?

2. **Task 1 (code):** Extend `server.py _trigger_phrases` with an llm-utterance source, toggle `SKILL_LLM_TRIGGERS`, test selftest (no network). Mirror to `scripts/build_triggers.py` or document divergence.

3. **Task 2 (deploy + reindex):** Deploy engine change to venv, reindex shadow with flag on.

4. **Task 3 (gate):** Verify `precision_eval.py` handles multivector comparisons correctly, run on 532-scenario corpus, record numbers.

5. **Task 4 (promote):** Snapshot live, promote shadow to live ONLY if gate passes (rank-1/top-5 recall rises, precision holds, no skill drops).

6. **Follow-on (deferred):** Flywheel item #3 (miss-auditor: transcript LLM-judge → labeled misses feeding back to generation) — after #1/#2 land live.

---

**Files for handoff:**
- `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/plans/2026-07-08-multivector-utterance-trigger-integration-plan.md` — the integration spec (read first for next operator decision)
- `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/plans/reports/autonomous-full-flywheel-run-decisions-260708-0408-report.md` — run history + parity blocker proof
- `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/plans/reports/qwen35-9b-thinking-on-investigation-260708-0302-report.md` — thinking dead-end evidence
- Generated data (gitignored, reusable): `eval/scenarios-shadow/` (532), `eval/triggers.json` (532 utterance layers)
