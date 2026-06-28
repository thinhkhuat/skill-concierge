# Prompt-Complexity Classification — Fit Analysis for skill-concierge

**Date:** 2026-06-28
**Scope:** Should skill-concierge add a per-prompt *complexity/mode classifier* (as built in `danielmiessler/LifeOS` PAI v5.0.0) to its per-turn enforcement path? If so, in what form, and how does it sequence against existing work?
**Method:** Primary sources only. (a) LifeOS `PromptProcessing.hook.ts` (v5.0.0) fetched and read verbatim this session; (b) skill-concierge hooks/scripts read this session (`enforcer.py`, `ledger.py`, `analyze.py`, `hooks.json`); (c) the **live invocation ledger** analyzed this session (`python3 scripts/analyze.py`, 456 events / 193 turn-windows). Every numeric and code claim below traces to one of these.

---

## 0. Decision (TL;DR)

**Do not adopt a prompt-complexity classifier as a mechanism in skill-concierge.** The system already performs the only triage its charter needs — *empirically*, via the semantic floor — and the live ledger shows the dominant failure is **not** complexity-misjudgment but **offered-turn dodge under a contaminated workload (93%)**, which no complexity signal can touch.

There is exactly **one** evidence-sized borrow: a **deterministic pre-embed triviality short-circuit** that closes a real but small hole — trivial prompts still get nagged on the ~11% of turns where the embed/Qdrant path falls back to mandate-only (the floor structurally can't suppress them there). That is a ~30-line, zero-dependency, deterministic change — **not** an LLM classifier — and it is a *minor hardening*, not a priority.

The LifeOS **effort-tier taxonomy (E1–E5)** is **out of skill-concierge's charter** (it governs *how much work*, a separate concern from *which skill / whether to use one*) and should not enter this codebase.

| Candidate | Verdict | Why (one line, evidence below) |
|---|---|---|
| LLM mode/tier classifier in the enforcer | **Reject** | Adds an inference call + failure mode for a job the cosine floor already does empirically; doesn't address the 93% dodge |
| Deterministic triviality short-circuit (pre-embed) | **Shelve — condition tested, failed** | The §7.2 gate was run (see §0.1): 0/18 fallback turns trivial, and the floor already separates trivia empirically. Target surface ≈ empty. |
| E1–E5 effort tiers | **Out of charter** | Governs effort budget, not skill selection; belongs to the separate effort layer, and only as an estimate, never a cap |
| Doing nothing about complexity, fixing measurement + offer-precision instead | **The actual priority** | The live numbers point here, not at the classifier |

### 0.1 Empirical update — the §7.2 gate and the floor were tested (verdict: shelve the borrow)

After drafting, the two experiments §7 prescribes were actually run on the live system. Both kill the "adopt" case for the triviality short-circuit.

**(a) Fallback-slice triviality (the §7.2 gate).** Every `fallback`-band event in the live ledger (18/158 offers) was inspected. **0 of 18 are trivial** — all are `embed_timeout` on long, substantive prompts (multi-line instructions, repo-study requests). The slice the short-circuit targets is empirically empty; payoff #1 (suppress mandate-on-trivia during fallback) does not occur. The real signal in this band is **embed latency on long prompts** — a different, better-targeted lever (shim throughput / the 200 ms cap / pre-embed truncation) if the 11% is ever worth attacking.

**(b) The floor already triages (live retriever).** The would-be-caught example prompts were run through the real embed + Qdrant pipeline:

| prompt | top score | floor @ 0.40 |
|---|---|---|
| thanks that totally worked | 0.271 | silent (getaway) |
| ok got it perfect | 0.256 | silent |
| what time is it | 0.310 | silent |
| **what does this function do** | **0.560** | **OFFER → gitnexus-exploring** |
| fix typo on line 12 | 0.392 | silent |
| fix the typo on line 42 of foo.ts | 0.365 | silent |
| yes please do it | 0.309 | silent |
| build me a complex application | 0.698 | OFFER → app-builder |
| audit the algorithm and update doctrine | 0.682 | OFFER → opus-validate |

The 0.40 floor already separates trivial (silent) from substantive (offer) — **empirically and catalogue-aware**. A hardcoded "skip single-fact questions / single-line edits" rule would **false-suppress** correct offers (e.g. "what does this function do" → 0.560 → `gitnexus-exploring`; single-line edits sit just under the floor and would cross it given a relevant project skill). The deterministic word-list is strictly worse than the cosine it would duplicate.

**Resulting verdict:** the triviality short-circuit moves from *adopt-conditionally* to **shelve**. §5 below is retained for the rationale that led there; its condition is now tested and failed. The priority is unchanged (Option D — measurement + offer-precision). *(Scores are index-specific; the structural conclusion — floor triages, word-list false-suppresses — is not.)*

---

## 1. What the LifeOS classifier actually is (grounded)

LifeOS `PromptProcessing.hook.ts` is a **bun/TypeScript `UserPromptSubmit` hook** whose *stated purpose* is tab-title + session naming; mode/tier classification is **one of several jobs riding a single inference call** ("One process, one inference call" — file header; `OUTPUT FORMAT` JSON carries `tab_title`, `session_name`, `mode`, `tier`, `mode_reason` together).

It classifies a prompt on two axes:

| Axis | Values | How decided |
|---|---|---|
| **MODE** | `MINIMAL` / `NATIVE` / `ALGORITHM` | Fast-path for MINIMAL only; otherwise **LLM inference** |
| **TIER** (ALGORITHM only) | E1–E5 | **LLM inference** only |

**Tier definitions (verbatim):**
> - 1 Standard: trivial single-file work that creates something new (~<90s).
> - 2 Extended: single-domain task spanning a few files, quality must be extraordinary (~3min).
> - 3 Advanced: substantial multi-file work, multi-step plan, root-cause investigation (~10min).
> - 4 Deep: cross-cutting design, doctrine changes, architecture changes, cross-vendor audit needed (~30min).
> - 5 Comprehensive: research / build with no time pressure (>2h).

**The deterministic path is narrower than it looks.** Verbatim, the only no-inference exits are:
- `isExplicitRating(prompt)` → emit `MINIMAL`, `latency_ms: 0`.
- `prompt.length < MIN_PROMPT_LENGTH` → emit `MINIMAL`, `latency_ms: 0`.
- the "detect current mode" block (`isMinimalInteraction ? 'minimal' : !isNativeMode(prompt) ? 'algorithm' : 'native'`) is used for **tab UI state**, not for the classification emitted to the agent.

So the **useful** distinction — NATIVE (simple edit / single fact → no heavy process) vs ALGORITHM + tier — is **LLM-inferred every time**. The deterministic path reliably catches only *praise/ratings/too-short*.

**Injection + fallback (verbatim):**
```
emitAdditionalContext → `MODE: ALGORITHM | TIER: E${tier} | REASON: ${reason} | SOURCE: classifier`
finalMode = validModes.includes(r.mode) ? r.mode : 'ALGORITHM'     // invalid → ALGORITHM
finalTier = ALGORITHM ? (1..5 ? r.tier : 3) : null                  // invalid → E3
inference failed/errored → emitAdditionalContext('ALGORITHM', 3, …)  // source: 'fail-safe'
```
Design intent: the classifier can only *reduce* effort from the maximum; on any uncertainty it defaults to ALGORITHM/E3 (full process). Telemetry (`appendPromptProcessingTelemetry`) logs `mode/tier/source/latency_ms` per prompt.

**The cost structure is the load-bearing fact for fit.** LifeOS pays for the inference *anyway* (it needs tab titles + session names); mode/tier is a near-zero-marginal-cost rider on that call. **skill-concierge has no such existing inference call to amortize onto** — adopting the classifier means paying the *full* per-turn inference cost (latency + API + a new failure mode) for the classifier alone.

---

## 2. skill-concierge already triages — empirically, not by tier (grounded)

The per-turn enforcer (`hooks/scripts/enforcer.py`, registered `UserPromptSubmit` in `hooks/hooks.json`) already routes every prompt through a triage that maps cleanly onto LifeOS's MINIMAL/NATIVE/ALGORITHM split — without an LLM:

| Stage | Code | Effect | LifeOS analogue |
|---|---|---|---|
| Cheap pre-gate (no I/O) | `enforcer.py:203–206` — empty / `startswith("/")` / `len(split) <= 2` → `return 0` | silent skip | the `MINIMAL` fast-path |
| Refusal guard | `:210–213` `_REFUSAL_RE` → mandate-only | suppress refused skill | — |
| Embed + retrieve | `:216–233` warm shim → Qdrant top-k, hard ~200ms timeout | get candidates | the inference call |
| **Semantic floor** | `:238–242` `top < GETAWAY_FLOOR (0.40)` → silent "getaway" | **drop no-fit/trivial prompts** | the `NATIVE`/no-skill decision |
| Offer | `:244–247` items ≥ `ITEM_FLOOR (0.18)` → inject ranked candidates | enforce + surface | the `ALGORITHM` route |

The tuning comment (`:47–54`) states the floor's empirical basis: *"pure trivia ('thanks, that worked') tops ~0.11; real tasks land ~0.22–0.40. A single LOW getaway floor cleanly drops trivia."* In other words, **skill-concierge already answers "does this prompt warrant a skill?" with a measured cosine, not a guessed tier** — and a cosine is a *better* instrument for skill-concierge's charter than a complexity label, because the charter is "*which* skill / *whether* to use one," which is a relevance question, not a complexity question.

**Critical asymmetry that kills naive borrowing.** LifeOS's NATIVE mode says *"simple edit → skip the heavy process."* Importing that into skill-concierge would mean *"simple edit → skip offering skills,"* which **directly contradicts skill-concierge's founding bet**: that a relevant skill should surface *even on a small task you'd otherwise wing*. A one-line edit that semantically matches a project lint/format skill at cosine ≥ 0.40 *should* still be offered. Complexity is the wrong axis; relevance is the right one, and the floor already measures it.

---

## 3. What the live data says the real problem is (grounded)

`python3 scripts/analyze.py` over the live ledger (456 events, 193 turn-windows) this session:

```
uptake            : 32/193   17%   (turn used a skill)
dodge             : 121/193  63%   (no skill, no search)  [proxy upper-bound]
offers            : 151      bands: {'offer': 131, 'fallback': 16, 'getaway': 4}
fallback rate     : 16/151   11%   (mandate-only: embed/qdrant down or slow)
offered-turn conv : 9/135    7%    (offered ≥1 skill → agent used one)
offered-turn dodge: 126/135  93%   (offered yet none used — the compliance gap)
per-skill offer→take (top offenders):
    review-docs                  0/21   0%
    ck:journal                   0/18   0%
    skill-search                 0/18   0%
    skill-concierge:skill-search 0/16   0%
```

Four facts that decide this analysis:

1. **The dominant failure is offered-turn dodge: 93% (126/135).** When the enforcer *does* surface a relevant skill, the agent takes it 7% of the time. **A complexity classifier changes none of this** — the skill was already correctly offered; it just wasn't taken.
2. **Triviality is already a non-problem in this workload: `getaway` fired only 4 times.** The 0.40 floor almost never has to say "no skill," because on this (meta-heavy) workload most prompts *do* retrieve something ≥ 0.40. The volume a triviality classifier would catch is tiny.
3. **The repeat-never-taken offenders are a *precision* problem, not a complexity problem.** `review-docs` offered 21×/taken 0×, `ck:journal` 18×/0×, `skill-search` 18×/0× — skill-*management* skills retrieved on prompts that are *about* skills/reports (workload contamination), where they score above floor but aren't wanted. Fix surfaces here are floor recalibration / negative filtering / a clean non-meta window — **not** a complexity tier.
4. **The fallback band is real but small: 11% (16/151).** This is the *only* slice where a deterministic triviality gate adds value (see §5).

`analyze.py:291–294` already encodes the right epistemics: global dodge/uptake are flagged as a *proxy upper-bound* that "include getaway/no-offer turns," and the real compliance signal (`offered-turn conv/dodge`) is *already* measured only on turns where a skill was actually surfaced. **The measurement layer already excludes the noise a triviality classifier claims to remove** — so "a classifier would clean the signal" is not a real benefit here.

---

## 4. Fit analysis — three questions

**Q1. Does skill-concierge need to *classify complexity* to do its job?**
No. Its job is relevance (which skill) + compliance (whether to use one). Relevance is measured by cosine (`GETAWAY_FLOOR`/`ITEM_FLOOR`); compliance is enforced by the mandate. Complexity tiers (E1–E5) answer "how much effort," which is a different layer's concern. Mapping a tier onto skill-offering would inject the wrong axis (§2 asymmetry).

**Q2. If we wanted a "should this turn use a skill at all?" gate, does it need an LLM?**
No — and LifeOS confirms it, in reverse: LifeOS only affords the LLM call because it amortizes onto naming inference it runs regardless. skill-concierge has no such call; an LLM gate would be pure added cost (latency on every prompt, an API dependency, and a new fail-safe-to-mandate path) for a decision the floor already makes in ~0–250ms locally. The deterministic subset LifeOS *does* run without inference (praise/ratings/too-short) is already covered by `enforcer.py:203–206` + the floor.

**Q3. So is there *any* real gap a LifeOS-style idea addresses?**
Yes — one, narrow. The `GETAWAY_FLOOR` triviality suppressor lives **only on the embed-success path** (`:238`). On embed-timeout / embed-down / Qdrant-down (`:216–233`), the enforcer injects the **full mandate and returns before the floor is ever evaluated**. So when the shim is down or slow, a trivial-but->2-word prompt ("thanks everyone, that did the trick") gets the SKILL-FIRST nag. The live `fallback rate` sizes this surface at **11% of offers**, of which only the *trivial* fraction is wrong. A **pre-embed** deterministic triviality check is the only thing that can suppress that, because it runs *before* the path that bypasses the floor.

---

## 5. The one borrowable change, scoped and sized

> ⚠ **Superseded — see §0.1.** The condition this section sets was tested on the live system and **failed** (0/18 fallback turns trivial; the floor already triages, and a word-list would false-suppress correct offers). Verdict moved to **shelve**. Retained below for the rationale that led there.

**Change:** extend the cheap pre-gate (`enforcer.py:203–206`) with a small deterministic triviality matcher that runs **before** the embed call, so trivial prompts short-circuit on *every* path — including the fallback path where the floor can't reach.

**Catches (deterministic, no LLM, no new dependency):**
- acknowledgments / praise: `thanks`, `ok`, `got it`, `perfect`, `nice`, `lgtm` (word-list, like LifeOS `POSITIVE_PRAISE_WORDS`)
- bare confirmations: `yes`, `do it`, `go ahead` (only as standalone short prompts)
- (optionally) explicit ratings, à la LifeOS `isExplicitRating`

**Deliberately does NOT catch** "simple edits" / "single-fact questions" — those are exactly the prompts a relevant skill might serve, and the floor already judges them empirically (§2 asymmetry). This is the one place the LifeOS taxonomy must *not* be copied wholesale.

**Three honest, small payoffs (no overstatement):**
1. suppress mandate-on-trivia during the **11%** fallback slice (the floor cannot);
2. save the ~100–250ms embed round-trip on obvious trivia;
3. close a telemetry hole — the current pre-gate skips (`:203–206`) `return 0` with **no `_append_offer`**, so they are invisible in the offer stream. A `band="skip"` event makes them countable (and lets us *verify* the gate's value from the ledger).

**Sizing caveat (why it's low priority):** the addressable surface is the *trivial fraction of 11%* of offers. The 93% offered-turn dodge and the 0%-take precision offenders are orders of magnitude larger. This change is correct hardening, not a needle-mover.

**Anti-scope:** no mode label injected into the agent's context, no tier, no effort signal, no LLM. The deliverable is a *quieter hook on trivial+degraded turns*, nothing more.

---

## 6. Options matrix

| Option | Cost | Addresses the 93% dodge? | Addresses precision offenders? | Charter fit | Recommend |
|---|---|---|---|---|---|
| A. Full LLM mode/tier classifier | High (per-turn inference, API dep, fail-safe path) | No | No | Poor (wrong axis) | ✗ |
| B. Deterministic triviality short-circuit (§5) | ~30 LOC, deterministic | No | No | Good | ✗ (gate tested → failed, §0.1) |
| C. Effort-tier taxonomy in skill-concierge | Medium | No | No | Out of charter | ✗ |
| D. Actionability gate + negative-anchor substrate, grounded on the transcript corpus | Medium | **Yes (the real lever)** | **Yes** | Core | ✓ (the priority) |

---

## 7. Implementation plan (experiment-first, falsifiable)

Sequenced so each phase produces evidence that gates the next. Phases 1 and 3 carry the value; Phase 2 was the small borrow and is now shelved (§0.1).

**Phase 1 — Build the grounding dataset from the transcript corpus (no waiting). [priority]**
- Mine `~/.claude/projects/**/*.jsonl` (measured this session: **774 sessions, 4,427 user prompts**, cross-project) for `(prompt → did the agent do real tool-work?)` pairs. The label is mostly free and deterministic: an Edit/Write or ≥3-tool turn → `actionable` (~25–39%); prose-only → `conversational` (~21%); an LLM refines only the read-only middle.
- Output: a large, cross-project, **already-clean** labeled set — the grounding + evaluation data for the gate. This opens the solution horizon the way a small, post-hoc, single-deployment view never could, and it requires waiting for nothing to accrue.
- Success criterion: a labeled `(prompt, actionable)` dataset big enough to backtest any gate design against real, diverse history.

**Phase 2 — Triviality short-circuit (§5). [DONE — gate ran, result: SHELVE. See §0.1]**
- Gate (RUN 2026-06-28): grepped `band:"fallback"` events (`q` logged at `enforcer.py:220`) — **0/18 trivial**, all `embed_timeout` on long prompts; and the live floor test (§0.1b) showed the floor already triages while a word-list would false-suppress. Per the rule "if fallback is rare/non-trivial → shelve and record why," → **shelved**.
- Not built. The would-be matcher (~30 LOC + `band="skip"`) is documented for the record only; revisit solely if a future non-meta workload shows a material chat-trivia volume reaching the embed/fallback path.

**Phase 3 — Offer precision on the real workload. [priority]**
- **Backtest update (2026-06-28) — score-tuning is a dead end.** On the live ledger: dodged offers score *higher* than taken ones (median top **0.445 vs 0.408**); a margin/separation gate doesn't move the 93% dodge (only shrinks volume); demoting the 15 chronic "offered-≥8 / taken-0" skills moves it **~0%** (another topical match fills the slot). **Cosine does not predict adoption** — so `GETAWAY_FLOOR`/`ITEM_FLOOR` recalibration and per-skill demotion are both falsified as dodge levers.
- **The discriminating axis is actionability/intent, not score.** The 9 taken offers are imperative, skill-shaped commands ("write the handoff" → `session-handoff`; "return to ck:plan" → `ck:plan`); the 127 dodged are conversational/status/approval/meta turns that topically clear 0.40 but want no skill. With ~500 skills, *something* always clears a fixed floor — the floor rubber-stamps instead of gating.
- **Levers, in order:** (1) an **actionability gate** that suppresses offers on non-task turns (imperative-verb + named-artifact vs discourse-marker/opinion/status); cheap+deterministic first, then grounded on the transcript dataset (Phase 1) — e.g. a `prompt_intent` kNN over the existing embedder + Qdrant. Distinct from the shelved triviality gate (§0.1), which targeted short praise, not long non-actionable turns. (2) **Negative anchors + firing-condition enrichment** of the index substrate (extend `_REFUSAL_RE` from user-refusals to skill-stated "do NOT use for" anti-triggers; enrich vectors with when-to-invoke, not topic). (3) **Redefine the metric** to take-rate *on actionable turns* — the raw 93% is mostly correct declines and is a vanity-scare number.
- Success criterion: take-rate on actionable turns rises; offer volume on conversational turns falls. Each lever is backtestable on the transcript-grounded dataset (Phase 1) before shipping.

**Explicitly not in this plan:** any LLM call in the enforcer; any `MODE`/`TIER` token injected into agent context; any effort-budget logic. Those are rejected (§6 A, C).

---

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Triviality matcher false-skips a prompt a skill should serve | Low if scoped to praise/confirm/rating only | `--selftest` pins the silent-on-edits/questions contract; never extend to "simple edits" |
| Transcript actionability label is noisy on the read-only middle band (~40%) | Medium | Deterministic-label the clear Edit/Write vs prose-only ends; LLM-refine only the middle; use a graded, not binary, label |
| Over-fitting the gate to historical behavior (most transcripts predate the enforcer → the agent rarely used a skill) | Medium | Label the prompt's *actionability*, never "the action taken" — past non-use reflects no enforcer, not that a skill wouldn't have helped |
| Scope creep toward "just add the tier, it's free" | Medium | §1 cost structure: it is *not* free here — skill-concierge has no naming-inference to amortize onto |

---

## 9. Open questions

1. **Is `GETAWAY_FLOOR = 0.40` calibrated for a non-meta workload?** Live data shows it rarely fires (`getaway` = 4) because meta prompts retrieve skill-management skills above floor. Testable on the transcript corpus (Phase 1) — though §0.1/Phase 3 already show floor-tuning is not itself a dodge lever.
2. ~~What fraction of the 11% fallback band is actually trivial?~~ **ANSWERED (2026-06-28): 0/18 — none; all `embed_timeout` on long prompts.** Phase 2 shelved (§0.1). Follow-on: is embed-timeout-on-long-prompts worth attacking (shim throughput / cap / truncation)?
3. **Is the 93% offered-turn dodge a contamination artifact or a real compliance failure?** The enforcement organ's justification rides on this. Answer it from the transcript corpus (Phase 1): re-score historical turns by whether they were skill-shaped, then measure dodge only on the actionable ones — no waiting on a live window.
4. **Does any task ever need a complexity signal *for skill selection* (not effort)?** e.g. a doctrine-audit prompt wanting broader/different candidates than a one-file change. Speculative, data-blocked — flagged, not planned.

---

*All claims grounded in primary sources read this session: LifeOS `PromptProcessing.hook.ts` (v5.0.0, fetched verbatim), skill-concierge `enforcer.py` / `ledger.py` / `analyze.py` / `hooks.json`, and the live invocation ledger via `analyze.py`.*
