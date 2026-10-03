# Phase 1 implementation report: sieve recall instrument, frozen cases, queries

Date: 2026-10-04 (Asia/Saigon). Status: DONE_WITH_CONCERNS. Every number below comes from a command run in this phase.

## Files

- `scripts/sieve_recall.py` (new): subcommands `build`, `queries [--retry-failed] [--freeze]`, `gate [--arms] [--composites] [--combine FLAGS:PARTS]`.
- `tests/test_sieve_recall.py` (new): 25 tests.
- Private data in `~/.claude/skill-concierge/jev-calibration/` (dir 0700, files 0600, verified with `stat`): `sieve-eval-cases.jsonl`, `sieve-eval-queries.jsonl`, `sieve-eval-manifest.json` (the lock file is removed after each run).
- Log: `logs/sieve-queries-run.log` (gitignored).
- No git operations. No Jev calls. The held-out gate was not run; only the `gate --arms A0` smoke (plan step 5) ran, which prints no verdicts.

## Tests

- `python3 -m pytest tests/test_sieve_recall.py -q`: `25 passed in 1.18s`.
- `python3 -m pytest tests/ -q`: `886 passed in 112.38s`. No failures. I have no pre-phase run to diff against, so "no new failures" rests on zero failures now (883 passed before the last additions to my own test file).
- Every test named in phase-01 exists. Added beyond the plan: arm-query shapes, fake-engine end-to-end (`run_arms` + `evaluate`, including a flag decision failing without composites), combination arm C, ship choice, missing-query INSUFFICIENT, strata report, real reply shapes, re-freeze.

## Counts: actual vs plan

| Item | Plan (dry count) | Actual `build` |
|---|---|---|
| Cases | 167 | 168 |
| Eligible turns before cap | 205 | 206 |
| Labels | 82 | 83 |
| Sessions | 105 | 105 |
| Not offered | 103 (74 sessions) | 104 (74 sessions) |
| Offered / unknown | 61 / 3 | 61 / 3 |
| Composite pairs | 83 | 84 |
| Label resolution exact / key / short | 257 / 2 / 8 | 257 / 2 / 8 |
| Named in prompt | 48 | 48 |
| Collisions (2+ base points / cross tier) | 131 / 84 | 131 / 84 |
| Not indexed | 47 | 45 |
| Index | 2,902 base points | points 44730, base 2902 |
| Gateway calls | ~513 | 516 planned (168x3 + 12), 518 made |

The plan's dry count and `build` differ by exactly one case (one extra label with one case, in the not-offered group). Resolution, named-in-prompt and collision counts match exactly, so the difference is one extra candidate that the dry count dropped by a rule I could not recover. I tested the plausible causes: consult-session filter (no effect on the count), word minimum, duplicate keys in a row. None reproduces 205. Two cases carry a `skill_named_in_prompt` field set where the registered rule 4 (whole key as a token) does not fire (`9router` named as `9router-*`, `memory-config` named without its namespace). I kept the registered rule. n stays above 30 everywhere, so the difference changes no gate outcome.

## Generation

- Model `cmc/deepseek/deepseek-v4.1-flash`, temperature 0.4, serial through `flywheel_llm.chat`. 518 calls: 516 planned plus 2 retries. Latency was about 17 s per call (not the plan's 6 s), so the run took 2 h 19 min (02:45 to 05:04).
- 2 calls failed first (`TruncatedCompletion` at `how`, `JSONDecodeError` at `how`); `--retry-failed` fixed both.
- The frozen file: sha256 `f83ab731bbe202678991709ddb2b6e92750b84c3d77f60167b961bb045f4bece`; per part `d0` 180 keys (168 cases + 12 real runs), `how` 168, `split` 168; 0 failed.
- A second `queries` run exits 2 with "queries are frozen".

## Fidelity (12 real consult runs, deduped on task + queries; top_n 40, flags off; 41 = >40)

| Run | Chosen skill | Real queries | Generated d0 |
|---|---|---|---|
| 0 | vn-editor | 1 | 41 |
| 1 | vn-editor | 41 | 41 |
| 2 | compound-to-skill | 41 | 40 |
| 3 | ak-agent-browser | 41 | 41 |
| 4 | ak-cook | 41 | 41 |
| 5 | impeccable | 41 | 41 |
| 6 | vn-news-coverage-tracker | 1 | 2 |
| 7 | tk-research | 41 | 41 |
| 8 | ak-plan | 41 | 41 |
| 9 | session-handoff | 41 | 4 |
| 10 | hooks-audit | 41 | 41 |
| 11 | compound-to-skill | 28 | 34 |

Median absolute rank difference 0.0 (most pairs are both ">40"); both <=20 or both >20 in 10 of 12 runs. The real-query column reproduces the debugger report (hits at rank 1, run 11 at 28, the rest >40). The two disagreements run in opposite directions (run 0 lost, run 9 found), so generated queries are a weak proxy per case.

## Smoke run `gate --arms A0` (not a verdict)

- Both INDEX-LOCK lines identical: `points=44730 base=2902 names_sha256=13a374b8...`; drift vs build +0 -0.
- Engine loaded from the repo path `vendor/skill-search/skill_search/server.py`; both phase-2 flag readers were already present when I ran it.
- Cases dropped by the leak check: 85. Remaining 83 cases, 59 sessions: not_offered 60 (44 sessions), offered 23 (21 sessions), unknown 0, English 75, process group 4.
- A0 recall@20 33.7%, @40 36.1%, p50 39 ms, p90 45 ms (n=83).

## Concerns

1. **The pre-registered leak check removes 85 of 168 cases (51%).** Any label word of 4+ letters appearing in any generated query drops the case, so generic words (`plan`, `skill`, `session`, `research`, `handoff`) remove whole labels: 40 of 83 labels drop out entirely, 43 remain. Effects on phase 3:
   - Composite pairs with both members surviving: 24 of 84 (the composite guard on slots/RRF rests on 24 pairs).
   - The process-skill group is 4 cases, and the `how` decision's target skills (`ak-plan`, `session-handoff`, `ak-cook`...) are nearly all excluded, so the doctrine verdict says little about process skills.
   - Primary sets stay above G1: all 83, not_offered 60. The surviving label mix leans toward distinctive names, which the plan's risk table anticipated ("G1 protects against a set too small"), not a set that is unbiased. I did not change the rule: changing it after the freeze voids the gate. Changing it now means rebuilding, regenerating nothing (the leak check runs at gate time over the frozen queries), so a rule change before the gate is cheap if Thinh wants one.
2. **A mistake and its repair.** I froze the query file while 40 `how` replies looked like failures: the model answered `{"query": [...]}` (a list) for 38 of them, a bare list for 1 and a wrapped `queries` for 1. The reply parser was too strict, not the generation. I fixed `queries_of` to read those shapes (the `how` arm takes the first string), and re-recorded the manifest counts through `queries --freeze`, which now re-records counts only when the query file's sha256 is unchanged (it refuses otherwise, test included). The query file is byte-identical (sha256 above), no gate had run, and the manifest holds `refrozen_utc`. This is a parser fix made before any verdict, not a change to a pre-registered rule.
3. **Added system text.** The generating model gets one fixed role sentence plus a JSON-format sentence around each doctrine text (`_ROLE`, `_FMT_*` in the script); the doctrine constants are verbatim. This is part of each system text's recorded sha256 (`doctrine_sha`, manifest `system_sha256`).
4. **Generation was 2h19, not 51 min** (gateway latency). Serial as planned.
5. **Phase file not updated.** `phase-01-start.md` is not in my ownership list, so its status line is untouched.

## Judgement calls

- Case = (turn, label) pair, id `<uuid>|<skill key>`. A turn with two resolved labels would give two cases; the cap is 5 per label key.
- "Session has no recorded consult run" uses consult-eval sessions plus label rows with `consult_call`; the filter changed nothing in the count.
- Gate `--arms` defaults to A0, A1, A2, T, H, S. Arm C runs automatically when 2+ decisions pass (or from `--combine FLAGS:PARTS`), and a flag decision cannot pass without `--composites` (an unrun guard fails).
- Gate always checks the freeze (labels, cases, queries sha256); `--check-freeze` is accepted but redundant.
- Prompts are stripped of injected skill/rule blocks and redacted before leaving the machine.

## Unresolved questions

- Does Thinh want the leak rule left as registered (51% dropped), or narrowed (for example drop only on the label's most specific word) before phase 3 runs the gate?
- The dry count's exact rule for the missing 168th case is unrecovered.

Status: DONE_WITH_CONCERNS
