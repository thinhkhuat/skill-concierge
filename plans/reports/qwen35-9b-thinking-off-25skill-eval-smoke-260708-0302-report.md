# Smoke Report — 25-skill eval-scenario generation, qwen3.5-9b (thinking-OFF)

**Date:** 2026-07-08 · **Model:** `qwen/qwen3.5-9b` (LM Studio :4310, MLX, **thinking disabled** in server config) · **Script:** `scripts/llm_eval_gen.py`
**Purpose:** Matched A/B against the gemma-4-12b-it-optiq run (same 25 skills, same params) — see companion report `gemma-4-12b-optiq-25skill-eval-smoke-260708-0254-report.md`.
**Note:** thinking is OFF because it was disabled originally for cognee's JSON extraction; cognee no longer uses :4310. A thinking-ON qwen A/B is the logical follow-up.

## Setup (identical to the gemma run)

Endpoint `http://localhost:4310/v1/chat/completions`; `response_format: json_schema` (strict); temp 0.4; max_tokens 2048; VN-retry (re-ask once if <2 Vietnamese positives); `--limit 25 --rate 1`; output `eval/scenarios-shadow-qwen/`.

## Result

| Metric | qwen3.5-9b (off) | gemma-4-12b-it-optiq |
|---|---|---|
| Files generated | 25/25 (0 chat failures) | 25/25 |
| **VN coverage (≥2 VN positives)** | **8/25 (32%)** | **25/25 (100%)** |
| VN utterances total | 41 | 85 |
| VN-retry fired | **17/25** (and still short on all 17) | 0 |
| Total positives | 293 | 302 |
| Total negatives | 147 | 116 |
| Wall time (25 skills) | ~7-8 min (retry-inflated: 17 skills = 2 calls each) | 4m27s |

## Reading

- **JSON reliability is a wash** — the strict `response_format: json_schema` fixed the unquoted-key failure for **both** models; qwen produced 25/25 valid files, same as gemma. That was never a qwen weakness once schema-constrained.
- **Vietnamese is qwen's failure axis.** Thinking-off qwen honored the ≥3-Vietnamese instruction on only 8/25 skills, and the forced retry could not rescue the other 17 — it re-emitted all-English. This is an instruction-following gap at this size/quant with thinking off, not a JSON or a prompt problem (gemma got 100% on the identical prompt).
- **17 VN-light skills** (kept, flagged): Defense-in-Depth Validation, Excel Analysis, Getting Started with Skills, Root Cause Tracing, Verification Before Completion, speech, and 11 `agent-skills:*` skills.

## Verdict

**For this VN-heavy job, thinking-off qwen3.5-9b is not viable** (32% VN). gemma-4-12b-it-optiq remains the recommended generation model. Open question this raises → does **thinking-ON** close qwen's VN gap? That A/B is the next report.

## Open questions

1. Thinking-ON qwen3.5-9b smoke (same 25 skills) — does reasoning let it plan the VN quota? Pending a toggle probe on :4310.
2. Even if thinking-on lifts qwen, it will be slower (reasoning tokens) than gemma, which already hits 100% VN with no thinking — so qwen would need a compelling size/speed edge to displace gemma.
