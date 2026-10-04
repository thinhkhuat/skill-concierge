# ADR-0078: Consult sieve widening with Jev's whole-catalogue top 10

- **Status:** Accepted (2026-10-04, owner's order to work the plan until proven, plan `plans/261003-1907-consult-sieve-recall-fixes/`). Shipped as 0.58.0. The widening is live; the two earlier sieve flags stay default OFF.
- **Extends:** ADR-0049 (consult), ADR-0076 (Jev fit matrix, `scripts/jev_client.py`), ADR-0061 (Jev router, the wide whole-catalogue question).

## Context

`consult_candidates` is the embedding sieve behind `skill-concierge:consult`. The ADR-0076 live evaluation found that in 11 of 13 consult runs the primary the agent finally chose was not among the sieve's rows, so the sieve's recall is the weak link of the consult layer.

Iteration 1 tested two engine flags (`SKILL_CONSULT_SLOTS`, `SKILL_CONSULT_RRF`) and three query-wording changes on 83 mined turns. Every decision failed the pre-registered gate, and nothing shipped ([iteration-1 verdict](../../plans/261003-1907-consult-sieve-recall-fixes/reports/phase-03-gate-verdict.md)). A diagnosis of those 83 turns ([diagnosis](../../plans/261003-1907-consult-sieve-recall-fixes/reports/iter2-diagnosis.md)) found a different lever: Jev ranks the whole installed shelf against the task text, so it finds skills that no keyword-style query names. That diagnosis ran on a set that had informed the fixes, so it was a hypothesis, not proof. Proof needed a fresh set, and a pre-registration written before any arm ran on it.

## Decision

1. **`scripts/consult_fit.py widen` adds Jev's top 10 to the sieve rows.** The consult skill's step 2 calls `consult_candidates` with `top_n` 40, then pipes the user's request text (verbatim) and that response into `widen`. Jev's whole-catalogue top 10 (round-robin across catalogue chunks) goes first, the sieve rows follow in order, duplicates are dropped by full skill key, and the list is cut to 20. Each row carries `source`: `jev`, `both` or `sieve`. The logic is ported from `scripts/sieve_recall.py`, the code the gate measured: one attempt on the `ts` tier, 3 s timeout, empty conversation context, the request redacted and capped at 4000 characters before it leaves the machine.
2. **Script-side, not in the engine.** The TypeSafe key lives with the offline scripts (ADR-0076 decision 1); the MCP server's env does not reliably carry it. `consult_candidates` is unchanged.
3. **Kill switch `SKILL_CONSULT_JEV_WIDEN`, default ON.** `=0` returns the sieve rows (first 20) with no Jev I/O. Script-side, so not in `ENGINE_ENV_KEYS`.
4. **Any Jev failure falls back to the sieve rows.** A non-zero exit or `jev.failed: true` means the card says `sieve: not widened`.
5. **Jev-only rows have no `path`.** The consult skill and `agents/analyst.md` read a path-less row with `get_skill(name)`.
6. **`--top N` now applies only when `widen` is off or fails.** A widened run always uses 20 rows.
7. **`SKILL_CONSULT_SLOTS` and `SKILL_CONSULT_RRF` stay default OFF.** They failed iteration 1 and failed again in iteration 2 (D_SR40, below).

## Evidence

Pre-registration: `plans/261003-1907-consult-sieve-recall-fixes/iter2-prereg.md` (sha256 `60c3389de3b41940e896458a87e38d644730ca6e6353583cdec79033cf1fbaaa`), pushed as `7b339dd` before the run. The gate ran once; raw output is `plans/261003-1907-consult-sieve-recall-fixes/reports/iter2-gate-raw.txt`, metadata `iter2-gate-meta.txt`. Verdict lines, copied from the raw file:

```
VERDICT: D_J20 PASS n=29 (J20 vs A0@20, not_jev) recall@20 24.1 -> 48.3 (gain 24.1 pts) G2=True G3=True (lost 0, gained 7) G4 p=0.0156 holm_p=0.0469 holm=True (sessions +6/-0) G5=True (median ext 7, share 61.9->33.1) G6=True (p90 73->969 ms)
VERDICT: D_SR40 FAIL n=57 (SR40 vs A0@40, all) recall@40 28.1 -> 33.3 (gain 5.3 pts) G2=True G3=False (lost 2, gained 5) G4 p=0.2266 holm_p=0.2266 holm=False (sessions +5/-2) G5=True (median ext 12, share 62.3->30.6) G6=True (p90 75->92 ms)
VERDICT: D_J40 PASS n=29 (J40 vs A0@40, not_jev) recall@40 27.6 -> 51.7 (gain 24.1 pts) G2=True G3=True (lost 0, gained 7) G4 p=0.0156 holm_p=0.0469 holm=True (sessions +6/-0) G5=True (median ext 20, share 60.4->48.9) G6=True (p90 75->969 ms)
JEV: calls 57 failed 0  p50 839 ms p90 969 ms
```

Reading: the primary set is not shaped by a Jev offer. On it, the widening raised recall@20 from 24.1 to 48.3 (7 cases gained, 0 lost; 6 sessions gained, 0 lost). **The statistical margin is narrow:** Holm-adjusted p is 0.0469 against a 0.05 bar, on 6 sessions and n=29. D_J40 passed with the same counts. Per the pre-registered tie rule (smallest Holm p, then larger gain), the smaller list ships. D_SR40 failed (G3 and G4), so slots and RRF stay OFF.

What this does not prove: the cases are single-skill turns with generated queries, a proxy for real consult requests (deliberation-shaped). The real-consult effect stays UNMEASURED. The Jev call is one extra ~0.8 s (p90 969 ms) on a deliberate consult step, inside the 1500 ms bar set for Jev arms.

### Judgement calls made without asking

Logged with their reasons in `plans/reports/decisions-261004-0942-sieve-iter2.md`. The ones that bear on how far to trust the result:

- **Spent set.** The 83 iteration-1 cases informed the diagnosis, so they were treated as spent: diagnosis only, never proof.
- **Pool extension (decision 7).** The Jev primary stratum had 23 fresh cases, under the 30-case floor. Iteration-1 corpus rows never among the 168 iteration-1 cases (`pre_router_unseen`, capped at 5 per label, blocklist-dropped) were added. They predate the Jev router, so there is no circularity, and no tuning step saw them. Cost: some share sessions with spent cases.
- **Jev case floor 25 (decision 8).** Lowered from 30 to 25 for the two Jev decisions after the count (29) was known, from counts only, before any arm ran. False passes are controlled by the per-session sign test with Holm, not by the floor, which guards power.
- **G6 1500 ms for Jev arms (decision 5).** The default rule (baseline + 100 ms) fails any Jev arm by construction (~0.8 s per call). SR40 kept +100 ms.
- **Primary stratum (decision 4).** Jev decisions are judged only on cases whose chosen skill was not in a Jev-produced live offer, conservative for Jev.

## Consequences

- Consult candidate sets change: the first 10 rows are Jev's, the rest come from the sieve, 20 in total. Externals no longer fill most of the list.
- Jev adds a network call to every consult run while the switch is ON. A Jev outage costs nothing but the widening.
- A Jev-only row has a name and description, no capsule and no path. The analyst reads its body with `get_skill`.
- Round-robin across catalogue chunks puts rank 1 of every chunk first, so some low-fit rows appear near the top of the Jev block. That is the gated design, not a bug.
- `widen` computes the sieve rows itself, in a child process of the installed engine venv run from the caller's folder, so project-scoped skills the MCP tool sees stay in the rows. The gate ran every arm from the home folder, so project-scoped skills were absent from both its baseline and its arms; the measured gain says nothing about them either way.
- Not checked: widen under a non-Claude harness, and Jev with recent context (the router passes it; widen does not).
- Live behaviour is watched in `docs/epoch-watch.md` (v0.58.0, W37).

## Revert path

`SKILL_CONSULT_JEV_WIDEN=0`: the consult skill keeps calling `widen`, which returns the sieve rows untouched. To remove the call itself, revert the step-2 change in `skills/consult/SKILL.md` (and the path-less-row note in `agents/analyst.md`) and `scripts/consult_fit.py widen`. Turning SLOTS or RRF on needs the flag in that harness's MCP server env plus a server restart, and a new pre-registered gate.
