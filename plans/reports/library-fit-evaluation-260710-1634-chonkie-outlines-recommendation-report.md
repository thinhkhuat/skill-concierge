# Chonkie & Outlines — fit assessment for skill-concierge

**Date:** 2026-07-10 · **Scope:** analysis only, no code changed · **Verdict: adopt neither.**

Both libraries are well-built and both solve real problems. Neither solves a problem
skill-concierge has. One of them (chonkie) would measurably make retrieval *worse*.

The study was still worth doing: instrumenting the live index to test the two adoption
cases surfaced four findings about skill-concierge itself, one of which is a latent defect
that arms itself the first time anyone adds a `pattern` — or any hard-to-satisfy
constraint — to the flywheel's schema.

> **Revision note (2026-07-10, post-validation).** An earlier draft of this report claimed a
> `pattern` keyword *silently breaks / disintegrates LM Studio's constrained decoding*.
> **That claim was wrong and is retracted.** `pattern` is enforced correctly. The corrected
> root cause is in **F1** below. It was reproduced deterministically, then independently
> re-run by an adversarial Opus validator instructed to refute it: all eight claims came back
> CONFIRMED, none refuted. Its three precision corrections are folded in and attributed.

---

## Part 1 — Where the codebase stands

skill-concierge is a governance layer over Claude Code's skill mechanism, built on three
organs (`openwiki/quickstart.md:28-34`):

| Organ | Question it answers | Mechanism |
|---|---|---|
| **Retrieve** | *Which* skill fits? | Qdrant + `paraphrase-multilingual-mpnet-base-v2` (768-dim), MAX-pool over per-skill "trigger" points |
| **Enforce** | *Whether* a skill is used at all | per-turn `UserPromptSubmit` hook (`hooks/scripts/enforcer.py`) |
| **Ledger** | *What* actually got used | append-only invocation log → data-backed always-on curation |

**Live state:** version `0.19.1` + an unreleased entry. Qdrant collection `claude_skills`
holds **6,477 points across 427 skills** (~15 points/skill), configured per `.mcp.json` with
`SKILL_LLM_TRIGGERS=1`, `TRIGGERS_MAX=16`, `SKILL_TOP_K=10`.

**Recent arc (last ~15 commits), in order of consequence:**

1. **The retrieval flywheel became first-class** (`0f9a468`, `718ce51`) — an offline local-LLM
   generator writes ~10 natural "utterance" trigger phrases per skill (EN+VN), layered
   *first* into the MAX-pool trigger index ahead of description- and body-derived phrases
   (ADR-0026).
2. **The generator's central lesson was vocabulary distance, not sentence-likeness**
   (`2310b8a`). Measured on the live embedder: phrases that echo the description score
   0.5731 against a genuine paraphrase; phrases deliberately using *different* vocabulary
   score 0.7558 (`scripts/llm_triggers.py:50-55`). Long natural sentences *lose* on this
   embedder.
3. **Multi-session index scoping** (`e361ad3`, ADR-0028) — concurrent sessions shared one
   Qdrant collection and were deleting each other's project skills. Points now carry an
   owning `scope`.
4. **The same CWD-scoped bug repeated in the override map** (`5199d49`) — a globally-shared
   artifact driven by a project-scoped view.
5. **Generation model swapped** to `gemma-4-e4b-it-qat-optiq` — MRR 0.231 → 0.462, mean rank
   56.6 → 13.1 on a 20-probe held-out eval. The CHANGELOG is admirably honest that the
   headline gain is partly carried by 6 skills that previously had *no* utterances at all,
   and that `precision_eval.py` could not adjudicate the swap because the same run
   regenerated the eval scenarios, making it circular.

The house style is unusually disciplined: immutable ADRs, one-var reverts for every engine
flag, shadow-first rollout of risky filters, and a loud, repeated warning that ledger
metrics are **epoch-scoped and must never be pooled across config changes**
(`AGENTS.md:75-94`). **No ledger rate is cited anywhere in this report.**

---

## Part 2 — The verdicts

### Outlines — **No.** It adds zero constraint power on this architecture.

The flywheel client already gets grammar-constrained JSON from LM Studio server-side
(`scripts/flywheel_llm.py:76-80`), via `response_format: {"type":"json_schema", strict:true}`.

Outlines splits its backends into two hard groups (`src/outlines/models/__init__.py:32-45`):

- **`SteerableModel`** = `LlamaCpp`, `MLXLM`, `Transformers` — these get real in-process,
  token-level logit masking driven by an FSM compiled from the schema by the Rust
  `outlines_core` crate.
- **`BlackBoxModel`** = everything else, *including `LMStudio` and `OpenAI`*. For these,
  Outlines' own generator docstring says it plainly: *"Synchronous generator for which we
  don't control constrained generation. The output type provided is not compiled into a
  logits processor, but is instead directly passed on to the model."*
  (`src/outlines/generator.py:28-35`)

`LMStudio.generate` does exactly one thing of substance: `kwargs["response_format"] =
format_output_type(output_type)` then `model.respond(...)` (`src/outlines/models/lmstudio.py:213-226`).
That is byte-for-byte the payload `flywheel_llm.chat()` already builds by hand.

So adoption would mean: **replace one dependency-free `urllib.request` call with ~10
third-party packages** (`jinja2, cloudpickle, diskcache, pydantic, jsonschema, pillow,
genson, jsonpath_ng, outlines_core` (a Rust wheel), plus the `lmstudio` SDK) **to produce an
identical HTTP body.** It would also *remove* capability: the LM Studio adapter raises
`TypeError` on Outlines' `Regex` and `CFG` output types (`lmstudio.py:141-153`) — even though,
as **F1** establishes by measurement, LM Studio's own server enforces schema `pattern` perfectly
well. A raw schema dict with `"pattern"` does pass through Outlines untouched; the `Regex` *type*
is what's blocked.

**The one condition under which Outlines becomes the right answer:** if skill-concierge ever
abandons the "call a separately-running LM Studio server" shape and loads a model in-process
(llama.cpp / transformers / MLX). Then, and only then, you get FSM-guided decoding, regex
constraints, and Lark CFGs — things HTTP `json_schema` genuinely cannot express. That is a
deployment-model change, not a library swap.

**One thing the flywheel wanted that Outlines cannot deliver either:** the "≥3 of these 10
array items must be Vietnamese" rule. JSON Schema has no cross-item cardinality construct,
and Outlines ships no primitive for it. The current post-hoc count-and-retry-once heuristic
(`scripts/llm_triggers.py:179-183`) is, honestly, the pragmatic answer.

### Chonkie — **No.** Measured: it degrades retrieval here.

Chonkie v1.7.0, MIT, upstream `chonkie-inc/chonkie` (the `feyninc` remote carries no
rebranding; it reads as a sync fork). Twelve chunkers, a Rust core, real benchmarks against
LangChain/LlamaIndex on 100K-Wikipedia-article workloads.

The apparent case for it looked strong. I measured it and it collapsed.

**The apparent hole.** `server._skill_text()` embeds `name + description + body[:4000]`
(`vendor/skill-search/skill_search/server.py:340-342`). The live tokenizer truncates at
**512 tokens** — I read it off the loaded model: `{'max_length': 512, ...}`. Measured across
the real 427-skill corpus:

- **403 / 427 skills (94.4%)** exceed the window on their base point.
- Of 496,194 tokens handed to the embedder, **283,085 (57.1%) are silently discarded.**
- The `body[:4000]` character cap is effectively dead code — the tokenizer cuts first.
- Confirmed adversarially: appending 3,200 characters of unrelated text about banana exports
  to a skill body changes its embedding by **cosine 1.000000** — i.e. not at all.

That reads like a textbook chunking problem. It isn't.

**Why it doesn't matter.** Retrieval is MAX-pool: `query_points_groups(group_by="name",
group_size=1)` keeps each skill's single best-matching point. I probed the live index with 16
realistic queries × top-10 = 160 skill slots and recorded which *kind* of point won:

```
trigger   160  (100.0%)
base        0  (  0.0%)
```

**The base point never wins. Not once.** Short queries match short trigger phrases; a
512-token mean-pooled blob cannot compete. The 57% truncation loss is real and completely
inert.

**What adding chunks would actually do.** I simulated a chunk layer — markdown-header split,
packed to ≤400 tokens, capped at 30/skill — over a random 60-skill sample (1,083 chunks,
~18 new points/skill on top of ~15). Note this is close to what Chonkie's `RecursiveChunker`
does *by default*: its rule cascade is paragraph → sentence → punctuation → whitespace, with
**no markdown-heading awareness at all**. (Heading-aware splitting is not in the library; it
lives in an external HuggingFace-hosted "recipe" fetched over the network at runtime.)

Against 12 realistic intent queries, holding the skill set fixed:

| Metric | Live index | + body chunks |
|---|---|---|
| mean top-1 margin over median | 0.283 | **0.264** (−6.9%) |
| top-1 winner changed | — | **2 / 12 queries** |

Both flips went to a *worse* skill: `"review my pull request"` → `supabase-apply-migration`;
`"build an MCP server for my API"` → `ck:gkg`. Across 720 (skill, query) pairs, a body chunk
outscored the skill's existing best point 41.7% of the time — but overwhelmingly for
**irrelevant** skills (`hermes-agent` 0.378 → 0.643 on the MCP query; `vn-news-coverage-tracker`
0.192 → 0.327 on a database-schema query). Chunks raise the noise floor and compress the
margin the retriever depends on.

This is exactly the failure ADR-0023 already predicted and is shadow-filtering against:
body prose is *workflow narration*, and *"a summary embeds near generic process-prose rather
than user intent, so indexing it as a trigger point pulls the skill toward the wrong
queries and buries it under its own noise."* The repo reached this conclusion before I did.
Chonkie would inject more of precisely that content.

**A hypothesis of mine that the data refuted.** I expected chunks to raise false-fire against
the enforcer's `GETAWAY_FLOOR = 0.45`. They don't — chunk max on chit-chat averaged **0.379**
vs the live index's **0.539**. Chunks are *less* false-firey than the trigger layer. I was
wrong, and the number is above.

**Secondary reasons, all confirming:** no fastembed/ONNX adapter exists in chonkie
(`SemanticChunker` would need a second embedding stack — `model2vec` or `sentence-transformers` —
deciding chunk boundaries in a different vector space from the one doing retrieval); the base
install adds `numpy, tqdm, tenacity, httpx, tokie, chonkie-core` (a Rust wheel) to an engine
venv that today carries only `mcp, qdrant-client, fastembed, requests`; and the corpus is 427
short structured markdown files, not a throughput problem.

---

## Part 3 — What the study actually surfaced

The libraries are a "no". These four findings are the return on the investigation.

### F1 — A hard-to-satisfy `pattern` starves the string-close token (highest value)

Both the constraints work. The failure is a **prompt-vs-constraint conflict**, not a broken grammar.

**Controlled repro** (`scratchpad/repro_pattern.py`, temperature 0.0, seed 42, 3 trials/arm,
`gemma-4-e4b-it-qat-optiq`). One variable changed per arm:

| arm | schema | result | `finish_reason` |
|---|---|---|---|
| A | no `pattern` | OK | `stop` |
| B | `pattern` on items, ASCII `^[A-Za-z ]+$` | OK | `stop` |
| D | `pattern` on a scalar string | OK | `stop` |
| E | `pattern` on a scalar, unicode class | OK | `stop` |
| F | `pattern: ".*"` (trivial) | OK | `stop` |
| **C** | `pattern` requiring a Vietnamese char, **English prompt** | **BROKEN 3/3** | **`length`** |

Four arms carry `pattern` and finish cleanly. Only the arm whose regex demands a character the
model won't emit fails — and it fails by running to `max_tokens`, not by erroring.

**Disambiguation.** Three further arms isolate the true variable:

- **It is not unicode.** A pure-ASCII regex requiring a *digit* (`^[^"]*[0-9][^"]*$`) with the same
  English prompt reproduces the identical failure (`length`, malformed).
- **It is not the regex.** That *same* Vietnamese-requiring regex with a *Vietnamese* prompt returns
  valid JSON, `finish_reason: stop` → `['commit code nhanh chóng', 'push thay đổi lên remote', …]`.
- **It is not the token budget.** Raising `max_tokens` 500 → 2000 still truncates.

**Mechanism.** The FSM masks the string-closing `"` until the regex's character-class obligation
has been consumed. `[^"]*` lets the model emit non-quote characters indefinitely beforehand. Steered
by an English prompt, it never produces the required character, never earns the right to close the
string, and generates until the token cap. The output is a truncated, unterminated JSON string.

*(Precision, per the validator: the close token is masked **until the obligation is met**, not
"never permitted". And the failure is deterministic while the bytes are not — content varied across
5 runs at temperature 0, but 5/5 hit `length` and 5/5 were malformed.)*

**The decisive proof, run independently.** With the VN-requiring pattern, the raw truncated content
contains exactly **three** double-quotes (two around the `triggers` key, one opening the first array
string), **zero** Vietnamese characters, and **no closing quote**. Had the grammar been ignored, a
bare `"` would have closed a Vietnamese-free string. It never did. The constraint held.

**`minItems` is genuinely coercive**, not mere prompt compliance:

- schema `minItems: 25, maxItems: 25` vs prompt *"Give exactly TWO. Only two."* → **25 items**, `stop`.
- validator pushed harder: `minItems: 40` vs *"Return an empty list. No items at all."* → **40 items**, `stop`.

So the flywheel's `minItems: 4` is real — and the biggest unverified item from the Outlines audit
(*"does `minItems` survive into the compiled FSM?"*) is now answered: on this backend, yes.

**Correcting the Outlines footnote.** An earlier draft said Outlines' LM Studio adapter *"refuses to
pass `pattern` at all,"* and called that correct. Both halves are wrong. `format_output_type`
(`lmstudio.py:141-153`) rejects only the **`Regex` DSL type** and `CFG`; a raw JSON-Schema dict
containing `"pattern"` passes straight through `JsonSchema.is_json_schema(...)` →
`JsonSchema.convert_to(...)`. And since LM Studio *does* enforce `pattern` correctly, the block on
the `Regex` type is an over-restriction, not a virtue.

**Consequence for this repo.** `pattern` is usable, but a regex the model is unlikely to satisfy
converts a well-formed request into a silent per-skill drop. See **F1b**.

### F1b — The real defect: `chat()` never inspects `finish_reason`

`flywheel_llm.chat()` reads `["choices"][0]["message"]["content"]` and nothing else
(`scripts/flywheel_llm.py:92`). Its retry loop fires on **HTTP 503 only** (`:95-98`). Therefore a
`finish_reason: length` truncation is:

1. never retried,
2. indistinguishable from any other malformed reply,
3. surfaced as a `JSONDecodeError` out of `parse_json_reply()` (`:49-52`),
4. caught by `llm_triggers.run()`'s bare `except Exception` (`:184-187`), which prints `WARN` and
   `continue`s — **dropping that skill from the utterance layer entirely.**

The only signal is a line on stdout. No metric, no `finish_reason` check, no distinction from a
genuine model error.

**Severity — upgraded.** I first called this "low". The validator pushed back, correctly: it is
dormant *only* because the live schema happens to contain no `pattern`. Anyone who later tightens
that schema re-arms it instantly. It is a loaded gun, not a spent one. The cheap guard is to raise
on `finish_reason != "stop"` inside `chat()` so truncation fails loudly instead of costing a skill.

### F2 — The base point is dead weight

0/160 wins. It costs an embed on every reindex for 427 skills, and it exists to serve two
things that don't need a vector: `get_skill`'s O(1) path lookup by `_point_id(name)`
(`server.py:576-582`) and a fallback description. **This is a cheap, safe cleanup** — retrieval
would be unchanged by construction, and reindex gets faster. Worth its own ADR rather than a
drive-by; I am flagging it, not doing it, because it is out of the scope you set.

### F3 — Score floor alone would pass 9/10 chit-chat turns

Against the live index, 9 of 10 handpicked conversational strings score **above** the
`GETAWAY_FLOOR = 0.45` on their top skill (mean 0.539). `"what did you just say?"` scores
0.661. Suppression therefore rests almost entirely on the second line of defence — the
actionability gate at `enforcer.py:605` — not on the score floor.

This is not new to the repo: the bge-m3 plan recorded the same structural point ("`GETAWAY_FLOOR=0.45`
goes inert; suppression falls entirely on the relative actionability gate"). This measurement
says it is *already* nearly inert on mpnet. **Caveat: 10 handpicked strings is not a rate, and
scoring above the floor is not the same as firing an offer** — the intent gate catches these.
This is a structural observation, not a telemetry claim.

### F4 — Deep body content is ~40% retrievable, for a query distribution that doesn't exist

Probing with verbatim sentences drawn from *past* the 512-token cut, the owning skill came
back in the top-10 for only **5 of 12** probes. A real hole — but nobody queries a skill router
with a verbatim sentence from deep inside a SKILL.md. The retrieval target is *intent → skill*,
and the trigger layer models intent directly. **Optimizing this hole would be optimizing a
query distribution that does not occur.**

---

## Part 4 — The one idea worth stealing (and its honest limits)

Studying Outlines' type system suggests a **zero-dependency** restructuring of the flywheel
schema. Since `minItems` *is* enforced (F1) and `pattern` is not, carry the Vietnamese
guarantee **structurally** rather than by prompt rule:

```python
# instead of one array + "RULE 5: at least 3 MUST be Vietnamese" + post-hoc count + retry
{"triggers_en": {"type":"array", "minItems":7, "maxItems":7},
 "triggers_vn": {"type":"array", "minItems":3, "maxItems":3}}
```

This converts a *probabilistic prompt rule* into a *structural guarantee*, eliminating the
retry round-trip (`llm_triggers.py:179-183`) that costs a second LLM call on every
non-compliant skill.

**Honest limits, measured.** On 3 test skills the current prompt already complied (3–4 VN
phrases, zero retries), so the split schema **did not beat it** — same 10 phrases, same VN
count. Its value is bounding the *tail* (the CHANGELOG reports mean VN phrases/skill at 3.33,
which implies skills below 3 exist), not lifting the mean. It also cannot force the *content*
of `triggers_vn` to actually be Vietnamese — only that three slots exist. And in my test the
reworded prompt drifted into question forms (`"Làm sao để ghi lại thay đổi?"`) that the
current RULE 4 explicitly forbids.

**Verdict on the idea: promising, unproven, n=3.** It deserves a proper A/B against the
existing generator before anyone touches `llm_triggers.py`. I am not recommending it be
shipped on this evidence.

### Why `pattern` is the wrong tool for the Vietnamese requirement — measured

The obvious alternative is to force Vietnamese with a regex. Don't. Following F1's mechanism, a
regex that *front-loads* the required character terminates cleanly — and produces garbage:

| pattern shape | `finish_reason` | output |
|---|---|---|
| `^[^"]*[VN][^"]*$` (wandering) | `length` | truncated, malformed |
| `^[VN].*` (required char first) | `stop` | `['éto commit', 'éto push', 'éto pull']` |
| `^.{0,20}[VN].{0,40}$` (bounded) | `stop` | `['Commit your changes.â', 'Push to remote.â', …]` |

The FSM satisfies the constraint by **injecting the required character as noise**. `é`, `â` — legal
under the regex, meaningless as Vietnamese. Constrained decoding can force *characters*; it cannot
manufacture a *language*.

This is the strongest argument for leaving `llm_triggers.py` alone: the existing count-and-retry
heuristic (`:179-183`) asks the model to *mean* Vietnamese and checks whether it did. A grammar can
only compel bytes. **Do not replace a semantic check with a syntactic one.**

---

## Summary

| Question | Answer |
|---|---|
| Adopt Outlines? | **No.** Zero added constraint power on an HTTP/LM-Studio architecture; ~10 deps for an identical payload. Revisit *only* if the flywheel moves to an in-process model. |
| Adopt Chonkie? | **No.** Measured −6.9% top-1 separation and 2/12 wrong winner flips. It injects exactly the body-prose noise ADR-0023 is filtering out. |
| Was anything gained? | Yes — **F1b** (`chat()` ignores `finish_reason`, so a truncation silently drops a skill) is a real latent defect, and **F2** (base point never wins) is a free cleanup. |

## Recommended actions (none taken; analysis-only scope)

| # | Action | Risk | Basis |
|---|---|---|---|
| 1 | In `flywheel_llm.chat()`, raise on `finish_reason != "stop"` so truncation fails loudly instead of silently costing a skill. | Very low | F1b, validator-confirmed |
| 2 | Do **not** add `pattern` to the flywheel schema; keep the semantic count-and-retry check. | — | Part 4 (constrained decoding injects noise characters) |
| 3 | Treat `minItems` as coercive. A large `minItems` on a thin skill will pad with junk at `finish_reason: stop` — quality rot, not a crash. | Low | F1, `minItems: 40` vs "empty list" → 40 items |
| 4 | Consider retiring the base point (ADR, not a patch). | Medium | F2 |

## Unresolved questions

1. **F2 cleanup scope.** Removing the base point changes `get_skill`'s fast path and the
   `description` payload used by `_fuse_ranked`. Needs an ADR, not a patch.
2. **Cross-model generality of F1.** Confirmed on `gemma-4-e4b-it-qat-optiq` and
   `gemma-4-12b-it-qat-optiq` (both `length` + malformed, grammar held). `qwen3.5-4b-optiq` is
   **UNVERIFIED** — LM Studio returned HTTP 400 "Failed to load model". `gpt-oss-20b-optiq`
   untested. Some engines emit `stop` with a best-effort *violation* instead of running to
   `length`; if the flywheel model changes, re-run `scratchpad/repro_pattern.py`.
3. **The split-array schema needs a real A/B** across the full 427-skill corpus, scored on
   held-out retrieval, before it is more than a hypothesis.
4. **F1's "75–97 completion tokens" band** rests on 3 samples of mine plus 1 independent sample
   (81) from the validator. Directionally solid; the full envelope is **UNVERIFIED** — and per this
   repo's epoch-scoping rule I did not consult the ledger for it.
4. **`feyninc/chonkie` vs upstream diff** was not computed — the clone is shallow (1 commit) and
   I used no network compare. Nothing in the tree carries `feyninc` branding.
5. **Chunk simulation used one configuration** (header split, ≤400 tokens, ≤30 chunks/skill) on a
   60-skill sample with no ground-truth relevance labels; `margin over median` is a proxy for
   separation. A `SemanticChunker` configuration could behave differently, though it would still
   be embedding body prose.
