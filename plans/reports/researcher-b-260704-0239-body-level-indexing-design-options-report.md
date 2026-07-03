# Body-level signal in retrieval — design options, scored

Angle: does the vector store need to hold skill BODY content (not just frontmatter description) so
the "when/how/which to use" signal that lives in the body becomes retrievable? Independent read of
`vendor/skill-search/skill_search/skills_discovery.py`, `server.py`, `scripts/embed_server.py`,
`scripts/enrich_index.py`, plus the ADRs/journals that already litigated adjacent decisions.

## Ground truth first — the premise needs one correction

The body is **already embedded**, and the frontmatter description is **not** compacted at the index
layer:

- `vendor/skill-search/skill_search/skills_discovery.py:79-91` — `parse_skill` embeds the FULL
  `description` (+ `when_to_use` frontmatter if present, line 82-86), plus `body.strip()[:4000]`
  (char-capped "so embeddings stay cheap", line 91).
- `vendor/skill-search/skill_search/server.py:270-272` — `_skill_text()` concatenates
  `name + description + body` into ONE string that becomes the single `kind="base"` point
  (`server.py:352-356`).
- The "compaction" the task description refers to is Claude Code's native ~1% skillOverride
  listing tax — the thing this whole system exists to **replace** (`server.py:5-6`). Inside
  skill-search's own index, the description is full-length and the body is present too.

So the real gap is narrower than "body isn't indexed": it's (a) the body is capped at 4000
**characters**, not tokens, against a much smaller real token budget (below), (b) it's blended into
one big vector alongside name+description rather than getting its own queryable point, and (c) the
proven recall lever in this codebase — the multi-vector trigger layer — is built **only** from
`description` phrases (`server.py:242-267`, `_split_phrases`), never from body text. That's the
actual "decisive body signal is invisible to search" problem.

**Token limit that bounds options 1 and 4:** the *deployed* embedder is not the vendor package's
default. `vendor/skill-search/skill_search/server.py:73` defaults to
`BAAI/bge-small-en-v1.5`, but the actually-running engine overrides this —
`scripts/embed_server.py:13-16,41-46` and `scripts/enrich_index.py:12-19` pin
`SKILL_EMBED_MODEL=sentence-transformers/paraphrase-multilingual-mpnet-base-v2` (768-dim,
fastembed 0.8.0). Queried live: `fastembed.TextEmbedding.list_supported_models()` reports this model
as **"384 input tokens truncation."** The existing 4000-char body cap (`skills_discovery.py:91`) is
not token-aware and routinely exceeds 384 tokens for any body with more than a few sentences — so
today's single base-point embedding is *already* silently truncating most bodies mid-thought before
anything reaches the model. Any option that embeds body text (1, 4) inherits this 384-token ceiling
per embedded unit.

**Direct precedent against blending body/trigger signal into one vector:** this was tried and
killed. `docs/adr/0012-multi-vector-max-pool-retrieval.md:8-14` — the MEAN-centroid enrichment
overlay (`scripts/enrich_index.py`) averaged trigger embeddings INTO the one base vector; the ADR's
own words: *"a centroid dilutes the one distinctive phrase"* — measured worse than MAX-pooling over
**separate** points (rank-1 11.3%→25.0%, 2.2x, ADR-0012 evidence section). `doctor.py` and `setup.sh`
now actively guard against re-running that MEAN reapply under the multi-vector index
(`docs/multivector-retrieval-arc.md:38-39`). Any body-indexing option that blends rather than
adds-a-separate-point is repeating a mechanism this repo already disproved.

**Two retrieval paths, not one — matters for scoping every option:** `docs/adr/0012:43-46` — the
enforcer hook (`hooks/scripts/enforcer.py`, subprocess per prompt, budget-capped
≲300ms total per `docs/adr/0008-warm-embed-shim-timeout-calibration.md:19,39`) and the MCP
`search_skills` tool (agent-invoked, no hard latency budget) both must retrieve from the SAME index
and were deliberately kept in sync. An option that only fixes one path is weaker than one that fixes
both, and ADR-0012 spent real effort catching a divergence bug between them (stale-MCP-process
duplicate hits).

**A structural caveat that outranks all of this:** `docs/journals/journal-2026-06-29-...-v060.md:65`
— *"the substrate measures topic, not usefulness/intent... cosine score did not predict adoption"*.
More topical text (body or description) doesn't by itself fix an intent-disambiguation problem that's
already been diagnosed as structural. Recall-lever changes (this report) and intent/actionability-gate
changes (already partially shipped in `enforcer.py`'s class-margin gate) are different levers; body
indexing is squarely a recall lever, not an intent-classification fix.

## Options, scored

Axes (1-5, 5=best), plus a **Gate** column for hard architectural incompatibilities a flat sum can't
capture:

| # | Option | Recall-fix¹ | Precision risk² | Cost | Complexity | Maintenance | Gate | Total |
|---|---|---|---|---|---|---|---|---|
| 1 | Full body, chunked + MAX-pooled | 4 | 2 | 2 | 2 | 2 | PASS | 12/25 |
| 2 | Description recall + body rerank | 2 | 4 | 2 | 2 | 2 | **VETO** (hook path) | 12/25 (gated) |
| 3 | Progressive disclosure (`get_skill`) prompting | 1 | 5 | 5 | 5 | 5 | PASS (MCP-path only) | 21/25 (partial scope) |
| 4 | Extract body's own trigger/when-to-use text into the trigger layer | 5 | 4 | 4 | 3 | 4 | PASS (both paths) | 20/25 |
| 5 | Frontmatter enrichment (revive `enrich_index.py` / push `description`) | 2 | 2 | 4 | 4 | 2 | **VETO** | 14/25 (gated) |

¹ Does it make body-only decisive signal *retrievable at all* (fixes a miss), vs. only reranking/
disambiguating candidates `search_skills` already surfaced?
² 5 = low dilution/noise risk, 1 = high.

**Why the totals don't just get summed and ranked** (a flat score would mis-rank this):

- **Option 2 is gated, not merely expensive.** A cross-encoder or LLM rerank pass cannot fit inside
  the enforcer hook's ≲300ms total budget (`docs/adr/0008:19,39` — the shim itself already blew the
  original 90ms cap under real contention and had to be threaded). It could theoretically live in the
  MCP-only path, but that recreates exactly the hook/MCP divergence ADR-0012 fought to eliminate, for
  a mechanism (2) that doesn't even fix the stated recall miss — it only reorders whatever `search_skills`
  already returned. Net: high effort, half-system applicability, doesn't solve the actual problem.
- **Option 5 is gated on evidence, not opinion.** If "frontmatter enrichment" means reviving
  `enrich_index.py`, that IS the MEAN-centroid mechanism ADR-0012 measured as inferior and superseded
  — reviving it fights a shipped, evidenced decision. If it means "write richer descriptions," that
  re-introduces the per-listing token cost this system was built to eliminate. Note: a *partial*
  version of this already exists and is under-used — `skills_discovery.py:82-86` reads an optional
  `when_to_use:` frontmatter field into the embedded text. Live check: only **101 of 688** installed
  `SKILL.md` files (~15%) set it. That's a legitimate low-cost lever (skill-authoring guidance, not an
  engine change) but it is NOT the same thing as reviving the centroid script.
- **Option 3 scores highest but does not fix the stated problem** — it only helps once a skill has
  already cleared retrieval into the top-K; if the decisive signal is body-only and the skill never
  surfaces, no amount of `get_skill` pulling helps, because the agent never knows to call it. It's
  also scoped to the MCP/agent path only — the enforcer hook can't run a multi-step
  search→pull-body→decide loop inside its per-turn budget, it can only emit the offer line. Treat 3
  as a cheap **complement**, not a substitute for 4.
- **Option 4 is the only option that raises recall for body-only signal while reusing a proven,
  budget-compatible, both-paths mechanism.** It extends the exact MAX-pool trigger architecture that
  already measured 2.2x rank-1/separation (`docs/adr/0012` evidence section) — same stable
  per-(skill,slot) point-id scheme, same incremental-reindex-safety, same content-hash change
  detection (`server.py:346-363`) — just sourcing phrases from the body's own "when to use"/"Triggers:"
  prose (many SKILL.md bodies already write this explicitly — several in this catalog literally start
  a paragraph with "TRIGGER —" or "Use when:") instead of only the frontmatter description. Short
  extracted phrases stay well under the 384-token cap per point, so it doesn't inherit the truncation
  problem that a full-body chunk (option 1) would.

## Ranked recommendation

1. **Ship Option 4 first — it's the actual answer to the stated concern.** Add a body-section
   extractor mirroring `_split_phrases`/`_LABEL_RE` (`server.py:245-267`) that pulls "when to
   use"/"Triggers:"/"Use when:" — labeled sections or bulleted lists from the body — and feeds them
   through the same `_split_phrases` → trigger-point → MAX-pool pipeline, capped like description
   triggers (`_TRIG_MAX=12`, `server.py:248`). Bounded point growth, reuses proven infra, works in
   both the hook and MCP paths, no dilution risk (separate points, not a blended vector). Validate the
   same way ADR-0012 did — shadow A/B via `scripts/multivector_experiment.py` before going live, not
   a blind ship.
2. **Ship Option 3 alongside it, same PR or next — it's free and orthogonal.** Nudge the MANDATE /
   `search_skills` docstring so the agent calls `get_skill(name)` when a top candidate's fit is
   unclear from the truncated description shown in the offer (enforcer.py's `_DESC_CHARS=96` slice is
   very lossy) — but scope it to "when ambiguous," not "always," to avoid re-taxing context budget on
   every candidate. This only helps the MCP/agent-turn path, never the hook's offer decision, so it
   doesn't substitute for (1).
3. **Hold Option 1 in reserve, gate it on data.** Only revisit full-body chunking if, after (1)+(2)
   ship and a traffic window runs, `analyze.py`/`skill-usage-audit` still shows misses attributable to
   body-only signal that isn't in an extractable "when to use" section. If so, chunk by markdown
   heading, MAX-pool per chunk (never centroid), and token-cap each chunk to fit under 384 tokens —
   accept the real cost: multiplies point count (current index is already 2312 points / 500 base +
   1812 trigger per `docs/multivector-retrieval-arc.md:14`; per-chunk-per-skill could 2-4x that),
   more reindex churn since bodies edit more often than descriptions, and precision risk from
   procedural/code-snippet noise that a labeled "when to use" section (option 4) wouldn't carry.
4. **Do not pursue Option 2 as scoped.** The hook-path latency budget is a hard architectural wall
   (ADR-0008), not a tuning parameter, and even the MCP-only variant doesn't fix the actual miss
   Option 4 fixes. If disambiguation quality is still a problem after (1)+(2), that's an
   intent/actionability-gate question (already a live area — `enforcer.py`'s class-margin gate), not
   a rerank-the-vector-hits question.
5. **Do not revive `enrich_index.py`'s MEAN-centroid path as "frontmatter enrichment."** It's the
   exact mechanism ADR-0012 measured as worse and superseded; `doctor.py`/`setup.sh` already guard
   against it running under the multi-vector index. The legitimate low-cost lever hiding inside
   "Option 5" is encouraging `when_to_use` frontmatter adoption (currently ~15%, 101/688) — that's a
   skill-authoring/docs fix, track separately from any engine change.

## Unresolved questions

- No `eval/triggers.json`-equivalent labeled corpus exists yet for body-derived "when to use"
  extraction quality — Option 4 needs a way to measure extraction precision (how many bodies have a
  cleanly labeled section vs. free prose) before estimating real coverage gain, not just point count.
- Whether Option 4's extractor should also read the ~15% of bodies with duplicate `when_to_use`
  frontmatter (skip to avoid double-counting) — a decision for whoever implements it.
- Did not independently verify the 384-token figure against the SentenceTransformers HF config
  (`sentence_bert_config.json` `max_seq_length`) — pulled from fastembed's `list_supported_models()`
  metadata string only, via a live query against the installed fastembed package. Consistent with the
  model's known SBERT lineage but worth a second source if this number becomes load-bearing for an
  implementation PR.
