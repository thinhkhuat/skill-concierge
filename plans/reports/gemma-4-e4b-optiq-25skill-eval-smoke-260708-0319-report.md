# Smoke Report — 25-skill eval-scenario generation, gemma-4-e4b-it-optiq

**Date:** 2026-07-08 · **Model:** `gemma-4-e4b-it-optiq` (~6 GB, the small E4B Gemma-4 variant, LM Studio :4310) · **Script:** `scripts/llm_eval_gen.py`
**Purpose:** Test whether a smaller/faster Gemma-4 holds quality vs the 12B. Matched to the gemma-4-12b-it-optiq and qwen3.5-9b 25-skill runs.

## Result

| Metric | e4b | gemma-4-12b (ref) | qwen3.5-9b off (ref) |
|---|---|---|---|
| Files | 25/25 | 25/25 | 25/25 |
| VN ≥2 | **25/25 (100%)** | 25/25 (100%) | 8/25 (32%) |
| VN utterances | 78 | 85 | 41 |
| Pos / Neg avg | 11.8 / 4.8 | 12.1 / 4.6 | 11.7 / 5.9 |
| **Wall time (25)** | **2m25s** | 4m27s | ~7-8 min |

**Headline: e4b matches the 12B on VN coverage (100%) and success (25/25) at ~1.8× the speed** (~5.8s/skill vs ~10.7s). Projected full 498 run: ~48 min vs the 12B's ~89 min.

## The one real gap — negative quality

e4b's positives (incl. Vietnamese) are natural and on-target, indistinguishable in quality from the 12B. **The difference is in the negatives** — the confusable "should NOT fire" utterances that make the precision gate meaningful:

- **e4b (softer, generic off-topic):** speech → *"What is the capital of France?"*, *"Play the last song I was listening to."*, *"Search for flights from New York to London."* — trivially separable, not boundary-tests.
- **12B (sharp, boundary-aware):** speech → *"create a custom voice clone from my own recording"* (the skill marks custom-voice **out of scope**), *"check the grammar in this speech draft"* (wordplay on "speech").

e4b's dev-domain negatives are better than its speech ones (Root-Cause → "deploy this feature", "optimize database query", "generate a unit test" — same domain, different task), but across the board e4b produces **easier** negatives than the 12B.

**Why it matters:** easy negatives inflate the true-negative precision score (they're trivially separated in embedding space), so an e4b corpus would make the Task-4 precision gate **less rigorous** — it would under-detect cannibalization. Hard negatives are exactly what stress the boundary.

## Verdict / options

- **e4b** — best when speed/scale dominate. 100% VN, solid positives, ~2× faster. Weaker precision test.
- **12B** — best for the eval corpus specifically: sharper negatives → a trustworthy precision gate. The corpus is a one-time build, so the extra ~40 min buys a better benchmark.
- **Hybrid worth considering:** 12B for scenarios (needs hard negatives), e4b for triggers (short phrases, no negatives, speed matters). Not yet tested.

Recommendation: **12B for the scenario corpus** (negative sharpness is load-bearing for the precision gate); e4b is a strong fast fallback and a good candidate for the triggers pass.

## Open questions

1. Is the precision-gate rigor worth ~40 extra minutes (12B over e4b) for the one-time corpus build? Operator's call.
2. Untested hybrid: e4b for `llm_triggers.py` (no negatives) — likely fine and fast.
