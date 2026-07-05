# CORRECTED INTEGRATED FINAL — skill-concierge: Epoch-Scoped Re-Run

**Date:** 2026-07-05 00:18 (Asia/Saigon) · **Author:** orchestrating agent (research-synthesis)
**Supersedes** `from-audit-and-openspace-syntheses-260704-2333-…` (built on epoch-pooled ledger data).
**Integrates:** the CORRECTED audit synthesis (`from-corrected-audit-team-synthesis-260705-0018-…`, 4 corrected
dimension reports) + the OpenSpace transferables synthesis (`from-openspace-study-team-synthesis-260704-2312-…`,
**carried forward unchanged** — see Methodology). Read-only; nothing applied.

## Synthesis Overview
| Field | Content |
|---|---|
| **Question** | skill-concierge's true state vs its origin, and the next build direction — grounded ONLY on config-current, decontaminated data. |
| **Decision** | Owner-authorized build direction; this brief is the evidence, not the decision. |
| **Data discipline** | Every ledger figure windowed to the current config epoch (since v0.12.0, 2026-07-04 05:32), subagent/meta/self-session traffic excluded; tiny samples labelled INSUFFICIENT DATA. (`AGENTS.md` → Guardrails.) |
| **Key conclusion** | The engine is intact and our retriever is the stronger substrate. The fork's problems are (a) **over-engineering** — proven, config-independent (a ~840-LOC inert graveyard that fired **0 of 601** times), and (b) **an enforcement layer whose value has NEVER been measured on real usage**: the entire current-config window is 100% self-referential (0 organic turns). The prior "enforcement is net-negative" verdict is **WITHDRAWN → INSUFFICIENT DATA**. OpenSpace's **closed feedback loop** is still the right direction — and the correction makes its measurement half the *precondition* for judging anything, not an optional upgrade. Corrected thesis: **you cannot decide the enforcement question until you first measure it on organic usage — which has never happened; meanwhile, delete the proven bloat.** |
| **Shelf life** | Static findings hold indefinitely; ALL value/rate conclusions are pending a clean organic measurement window that must be generated forward. |

## The integrated picture (corrected)
The fork wrapped a lean retriever in a governance layer, then measured that layer with a ledger it pooled
across its own rapid evolution — manufacturing a false "it's failing" signal. Strip the measurement error and
two things remain true and one becomes clear: the **over-engineering is real** (deletable today, safely), the
**retriever is genuinely good**, and the **enforcement bet is simply untested** — the tool has only ever been
used on itself. OpenSpace supplies the missing organ (a closed measure→improve loop); the correction shows that
organ's *first job* is to produce the honest measurement the fork never had.

## Findings by evidence strength
### STRONG (config-independent; Opus-validated; unaffected by the data correction)
1. **Engine novelties kept, retriever is the stronger substrate** — drift `warning`, dark/stale `health`, token
   proof, 30 unit tests all kept; mpnet MAX-pool > OG whole-doc cosine (measured A/B, rank-1 2.2×).
2. **DELETE the inert graveyard** — per-skill tau, deterministic routes, dominance collapse, keep-off, legacy
   `enrich_index`. **0 of 601 offer-events** ever fired a route or keep-off drop (binary, epoch-independent).
   ~840 LOC / `config/*.json=[]`. Safe to remove now.
3. **Enforcer is over-engineered on its own merits** — four inert stages in the per-turn hot path, judged on
   design, independent of value.
4. **Recoverable losses:** service-free default (~10 LOC), a published recall number (harness exists), the
   cache-honesty doc section.

### INSUFFICIENT DATA (the corrected core — do NOT treat as a verdict either way)
5. **Enforcement value is UNMEASURED — organic n ≈ 0.** Current-config window = 27 offers / 17 surfaced, **100%
   self-referential** (9 from this audit session, 4 subagent notifications, 0 organic). Genuine-turn
   `embed_timeout` ≈25% (n≈20) vs a 15% healthy baseline — suggestive, far too small to conclude. Not negative,
   not positive: **untested on real work.**

### UNMEASURED / ENVIRONMENTAL
6. **Body-trigger layer (+60% index)** — offline A/B never ran; genuinely unmeasured (D3, ledger-independent).
7. **The 07-02 `embed_timeout` spike** — onset 2 days before v0.12.0 ⇒ **environmental ops incident**
   (shim/Docker/load), triage separately; not an enforcement-design property.

## OpenSpace transferables (carried forward — unchanged by the correction, but re-prioritized)
Verified in OpenSpace's shipped DB last pass (config/ledger-independent):
1. **Close the loop: record → "did it help?" → quality rates → rewrite skill *metadata*.** HIGH.
2. **Add an async "actually helped?" `effect` signal.** HIGH — **now the linchpin:** it is simultaneously the
   *measurement instrument* the fork lacks (finding 5) AND the prerequisite for the loop. One build answers both.
3. **Two-stage retrieval** (over-fetch → exact-name rerank) — MED, ~20 LOC; our path is single-stage.
4. **Plan-then-select + abstain-to-empty doctrine** — MED, zero infra; sharpens precision + skip.
5. **Env-override gate tuning + precedence ladder** — MED, cheap; helps the against-data-floor problem.
**REJECTED (unchanged):** cloud experience-sharing (anti-goal + just a registry), auto-skill-generation (their
DB proves sprawl), multi-host abstraction (abandons the CC-coupling that makes enforcement possible).

## Tensions (corrected)
- **"Measure first" and "close the loop" are the SAME build.** OpenSpace's `effect` signal is both the honest
  measurement the fork never had and the loop's input — so the linchpin is unambiguous: build the async effect
  signal first; it unblocks both the value verdict and the feedback loop.
- **The loop must not become the next per-turn tax** — the over-engineering the audit condemns. Async, off the
  hot path, additive fail-silent.
- **Delete vs invest:** the graveyard delete is safe and independent of the value question — do it regardless.

## Corrected prioritized roadmap (proposals — owner-authorized; nothing applied)
1. **GENERATE clean measurement — foundational, and it doubles as OpenSpace's `effect` signal.** Freeze v0.12.0;
   ledger filter excluding subagent/`<task-notification>` + skill-concierge-meta + the measuring session's sid;
   accumulate **~80–150 organic offered turns**; add the async "did it help?" event. Until this exists, every
   value claim stays INSUFFICIENT DATA.
2. **DELETE the inert graveyard** — safe now, config-independent, ~840 LOC KISS win.
3. **Triage the 07-02 embed_timeout spike** as an ops/infra incident, decoupled from enforcement.
4. **Cheap sharpeners:** plan-then-select doctrine + exact-name rerank.
5. **Reopen the two against-data gate knobs** with the owner; env-override tuning to make it cheap.
6. **Close the loop (metadata self-improvement)** — once #1's effect signal + clean window exist.
7. **Settle the rest:** body-trigger A/B, publish a recall number, restore the service-free option.

## Evidence gaps
| Gap | Why it matters | What fills it | Priority |
|---|---|---|---|
| Enforcement value (organic n≈0) | The central "is the layer worth it" question is untested | ~80–150 organic offered turns under frozen config, contamination filtered | HIGH |
| 07-02 timeout onset (environmental) | Degrades retrieval regardless of enforcement value | Instrument shim under contention; check Docker/load | HIGH |
| Body-trigger lift | +60% index shipped on faith | `SKILL_BODY_TRIGGERS=1/0` offline A/B + a body-only corpus | MED |
| Recall on our universe | Retrieval quality asserted, not shown | `precision_eval.py` on the mpnet index | MED |

## Methodology notes / what this re-run changed
- **This is the corrected re-run** the user ordered after the prior pass built on epoch-pooled ledger data. The
  audit workstream was **fully re-run** under the epoch-scoped discipline (4 corrected dimension reports).
- **The OpenSpace workstream was carried forward unchanged, by design:** the correction is about *how we assess
  our ledger*; the OpenSpace study reads an external repo + its own DB with zero skill-concierge-ledger
  involvement, so no finding could change. Re-collecting it would manufacture rigor, not add it (the very
  anti-pattern this whole episode taught). It remains Opus-validated PASS.
- **What genuinely changed vs the flawed final:** the enforcement-value verdict flipped from "measured
  net-negative" to **INSUFFICIENT DATA (organic n≈0)**, and the roadmap now leads with *generating* honest
  measurement (which is also the loop's prerequisite). The config-independent findings — engine intact, delete
  the graveyard, retriever stronger, OpenSpace loop as target — are unchanged and remain the trustworthy core.
- **Nothing is applied.** Owner-gated proposals only.
