# Investigation Report — should qwen3.5-9b thinking be enabled for the generation job?

**Date:** 2026-07-08 · **Model:** `qwen/qwen3.5-9b` (LM Studio :4310) · **Context:** thinking was disabled on :4310 originally for cognee's JSON extraction; cognee no longer uses :4310, so the constraint was revisited.

## Question

Enable qwen thinking for eval-scenario generation, now that the cognee reason for disabling it is gone? Motivation: thinking-off qwen only hit 32% Vietnamese coverage (companion report `qwen35-9b-thinking-off-...`); could reasoning close the VN gap?

## Findings (raw, proven)

**1. The toggle is per-request.** `reasoning_effort: "low|medium|high"` activates qwen reasoning on :4310 (probe: `reasoning_content` filled 867 chars). `chat_template_kwargs.enable_thinking` is **ignored**. No LM Studio GUI change needed.

**2. Thinking is INCOMPATIBLE with our strict JSON schema.** With `reasoning_effort` set AND `response_format: json_schema` (strict) active:
- `content: ''` (empty), `reasoning_content` only 34 chars, `finish_reason: stop`.
- A 3-skill probe → 3/3 failed with `Expecting value: line 1 column 1 (char 0)` (empty content parsed as JSON).

Without the schema, thinking works fine:
- `reasoning_content` 5381 chars, then valid fenced JSON `{"colors": ["#FF0000", "#0000FF"]}`.

So on this LM Studio build the grammar-constrained decoder and the reasoning path do not coexist — turning thinking on **empties the content** whenever the strict schema is enforced.

## Implication

To use thinking at all, we must **drop the strict `response_format: json_schema`** — the exact mechanism that fixed the original 60% unquoted-key JSON failure (see gemma/qwen smoke reports). That trades a proven reliability guarantee for prompt-guided JSON (unquoted-key risk returns), purely to chase Vietnamese coverage that **gemma-4-12b-it-optiq already delivers at 100% with the schema intact and no thinking**.

## Verdict

**Do not enable thinking for this job.** Two independent reasons:
1. It breaks the strict-schema JSON guarantee (empty content) — a hard regression.
2. Even if worked around (schema-less), it would at best approach what gemma already achieves (100% VN), while being slower (reasoning tokens) — no net gain.

Keep **gemma-4-12b-it-optiq + strict schema, thinking off** as the generation config.

## Change landed

`scripts/flywheel_llm.py` `chat()` gained an env toggle `FLYWHEEL_REASONING_EFFORT` (default unset → thinking off; gemma path unaffected). It widens max_tokens/timeout when set, and carries a code warning that it is incompatible with the strict schema. Left in as a documented, off-by-default escape hatch — not used by the production path.

## Addendum (2026-07-08, after operator enabled thinking SERVER-SIDE at medium)

The operator flipped qwen's LM Studio server config to thinking-on (medium) by default and asked to re-test — the earlier finding was per-request only. Server-side activation was tested and closes the question completely:

| thinking (server-side) + ... | result |
|---|---|
| strict `json_schema` | content **empty** (reasoning 29) — same as per-request |
| non-strict `json_schema` | content **empty** |
| `json_object` | server **error** (no choices) |
| **no** response_format, trivial prompt ("two colors") | valid JSON, reasoning 512 — works |
| **no** response_format, real generation prompt | **empty** content, 3/3 fail, 4m11s/3 |

**Why schema-less also fails on the real job:** the generation prompt is complex (long skill description + "12 positives, ≥3 Vietnamese, 4-6 confusable negatives"). Thinking-on burns the entire token budget on `reasoning_content` and never emits the final JSON within 4096 tokens → empty/truncated content. It only "works" on trivial prompts.

**Conclusion (final):** qwen3.5-9b thinking-on is unusable for this job by **every** path — activation method (per-request or server-side) and output mode (strict/non-strict schema, json_object, schema-less) all fail. The operator's server-side switch, fine for qwen's general use, makes qwen unusable for the flywheel specifically.

**Code:** the experimental `FLYWHEEL_REASONING_EFFORT` / `FLYWHEEL_NO_SCHEMA` toggles were REVERTED out of `flywheel_llm.py` (proven dead). `chat()` now documents that the generation model must have thinking off; `FLYWHEEL_LLM_MODEL` (model override) is retained. gemma-4-12b-it-optiq stands as the production model.
