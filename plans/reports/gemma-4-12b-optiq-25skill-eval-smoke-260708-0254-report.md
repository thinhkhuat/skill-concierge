# Smoke Report — 25-skill eval-scenario generation, gemma-4-12b-it-optiq

**Date:** 2026-07-08 · **Model:** `gemma-4-12b-it-optiq` (LM Studio, MLX, local) · **Script:** `scripts/llm_eval_gen.py`
**Purpose:** Validate the eval-scenario generator (Task 1 of the local-LLM retrieval flywheel) at sample scale before the full 498-skill run. Companion report: qwen-3.5-9b run (same 25 skills).

## Setup

| Item | Value |
|---|---|
| Endpoint | `http://localhost:4310/v1/chat/completions` (LM Studio OpenAI-compat) |
| Structured output | `response_format: {type: json_schema, strict}` — grammar-constrained valid JSON |
| Params | temp 0.4, max_tokens 2048, VN-retry (re-ask once if <2 Vietnamese positives) |
| Sample | first 25 skills (sorted), `--limit 25 --rate 1` |
| Output | `eval/scenarios-shadow-gemma/` (preserved) |

## Result — clean pass on every axis

| Metric | Result |
|---|---|
| Skills generated | **25 / 25** (0 skips, 0 chat failures) |
| VN coverage (≥2 Vietnamese positives) | **25 / 25 (100%)** — VN-retry never fired |
| Vietnamese per skill | 3-4 (total 85 VN utterances) |
| Positives per skill | 12-13 (total 302) |
| Negatives per skill | 4-5 (total 116) |
| Empty strings | 0 |
| Real skill-name leaks | 0 (a heuristic flagged 15, all verified domain-word false positives, e.g. "validation", "migration", "speech") |
| Wall time | 4m27s (~10.7s/skill incl. cold-load) → ~89 min projected for 498 |

## Quality (manual read)

- **VN natural, not translated-sounding:** e.g. speech → *"Làm ơn đọc đoạn văn này cho tôi nghe."*; Excel → *"Tính tổng doanh thu từ file Excel này giúp tôi với."*; ci-cd → *"Giúp tôi thiết lập pipeline CI/CD cho dự án React của mình."*
- **Boundary-aware negatives:** speech's negatives included *"create a custom voice clone from my own recording"* (the skill's description marks custom-voice **out of scope**) and *"check the grammar in this speech draft"* (wordplay on "speech") — sharp near-misses that test the retrieval boundary, not random off-topic lines.
- **True name preserved:** the `"skill"` field keeps the exact live-index key (incl. quoted names like `"\"speech\""` and spaced names like `"Root Cause Tracing"`); only the FILENAME is slugged. So `precision_eval.py` / `enrich_index.py` still match.

## Context — what this run also proved fixed

The earlier RTX-box smoke failed 6/10. Root causes fixed before this run:
- **Unquoted-key JSON** (60% failure): the prompt's example used unquoted keys and Ollama's loose `format:"json"` let the model mirror them. Fixed by moving to LM Studio's strict `response_format: json_schema` → 10/10, then 25/25.
- **Filename corruption:** live-index names carry literal quotes/spaces; `slug()` now sanitizes all filesystem-unsafe chars while the stored name stays true.

## Verdict

**gemma-4-12b-it-optiq is proven at 25-skill scale — recommended for the full 498 run.** 100% success, 100% VN, tight in-spec counts, natural VN, boundary-aware negatives, no retries needed.

## Open questions

1. Full-run cost ~89 min (eval-gen) + similar (triggers) on the Mac MLX box — schedule vs run-now is the operator's call.
2. Triggers generator (`llm_triggers.py`) needs the same VN strengthening folded in before its full run.
3. Delta confound / description-weight dilution (from code review) still to be settled at the Task-4 precision gate, not here.
