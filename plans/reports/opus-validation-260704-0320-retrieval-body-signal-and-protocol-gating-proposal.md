# Opus Validation Report

**Subject:** architecture / design-proposal (advisory analysis — no code changed)
**Scope:** `plans/reports/proposal-260704-0244-retrieval-body-signal-and-protocol-gating-report.md`, verified against its three source researcher reports and primary code/ADR sources (plus one live Qdrant probe).
**Verdict:** FAIL
**Date:** 2026-07-04
**Evidence Files Examined:** 13 (proposal + 3 source reports + `skills_discovery.py`, `server.py`, `enforcer.py`, `embed_server.py`, `enrich_index.py`, `doctor.py`, `setup.sh`, `audit_skill_usage.py`, `skill-first.md`, `.mcp.json`, ADR-0008/0009/0012) + live Qdrant count.

## Executive Summary

FAIL, on a single but material evidence-integrity defect: the proposal's "ground truth of what's indexed today" section states (layer 3, lines 37-38) that the `enrich_index.py` MEAN overlay is **live** — this is verified **false** by five independent sources including the live index (0 enriched points). Every other load-bearing claim I checked — body-is-embedded-and-char-capped, deployed model, `get_skill` uncapped disclosure, enforcer silence on getaway/intent_skip, per-turn-retrieval-equals-`search_skills`, ADR-0009 anti-correlation numbers, ADR-0012 2.2× numbers, the intent-margin/imperative-veto signals, the audit-detector gap — is faithfully reproduced from primary sources.

**Read the FAIL narrowly.** It flags one false current-state premise, self-contradicted by the report's own (correct) rejection of "reviving" the same overlay. The remedy is a one-paragraph correction of layer 3. The proposal's actual recommendations — Option 4 (body triggers into the MAX-pool layer) and the split-rollout gating fix (ship the intent-margin leg, quarantine the getaway-floor leg) — are independently verified, evidence-backed, and unaffected by the defect. This is not "the ideas are wrong"; it is "the baseline lies in one spot, fix it before the report is used as a current-state reference."

## Observable Truths

| # | Claim (from proposal) | Status | Evidence |
|---|-------|--------|----------|
| 1 | Base point = `embed(name + description[+when_to_use] + body[:4000 chars])`, one blended 768-d vector | ✓ | `skills_discovery.py:79-91` (desc+when_to_use, `body.strip()[:4000]`), `server.py:270-272` (`_skill_text` = name+desc+body) |
| 2 | Body is embedded but **discarded from the Qdrant payload** | ✓ | `server.py:354-356` payload = name/description/path/content_hash/kind — no `body` key |
| 3 | Trigger layer splits intent phrases from **description only**, MAX-pooled (default ON) | ✓ | `server.py:358` `_split_phrases(s["description"])`; `server.py:82` `MULTIVECTOR` default on; `_retrieve`/`search_skills` group_by name, group_size 1 (`server.py:414-416`) |
| 4 | Deployed embedder = `paraphrase-multilingual-mpnet-base-v2` (not the code's bge-small default) | ✓ | `.mcp.json:8`; `server.py:73` default `BAAI/bge-small-en-v1.5`; `embed_server.py:42-45` sets mpnet before import |
| 5 | Real cap is **384 input tokens**, so most bodies are silently truncated | ⚠ single-source | Researcher-b via `fastembed.list_supported_models()` metadata only (`researcher-b:36-40,157-161`); proposal itself flags it unresolved (`proposal:224`). Not independently confirmed against SBERT config. |
| 6 | `get_skill` already does full, uncapped progressive disclosure from disk | ✓ | `server.py:439-457` `Path(path).read_text(...)`, fallback `discover_skills()` at 454-456 |
| 7 | Trigger layer is the proven recall lever: rank-1 11.3%→25.0% (2.2×) | ✓ | `ADR-0012:33` (rank-1 11.3→25.0%, separation 0.049→0.105); `server.py:81` "2.2x rank-1/separation" |
| 8 | ADR-0012 measured MEAN-centroid **worse** than MAX-pool over separate points | ✓ | `ADR-0012:11-14` "a centroid dilutes the one distinctive phrase"; `ADR-0012:5,50-51` supersedes overlay |
| 9 | **Enrich overlay is LIVE via `setup.sh:77` + `doctor.py` auto-fix (base vectors are MEAN-blended in steady state)** | ✗ **FALSE** | `setup.sh:76-78` gates `--reapply` behind `SKILL_MULTIVECTOR=0`; `doctor.py:499-503` skips reapply under MULTIVECTOR; `doctor.py:306-308` returns OK when `enr==0`; `ADR-0012:50-51`; **live Qdrant: enriched=0** (base=488, trigger=1743) |
| 10 | ADR-0009: taken 0.414 vs dodged 0.457; floor 0.40→0.45 removes ~22% noise but 50% of adopted | ✓ | `ADR-0009:18` (median 0.414 vs 0.457; 20/91 noise = 22%, 3/6 adopted = 50%); `enforcer.py:66` restates verbatim |
| 11 | Enforcer injects **nothing** on getaway/intent_skip, unlike every other path (which injects MANDATE) | ✓ | `enforcer.py:473-477` (getaway `return 0`, no `_inject`), `483-485` (intent_skip, no `_inject`); fallbacks inject at `433/441/445/453` |
| 12 | Per-turn retrieval **is the same call** as `search_skills` (same embed fn, collection, query shape) | ✓ | `embed_server.py:48` `from skill_search.server import embed`; `enforcer.py:311-328` vs `server.py:414-416` identical query shape. Caveats (TOP_K 5 vs 6, raw vs reformulated query) correctly stated by report |
| 13 | intent-margin classifier: ~2% false-suppression, held-out validated; fail-open | ✓ | `enforcer.py:78-80,404-411` |
| 14 | Imperative veto never suppressed | ✓ | `enforcer.py:368-370` "Imperative turns are NEVER suppressed" |
| 15 | Audit scores false-SKIP as `SKIPPING` with no `search_skills` in same turn; needs a marker patch | ✓ | `audit_skill_usage.py:101-116` (`_skip_verdicts`), `_SEARCH_SLUGS` at `:50` |
| 16 | Only 101/688 skills (~15%) set `when_to_use` frontmatter | ? PARTIAL | Live count, denominator-dependent; not independently reproducible (my `~/.claude` recount: 300/5242 incl. caches = 5.7%; live index has 488 base skills). Proposal flags it separate + unresolved (`:100-102,221-222`) |
| 17 | Body rerank (Option 2) can't fit hook latency budget (ADR-0008 ≲300ms) | ✓ | `ADR-0008:31,43` (200ms embed cap within ≲300ms total) |
| 18 | Getaway-floor leg deletes a **reformulated-query** recovery path (doctrine embeds "in your own words") | ✓ | `skill-first.md:30`; recovery value backed by `ADR-0009:18` (adopted offers below floor) |
| 19 | Option 4 = recommendation (20/25), the only option fixing the recall miss on both paths | ✓ | `researcher-b:76` (Option 4 = 20/25); Option 3 scored 21/25 but partial-scope, correctly cast as a complement, not hidden |

## Key Dependency Verification

| From (proposal claim) | To (primary source) | Via | Status | Details |
|------|----|-----|--------|---------|
| "Enrich overlay live" (layer 3) | Current index state | `setup.sh` / `doctor.py` / live Qdrant | **FAIL** | Both cited mechanisms are the exact ones gated OFF under default multivector; live index has 0 enriched points |
| "The body is already embedded" | `_skill_text` | `skills_discovery.py:91` → `server.py:270-272` | PASS | body[:4000] concatenated into base text |
| "same call as search_skills" | embed shim + retrieve | `embed_server.py:48` → `server.py` `embed` | PASS | Direct import of the engine's own `embed`; same collection/query |
| "2.2× proven lever" | ADR-0012 evidence | shadow A/B | PASS | rank-1 11.3→25.0%, separation 2.2× |
| "score anti-correlated w/ adoption" | ADR-0009 | live ledger + backtest + corpus | PASS | three independent confirmations, floor cost 50% adopted |
| Option-4 extractor mirrors `_split_phrases`/`_LABEL_RE` | server code | `server.py:245-267` | PASS | `_LABEL_RE` already matches `triggers?|examples?|use when|also use|use this skill` — body-section extraction is a natural extension |

## Blocking Issues (FAIL)

1. **The "enrich overlay is live" premise is verified FALSE (evidence-integrity failure).** Proposal lines 37-38: *"Enrich overlay (`enrich_index.py`, live via `setup.sh:77` + `doctor.py` auto-fix) — post-hoc blends trigger vectors into the base vector as a MEAN."* This is contradicted by five independent sources:
   - `setup.sh:76-78` runs `enrich_index.py --reapply` **only** inside `if [ "${SKILL_MULTIVECTOR:-1}" = "0" ]` — i.e. never under the default (MULTIVECTOR on). The setup comment states it outright: *"The LEGACY MEAN enrichment overlay is superseded and must NOT run on a multi-vector index."*
   - `doctor.py:499-503` (`fix_reindex`): under MULTIVECTOR the reindex auto-fix **skips** reapply — *"multi-vector supersedes the overlay."*
   - `doctor.py:306-308` (`check_enrichment`): when `enr==0` it returns `OK` "not enriched (no overlay in use)" — no WARN, no auto-fix. The `--reapply` fix only arms when `0 < enr < total`, which the default index never reaches.
   - `ADR-0012:50-51`: *"The MEAN enrichment overlay is superseded; `doctor --fix` no longer runs the legacy reapply when MULTIVECTOR is on."*
   - **Live Qdrant probe:** `enriched` point count = **0** (base=488, trigger=1743, total=2231). Base vectors are pure `embed(_skill_text)`, not MEAN-blended.

   **Impact & scope:** This is a false statement of current index state in the section whose sole purpose is factual accuracy, and it is **internally self-contradicting** — line 98 rejects *"revive `enrich_index.py`'s MEAN-centroid — the exact mechanism ADR-0012 superseded,"* which cannot be "revived" if it were already "live." A grep of the proposal confirms the false current-state assertion appears **only** at lines 37-38; the through-line (62-64), risks (207), and Option-5 rejection (98, 202) all correctly treat MEAN as superseded/hypothetical-future, not live. **Remedy:** rewrite layer 3 to state the overlay is superseded and inert under the default multi-vector index (0 enriched points; base vectors un-blended). No recommendation depends on the false reading — in fact the operative recommendation (reject MEAN revival) is the correct one — so the fix is isolated and does not cascade.

## Advisory Suggestions (WARN)

1. **Intent-margin leg — "re-deriving buys nothing" slightly overstates its safety.** The proposal (lines 152-154) contrasts the intent-margin leg as safe because "re-deriving it buys nothing" against the getaway leg's recovery-path deletion. But the reformulated-query recovery the report (correctly) uses to quarantine the getaway leg **also** applies to the intent-margin leg's ~2% false-suppression cases (`enforcer.py:78-80`) — on those turns, re-searching could recover. The leg-split's *direction* is sound (the getaway leg fires in a band with a documented 50% adopted-offer loss vs the intent-margin leg's validated ~2%), an order-of-magnitude difference that justifies shipping one and gating the other. Recommend softening "buys nothing" to "buys little (residual ~2%)". Non-blocking.
2. **384-token figure is single-sourced.** From `fastembed.list_supported_models()` metadata only, not the model's SBERT `max_seq_length`. The proposal already flags this (`:224`) and researcher-b flags it (`:157-161`). Fine to keep as a directional argument (bodies are truncated regardless of the exact number), but do not let "384" become load-bearing in an implementation PR without a second source. Note: several sentence-transformers `paraphrase-multilingual-*` configs cap at 128, which if true would *strengthen* the truncation argument, not weaken it.
3. **`when_to_use` ~15% (101/688) is a live, denominator-sensitive count.** Not independently reproducible to an exact figure — my `~/.claude` recount hit a different universe (5242 SKILL.md incl. cache/vendored dupes → 5.7%; the live index holds 488 base skills). Directionally consistent (adoption is low), and the proposal correctly scopes it as a separate, non-engine, unresolved item. Keep it advisory; don't cite the exact percentage as fact.
4. **"100% precision by construction" for the imperative veto** (line 179) is acceptable shorthand for "as a suppression-veto it never falsely suppresses," but the code describes the *detector* as "high precision on the open, low recall by design" (`enforcer.py:368-370`), not literally 100%. Cosmetic.
5. **"~2,312 points" (line 95)** is the documented arc figure; live index is 2231 (skills drift). The "~"/"already" hedges are adequate.

## Validation Dimensions

- [x] Evidence integrity — body indexing & payload (Truths 1-3, 6) — **PASS** — `skills_discovery.py:79-91`, `server.py:270-272,354-362,439-457`
- [x] Evidence integrity — deployed model & token cap (Truths 4-5) — **PASS (model) / single-source (token)** — `.mcp.json:8`, `embed_server.py:42-48`; 384-token unverified
- [x] Evidence integrity — enrich overlay current state (Truth 9) — **FAIL** — `setup.sh:76-78`, `doctor.py:306-308,499-503`, `ADR-0012:50-51`, live enriched=0
- [x] Evidence integrity — ADR numbers (Truths 7-8, 10) — **PASS** — `ADR-0012:11-14,33`, `ADR-0009:18`
- [x] Evidence integrity — enforcer gating internals (Truths 11-15, 18) — **PASS** — `enforcer.py:66,78-80,311-328,368-370,473-485`, `skill-first.md:30`, `audit_skill_usage.py:101-116`
- [x] Reasoning — "library doctrine" (asymmetric error cost, burden-of-proof on SKIP) — **PASS** — coherent with ADR-0009 anti-correlation; escalate-to-`find-skills` is consistent
- [x] Reasoning — AUTHORIZED-SKIP leg-split correction of researcher-c's "cannot worsen under-gating" overclaim — **PASS (one WARN)** — correction is coherent and evidenced (`skill-first.md:30` + `ADR-0009`); intent-margin "buys nothing" mildly overstated (Advisory 1)
- [x] Reasoning — Option 4 recommendation + vetoes (rerank latency, MEAN revival) — **PASS** — vetoes backed by `ADR-0008:31,43` and `ADR-0012`; synthesis of researcher-b scoring is faithful (Option 3's higher raw score correctly explained as partial-scope)
- [x] Synthesis faithfulness to source reports — **PASS** — proposal's numbers and framings trace to researcher-a/b/c; the one place it *diverges* from a source (correcting researcher-c's overclaim) is an improvement, and the one place it *inherits* a source error (researcher-a Q5's "steady-state MEAN") is the blocking issue

## Unverifiable Items

1. **384-token truncation figure** — verifiable only against the model's SBERT config, which requires the HF model card / `sentence_bert_config.json` (no confirmed network/model-file access this pass). Single-sourced from fastembed metadata; flagged by the proposal itself.
2. **`when_to_use` exact 101/688 (~15%)** — a point-in-time filesystem count over an unspecified skill universe; not reproducible to the same figure (denominator differs by dedup/dir scope). Directionally corroborated (adoption is low), exact value not pinned.
3. **Byte-level identity of the shim's `embed()` vs an in-process `search_skills` embed** — researcher-c flagged it unproven (`researcher-c:188-191`); the shared direct import (`embed_server.py:48`) makes divergence implausible, but I did not diff two vectors. Does not affect any conclusion.

## Context Gaps

No context gaps that block the verdict. The proposal, its three source reports, all cited code, and the three governing ADRs were readable; the single load-bearing runtime claim (overlay live?) was settled directly against the live Qdrant index. The post-v0.10.0 score↔adoption re-measurement the proposal names as prerequisite #4 is, as the proposal states, not yet done — that is correctly logged as an open item, not a gap in this validation.
