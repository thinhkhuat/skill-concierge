# Phase 3 — held-out gate verdict (2026-10-04 05:09)

Run once: `scripts/sieve_recall.py gate --composites` under the engine venv, importing the repo engine. Raw output: `phase-03-gate-raw.txt`; run metadata (HEAD, diff stat, server.py sha256): `phase-03-gate-meta.txt`. Index lock lines identical at start and end (points 44,730, base 2,902, same name-set hash); no index drift; 85 of 168 cases dropped by the pre-registered leak check (kept unchanged — AFK decision #5).

| Decision | n | recall@20 baseline -> arm | Verdict |
|---|---|---|---|
| Installed slots (`SKILL_CONSULT_SLOTS`) | 83 | 33.7 -> 33.7 | FAIL |
| Rank fusion (`SKILL_CONSULT_RRF`) | 83 | 33.7 -> 34.9 | FAIL |
| Task-sentence query (proxy) | 60 not-offered | 21.7 -> 18.3 | FAIL |
| "How" query (proxy) | 83 | 33.7 -> 33.7 | FAIL |
| One sub-goal per query (proxy) | 83 | 33.7 -> 34.9 | FAIL |

No decision passed G2 (gain >= 5 points) or the Holm-corrected G4. Composite guard held for slots and RRF (lower bound 0.0). Latency and external-share guards (G5, G6) passed everywhere.

**Applied (per plan):** nothing flips; both flags stay default OFF; SKILL.md unchanged; no release, no ADR. Both flags documented in AGENTS.md, CLAUDE.md and README.md.

**What the numbers say (inference, not a gate result):**
- Slots move installed skills up but mostly into ranks 21-40: recall@40 rises 36.1 -> 43.4 while recall@20 stays flat.
- The debugger report's large gains came from 10 real consult misses studied in-sample; on 83 held-out mined turns the same fixes barely move recall@20. The mined set is single-skill turns with generated queries (a proxy), so the real-consult effect stays UNMEASURED, not disproven.
- Query fidelity: generated vs real queries agree on the side of rank 20 in 10 of 12 real consults, but disagree in both directions on the other 2.

**Open:** whether a larger `top_n` (recall@40 view) or the slots flag at 40 is worth a new pre-registered test; the process-skill group (4 cases) is too small to judge.
