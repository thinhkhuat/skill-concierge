# Epoch watch — the canonical monitoring scope

One doc, one section per telemetry epoch. Each section records WHAT to watch, the
TRIGGER that demands action, and the ACTION (always env-first, never a re-release).
New epoch → append a section; never edit a closed one except to mark a watch RESOLVED
with the resolution date and evidence. This file is the single canonical reference —
primary docs point here and never restate the items.

**How to measure (all sections):** epoch-scoped only —
`analyze.py --since "<epoch deploy time>"`, exclude subagent + self-session traffic,
say "insufficient data" when the window is too small. Never pool across epochs
(full rule: [`AGENTS.md`](../AGENTS.md) → *Guardrails*).

---

## v0.43.0 — consult-intent routing (ADR-0049 phase 2; deployed 2026-08-29 late)

Live epoch. Routing fires only on main sessions (subagent payloads suppressed) and
only on the EN phrase class (v2 since 0.43.1 — widened from the first live miss,
"which set of skills that we should be using", replayed from the ledger per the W1
rule; negative guards hold out past-conditional/reflexive/skills-gap shapes) —
segment by ledger `band: consult_route` rows.

| # | Watch | Trigger | Action |
|---|-------|---------|--------|
| W1 | **False-route rate.** Replay every `consult_route` ledger row's prompt against the intent it actually carried. | ≥1 in 5 routed turns was NOT a deliberation ask (over-fire), OR known consult-shaped phrasings repeatedly failing to route (under-fire, e.g. "consult me with this sequence of tasks" — deliberately unmatched v1). | Over-fire → tighten `_CONSULT_RE` anchors (add negative context); under-fire → add the replayed phrasing as a new pattern. NEVER widen from vibes — only from replayed ledger evidence. |
| W2 | **Route→consult uptake.** Routed turns that actually invoke `skill-concierge:consult` (the `auto` row naming it in the same sid). | Routed turns repeatedly answered from the preview instead of invoking consult. | Strengthen the CONSULT-ROUTE mandate wording (the "never from a per-turn preview alone" clause); if still dodged, route-dodge joins the dodge metrics. |
| W3 | **--fast depth adequacy.** Fast-tier routed consults leading to re-consults at depth. | ≥3 same-task re-consults asking deep after a routed fast consult. | Flip the routed default to deep, or drop the fast default (owner taste — the ADR left it a judgement call). |
| W4 | **Route volume.** Share of offer-bearing turns that are consult_route. | Sustained >10% — the phrase class is catching ordinary task turns. | Same replay discipline as W1; expect the true rate near the deliberation-ask frequency (low single digits). |

## v0.42.0 — consult deliberation layer (ADR-0049; deployed 2026-08-29)

Live epoch. The consult layer is opt-in, so segment by sessions whose ledger carries a
`consult_verdict` row (or the `auto` row naming the consult skill) — never pool these
into all-turn rates.

| # | Watch | Trigger | Action |
|---|-------|---------|--------|
| W1 | **Verdict→take conversion.** How many `consult_verdict` primaries get an `auto` take in the same session. | After ≥10 consults: <50% take-rate on high-confidence verdicts. | Read those verdicts' gap lines — low take on clean cards means the funnel misranks (tune the analyst prompt, bump `PROMPT_VERSION`); low take on gap-heavy cards is the funnel honestly reporting NONE-shaped tasks. |
| W2 | **Sieve recall gaps persist.** Manual `sieve-missed` admissions appearing in verdict chains (the practice-run failure mode). | Admissions in ≥1/3 of consults after capsule coverage passes ~50% of the index. | Capsule vocabulary is not reaching the sieve — evaluate feeding capsule purpose/capabilities into the trigger-point layer (ADR-0026 v2-style eval FIRST; separate ADR). |
| W3 | **Capsule corpus staleness.** Body edits outrunning regeneration (fingerprint invalidated but no `--capsules` run since). | `capsule_coverage.have/total` from sieve calls drifting down over weeks while skill churn continues. | Operator runs `flywheel.py --generate --capsules`; if chronic, revisit auto_flywheel inclusion with a per-run cap (ADR-0049 deliberately kept it operator-commissioned). |
| W4 | **External share of verdicts.** The `externals` field of `consult_verdict` rows. | Sustained 0 external picks across ≥10 consults on cross-domain tasks. | Not a defect by itself (fit rules); investigate only alongside W2 — the same vocabulary gap starves externals at the sieve. |
| W5 | **--fast vs deep divergence.** Fast-tier cards leading to a different chain than a deep consult on the same task. | User re-consults deep after a fast card on the same task ≥3 times. | Mark `--fast` screening-only in the skill body; if divergence persists, drop the flag. |

## v0.41.0 — complement annex (ADR-0048; deployed 2026-08-29 ~16:30 local)

Design intent being watched: the annex becomes the builtin's complement — volume
collapses on well-served intents (beaters only), take-rate rises. The inversion of
those two numbers IS the success metric.

| # | Watch | Trigger | Action |
|---|-------|---------|--------|
| W1 | **External take-rate rises while annex volume collapses.** Baseline: 410/2,656 offers carried externals, 6 pulls ever (pre-0048 era). Measure both from epoch start. | After ≥1 week of data: take-rate flat-or-down while volume fell — the gate cut noise but found no value; or volume unchanged — gate not biting. | Flat take-rate with collapsed volume = design working as ordered (noise cut), no action. Volume unchanged → check `ENFORCER_ANNEX_COMPLEMENT` is on in the live hook env; then lower `ENFORCER_ANNEX_BEAT` 0.04 → 0.02. |
| W2 | **Beat-gate starvation.** An external is repeatedly the semantically right answer (search_skills surfaces it high) but never annexes because it trails the installed top by ≤0.04. | ≥3 distinct sessions where manual search surfaced a fitting external the annex had gated out that same turn. | Lower `ENFORCER_ANNEX_BEAT=0.02`. If still starved, `ENFORCER_ANNEX_COMPLEMENT=0` (full revert to margin rule) and re-open the ADR — record the evidence first. |
| W3 | **Annex-at-cap should be rare now.** Under the complement gate, a full 4-row annex implies a thin intent (top < 0.45) — near-nonexistent on this 2,676-skill index. Cap-4 on well-served turns = a gate leak. | Any live observation of 4 external rows alongside an installed top ≥ 0.55. | Inspect: which row beat the top by 0.04? Genuine complements are fine; systematic near-misses (top+0.04…top+0.05) suggest the beat delta is at noise level on the cosine band → raise `ENFORCER_ANNEX_BEAT` to 0.05. |
| W4 | **Proven-first ranking observable.** The 4 proven externals (`antigravity:apple-container`, `multi-source-search` at 2 sessions; `active-directory-attacks`, `pdf-conversion-router` at 1) should surface FIRST with `used N×` when their domains recur. | A proven external annexes BELOW an untaken higher-scorer (sort broken), or `used N×` missing while ranking still applies (render/digest divergence). | Sort/render bug → fix in enforcer (`_retrieve_external` sort / `_ranked_mandate` takes); re-pin selftest 11c. |
| W5 | **Digest freshness + promotion watch.** `external-takes.json` refreshes only on unthrottled auto_promote passes (6h throttle, 1 MB ledger tail). Counts at 2 sessions are one pull from promotion (3 distinct sessions → symlink install + reindex). | A pull that doesn't show in the digest within a session; or a promotion firing — verify the reindex picked the promoted skill up as installed. | Stale digest is advisory-only (ranking lags, nothing breaks) — no action unless W4 also fires. Post-promotion: confirm `doctor` retrieval-health row and the skill appearing in the primary list, not the annex. |

**Non-goals of this watch** (settled, do not re-litigate without new evidence): no
re-merge into the primary pool (ADR-0047 reverted it); no chain-hint admission of
externals; no floor relaxation for proven rows (ranking only).

## v0.40.0 — annex restore (ADR-0047; superseded same day by 0048)

Closed 2026-08-29: the annex-at-cap watch ("if live annexes run at cap on most
offer-bearing turns, drop margin back toward 0.05") resolved by ADR-0048 replacing the
margin rule entirely — the complement beat gate answers the same concern structurally.
Carry-over watch lives in W3 above.

## Older epochs

Pre-0.40.0 epochs had no standing watch items (ADR-0045's parity epoch lasted one day
and its metrics are void — never cite them pooled with anything).
