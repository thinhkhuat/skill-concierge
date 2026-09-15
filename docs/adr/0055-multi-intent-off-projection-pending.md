# ADR-0055 — Multi-intent offers switched off (Claude trial); ROUTE projection kept pending clean data

Status: Accepted (2026-09-15, owner GO after discussion)
Relates to: ADR-0041 (multi-intent offers + route projection — partly reversed here), ADR-0054 (harness-message lane — the reason the old data is void), ADR-0029 (chain hints — untouched).
Evidence: the v0.46.0 usage audit (`plans/reports/audit-260914-2325-concierge-usage-strengthen.md`, R9) and the human-prompt backtest below.

## Context

ADR-0041 added two context-only layers to the per-turn offer: **multi-intent shaping** (when ≥2 lexically disjoint comparable clusters exist, render N primaries leads-first plus a "Reads as N distinct intents" line) and **ROUTE projection** (a "ROUTE: if <top> fits, the catalogue's typical continuation is …" line from the top candidate's chain map). Neither changes gating; both add text to the preview.

The v0.46.0 audit found both unmeasured in practice: 14 of the 19 ROUTE projections fired on harness-generated text, and multi-intent's 0/143 was pooled over the same polluted population. R9 therefore deferred any decision until clean data existed. The owner asked why wait and what could be decided now.

## Backtest on human prompts only (v0.46.0 epoch, harness turns excluded, take within the same offer window)

| Layer | Fired | Paid off | Control |
|---|---|---|---|
| ROUTE projection | 5 | 0 | — |
| Multi-intent offers (≥2 distinct takes) | 84 | 5 (6 %) | single-intent offers 7/98 (7 %) |
| Chain hints (strict next-offer join) | 11 | 1 | 8/16 with the session-wide join the reviewers deemed correct for hints |

Render cost, measured from recent transcript hook attachments: the multi-intent line averages ~245 chars and appeared on 44 of the sampled offer-bearing turns (about half); the ROUTE line averages ~183 chars and appeared on 4. A live false positive was observed the same day: a single-question prompt rendered "Reads as 2 distinct intents".

## Decision

1. **Multi-intent offers OFF, as a Claude-side trial.** `ENFORCER_MULTI_INTENT=0` in `~/.claude/settings.json` `env` (backup `~/.claude/settings.json.bak-multiintent-20260915-100413`). The evidence is not thin — 84 clean offers with zero lift over the control — and the layer has a visible false-positive habit at a real per-turn cost. Other harnesses keep the code default ON; the code default itself is unchanged. Revert = delete the env line.
2. **ROUTE projection stays ON.** Five clean samples is not a verdict, and since ADR-0054 the top candidate is often a *named* skill whose declared chain is curated (`ak-cook → ak-test, ak-code-review`), so projection may only now be measuring what it was designed for. Decide at epoch-watch v0.47.0 W6 once ≥30 human-prompt projections exist (`analyze.py --continuation --since "2026-09-15 09:10"`); kill-switch `ENFORCER_CHAIN_PROJECTION=0`.
3. **Chain hints untouched** (ADR-0029; 8/16 follow under the correct join).

Options considered and rejected: turning both off now (decides projection on 5 samples and forfeits the named-skill-chain effect); keeping both and waiting (pays the multi-intent line for weeks on a layer the clean data already says does nothing); reshaping projection to fire only after a route hit or keep-on top candidate (a code change with no evidence yet — revisit if W6 shows projection following only on curated chains).

## Consequences

- Claude previews lose the "Reads as N distinct intents" line and the leads-first multi-primary shaping; the ranked list itself is unchanged. `n_intents` keeps being logged as 1.
- Cross-harness comparison of multi-intent uptake is possible in the same epoch (Claude OFF vs OMP/others ON) — the only way to measure the layer's lift without a second reversal.
- If a later epoch shows ≥2-take lift on multi-intent offers over the control in the ON harnesses, re-enable by deleting the env line and record it under this ADR's supersession.
- The ADR-0041 route-projection decision is explicitly *not* reversed; W6 owns it.
