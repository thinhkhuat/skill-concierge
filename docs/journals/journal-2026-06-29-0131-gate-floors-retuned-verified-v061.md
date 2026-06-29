# Gate Floors Re-tuned by Operator Order, Verified Live (v0.6.1)

**Date:** 2026-06-29
**Component:** skill-concierge enforcer (pre-gate word floor + getaway score floor)
**Status:** Shipped + independently verified live
**Version:** 0.6.0 → 0.6.1

## What shipped

Two enforcer gate knobs raised by operator order: `MAX_SHORT_WORDS` 2→5 (the pre-gate now skips ≤5-word prompts before any embed) and `GETAWAY_FLOOR` 0.40→0.45 (an offer needs top cosine ≥0.45). Both are **operator-set AGAINST a data-backed recommendation** — recorded loudly in ADR-0009, in-code comments, and CHANGELOG [0.6.1], with a one-line revert.

## The analysis that preceded it (both knobs argued against)

Before touching anything, tested the proposal against the live ledger (147 real offers, 10 taken) and the 2,032-prompt transcript corpus:

- **Score floor 0.40→0.45.** Cosine is anti-correlated with adoption here (taken median top 0.414 < dodged 0.457). Among current-floor survivors (97: 6 taken / 91 dodged), 0.45 removes ~22% of noise but ~50% of adopted offers; surviving-offer take-rate falls 6.2% → 4.1%. The offers it cuts ([0.40,0.45)) convert *better* than the ones it keeps.
- **Word floor 2→5.** ~93% of conversational noise is >5 words (the floor can't reach it); the 3–5-word band is ~2:1 actionable:conversational (66 vs 33) — it suppresses more signal than noise, and runs *before* the imperative-veto built to protect short commands.

Verdict: neither helps; the real lever is the intent gate. The operator chose to ship anyway — perceived live behaviour, bounded blast radius (fail-open additive hook), one-line revert.

## Implementation

- `enforcer.py` lines 65/67 — the two values + `OPERATOR-SET … ADR-0009 … Revert` comments.
- `docs/adr/0009-operator-set-gate-thresholds.md` (new) — decision + evidence-against + revert; ADR index row; `CHANGELOG.md` [0.6.1].
- Version triple + README badge → 0.6.1; `driftcheck.py` IN SYNC.
- Commit `6995fd8`, pushed; `/plugin marketplace update` + `/reload-plugins` → live.

## Independent live verification (verify-as-claimed)

Spawned a separate-party verifier (builder ≠ verifier). Verdict **GO**:
- Active artifact = cache `0.6.1` (`installed_plugins.json`, gitCommitSha `6995fd8`); deployed == committed source (three empty diffs).
- Behavior proven by raw bytes: word boundary 5w silent vs 6w offer (0.5679); a meta turn at top **0.4103 → getaway**, which directly rules out the 0.40 value; offers fire at ≥0.45; negation / intent_skip / encoding / malformed-JSON all per contract; zero fail-open artifacts (deps up).
- Raw evidence: `plans/reports/verify-260629-0107-skill-concierge-0-6-1-gate-thresholds-live-raw-evidence.md`.

## The open question (mechanism verified ≠ impact proven)

Verification proves the gate executes correctly at 5/0.45 — NOT that the change helped adoption. The verifier's clean test prompts scored 0.52–0.84, but real adopted offers sit at median 0.414 (inside the [0.40,0.45) band the new floor cuts), so the live drives cannot settle impact; the honest read still points at "it bites real traffic." The predicted false-suppression is confirmed live: "update the handoff" (3w) and "fix the parser bug" (4w) are now dropped before the imperative-veto.

## Next

A fresh-session dogfood kickoff was prepared (`plans/reports/kickoff-meta-prompt-260629-0110-dogfood-0-6-1-thresholds.md`) to replicate-or-falsify the prediction on accrued live data via `analyze.py` offered-turn conversion (split on the `6995fd8` ship time). Keep / revert / adjust is the dogfood's call. Revert: set 2 / 0.40 (or `ENFORCER_GETAWAY_FLOOR=0.40`), supersede ADR-0009 with ADR-0010.
