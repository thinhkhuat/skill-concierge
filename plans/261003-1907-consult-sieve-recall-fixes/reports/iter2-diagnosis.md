# Iteration 2: consult sieve miss diagnosis and candidate fixes (spent set)

Date: 2026-10-04 09:40 (Asia/Saigon). Data: the 83 kept cases of the spent gate set (168 frozen, 85 dropped by the leak check, the same rule the gate applied). Everything here is **exploratory**: the set is spent, so every gain below is an in-sample figure and will shrink on fresh data.

## Outcome

The sieve does not miss because its list is too short or its ordering is off. It misses because the generated queries never describe the skill the agent ended up using: 42 of the 55 misses rank below 100, and for 29 of them no single query puts the label in its own top 100. Ordering and list-size fixes cannot reach those cases. Jev's whole-catalogue ranking can, because it reads the task text against every installed skill at once. Adding Jev's top 10 to today's sieve raises recall@20 from 33.7 to 59.0 (+25.3 points; sessions +19/-1). The best fix that needs no new code is the two existing flags turned on together (slots + RRF): +8.5 at 20 rows and +10.8 at 40.

## Method

- Engine: the repo's `server.py` through `sieve_recall.load_engine()`, cwd = home, the engine env forwarded (the instrument's own loader). Every arm uses the frozen d0 queries (`arm_queries("A0", …)`), up to 5 per case.
- Ranks beyond 40: the engine caps `top_n` at 40, so I rebuilt the list from the engine's own primitives (`embed_queries`, `_qdrant.query_groups` with `_scope_filter()`, `_fuse_ranked`, `_blocked`). Checked against `srv.consult_candidates` on all 83 cases at 20 and 40: same skill sets in all 166 lists. In 10 lists, tied rows come back in a different order, which does not change recall@N. The engine cuts to `top_n` first and only then drops blocked rows, so some engine lists hold 39 rows; the replica applies the same rule.
- Baseline check: replica recall 33.7 at 20 and 36.1 at 40, the same as the gate's A0 (`phase-03-gate-raw.txt`).
- Jev: `scripts/jev_client.load_enforcer()` (relay off, direct), `_jev_catalog()` (604 invocable installed skills, 3 chunks of up to 250), `_jev_wide_questions`, `_jev_call` on the ts tier (`jev-1.13.0`), one attempt, timeout 3 s. State: `{"request": gen_text[:4000], "recent_context": "", "skills_already_loaded_this_session": []}`. Also ran the router's rerank (`_jev_rerank_questions` over the top 5 of each chunk). Ran everything twice to measure stability. **0 failures in 166 wide calls and 166 rerank calls.**
- Union rule: Jev's top k first, then the sieve rows in order, deduplicated by skill key, filled to exactly L rows (L = 20 or 40). Jev order inside the top k is round-robin across chunks (rank 1 of each chunk, then rank 2, and so on), because the enforcer notes that chunk probabilities cannot be compared across chunks. Sorting by raw probability (`wide-glob`) measured worse at k = 5 and k = 10.
- Latency: engine arms are timed around `consult_candidates` at `top_n` 40. Union latency is max(sieve, Jev), which assumes the two run in parallel.

Commands (all run from `_RESEARCH_ARTIFACTS/iter2/` with `~/.claude/skill-concierge/venv/bin/python3`):

```
probe.py ; probe2.py ; eqcheck.py        # engine load, replica == engine check, Jev catalogue size
diag.py                                  # per-case ranks to 100 -> diag.jsonl
jev_run.py ; jev_run_rep2.py             # Jev wide + rerank, two runs -> jev_wide*.jsonl
arms_engine.py                           # engine flags x top_n 20/40 -> arms_engine.jsonl
arms_replica.py ; inst_rrf.py            # orderings with no engine flag -> arms_replica.jsonl, inst_rrf.jsonl
analyze_iter2.py > analyze_iter2.out     # all arms, recall, latency, gained/lost
strata.py > strata.out                   # strata, session sign test, bootstrap, router state
stability.py > stability.out ; causes.py > causes.out ; g5.py > g5.out
```

## 1. Why the baseline misses (55 misses at recall@20)

Where the label ranks (`diag.py`; 101 means beyond 100):

| Label rank (A0, flags off) | Cases |
|---|---|
| 1-20 (hit) | 28 |
| 21-40 | 2 |
| 41-100 | 11 |
| beyond 100 | 42 |

Recall by list size: 33.7 at 20, 36.1 at 40, 49.4 at 100. Even a sieve of 100 rows would miss half the labels.

Causes. Each miss is counted once, in the order listed (`causes.out`):

| Cause | Count | What it means | Recovered by A0 ∪ Jev top 10 at 20 | Recovered by slots+RRF at 20 |
|---|---|---|---|---|
| C0 label is on the blocklist | 2 | `whereami` is on Thinh's blocklist, so the sieve must hide it and no arm can win these cases | 0 | 0 |
| C1 crowded out by externals | 7 | ranks in the top 20 among installed skills only, but externals push it out | 4 | 5 |
| C2 buried by MAX pooling | 1 | one query ranks it in the top 20, but the merged list does not | 1 | 1 |
| C3 no query matches it | 29 | no single query ranks it in the top 100 | 7 | 0 |
| C4 weak in every query | 16 | best single-query rank is 21-100 | 11 | 1 |

Supporting facts:
- On misses, the label's best score against any query is a median of 0.123 below the 20th row's score (10th to 90th percentile: -0.27 to -0.03). The 20th row scores a median of 0.641. These are not near misses.
- Externals hold 663 of the 1,100 top-20 rows on miss cases (60%). Restricting the sieve to installed skills alone gives 41.0 at 20, so external crowding explains about 7 points, not the gap.
- C3 and C4 labels are mostly process or discipline skills, picked because of standing rules rather than the task's subject matter: `come-clean` (4), `unlazy` (3), `ak-debug` (3), `ak-cook` (3), `directional-prompting` (2), `verification-before-completion`, `which-skills`, `opus-validate`, `brief-me`. All 4 process-group cases miss. The doctrine tells the agent to write queries as "INTENT + DOMAIN TERMS", which describes what the task is about, not how the work is done, so these skills never match.
- No "hub" skill dominates: no name appears in the top 20 of 25% or more of the cases.
- Description weighting does not help. Every hit is won by a trigger point (124 of 124), and 243 of 248 best-hit points on misses are triggers too. Searching only base (description) points drops recall@20 to 24.1; searching only trigger points gives the same lists as today (33.7).
- The raw task text is a worse query than the generated ones: the redacted prompt as a single query scores 21.7 at 20 and the 300-character task sentence 24.1, against 33.7 for the generated queries.
- Router group: 47 of the 55 misses are in `not_offered` (60 cases); 8 are in `offered` (23 cases).

## 2. Candidate fixes (n = 83, from `analyze_iter2.out`, `strata.out`, `stability.out`)

g/l = cases gained/lost against A0 at the same list size; p = exact sign test on cases. Latency is per consult call.

### a. Larger sieve and the existing flags (engine, `arms_engine.py`)

| Arm | recall@20 | recall@40 | g/l @20 | g/l @40 | p50 / p90 ms |
|---|---|---|---|---|---|
| A0 (flags off) | 33.7 | 36.1 | — | — | 41 / 51 |
| slots | 33.7 | 43.4 | +1/-1 | +6/-0 | 53 / 59 |
| RRF | 34.9 | 41.0 | +2/-1 | +5/-1 | 41 / 50 |
| **slots + RRF** | **42.2** | **47.0** | +7/-0 (p 0.016) | +10/-1 (p 0.012) | 53 / 63 |

Session level, slots + RRF: +8.4 points at 20 (sessions +7/-0, p 0.0078, bootstrap 95% lower bound +2.9); +10.8 points at 40 (sessions +9/-1, p 0.011, lower bound +2.8). The gate never measured this pair, because arm C runs only when two decisions pass. Why it works: slots keep externals out of most rows (median externals in the top 20 fall from 11 to 6), and RRF reorders the installed tier so that a skill one query ranks well is not buried by other queries' strong scores. Neither flag does both alone.

Replica orderings (no engine flag; `arms_replica.py`, `inst_rrf.py`):

| Arm | recall@20 | recall@40 |
|---|---|---|
| installed-only sieve (MAX) | 41.0 | 44.6 |
| installed-only sieve, RRF k = 60 | 43.4 | 50.6 |
| installed-only, round-robin | 37.3 | 43.4 |
| mixed, round-robin across queries | 30.1 | 37.3 |
| mixed, RRF k = 1 / 5 / 20 | 31.3 / 34.9 / 34.9 | 38.6 / 38.6 / 41.0 |

Installed-only plus RRF reaches +14.5 at 40 (sessions +13/-2, lower bound +5.6). It needs a new code path, and it drops externals entirely: the case set cannot score that loss, because only 3 of the 83 labels are external.

### b. Jev union (`jev_run.py`, two runs)

| Arm | recall@20 | recall@40 | g/l @20 | g/l @40 | p50 / p90 ms |
|---|---|---|---|---|---|
| Jev only, wide, round-robin | 61.4 | 65.1 | +28/-5 | +30/-6 | 703 / 797 |
| Jev only, router rerank (up to 15 rows) | 59.0 | 59.0 | +26/-5 | +25/-6 | 1007 / 1130 |
| A0 ∪ Jev wide top 5 | 51.8 | 54.2 | +16/-1 | +15/-0 | 703 / 797 |
| **A0 ∪ Jev wide top 10** | **59.0** | **62.7** | +23/-2 | +22/-0 | 703 / 797 |
| A0 ∪ Jev wide top 20 | 61.4 | 67.5 | +28/-5 | +27/-1 | 703 / 797 |
| slots ∪ Jev wide top 10 | 60.2 | 65.1 | +23/-1 | +25/-1 | 703 / 797 |
| slots+RRF ∪ Jev wide top 10 | 57.8 | 65.1 | — | — | 703 / 797 |
| installed-only ∪ Jev wide top 10 | 60.2 | 65.1 | +23/-1 | +25/-1 | 703 / 797 |
| A0 ∪ Jev rerank top 5 | 55.4 | 57.8 | +19/-1 | +18/-0 | 1007 / 1130 |

For every union arm in this table with a g/l entry, p is below 0.004 at both sizes. Unions built on the round-robin sieve score lower; one has p 0.035. Exact values are in `analyze_iter2.out`.

- Session level, A0 ∪ Jev top 10: +25.3 points at 20 (sessions +19/-1, p 0.00002, bootstrap lower bound +15.0); +26.5 points at 40 (sessions +19/-0, lower bound +17.6).
- Stability: run 2 gives 60.2 at 20 and 63.9 at 40 (run 1: 59.0 and 62.7). The two runs' top-10 lists overlap by 88.6% on average, and 3 cases flip their Jev top-10 hit. The model was `jev-1.13.0` in both runs.
- Strata (from `strata.out`; recall@20 / recall@40):
  - not_offered, n = 60: A0 21.7 / 25.0, union 50.0 / 55.0.
  - offered, n = 23: A0 65.2 / 65.2, union 82.6 / 82.6.
  - English, n = 75: A0 32.0, union 56.0.
  - non-English, n = 8: A0 50.0, union 87.5.
  - without the 2 blocklisted cases, n = 81: A0 34.6, union 60.5.
- The union loses 2 cases at 20 and none at 40. At 20, Jev's 10 rows push sieve ranks 11-20 out: `vn-gov-docx` (sieve rank 12) and `superpowers:systematic-debugging` (sieve rank 17). The second is also outside Jev's invocable catalogue.
- Not in Jev's catalogue: 5 of the 43 distinct labels (`whereami`, which is blocked; 2 `antigravity:*` externals; `pdf:pdf`; `superpowers:systematic-debugging`).
- External-share guard (G5): the union's top 20 has a median of 6 externals and a 29.3% external share (A0: 11 and 55.7%), so G5 holds. slots + RRF: 6 externals, 30.7%.
- **Circularity check: clean on this set.** All 83 turns have `ledger_jev` = null, meaning the live Jev router decided none of them. The labels were therefore not shaped by a Jev offer. The case timestamps run from 2026-06-29 to 2026-09-25.

### c. Other fixes the analysis pointed to

| Idea | Result | Verdict |
|---|---|---|
| Base (description) points only | 24.1 / 26.5 | worse |
| Redacted task text as a single query | 21.7 / 32.5 | worse |
| 300-character task sentence as a single query | 24.1 / 31.3 | worse |
| Round-robin or low-k RRF over the mixed list | 30.1 to 34.9 at 20 | no gain |
| Installed-only, plus RRF | 43.4 / 50.6 | +9.6 / +14.5, but drops externals |

## 3. Risks for the fresh run (these must go into the pre-registration)

1. **Jev circularity on new turns.** The router shipped on 2026-09-26 09:47 (commit `0b03c88`), and the label corpus was cut the same day at 16:07: only 7 corpus turns were router-ok (`strata.py` / corpus count). A fresh set built from newer turns will be mostly router-decided turns, where the agent was handed Jev's own top 5. A Jev arm would then partly re-find its own offer. Pre-register the primary set as cases whose label was **not** in that turn's live offer (`ledger_offered`, whatever produced it), and report the offered stratum separately. This choice is conservative for Jev, because it keeps exactly the turns where Jev's live offer missed.
2. **The latency guard G6 fails a Jev arm by construction.** The rule allows p90 at most 100 ms above baseline; the Jev union adds about 700 ms (p50) and 800 ms (p90). Before the run, the guard needs a bound that fits a deliberate consult call (for example p90 at most 1,500 ms and Jev failure rate at most 5%). That is a decision for main or Thinh, not for me.
3. **Blocklisted labels.** Drop cases whose label is blocklisted when the set is built (2 of 83 here were unwinnable).
4. **Query-free Jev.** Jev reads the task text, not the generated queries, so the leak check does not protect the Jev side. Cases whose prompt names the skill are already dropped at build (`named_in_prompt`), which covers the main leak.
5. **Proxy population.** As at the gate, these are single-skill turns, not real consult requests. The real-consult effect stays unmeasured.

## 4. Hypotheses for the fresh held-out run

HYPOTHESES-FOR-HELDOUT: 1) **Jev union at 20 rows.** The sieve list is Jev's wide whole-catalogue Choice: `_jev_catalog` + `_jev_wide_questions`, ts tier `jev-1.13.0`, state `request` = the case's redacted task text (up to 4,000 characters) with empty context, one attempt, timeout 3 s, a failure counted as Jev contributing nothing. Take its top 10, in round-robin order across chunks, then today's sieve rows (d0 queries, `SKILL_CONSULT_SLOTS=0`, `SKILL_CONSULT_RRF=0`), deduplicated by skill key and filled to 20. Baseline: A0 at `top_n` 20. Spent-set gain: 33.7 -> 59.0 (+25.3 points; run 2: +26.5; sessions +19/-1; bootstrap lower bound +15.0); not_offered stratum 21.7 -> 50.0. Mechanism: Jev ranks the whole installed shelf against the task text, so it finds skills that no keyword-style query names (it recovers 18 of the 45 C3+C4 misses). 2) **slots + RRF together at 40 rows.** `SKILL_CONSULT_SLOTS=1` and `SKILL_CONSULT_RRF=1`, `top_n` 40, d0 queries, no code change. Baseline: A0 at `top_n` 40. Spent-set gain: 36.1 -> 47.0 (+10.8; sessions +9/-1; lower bound +2.8); at 20 rows 33.7 -> 42.2 (+8.5, below the 10-point preference). Mechanism: slots stop externals taking 60% of the rows, and RRF keeps a skill that one query ranks well from being buried. 3) **Jev union at 40 rows.** Same as 1, filled to 40, against A0 at `top_n` 40. Spent-set gain: 36.1 -> 62.7 (+26.5; sessions +19/-0; lower bound +17.6; no case lost). This is the safest form of 1: at 40 rows the union keeps every sieve hit.

Recommended primary: hypothesis 1 (or 3 if the consult funnel can take 40 rows). Expect shrinkage. A gain of about +25 on the spent set leaves a wide margin over a 5-point bar even if half of it vanishes. Hypothesis 2 has a narrow margin (lower bound +2.8), so it should not be expected to clear a 5-point bar on fresh data.

## Unresolved questions

- The latency guard for a Jev arm (risk 2) and the primary stratum rule (risk 1) need a decision before the fresh set is frozen.
- Where the union would live is not decided. `consult_candidates` runs in the MCP server, whose env may not carry `TYPESAFE_API_KEY`; the consult skill's script side (`consult_fit.py` already calls Jev) is the other option. I did not test either.
- Jev sees only the request here. Whether real consult tasks, which are deliberation-shaped, behave like these single-skill turns is unmeasured.
- Not checked: Jev with recent context (the live router passes it), Jev on the 85 leak-dropped cases, and whether the case set's mostly-installed labels (80 of 83) understate the cost of dropping externals.

## Honest status

Every figure above comes from the scripts and outputs listed in `_RESEARCH_ARTIFACTS/iter2/` (commands in the Method section). Files contain skill names, case ids, ranks and probabilities only. A `grep -F` scan for prompt fragments matched no scratch file. No repo source, private data file, git state or installer was touched. Decisions I made without grounding: union order (Jev first, then sieve rows), round-robin order across chunks, and an empty `recent_context` for Jev.
