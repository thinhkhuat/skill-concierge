# Embedder recall trial and cutover record — mpnet → embeddinggemma-2

**Date:** 2026-10-22 (Asia/Saigon) · **Scope:** which embedding model the skill-retrieval index should use as primary, and the cutover itself · **Status:** trial complete, cutover executed this session, independent adversarial review still in flight

## Quick read

A 30-query graded recall trial over the real skill catalogue compared three embedding configurations. `embeddinggemma-2:270m` led the deployed `paraphrase-multilingual-mpnet-base-v2` on recall@1, recall@6, MRR, precision@6 and NDCG@6 in all three query groups. On that evidence the cutover was ordered and executed.

**Independent adversarial review (run after the cutover, at the operator's order) returned FAIL on the inference drawn from those numbers.** The arithmetic and the scoring code are sound and exactly reproducible; the *conclusion* is not decision-grade. Three things are now established against the original framing, each verified in this repo rather than taken on the reviewer's word:

1. **The trial does not isolate the embedder.** mpnet truncates every document at roughly 200 words and ignores the remainder; embeddinggemma-2 reads the whole body. Replacing the second half of a real skill body with gibberish gives cosine **1.000000** under mpnet on 8 of 8 long bodies tested. Skill bodies here average 517 words, so most of each document is invisible to mpnet. Part of every measured gap is document coverage, not semantic matching quality.
2. **The English advantage is substantially a graded-label artifact.** Several correct answers were left ungraded (scored 0), including a byte-identical twin of a grade-3 label. Repairing those, each traceable to the skill's own description, collapses English recall@1 to a 9/10 tie between the two arms.
3. **No comparison reaches conventional significance.** Overall recall@1 is 14/30 versus 9/30; paired discordance 8–3 gives exact McNemar **p = 0.227**. The strongest comparison in the trial (overall recall@6, 27/30 vs 21/30) is **p = 0.109**. The pre-registered Vietnamese bar is met on direction only — McNemar **p = 1.000** at n=10.

**What this does and does not overturn.** For the operational question — which embedder should this catalogue use — the trial is still informative: these skill bodies are long, mpnet demonstrably ignores most of each one, and a model that reads them is a real advantage on *this* corpus. That is a property of the embedder as deployed, and it is the property that matters here. What is not supported is the stronger claim that embeddinggemma-2 is a better *semantic* matcher, or that the code-query gain reflects the published MTEB code figure; the published benchmarks use short snippets where truncation is not in play.

Matryoshka truncation to 128 dimensions was tested and **rejected**: it is never better than full 768 and costs 30% of English NDCG.

## 1. Method

**Corpus.** One point set shared by every arm, extracted from the live discovery layer: 46,029 texts — 2,966 base points (`_skill_text`: name + description + body) and 43,063 trigger-phrase points (`_trigger_phrases`). All arms are handed byte-identical texts.

**That is not the same as all arms *seeing* byte-identical texts.** mpnet truncates at roughly 200 words and embeddinggemma-2 does not, so for long documents the two models are scoring different amounts of content. Verified here by replacing the second half of real skill bodies with gibberish: mpnet's vector is unchanged (cosine 1.000000 on 8 of 8 bodies of 547–756 words), while embeddinggemma-2's shifts. 95% of base texts exceed the cut, averaging 517 words. Document coverage is confounded with embedder in this design. The trigger layer is unaffected — trigger phrases average 7 words, far under the cut — so the confound applies to the base points only.

**Scoring.** In-memory cosine similarity with max-pooling per skill name, mirroring the live store's `group_by=name, group_size=1`. No vector store was written during the trial. Both models emit 768 dimensions, so the comparison is like-for-like at the vector level.

**Candidate pools.** `installed` (**940** skills — visible scopes, external catalogue and blocklisted names excluded) is the production universe and the primary read. `full` (**2,934**, everything discovered minus blocklisted) is a stress test. Both figures are after the blocklist subtraction; the raw counts before it are 970 and 2,966, and an earlier draft of this report quoted those instead.

**Probes.** 30 queries in three groups of 10: English, Vietnamese, code. Each carries graded relevance — 3 ideal, 2 acceptable, 1 plausible-but-wrong distractor — 91 judgments in total, each assigned from the skill's own description rather than its name. Every labelled name was verified present in the installed universe and not blocklisted. `expect[]` is derived as grade ≥ 2, so a distractor can never score as a hit.

**Baseline validity.** Live stored vectors scored cosine 1.000000 against fresh embeds from the trial's own venv, so the mpnet arm is the production retriever rather than a lookalike.

## 2. Results — installed pool, n = 30

| Arm | Recall@1 | Recall@6 | MRR | Precision@6 | NDCG@6 | Mislead rate |
|---|---|---|---|---|---|---|
| mpnet (deployed) | 0.300 | 0.700 | 0.477 | 0.200 | 0.419 | 0.033 |
| **eg2-768** | **0.467** | **0.900** | **0.651** | **0.244** | **0.576** | 0.033 |
| eg2-128 | 0.367 | 0.833 | 0.553 | 0.211 | 0.492 | 0.033 |

EG2-768 takes 12 of 12 metric cells across the three groups. The only cell it loses is `wrong_hit@3` (3 distractors surfaced versus mpnet's 2).

### By query group — installed pool

| Group | mpnet R@1 / R@6 / NDCG@6 | eg2-768 R@1 / R@6 / NDCG@6 |
|---|---|---|
| English | 0.30 / 0.80 / 0.419 | 0.50 / 0.90 / 0.511 |
| Vietnamese | 0.50 / 0.80 / 0.578 | 0.60 / 0.90 / 0.655 |
| Code | 0.10 / 0.50 / 0.258 | 0.30 / 0.90 / **0.564** |

Code is the decisive difference. mpnet places only half of all code probes inside the top 6; EG2-768 places 9 of 10, and NDCG@6 more than doubles (+119%). This is directionally consistent with the published +14% MTEB code figure for embeddinggemma-2, though the two are not the same measurement.

### Full-pool stress test (1,996 external catalogue skills added)

Everything degrades, as expected when the candidate set triples. EG2-768 still leads on Recall@6, MRR and NDCG@6. mpnet's code recall collapses to 0.10, its worst cell in the whole trial.

## 3. What the numbers do and do not show

**Data.** n = 10 per group means one probe equals 10 points. The Vietnamese margin is exactly one probe on every metric. Paired testing does not separate any of this from noise: overall recall@1 (14/30 vs 9/30, discordant 8–3) gives exact McNemar **p = 0.227**; overall recall@6 (27/30 vs 21/30, discordant 8–2) gives **p = 0.109**, the strongest comparison in the trial; Vietnamese recall@1 gives **p = 1.000**. An earlier draft of this section claimed the overall margin was "well outside the noise" — that was wrong, and it is withdrawn.

**Assessment.** Recall@6 alone would have understated the movement between arms (0.70 → 0.90) while NDCG@6 shows graded menu quality improving 37%. Precision@6 runs 0.18–0.30 across every arm: of the six skills shown, roughly one to one-and-a-half are genuinely good. The menu is mostly filler regardless of embedder — that is a separate problem from model choice and is not solved by this cutover.

The result is therefore a **consistent directional trend across many metrics**, not a measured difference. It is enough to justify an operational choice where the operational cost of being wrong is a two-line revert; it is not enough to claim a quality win.

**Metric caveat (from independent audit).** NDCG's IDCG is computed over all graded names while DCG sums only the top 6. That would under-scale NDCG for any probe with more than 6 graded names. Maximum graded names per probe in this set is 6, so **these results are unaffected**; the asymmetry should be fixed before a larger label set is run.

## 4. Matryoshka truncation to 128 dimensions — rejected

EG2 supports output truncation, and the mechanism was verified working through Ollama. The trial measured it as a third arm and it loses consistently:

| | English NDCG@6 | Vietnamese NDCG@6 | Code NDCG@6 |
|---|---|---|---|
| eg2-768 | 0.511 | 0.655 | 0.564 |
| eg2-128 | 0.356 (−30%) | 0.616 | 0.504 |

Truncation is never better and is sometimes materially worse. The 6× storage saving is not free. English — where the vectors lose the most — is hit hardest.

**Assessment.** Do not cut to 128. If storage pressure ever forces the question again, re-run this arm rather than trusting the graceful-degradation claim.

## 5. Cutover record

Ordered by the operator this session ("cutover now … for me, it is EG2-768, now"). Independent adversarial review of the analysis was waived by that order and is running as a post-hoc check rather than a gate.

**Configuration changed (9 consumers, moved together — a migration finishes at its consumers):**

| File | Change |
|---|---|
| `.mcp.json`, `.codex-plugin/mcp.json` | `SKILL_EMBED_BACKEND` → `ollama`, `SKILL_EMBED_MODEL` → `embeddinggemma-2:270m` |
| `adapters/{zcode,omp,dsh,commandcode}/mcp.json` | same two values |
| `adapters/dsh/install.sh`, `adapters/commandcode/install.sh` | same two values in their generated config blocks |
| `setup.sh` | **fixed:** hardcoded `SKILL_EMBED_BACKEND=fastembed` — the backend was not actually configurable. Both embedder values now resolve from `.mcp.json`/env |
| `setup.sh` (owner start) | **fixed:** the index owner was started without the embedder env at all |
| `vendor/.../index_owner.py` | bare-start default moved to match the source of truth |

**Eight harnesses, two kinds.** Six carry their own duplicate of the embedder config and were swept together — Claude Code (`.mcp.json`), Codex (`.codex-plugin/mcp.json`), Command Code, OMP, ZCode, DSH. `driftcheck`'s `mcp-env-parity` check independently confirms all six stay in lockstep. The other two, **OpenCode v2** and **Cline**, hold no duplicate and derive the values from `.mcp.json` at runtime or install: OpenCode builds its server with `environment: row.env` read from `.mcp.json` (`adapters/opencode/plugin/index.ts`), and Cline rewrites the repo's `.mcp.json` into its own schema during install (`adapters/cline/agent_plugin.py:62`). OpenCode picks the change up on its next plugin load; Cline needs its installer re-run, which `adapters/install-all.sh` performs.

The OpenCode path is load-bearing and has failed before: `adapters/opencode/plugin/index.ts` records a live incident where an `env` field instead of `environment` made the server run on the inherited process environment and silently fall back to the 384-dimension default embedder. That is the same silent-mismatch class this cutover is exposed to, which is why model-name equality — not vector dimension — is what now has to hold across every start path.

**Why the two `setup.sh` fixes were not optional.** The repository declares `.mcp.json` the single source of truth for the embedder "so the built index can't diverge from the model the server uses". The backend half was hardcoded in one start path and entirely absent from another, so the invariant did not hold. The second defect was invisible rather than harmless: `paraphrase-multilingual-mpnet-base-v2` and `embeddinggemma-2` both emit 768 dimensions, so the owner's dimension guard cannot tell a wrong model from a right one. Correctness now rests on model-name equality, which is why every start path must carry the same value.

**Data migration.** Full rebuild (`--rebuild`) of the index on the new model. The existing collection was backed up to `~/.claude/skill-concierge/backups/index.sqlite.pre-eg2-cutover-261022` first. An incremental reindex is refused by design when the embedder changed — old and new vectors live in unrelated spaces, and a mixed index returns silently wrong rankings.

**One failure, caused by this session's own sequencing.** The first rebuild died partway with `Connection refused` on upsert. The cause was not the new embedder: the version bump had run *while the rebuild was in flight*, rewriting the venv stamp from `0.71.3` to `0.72.0`, and the index owner exited by design to pick up the new code — the owner log records `venv stamp rewritten ('0.71.3' -> '0.72.0'): exiting for the new code`. The in-flight writer then lost its store connection, leaving a partial collection of 17,728 points. The rebuild was re-run to completion once the owner was back on `0.72.0`. Lesson for future releases: **the version bump must not overlap a rebuild** — the stamp is a restart trigger.

## 6. Down path

Two config values in each of the 9 files above, then `./setup.sh` (idempotent; rebuilds the index). Nothing in the engine special-cases a model, so the previous embedder remains fully selectable — that was an explicit requirement of the cutover.

## 7. Operational costs accepted by this cutover

1. **Daemon dependency.** The `ollama` backend needs a running Ollama with the model pulled. The `fastembed` backend is in-process. This is the real cost, not latency.
2. **Per-query latency.** mpnet p50 4.2 ms / p95 4.5 ms versus EG2 p50 9 ms / p95 12 ms steady-state, with a measured 158 ms cold-load outlier, on a path that runs every turn.
3. **Indexing is faster.** EG2 measured 52.0 texts/s against mpnet's 13.5 texts/s over identical body-length texts — about 15 minutes for a full 46K rebuild versus about 58.

## 8. Trial harness quality

The harness is disposable scratch under `/tmp/eg2-trial-261022/` and is not shipped. Two real defects were caught by its own self-checks before results were reported and fixed before scoring:

- `miss` fired only when a target was absent from the entire ranking, so a target buried at rank 40 counted as a success. It now means "nothing acceptable in the top 6 the agent actually sees".
- The EG2 embed helper crashed at its final rename because `np.save` appends `.npy`. The embed itself had completed; the 134.9 MiB matrix was recovered rather than re-run.

Self-checks cover max-pooling over trigger points, rank and MRR computation, NDCG against values recomputed from each observed ranking, pool restriction, distractor exclusion from `expect[]`, and the mislead definition.

## 9. Independent adversarial review

A blind validator was given the raw artifacts and the report without being told the conclusion. Its verdict: **FAIL on the inference, PASS on the arithmetic and the scoring code.** Verified findings carried into this report:

| Finding | Status | Where it lands |
|---|---|---|
| Scoring code correct (max-pool, rank, IDCG, `miss`, `expect[]`) | confirmed | §1 method stands |
| `trial_results.json` reproduces exactly from the shipped code and cached vectors | confirmed | numbers stand |
| Pool sizes 970 / 2,966 were pre-blocklist | confirmed wrong | §1 corrected to 940 / 2,934 |
| mpnet truncates documents; eg2 does not | confirmed | §1 method corrected; new caveat |
| English recall@1 gap is largely ungraded-correct-answers | confirmed by repair | Quick read corrected |
| No comparison reaches significance | confirmed | §3 corrected, claim withdrawn |
| "won every metric in every group" | wrong, loses `wrong_hit@3` | Quick read corrected |
| NDCG IDCG counts grade-1 as relevant | real but immaterial (+0.01–0.03, ordering unchanged) | noted §3 |
| `wrong_hit@3` and `mislead_rate` have no power at n=30 | real | do not read those columns as evidence |
| 128 leaf-duplicate skill names split one skill across prefixes | real | fix before any larger label set |

Two further confounds the review could not rule out, neither excluded here: embeddinggemma-2's **required task-prefix convention was deliberately left off**, so the trial never saw it at its intended operating point; and the trial measures pure single-query dense cosine, not the production stack (scope filter, blocklist, multi-query fusion, keyword channel).

## 10. Open questions

1. **Keep or revert?** The cutover is executed and reversible (two config values plus `./setup.sh`; pre-cutover index backed up). The operational case for keeping it — mpnet demonstrably ignores most of each skill body, and these bodies are long — survives the review. The *quality* case does not. The operator ordered the cutover before this evidence existed; the call on whether the operational case alone is sufficient is his.
2. **Vietnamese margin is one probe** and McNemar p = 1.000. Nothing here separates a real VI gain from noise. The pre-registered bar ("must win Vietnamese clearly") is met on direction only, which is a weaker claim than it was stated to be.
3. **Precision@6 is low on every arm (0.18–0.30).** The six-slot menu is mostly filler whatever the embedder. This is the larger remaining problem and it is upstream of model choice.
4. **The truncation confound can be sized.** Re-embed the base points with both models under an equalised token budget and re-score. That is the single measurement that would separate "reads more" from "matches better". Until then, no quality attribution is available.
5. **A pooled blind re-judge would fix the labels.** Take the union of every arm's top-10 per probe, strip arm identity, grade each from the skill's own body. This is the one change that would make the trial decision-grade.
6. **NDCG IDCG counts grade-1 as relevant** and should be fixed before any larger label set runs. Immaterial to these results.
7. **Daemon failure mode not yet exercised.** What the per-turn path does when Ollama is down or cold has not been tested under this cutover.

---

Sources: trial artifacts in `/tmp/eg2-trial-261022/` (`trial_results.json`, `probes_graded.jsonl`, `eg2_recall_trial.py`, self-checks). Background research on both models: `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/plans/reports/research-261022-2023-embeddinggemma2-vs-concierge-embedder.md`. Live retrieval semantics from `vendor/skill-search/skill_search/server.py` (`_skill_text`, `_trigger_phrases`, `search_skills`, `_blocked`, `build_index`). Benchmark figures quoted from Google's embeddinggemma-2 model card and the mpnet model card; the two are different evaluators and the gap between them is indicative, not a measurement.
