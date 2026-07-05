# SYNTHESIS — Vendored Original (skill-search 0.1.0) vs skill-concierge (0.12.0): Audit Verdict

**Date:** 2026-07-04 23:12 (Asia/Saigon) · **Author:** orchestrating agent, synthesizing a 4-agent audit
**Inputs:** the four dimension reports (D1 novelty, D2 over-engineering, D3 retrieval, D4 ops) + handover
baseline, all in this dir. Read-only. Upstream confirmed still at v0.1.0 (no post-fork drift to miss).

## Bottom line
**Did we miss novelties from the original?** Mostly NO. The OG's engine-level novelties (drift
`warning`, dark/stale `health`, token proof harness, unit tests) are all KEPT — two strengthened. The
real losses are at the **deployment + narrative layer**, not the engine.
**Did we over-engineer and degrade?** YES, materially — and the audit surfaced ledger evidence the
added machinery is currently **net-unproven-to-negative on the only measured workload.**

## The two questions, answered with evidence

### Q1 — Missed novelties (D1): three real losses, all recoverable, none in the engine
1. **Service-free DEFAULT lost — MODERATE.** OG ran anywhere in ~4 commands (embedded Qdrant +
   fastembed, no Docker). Fork hard-requires Docker: `.mcp.json:6` pins the Qdrant server, `setup.sh:47-48`
   hard-`exit 1` on no-Docker, plus a 2nd embed-shim container. The engine STILL supports embedded mode
   (runs when `SKILL_QDRANT_URL` unset) — the capability is intact, only the default + setup path force
   the server tier. Recoverable in ~10 LOC.
2. **Prompt-cache rebuttal DROPPED — MINOR.** The OG's honest "caching is a billing win, not a
   context-window win" section (README:111-137) survives in no fork doc — lost intellectual honesty.
3. **No published recall number — MODERATE.** OG shipped a 24-query eval (bge-small recall@1 0.67). Fork
   correctly retired it as wrong-universe (`caveats §1`) and has a replacement harness (`precision_eval.py`
   + `eval/scenarios/`) but has published NO valid recall@k on its own mpnet/excluded-universe index.

### Q2 — Over-engineering & degradation (D2, D4): two headline findings
1. **The inert-feature graveyard (~840 LOC) the ledger proves NEVER fired.** Per-skill tau, deterministic
   routes (`config/deterministic-routes.json = []`), dominance collapse, keep-off (`config/keep-off.json
   = []`), legacy MEAN `enrich_index.py` (superseded footgun). Ledger scan: 0 deterministic-route hits, 0
   keep-off drops, ever. ~140 LOC inside `enforcer.py` + ~700 LOC of scripts carried permanently OFF.
2. **The semantic stack is BYPASSED on a majority of turns — the sharpest finding.** Live ledger
   (`scripts/analyze.py`, run this session): recent offer events = **63% `embed_timeout` fallback
   blended** — Opus validation disaggregates this to **~55% on genuine user turns vs ~94% on
   load-contended subagent-notification traffic** (lifetime **34%**, *worsening*). On those turns the
   whole shim + Qdrant + multi-vector stack is skipped and a ~15-line hook ships the plain mandate. The
   threaded-shim "fix" (`enforcer.py:56-62`) did NOT hold. AND when it DOES run, `analyze.py` = **11%
   offered-turn conversion (34/316) / 89% dodge / 41% hit@k**. ⚠ **These rates are RETRACTED as
   decision-grade** (added 2026-07-04 23:57): the ledger pools ~15 config epochs (v0.2→v0.12) and the
   `embed_timeout` spike is a **07-02 environmental onset** (9–20% before, 54–68% after — two days before
   v0.12.0 shipped), not a design property. The enforcement-value question is **UNMEASURED**, not
   measured-negative. A valid read needs a clean window under frozen v0.12.0 config on organic
   (non-subagent) traffic — see the integrated final report's *Data-validity note*.
3. **Two decisions shipped AGAINST their own data, in the hot path.** `GETAWAY_FLOOR=0.45`
   (`enforcer.py:66`; ADR-0009 shows taken offers score *lower* than dodged, 0.414<0.457) and the
   AUTHORIZED-SKIP getaway leg ON against ADR-0015's own recommendation (operator override, prerequisite
   re-measurement still open).

### Retrieval fidelity (D3): the patches split cleanly on evidence
- **Description-trigger MAX-pool (ADR-0012): MEASURED better, narrowly.** Held-out shadow A/B on the
  fork's mpnet index: rank-1 11.3→25.0% (2.2×), separation 0.049→0.105, false-fire flat 1.4%. Correctly
  MAX-pools over separate points (no MEAN-centroid dilution). Caveat: measured on 14 of 495 skills.
- **Body-trigger layer (ADR-0016, +60% points): UNMEASURED.** The patch the charter targeted. Improvement
  asserted by analogy to ADR-0012, never measured; the promised Phase-7 A/B was never run; shipped
  default-ON against the proposal's gate-first advice. Dilution soundly avoided (separate points, base
  vector untouched); topical-noise risk real but bounded (`_TRIG_MAX=12` + `Do NOT use` guard) and
  unquantified.

## What's genuinely EARNED (defended, not bloat)
The mpnet multilingual embedder + VN imperative lexicon (fix a real EN→VN recall miss); the Qdrant
**server** tier (OG's own caveat admits the embedded store locks to one process — concurrent sessions
need it); the fail-silent/additive hook contract; the curated 31-skill keep-on; the 16 ADRs (cheapest,
highest-leverage artifact in the repo). The fork did NOT break the engine — its core is intact and
slightly improved.

## Prioritized recommendations (grounded; owner-gated where noted)
1. **INSTRUMENT + FIX the 63% embed_timeout regression** — highest leverage. The enforcement premise
   can't be judged while its own retrieval is bypassed on most turns. Root cause uninstrumented (D2/D4).
2. **DELETE the inert graveyard** — `enrich_index.py`, `build_keep_off.py` + `keep-off.json`,
   dominance-collapse; demote per-skill-tau + deterministic-routes to an ADR note. ~840 LOC / net KISS win.
3. **REVERT `GETAWAY_FLOOR` 0.45→0.40 + split the authorized-skip flag to turn the getaway leg OFF** —
   both against-data; flag-and-reopen with the owner, not a unilateral change (ADR-0009/0015).
4. **RESTORE a service-free option** (~10 LOC in setup.sh + a `.mcp.json` fallback) — recover the OG's
   drop-in portability without losing the server tier.
5. **SETTLE D3** — run the `SKILL_BODY_TRIGGERS=1`-vs-`=0` A/B via the existing harness (+ build the one
   missing material: a body-only-signal labeled corpus) so the +60% patch is measured, not asserted.
6. **PUBLISH a recall number** on the fork's universe (harness exists) + restore the cache rebuttal in docs.

## Unresolved
- Root cause of the shim-timeout regression not instrumented — blocks judging the enforcement premise.
- "Never armed" proven only for the two ledger-observable inert features; inferred for the other three.
- Enforcement's central premise (per-turn tax lifts skill-first behavior) remains UN-measured vs
  proven-worse — no valid retrieval benchmark on the fork's universe yet.
- Recs #2/#3 touch shipped behavior + operator decisions — proposals for owner sign-off, not applied
  (this whole op is read-only).
