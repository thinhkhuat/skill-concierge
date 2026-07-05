# SYNTHESIS — OpenSpace Innovations Transferable to skill-concierge

**Date:** 2026-07-04 23:12 (Asia/Saigon) · **Author:** orchestrating agent, synthesizing a 3-agent study
**Target studied:** `/Users/thinhkhuat/LANDING_ZONE/OpenSpace` (Python agent-skill framework; "Smarter,
Low-Cost, Self-Evolving" agents). **Inputs:** study A (skill-engine/retrieval), B (self-evolution/
sharing), C (multi-host) — all in this dir, each grounded in OpenSpace file:line + its shipped DB.
Read-only; nothing written outside the workbench.

## The one insight that matters most (both workstreams converge here)
The OG-vs-fork audit found skill-concierge's **ledger is a dead-end** — it measures offer/take/dodge but
never feeds back (value measured at **10% conversion / 90% dodge** this session). OpenSpace's single
genuinely-working, code-verified innovation is exactly the missing piece: a **closed local feedback
loop** — record each run → an LLM judges "did each offered skill actually HELP?" → per-skill quality
rates in SQLite → thresholds trigger an LLM self-rewrite of the skill. Confirmed live in their shipped DB
(226 skills, generations 0–3, real lineage). **The thing our audit says we lack is the thing OpenSpace
proves works.** That convergence is the headline.

## Transferable innovations, ranked by impact-to-us

### 1. Close the loop: retrieval-metadata self-improvement from the ledger — HIGH / MED effort
OpenSpace: `record → LLM "did it help?" → quality rates → threshold-triggered FIX/rewrite`
(study B, verified in their SQLite). **Apply to us, retargeted at what drives OUR retrieval:** map a
skill's low offer→take / high top-hit-dodge into an LLM rewrite of its **description + body trigger
points** (the metadata our Qdrant index actually ranks on), not the skill body — stays inside our
hand-authored-skills design, no auto-generated sprawl. This directly attacks the D4 finding.

### 2. Add an "actually helped?" post-turn signal — HIGH / MED
OpenSpace judges each offered skill's real contribution, not mere invocation. **Apply:** an additive
post-turn `effect` ledger event (LLM or heuristic) capturing whether the taken skill helped. This
answers skill-concierge's OWN `skill-usage-audit` warning that offer→take ≠ usage — turns our shallow
take-rate into a true effective-rate. Additive, fail-silent — fits the existing ledger contract.

### 3. Two-stage retrieval: over-fetch → cheap rerank / exact-name boost — MED-HIGH / LOW effort
Studies A+C converge: OpenSpace over-fetches ~8 then reranks down to `max_select:2`
(`mcp_server.py:376-384`) with an additive exact-name/slug lexical boost (`cloud/search.py:60-82`).
Our `enforcer._retrieve` is **single-stage** (one Qdrant `query_points_groups`, top_k=5 — confirmed in
our code). **Apply:** keep Qdrant + mpnet (we're ahead there), add a ~20-line additive re-rank so an
explicitly-named skill can't be buried by a semantic near-miss. **Skip their BM25 pre-stage** — that
exists only because they have no vector DB; we do.

### 4. Plan-then-select doctrine + abstain-to-empty clause — MED / LOW effort
OpenSpace's selection prompt: "write a plan, match only TESTED procedures, and if nothing fits use NO
skill — a wrong skill is worse than none" (`registry.py:676-704`). **Apply:** fold this framing into our
enforce mandate. Zero extra LLM calls; sharpens precision AND the skip decision — directly relevant to
our getaway-leg / false-SKIPPING problems from the OG audit.

### 5. Externalize gate policy: env-override merge + precedence ladder + doctor shows winning source — MED / LOW
OpenSpace merges granular `OPENSPACE_*` env overrides into an effective config, with a documented
"higher tier blocks lower tier" ladder and every value logging its `source=` (`resolver.py:285-354`,
`config/README.md:16`). **Apply:** `SKILLCONCIERGE_GATE_*` overrides to tune floors per-machine without a
repo edit + full deploy — cheap fix for the exact against-data-threshold tuning pain the OG audit flagged
(GETAWAY_FLOOR). Have `doctor.py` print which source won each effective setting.

## Explicitly REJECTED (honest — do NOT chase)
- **Cloud "experience sharing / collective intelligence"** — anti-goal vs our private-ledger mission, and
  the code shows it's just a manual npm-style pull registry that omits the quality signal (study B).
- **CAPTURED-style auto-skill-generation** — their own shipped DB proves it causes sprawl (226 skills,
  duplicate-named families). Keep our curated, hand-authored catalogue.
- **Multi-host abstraction** (Codex/Cursor/nanobot) — a delegated MCP-sidecar model that ABANDONS host
  governance. Our Claude-Code hook coupling is the substrate that makes deterministic per-turn
  enforcement possible; giving it up to be portable is a net loss for us (study C — "correctly so").
- **"46% fewer tokens"** — it's a skill-EVOLUTION result (baking working flags into skills), NOT a
  retrieval win. Don't pursue it through our retrieve path.

## Where skill-concierge is already AHEAD of OpenSpace
Our per-phrase MAX-pool + Qdrant ANN + multilingual **mpnet-768** beats their single coarse whole-doc
vector (12k-char cap, English-only `text-embedding-3-small`) brute-forced with Python cosine (study A).
Our retrieval substrate is the stronger of the two — the gap is the feedback loop, not the retriever.

## Recommended sequence (proposals — implementation is a separate, owner-authorized step)
Cheap-and-sharp first, then the loop:
1. #4 plan-then-select doctrine text (hours, zero infra) + #3 exact-name rerank (~20 LOC).
2. #5 env-override gate tuning (unblocks fixing the against-data floors cheaply).
3. #2 `effect` post-turn signal (the measurement upgrade the audit demands).
4. #1 close-the-loop metadata rewrite (the big one — needs #2's signal first).

## Unresolved / caveats
- Study agents judged skill-concierge analogs from the brief, not by re-reading all our source. I
  cross-checked the two load-bearing ones against code I read this session: our retrieve IS single-stage
  (#3 valid) and our ledger has NO helped/effect signal (#1/#2 valid). Others (progressive disclosure)
  should be verified before building.
- #1 and #2 add an LLM-judgment cost per turn/skill — needs a budget + async design so it doesn't become
  a second per-turn tax (the very over-engineering the OG audit warned against).
- All of the above are PROPOSALS from a read-only study; none applied.
