# OpenSpace Study A — Skill Engine / Retrieval / Token Economy

READ-ONLY innovation study. Target: `/Users/thinhkhuat/LANDING_ZONE/OpenSpace`. Nothing modified.
Lens: how does OpenSpace RETRIEVE, SELECT, and SAVE TOKENS on skills, and what beats skill-concierge's Qdrant + mpnet-768 MAX-pool + per-turn hook mandate?

## TL;DR — honest framing

- OpenSpace is an **agent runtime with a self-evolving skill store**, not a Claude-Code governance layer. Its retrieval is a means to feed its OWN execution loop, not to nudge a host model. Some mechanisms transfer cleanly; some are worse than what we already have.
- **The "46% fewer tokens" claim is NOT a retrieval win.** It comes from skill *evolution* — evolved skills bake in working ffmpeg flags / codec fallbacks / API sequences so the agent stops burning tokens on sandbox trial-and-error (README.md:354). Retrieval/selection is where OpenSpace spends tokens carefully, not where it saves the 46%. Do not chase that number through our retrieve path.
- Our single strongest edge OpenSpace does NOT have: **per-phrase MAX-pool trigger embeddings + Qdrant ANN + multilingual mpnet-768.** OpenSpace embeds one truncated whole-doc vector per skill (12k-char cap, English-centric `text-embedding-3-small`) and brute-forces cosine in Python. On both retrieval granularity and multilingual (this workbench is Vietnamese-heavy) we are ahead. See "Where we are already better."

The two ideas most worth stealing are both about **precision and self-correction AFTER the vector hit**, which is exactly skill-concierge's weak spot (we retrieve well but can't prove the model picked/used the right one).

---

## Ranked innovations (impact-to-us first)

### 1. LLM "plan-then-select" precision gate on top of vector retrieval — HIGH

- **OpenSpace:** After BM25+embedding narrows candidates, an LLM does a 4-step selection: (1) write a brief plan, (2) match skills only if they teach a *tested procedure for a core part of the plan*, (3) prefer high success-rate skills, (4) **"Select at most N. If no skill closely matches you MUST return an empty list. Selecting an irrelevant skill is worse than selecting none — it forces the agent down an unproductive path and wastes the iteration budget. When in doubt, leave it out."** — `openspace/skill_engine/registry.py:676-704`. Returns `{"brief_plan": ..., "skills": [...]}`.
- **skill-concierge analog?** **No.** Our ENFORCE injects top-k + a SKILL-FIRST mandate and lets the model self-select from what we surfaced. We have a recall gate (retrieve) but no explicit *precision/abstain* gate that can say "none of these, use nothing."
- **Would it meaningfully improve us?** Yes — directly on our stated weak spot ("pick the RIGHT skill precisely + actually use it"). The "worse than none / when in doubt leave it out" framing is the antidote to over-injection noise, which our MAX-pool trigger recall can produce. The abstain-to-empty option is the key novelty.
- **Transferability:** HIGH concept / MED effort. We already have an LLM in the loop (the host model), so we don't need a *separate* selector call for the default path — we can port the **prompt doctrine** into the mandate text the hook injects: force a one-line plan, an explicit relevance test, and an explicit "if nothing fits, use no skill" escape. Zero extra LLM calls. A separate selector call (like OpenSpace) should be an *opt-in deep path* only, never the per-turn default (cost/latency — see caveat under #3).
- **How we'd apply it:** Rewrite the injected mandate from "here are k skills, prefer one" to a plan-then-match-then-abstain checklist mirroring registry.py:688-696. Add the abstain clause verbatim in spirit. Optionally expose a heavier `skill_select` MCP tool that runs the real OpenSpace-style LLM plan-select over our top-k for ambiguous prompts.

### 2. Closed-loop quality-weighted retrieval (self-pruning skills) — HIGH

- **OpenSpace:** Telemetry counters per skill — `total_selections / total_applied / total_completions / total_fallbacks` (`store.py:97-100`). At selection time skills are **filtered out** if `selections>=2 and completions==0` (chronically picked, never worked) or `applied>=2 and fallbacks/applied>0.5` (`registry.py:393-400`). Survivors carry their success rate INTO the selection prompt: `- **skill_id**: desc (success 3/4 = 75%)` or `(selected 2x, never succeeded)` (`registry.py:426-438`). Counters are incremented atomically after each run (`store.py:573-595`): applied if used, completion if used+task done, fallback if not-used+task-failed.
- **skill-concierge analog?** **Partial.** We have the LEDGER (append-only JSONL) and a `skill-usage-audit`, but the brief states it's for *manual* curation — telemetry does NOT feed back into ranking automatically.
- **Would it meaningfully improve us?** Yes. A skill that keeps getting retrieved but never actually used (offer without take) is exactly the signal our ledger already captures but doesn't act on. Feeding a success/take-rate prior into re-ranking (or into the injected catalog line) would raise precision over time with no model change.
- **Transferability:** MED-HIGH concept / MED effort. We already log the events; the missing piece is (a) aggregating ledger → per-skill take/complete rates, and (b) using them as a re-rank multiplier or a demotion filter, and (c) surfacing the rate in the injected mandate so the model sees "this skill is usually ignored."
- **How we'd apply it:** Add a periodic aggregation over the JSONL ledger → `{skill: take_rate, complete_rate}`. In the enforce hook, demote or drop skills below a floor (mirror the `selections>=2 & take==0` rule), and annotate surviving candidates with their take-rate. Keep it a soft prior, not a hard gate, to avoid cold-start starvation of new skills (OpenSpace marks new skills `(new)` and exempts them — copy that).

### 3. Two-stage BM25 → embedding, plus exact-name **lexical boost** — MED-HIGH

- **OpenSpace:** Stage 1 cheap BM25 lexical rough-rank prunes to `top_k*3`; stage 2 embedding cosine re-rank (`skill_ranker.py:107-137`). The cloud/search path adds a **lexical boost added onto the vector score**: exact slug-token match +1.4, prefix +0.8; exact name +1.1, prefix +0.6 (`cloud/search.py:60-82, 197`). So `final = vector_score + lexical_boost` — a skill whose *name* the query names verbatim gets pushed up even if the embedding blurs it.
- **skill-concierge analog?** **Partial/No.** We are pure-vector (Qdrant mpnet MAX-pool). MAX-pool over triggers gives us strong semantic recall, but exact-name / exact-slug queries ("run the doctor skill", "use skill-search") can be *outranked* by a semantically-fluffier neighbor because we have no lexical term that guarantees the named skill floats to the top.
- **Would it meaningfully improve us?** Yes, cheaply, on a specific failure class: the user names the skill (or a distinctive token in it) and we bury it under a semantic near-miss. Pure embeddings are known to under-weight rare exact tokens.
- **Transferability:** HIGH concept / LOW-MED effort. We do NOT need to add BM25 as a first stage (Qdrant ANN already scales better than their Python brute-force cosine — that part of their design is *worse* than ours; keep Qdrant). We only need the **lexical-boost re-rank on top of the Qdrant hits**: after Qdrant returns top-N, add a small additive boost for exact/prefix token overlap against skill name + id/slug, then re-sort.
- **How we'd apply it:** Post-Qdrant, compute `_lexical_boost(query_tokens, name, slug)` per hit (port cloud/search.py:60-82 directly, it's ~20 lines and dependency-free) and add to the cosine score before truncating to k. Tune the constants against our own eval set.
- **Caveat / where their two-stage is WORSE:** their BM25→embedding→brute-force-cosine pipeline exists because they have *no vector DB*. At 262 skills Python cosine is fine; it does not scale. Our Qdrant is the better substrate. Take only the lexical-boost idea, not the BM25 pre-stage.

### 4. Content-addressed embedding cache (auto-invalidating freshness) — MED

- **OpenSpace:** Cache key = `base64(skill_id):sha256(embedding_text)[:16]` (`skill_ranker.py:163-173`). Any edit to name/description/body changes the hash → the old entry is dead automatically, no external reindex trigger needed. Stale sibling entries for the same skill are dropped on write (`_drop_stale_entries_locked`, :175-185). Legacy skill_id-only keys are intentionally NOT migrated because they lack a text hash and "cannot be proven fresh" (:52-54).
- **skill-concierge analog?** **Partial.** We handle staleness via explicit `reindex` (doctor/setup). That works but relies on someone/something firing the reindex; a silently-edited SKILL.md between reindexes serves a stale vector.
- **Would it meaningfully improve us?** Modestly. A content hash stored alongside each Qdrant point lets the engine detect "this skill's source changed since indexing" and self-heal that one point, instead of trusting a global reindex cadence. Good hygiene, not a headline win.
- **Transferability:** MED / LOW-MED effort. Store `sha256(trigger-source-text)` in each Qdrant point's payload; on startup or search, cheaply diff the on-disk skill's hash vs payload hash and lazily re-embed mismatches.
- **How we'd apply it:** Add a `src_hash` payload field per point. `doctor` (or a lightweight pre-search check) flags/repairs points whose on-disk hash drifted — a targeted, per-skill freshness guarantee cheaper than a full reindex.

### 5. Mid-iteration `retrieve_skill` tool (pull guidance when stuck, not just at turn start) — MED

- **OpenSpace:** Skill guidance isn't only injected up front — a `retrieve_skill` tool is registered so the agent can pull in a skill *during* execution when "the current approach isn't working or the task requires domain-specific knowledge" (`retrieve_tool.py:34-39`, wired at `grounding_agent.py:547-562`). Same pipeline as initial selection.
- **skill-concierge analog?** **Partial — we may already have most of this.** Our `skill-search` MCP tool IS callable by the host model at any point, so the model *can* re-query mid-turn. The novelty in OpenSpace is (a) the explicit *framing/mandate* to do so when stuck, and (b) it reruns the full quality-filtered plan-select, not a raw search.
- **Would it meaningfully improve us?** Marginal-to-MED. Our ENFORCE fires once at UserPromptSubmit; if the task pivots mid-turn or the first retrieval missed, nothing re-nudges the model. A short "if your current approach stalls, call skill-search again before continuing" line in the mandate would close that gap at zero infra cost.
- **Transferability:** HIGH concept / LOW effort (it's a prompt line + we already have the MCP tool).
- **How we'd apply it:** Add the "re-query when stuck" instruction to the injected mandate. No new tool needed — point it at our existing `skill-search` MCP tool.

### 6. Progressive disclosure: headers-to-select, body-only-after-select — MED (likely already partial)

- **OpenSpace:** The selector LLM sees ONLY `skill_id + description + quality` (headers), never SKILL.md bodies; full content is loaded via `build_context_injection` only for the winners (`registry.py:352-358, 554-630`). Two-tier by design → the expensive tokens (bodies) are spent only on selected skills.
- **skill-concierge analog?** **Likely partial — verify.** Our enforce presumably injects names/descriptions + mandate, not full bodies. If so we already do this. If we ever inject body/trigger text for many candidates, that's a token leak to fix.
- **Would it improve us?** Only if we're currently over-injecting. Worth a quick audit of exactly what bytes our hook writes per turn.
- **Transferability:** N/A if already done; LOW effort to enforce the two-tier if not.
- **How we'd apply it:** Confirm the enforce hook injects header-only per candidate and defers body to the model's own skill invocation. If a body ever rides along, cut it.

### 7. Post-hoc LLM judge of "was the skill actually APPLIED" — MED (feeds #2)

- **OpenSpace:** After execution an LLM reads the transcript and emits per-skill `skill_applied` + task `task_completed` judgments (`analyzer.py:865-916`, types at `types.py:164-192`). This is the *source* of the quality counters in #2 — it distinguishes "selected" from "genuinely used" from the transcript, not from self-report.
- **skill-concierge analog?** **Partial.** Our `skill-usage-audit` reads the transcript SKILL-FIRST trail (the brief explicitly routes away from treating offer→take as usage). Same instinct — judge from the transcript. Difference: OpenSpace auto-feeds the verdict into ranking; ours is an on-demand audit.
- **Would it improve us?** It's the enabling piece for #2. On its own, MED. Together with #2, it's how the loop actually learns "this skill gets offered but never used."
- **Transferability:** MED / MED effort — we already have the transcript-trail auditor; the work is scheduling it and writing its verdicts back as the take/complete signal #2 consumes.
- **How we'd apply it:** Have `skill-usage-audit` emit structured per-skill `{offered, taken, completed}` rows into the ledger; #2's aggregator consumes them.

### 8. `.skill_id` sidecar — portable, name/path-independent identity — LOW-MED

- **What it is:** Each skill dir has a `.skill_id` file (262 of them) holding one line, e.g. `create-full-stack-panel-feature-enhanced__v3_3beb370f`. Format: `{name}__imp_{uuid8}` (imported) or `{name}__v{gen}_{uuid8}` (evolved). Generated on first discovery and then READ thereafter, so identity **survives renames, directory moves, and machine changes** and is deterministic (`registry.py:44-70`). All telemetry, caching, and evolution key off this stable ID, never off name or path.
- **skill-concierge analog?** **No** (our catalogue is static; we key by name/path).
- **Would it improve us?** Only if we adopt #2/#7 telemetry — then a stable ID is what lets you join "usage of skill X" across renames and edits. Without a learning loop it's overhead.
- **Transferability:** LOW-MED / LOW effort. Cheap to add if/when we build the quality loop; skip otherwise (YAGNI).

---

## Where we are already better (do NOT copy)

- **Retrieval granularity.** We MAX-pool over per-phrase trigger points mined from description + body. OpenSpace embeds **one whole-doc vector per skill**, truncated at 12k chars (`skill_ranker.py:41, 322-331`). Our per-phrase MAX-pool is strictly finer-grained recall than their single coarse vector. Keep ours.
- **Multilingual.** They use `text-embedding-3-small` (English-centric, `skill_ranker.py:40`). This workbench is Vietnamese-heavy; our multilingual mpnet-768 is the right call. Their choice would regress us.
- **Scale substrate.** They brute-force cosine in Python over a BM25-pruned set (no vector DB). Fine at 262 skills, doesn't scale. Our Qdrant ANN is the better foundation. Their two-stage exists to *compensate* for having no vector index — we don't need stage 1.
- **Per-turn cost.** Their default selection spends an LLM call every time (`registry.py:466`). Our zero-LLM UserPromptSubmit hook is cheaper for the always-on enforce path. Port their *doctrine* into the mandate (idea #1); do NOT adopt a mandatory per-turn selector LLM call.

## Non-transferable (different problem)

- `fuzzy_match.py` (6-level SEARCH/REPLACE chain) and `evolver.py`/`patch.py` serve **skill self-editing/evolution**, which is where their token savings actually come from — but skill-concierge is a static-catalogue governance layer, not a skill author. Out of scope for retrieve/enforce/token-economy.
- Cloud community sharing, auto-import, safety-flag gating on downloaded skills — irrelevant to a private static catalogue.

## Unresolved questions / assumptions

- I did NOT re-read skill-concierge source; analogs are judged against the task brief's description of our 3 organs (RETRIEVE/ENFORCE/LEDGER) + ADR-0015/0016 references. Idea #6 ("do we already do progressive disclosure?") and the exact bytes our enforce hook injects should be verified against `skill-concierge` before acting.
- Whether our ledger already records offer-vs-take per skill (idea #2/#7 depend on it) needs a quick check of the JSONL schema.
- OpenSpace's "46% fewer tokens" is an evolution-loop result on GDPVal, not independently reproduced here; treated as their claim, not a verified fact.

---

**Status:** DONE
**Summary:** Studied OpenSpace's skill engine, retrieval (BM25→embedding+lexical boost, quality-weighted LLM plan-select), and token economy. The 46% token win is skill-evolution, not retrieval; our per-phrase MAX-pool + Qdrant + multilingual embeddings are ahead of their coarse single-vector Python-cosine retrieval.
**Top 3 transferable:** (1) LLM plan-then-select doctrine with an explicit *abstain-to-empty* clause ported into our enforce mandate — attacks precision head-on; (2) closed-loop quality-weighted retrieval that self-prunes chronically-ignored skills from our ledger; (3) additive exact-name/slug **lexical boost** re-ranked on top of Qdrant hits (~20 lines, dependency-free) to stop semantic near-misses burying explicitly-named skills.
