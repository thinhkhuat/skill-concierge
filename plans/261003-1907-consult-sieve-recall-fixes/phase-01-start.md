---
title: "Phase 1: Sieve recall instrument, frozen case set and query generation"
status: todo
---

# Phase 1: Sieve recall instrument, frozen case set and query generation

<!-- Updated: Red Team + Validation Session 1 - rewritten for F2, F3, F5, F6, F7, F8, F9, F11, F12, F13, F14 -->

## Goal

Build the measuring tool and freeze the evaluation before any fix is judged. That means four things: a held-out case set with exactly resolved labels; recorded queries for today's doctrine and for each new doctrine part; the pass rules; and a harness that runs the repo's own engine under a locked index.

## Context (re-checked 2026-10-04)

- **Real consult runs.** `~/.claude/skill-concierge/jev-calibration/consult-eval.jsonl` holds 13 rows. Rows from sessions `129c86f2` and `79d00f5d` are one consult: both transcripts carry `tool_use` id `toolu_014DbZSAxfoPtAr6QdVt17dt` with the same record uuid. So there are 12 unique runs. The rows store task, queries, rows and primary but no call id (`scripts/consult_fit.py:237-238`), so this phase dedupes on (task, queries) and leaves `consult_fit.py` alone.
- **Baseline today.** I replayed the 13 recorded query sets through `server.consult_candidates(queries, 20)` in-process from `~`. Result: 2 hits; externals 6 to 17 of 20 rows (mean 11.5); p50 42 ms after a 215 ms warm-up call.
- **Labelled source.** `real-turn-labels.jsonl` has 3,036 rows, written 2026-09-26 by `scripts/extract_turn_labels.py`. The positive rule is `calibrate_jev_gate.is_positive` (`scripts/calibrate_jev_gate.py:177-182`); 431 rows pass it. Labels come from `final_names`. `gold()` (`:185-186`) cuts names to the part after the last `:` and is not used (F5). The field `ledger_offered` is a list of `[name, score]` pairs (sample read 2026-10-04).
- **Name collisions.** I scrolled all 2,902 `kind=base` points. 131 short names (the part after the last `:`) are shared by two or more points, and 84 of those are shared across installed and external. The enforcer's `_skill_key` (`hooks/scripts/enforcer.py:1626-1628`: strip, drop a leading `/`, cut at a space, `:` to `-`, lower-case) gives no collisions among full indexed names.
- **Dry count under the final rules below** (2026-10-04, read-only):
  - Label resolution: 257 exact, 2 by full key, 8 by a unique installed short name, 47 not indexed. 48 more were dropped because they are named in the prompt.
  - Cases: 205 eligible, 167 after the cap; 82 labels; 105 sessions.
  - Router groups: 103 not offered (74 sessions), 61 offered, 3 unknown.
  - 156 English by `_is_english`; 83 composite pairs.
  - This count exposed the held-out label mix before freezing. It is disclosed, and since nothing is tuned, it cannot shape a choice (F14).
- **Reusable code (re-grepped):**
  - From `scripts/precision_eval.py`:
    - it puts the repo engine first on the path (`sys.path.insert(0, str(ROOT / "vendor" / "skill-search"))`, `:52`);
    - `META_SKILLS` (`:69`);
    - `sign_test_p(lost, gained)` (`:240-252`, P(X <= lost) under Binomial(n, 0.5); it returns 0.0 when n = 0, so the harness treats n = 0 as p = 1);
    - `gains_losses` (`:267-271`), `lost_gained_cases` (`:274-279`);
    - `_load_module` (`:327`) and `_server_for(engine_root)` (`:344-356`), which load `server.py` from a given repo root.
  - From `scripts/calibrate_jev_gate.py`: `load_corpus` (`:201`), `is_positive` (`:177`), `load_enforcer` (`:90`).
  - From the enforcer: `_jev_redact` (`:1566`), `_is_english` (`:1621`), `_skill_key` (`:1626`).
  - From `scripts/flywheel_llm.py`: `chat(system, user, rate_s=6.0, timeout=120, schema=None)` (`:123`; temperature 0.4 at `:146`) and `parse_json_reply` (`:113`).
  - From `scripts/engine_env.py`: `engine_env()` (`:39`).
- **Why the repo engine must be loaded explicitly.** The stable venv at `~/.claude/skill-concierge/venv` holds a copied engine that stays stale by design until the release redeploys it (see `bin/skill-search-mcp:55-116`). A plain `from skill_search import server` under that venv could load the old copy, which has no new flags.
- **Gateway:** `https://api.thinhkhuat.com/v1/chat/completions`, model `cmc/deepseek/deepseek-v4.1-flash` (`~/.config/harness-env.sh:29, 33`). Thinh allowed redacted prompts to go there (D2).

## Files to Create / Modify

| File | Action | Owner |
|---|---|---|
| `scripts/sieve_recall.py` | Create | Phase 1 |
| `tests/test_sieve_recall.py` | Create | Phase 1 |

Private outputs live in `~/.claude/skill-concierge/jev-calibration/`, never in the repo. The directory is mode 700 and the files mode 600: `sieve-eval-cases.jsonl`, `sieve-eval-queries.jsonl`, `sieve-eval-queries.lock`, `sieve-eval-manifest.json`.

This phase runs in parallel with phase 2. Its one engine-touching step, the A0 smoke run, happens before phase 2 starts editing `server.py` or after phase 2 finishes.

## Requirements

### R1. Engine loading (F3)

`sieve_recall.py` sets up the engine in this order:
1. `os.environ.update(engine_env())`, then `os.chdir(Path.home())`.
2. Import `precision_eval` as `PE`, which puts `ROOT/vendor/skill-search` first on `sys.path`.
3. Load the server with `srv = PE._server_for(ROOT)`.
4. Before any arm runs, assert that `Path(srv.__file__).resolve()` is under `ROOT`.
5. For each arm that needs a flag, assert `hasattr(srv, "_consult_slots_on")` or `hasattr(srv, "_consult_rrf_on")`.

Any failed assert aborts the run with a message that names the loaded path.

### R2. Cases (pre-registered; changing a rule after the freeze voids the gate)

From `real-turn-labels.jsonl` as it stands (sha256 recorded):

1. `is_positive(r)` holds, `prompt_words >= 8`, and the session has no recorded consult run.
2. **Label resolution (F5).** Each `final_names` entry resolves to one indexed base name. The rules are tried in order:
   - an exact name match;
   - else a unique match on the full `_skill_key`;
   - else, only for a label with no namespace, a unique installed point with that short name.
   
   Ambiguous and missing labels are dropped. Both kinds are listed in the manifest, together with the full collision list (short names shared by 2+ points).
3. Labels in `precision_eval.META_SKILLS` are dropped.
4. A label is dropped when its full `_skill_key` occurs in the lower-cased prompt (`:` read as `-`) as a whole token: not preceded or followed by a word character or `-`.
5. Cases are ordered by `sha256(SEED + ":" + uuid)`; at most 5 cases per label are kept. `SEED = "sieve-recall-261004"`.
6. **Router group (F6).** A case is `offered` when its label's `_skill_key` is among the `_skill_key`s of `ledger_offered` names, `not_offered` when it is not, and `unknown` when `ledger_offered` is null.
7. **Process-skill group (F14):** labels `ak-cook`, `ak-plan`, `tk-research`, `session-handoff`, `compound-to-skill`. These are the process skills the debugger report named. The group is reported on its own and never gates.
8. **Composite cases (F7).** Cases are ordered by `sha256(SEED + ":pair:" + uuid)`. Each case is paired with the next unused case from a different session that has a different label. A case is used in at most one pair. A composite's queries are the first two `d0` queries of each component, so 4 queries. Each label is scored on its own.
9. All cases are held-out (F2). The 12 real consult runs are not cases; they serve only R6.

### R3. The metric

- A label is a hit at K when its resolved name's full `_skill_key` equals the `_skill_key` of one of the first K rows `consult_candidates(queries, top_n=K)` returns, after the blocklist filter. There is no short-name matching (F5).
- `recall@K` is hits divided by n. K = 20 gates; K = 40 is reported.

### R4. Queries: recorded once (F8, F13)

The doctrine texts are constants in `sieve_recall.py` and are fixed now:

- `DOCTRINE_TODAY`, copied verbatim from `skills/consult/SKILL.md:26-28` and `:39`: "Restate the task and split it into 2-5 sub-goals (label them A, B, C…). A niche skill that serves only one sub-goal must still surface — that is why the sieve takes one query per sub-goal, not one blended query." and "Phrase each query by INTENT + DOMAIN TERMS, away from the skill names you expect."
- `PART_TASK`: "Put the user's own words first: one query that copies the sentence where the user states the task, verbatim, up to about 300 characters."
- `PART_HOW`: "Add one query that says how the work will be carried out (the working method or process), with no domain terms; place it before the sub-goal queries."
- `PART_SPLIT`: "Each sub-goal is one action on one object; never join two actions in one query."
- `CAP_NOTE` ships with `PART_TASK` or `PART_HOW`. It states server behaviour (`server.py:1297`) and is not a tested part: "The sieve keeps only the first five queries, so the extra queries above push out the last sub-goal queries."

Generation calls, each through `flywheel_llm.chat`. The model receives `_jev_redact(prompt)` with whitespace collapsed, capped at 4,000 characters, and never the labels:

| Part | System text | Reply | Calls |
|---|---|---|---|
| `d0` | `DOCTRINE_TODAY` | `{"queries": [...]}` | 167 |
| `how` | `PART_HOW` | `{"query": "..."}` | 167 |
| `split` | `DOCTRINE_TODAY` + `PART_SPLIT` | `{"queries": [...]}` | 167 |
| `d0` (fidelity) | `DOCTRINE_TODAY` | `{"queries": [...]}` | 12 real runs |

That is 513 calls on `cmc/deepseek/deepseek-v4.1-flash`, serial at `rate_s=6.0`, about 51 minutes. Jev is never called.

Rules for the generation run:
- **Mechanical task sentence:** `_jev_redact(prompt)`, whitespace collapsed, first 300 characters. No model call.
- **Write as you go:** each record is appended as soon as its call completes, then flushed and fsync'd. A record holds the key (case id, part, doctrine sha256), model, temperature (0.4) and the raw reply.
- **Resume:** a rerun skips keys already written.
- **Retries:** failed keys are retried only with `--retry-failed`, and only before the freeze.
- **Lock:** `sieve-eval-queries.lock` is created with `O_EXCL` and holds the pid. A live lock makes a second run exit non-zero. A lock whose pid is dead is replaced.
- **Freeze:** `queries --freeze` writes the file's sha256 and the per-part call and failure counts into the manifest. After that, `queries` exits non-zero.
- **Leak check (F6):** a case is dropped from every arm when any generated query contains, as a whole word, any word of length 4 or more from its label's key (split on `-` and `:`). The count is printed.
- **Missing queries:** a case without queries for an arm's parts leaves that decision. If more than 10% of a decision's primary set lacks queries, that decision is INSUFFICIENT.

### R5. Arms and gate rules (F8, F9, F10)

| Arm | Queries | `SKILL_CONSULT_SLOTS` | `SKILL_CONSULT_RRF` |
|---|---|---|---|
| A0 | `d0` (<= 5) | 0 | 0 |
| A1 | `d0` | 1 | 0 |
| A2 | `d0` | 0 | 1 |
| T | task sentence + `d0`, first 5 | 0 | 0 |
| H | `how` + `d0`, first 5 | 0 | 0 |
| S | `split` (<= 5) | 0 | 0 |
| C | the shipping combination (R5, combination rule) | passing flags | passing flags |

On composites, A0, A1 and A2 run with the composite queries. Flags are set in `os.environ` before each call, because they are read per call. Arms run in a rotating order per case, and one warm-up call is discarded.

Decisions, primary set and comparison, each against A0 at top_n 20:

| Decision | Primary set | Extra non-inferiority guard |
|---|---|---|
| slots (A1) | all cases | composites, per label |
| rrf (A2) | all cases | composites, per label |
| task (T) | `not_offered` cases | `offered` cases |
| how (H) | all cases | none |
| split (S) | all cases | none |

Gate rules for each decision on its primary set:

- **G1** n >= 30 cases with queries in both arms. Otherwise `INSUFFICIENT`.
- **G2** recall@20 gain >= 5.0 points.
- **G3** losses <= 20% of gains. Every lost case is printed with its label, using `PE.lost_gained_cases`.
- **G4** session-level sign test. Each session's net is its gains minus its losses (`PE.gains_losses`). Sessions with net > 0 count as gained and net < 0 as lost. p = `PE.sign_test_p(lost_sessions, gained_sessions)`. Holm correction across all five decisions (m = 5, fixed even when one is INSUFFICIENT), at alpha 0.05.
- **G5** median external rows per response >= 4, and mean external share <= A0 share + 10 points.
- **G6** p90 latency <= A0 p90 + 100 ms.
- **Non-inferiority guard:** paired bootstrap 95% CI of the recall@20 difference (arm − A0) on the guard set; lower bound >= −5.0 points. 2,000 resamples, seeded with `SEED`. Resampling units are sessions for single cases and pairs for composites.

The doctrine decisions (task, how, split) print `VERDICT: … (proxy)`.

**Combination rule (F10).** When two or more decisions pass, phase 3 builds the configuration that would ship and runs it once as arm C against A0 on all cases:
- **Flags:** the passing flags.
- **Queries:** the passing doctrine parts, in order task sentence, then `how`, then (`split` if it passed, else `d0`), cut to 5.

C must pass G2, G3, G5 and G6, plus the session sign test at 0.05 with no Holm (it confirms, it does not search). If C includes a flag, it must also meet the composite guard. If C fails, only the single passing decision with the smallest Holm-adjusted p ships; a tie goes to the larger gain.

**Reported, never gating:** recall@40; the English-only stratum; the process-skill group; the `unknown` router group; session counts.

### R6. Fidelity of generated queries (F14)

For each of the 12 real runs, deduped on (task, queries):
- the rank of the resolved chosen skill under the real recorded queries, and under the generated `d0` queries;
- both at top_n 40, with ">40" scored as 41, and both flags off.

The report gives a paired table, the median absolute rank difference, and how many runs have both ranks <= 20 or both > 20. This is a continuous measure, not a gate. It says how far the "proxy" label should discount the doctrine verdicts.

### R7. Index lock (F12)

At gate start and at gate end, the harness records:
- `points_count` from `GET /collections/claude_skills`;
- the count and sha256 of the sorted names of all `kind=base` points (from a scroll).

The gate aborts unless start equals end. It also prints the difference between the build-time name set and the gate-start name set, and drops cases whose resolved label is no longer indexed (count printed).

## Implementation Steps

1. Write the pure functions:
   - eligibility and label resolution;
   - router group and composites;
   - task sentence and leak check;
   - the hit test;
   - G1-G6, Holm, session sign test and bootstrap.
   
   Write the tests below alongside them.
   Check: `python3 -m pytest tests/test_sieve_recall.py -q` passes.
2. Add the subcommands:
   - `build`;
   - `queries [--retry-failed] [--freeze]`;
   - `gate [--arms LIST] [--composites] [--combine FLAGS,PARTS] [--check-freeze]`.
   
   Engine and gateway imports are lazy, so the tests never need them.
   Check: `python3 scripts/sieve_recall.py --help` lists the three subcommands.
3. Run `build`.
   Check: it prints `cases 167`, groups `not_offered 103 / offered 61 / unknown 3`, `composites 83` and the collision count. Any difference is explained in the manifest by the index lines (labels newly missing or added).
4. Run `queries` in the background with output to a log, and watch the log. When it completes, run `queries --retry-failed`, then `queries --freeze`.
   Check: the manifest holds the sha256, model, temperature, per-part call and failure counts, and the leak-drop count. A second `queries` exits non-zero with "frozen".
5. Run the smoke test `gate --arms A0` (timed per R1/R7, with phase 2 not mid-edit).
   Check: it prints the index-lock lines and an A0 recall@20. The fidelity table prints the real-query ranks; for runs that were hits, the rank is <= 20.

## Tests

`tests/test_sieve_recall.py`. Each test checks behaviour and fails without the code:

- `test_label_resolves_to_the_exact_indexed_name` — `ak:plan` resolves to `ak-plan` by full key. A bare short name held by two installed points is dropped and listed.
- `test_hit_uses_the_full_skill_key_never_the_short_name` — label `ak-plan` hits row `ak:plan`. Label `x:review` does not hit row `review`.
- `test_label_named_in_prompt_as_a_whole_token_is_dropped` — "run session-handoff now" drops `session-handoff`. "my-session-handoffs" does not.
- `test_leak_check_drops_cases_on_label_words_of_four_letters_or_more` — a query containing "handoff" drops a `session-handoff` case. "git" does not drop an `ak-git` case.
- `test_router_group_reads_name_score_pairs` — `[["ak-plan", 0.6]]` makes an `ak:plan` label `offered`. `null` makes it `unknown`.
- `test_composites_pair_distinct_sessions_and_labels_once` — no case appears twice, and no pair shares a session or a label.
- `test_forked_consults_count_once` — two rows with equal (task, queries) give one fidelity run.
- `test_generator_never_receives_labels` — with the gateway faked, no request body contains a label string.
- `test_generation_appends_resumes_locks_and_freezes` — a crash after 2 of 3 calls, then a rerun, makes exactly 1 more call. A live lock makes a second run exit non-zero. After `--freeze`, `queries` exits non-zero.
- `test_gate_rules` — n 29 gives INSUFFICIENT. A 4.9-point gain fails G2. 5 losses for 20 gains fails G3, while 4 passes. A median of 3 external rows fails G5. p90 + 101 ms fails G6.
- `test_holm_adjustment` — p values (0.004, 0.02, 0.03, 0.2, 0.5) pass only the first at alpha 0.05 with m = 5.
- `test_sign_test_counts_sessions_not_cases` — 5 gained cases in one session plus 1 lost case in another give gained 1, lost 1; no discordant session gives p = 1, not the 0.0 `sign_test_p` returns.
- `test_bootstrap_lower_bound_is_seeded_and_paired` — the same seed gives the same bound. A constant −6-point difference gives a bound below −5.
- `test_index_lock_aborts_when_the_name_set_changes`.
- `test_engine_outside_repo_is_refused` — a server module whose path is outside ROOT, or that lacks the flag reader an arm needs, aborts before any call.

## Verification

```bash
cd /Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge
python3 -m pytest tests/test_sieve_recall.py -q
~/.claude/skill-concierge/venv/bin/python3 scripts/sieve_recall.py build
~/.claude/skill-concierge/venv/bin/python3 scripts/sieve_recall.py queries > ~/.claude/skill-concierge/jev-calibration/sieve-queries-run.log 2>&1   # background; watch the log
~/.claude/skill-concierge/venv/bin/python3 scripts/sieve_recall.py queries --freeze
~/.claude/skill-concierge/venv/bin/python3 scripts/sieve_recall.py gate --arms A0
```

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| The gateway is slow or down (`flywheel_llm` notes 2-10 s or 60-95 s latency on the same call) | Medium | Medium | Append-and-resume; retries before the freeze; > 10% missing in a decision makes it INSUFFICIENT |
| The widened leak check removes many cases with common label words (for example "plan" for `ak-plan`) | Medium | Medium | Counts printed per label; G1 protects against a set too small to judge |
| `real-turn-labels.jsonl` is regenerated by router work mid-plan | Low | High | Its sha256 is in the manifest; `gate` refuses on a mismatch |
| `precision_eval` import side effects | Low | Low | Its module level only sets paths and constants, and imports `skill_search.ports` (`:52-53`) |

## Rollback

`scripts/sieve_recall.py`, its test and the private files are standalone; nothing else reads them. Archive the private files to `~/_ARCHIVE/` rather than deleting them.
