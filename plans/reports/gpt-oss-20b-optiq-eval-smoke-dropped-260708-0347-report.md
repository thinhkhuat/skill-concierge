# Smoke Report — gpt-oss-20b-optiq eval generation (DROPPED)

**Date:** 2026-07-08 · **Model:** `gpt-oss-20b-optiq` (LM Studio :4310, a reasoning model) · **Script:** `scripts/llm_eval_gen.py`
**Outcome:** Not viable. Dropped by operator (below gemma-4 quality); the 20-skill second run was cancelled. gemma-4-12b-it-optiq stands as the generation model.

## Runs

| Run | Config | Result |
|---|---|---|
| 1 (5 skills) | max_tokens 2048 | **3/5** — 2 failed `Unterminated string` (JSON truncated mid-string) |
| 2 (5 skills, "fair") | max_tokens 4096 | **0/5** — 3 `Unterminated string` (one at char 4908), 2 emitted only `positive` (no `negative`) |

Speed: ~67s/skill at 4096 (5m37s/5) — ~7× slower than gemma-4-e4b (~5.8s) and ~6× slower than gemma-4-12b (~10.7s).

## Root cause

gpt-oss-20b is a reasoning model. Its reasoning consumes the token budget; the schema-constrained JSON then either **truncates** (unterminated string) or comes out **incomplete** (only the `positive` key). Raising the budget 2048→4096 made it *worse*, not better — the model reasoned/rambled longer and still failed to close valid JSON. So this is not a simple "needs more tokens" fix; the reasoning behavior itself fights bounded structured output on this complex prompt (same failure family as qwen3.5 thinking-on, different symptom: truncation vs empty content).

## Quality note (the 3 that did succeed at 2048)

VN-capable (2-4 Vietnamese positives) and valid schema — but only **8-9 positives** each (at the MIN_POSITIVE=8 floor) vs gemma-4's consistent 12. So even when it worked, output was thinner than gemma-4.

## Verdict

**Dropped.** gpt-oss-20b is slower, unreliable at completing bounded JSON, and thinner when it does. No path to gemma-4 parity for this job.

## Model comparison so far (25-skill smokes unless noted)

| Model | Success | VN ≥2 | Speed | Notes |
|---|---|---|---|---|
| **gemma-4-12b-it-optiq** | 25/25 | 100% | 4m27s | sharp negatives — **recommended for scenarios** |
| gemma-4-e4b-it-optiq | 25/25 | 100% | 2m25s | ~2× faster; softer negatives |
| qwen3.5-9b (thinking off) | 25/25 | 32% | ~7-8m | VN-unreliable |
| qwen3.5-9b (thinking on) | — | — | — | breaks JSON (empty content) |
| gpt-oss-20b-optiq | 0-3/5 | (n/a) | ~67s/skill | truncates/incomplete — **dropped** |

## Code

`FLYWHEEL_MAX_TOKENS` override (added to test the truncation) reverted — unused; gemma runs fine at the default 2048.
