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
