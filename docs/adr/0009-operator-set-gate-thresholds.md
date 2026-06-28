# ADR-0009: Operator-set gate thresholds over data-backed defaults (word floor 2→5, score floor 0.40→0.45)

**Status:** Accepted — operator override of the data-backed recommendation; explicitly reversible (see "Revert")
**Date:** 2026-06-29
**Deciders:** owner (thinhkhuat)

## Context

Two cheap pre-offer gates in `hooks/scripts/enforcer.py` decide whether a turn even gets a skill offer:

- `MAX_SHORT_WORDS` (was 2) — a prompt with ≤ this many words gets a silent getaway **before any embed and before the imperative-protect logic runs**.
- `GETAWAY_FLOOR` (was 0.40) — an offer fires only when the top retrieval cosine ≥ this value.

The operator perceived too much offer-noise (the live ledger shows ~94% of fired offers get dodged) and ordered both floors tightened: `MAX_SHORT_WORDS 2→5`, `GETAWAY_FLOOR 0.40→0.45`. Before changing anything, the proposal was tested against the live ledger (147 real offers, 10 taken) and the 2,032-prompt transcript corpus. **The analysis argued against both knobs.** This ADR records the change made anyway — on the operator's explicit order over that recommendation — so the decision is loud, attributable, and cheap to revert.

## The evidence against (why the data said no)

**Score floor 0.40 → 0.45.** Cosine magnitude is *anti-correlated* with adoption here: taken offers score LOWER than dodged (median top 0.414 vs 0.457 — three independent confirmations: this ledger, the prior backtest 0.408<0.445, and corpus separability). Among offers that clear the old 0.40 floor (97: 6 taken / 91 dodged), raising to 0.45 removes 20 of 91 noise offers (22%) but **3 of 6 adopted offers (50%)** — the take-rate of surviving offers FALLS, 6.2% → 4.1%. A higher score floor cuts the better-converting offers first.

**Word floor 2 → 5.** ~**92.9% of conversational/noise prompts are longer than 5 words** — the real dodge-noise is long-form, so a word floor cannot reach it. In the 3–5-word band it *does* fire on, the corpus is ~**2.0 : 1 actionable : conversational** (66 vs 33): it suppresses ~2 genuine short commands ("update the handoff", "cook that plan", "fix the report staleness") for every 1 noise prompt caught — and it runs *before* the imperative-veto built to protect exactly those. (One point in favour: in the ledger, 0 of 10 actually-adopted offers were ≤5 words, so no *observed* adoption is killed.)

These numbers are reproducible: ledger via `scripts/analyze.py` over `~/.claude/skill-telemetry/logs/skill-invocation-ledger.log`; corpus via `build_prompt_intent.mine()` word-counts per label.

## Decision

Set `MAX_SHORT_WORDS = 5` and `GETAWAY_FLOOR` default `0.45`, per operator order, **acknowledging the analysis recommends against both.** Accepted because: (a) the operator owns the precision/UX trade-off and is acting on perceived live behaviour the telemetry may under-capture; (b) the blast radius is bounded — the enforcer is an additive, fail-open hook, so a suppressed offer never blocks work, it only withholds a nudge; (c) both knobs stay environment-overridable and the revert is one line.

## Revert

To restore the data-backed operating point:
- `hooks/scripts/enforcer.py`: set `MAX_SHORT_WORDS = 2` and `GETAWAY_FLOOR` default `"0.40"`.
- Without editing code (score floor only): export `ENFORCER_GETAWAY_FLOOR=0.40`. The word floor is a literal, not env-backed — a code edit is required.
- Per the ADR convention (Accepted ADRs are immutable), supersede this with ADR-0010 rather than editing it.
- The decisive metric to re-check after any future change: `analyze.py` offered-turn conversion — confirm the tightening did not drop the take-rate of surviving offers.

## Verification

- `enforcer.py --selftest` — refusal guard + ranked-mandate + imperative-veto pass (this change touches no tested contract).
- `driftcheck.py` — version IN SYNC at 0.6.1.
- Shipped as 0.6.1 (patch — a default-value tune).

## Related

- ADR-0008 (sibling tuning decision — embed-timeout calibration; its lesson: trust the live ledger over desk intuition).
- ADR-0002 (the fusion/enforcer hook these gates live in).
