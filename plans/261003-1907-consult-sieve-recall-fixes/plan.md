---
title: "Consult sieve recall: installed slots, rank fusion, query formation, and a pre-registered gate"
description: "Measure consult sieve recall@20 on 167 frozen real-turn cases, then gate two default-OFF engine flags and three consult doctrine parts; a passing fix is turned on in the same run."
status: completed
priority: P1
effort: 17h
tags: [consult, sieve, recall, rrf, evaluation, pre-registration, vendored-engine]
created: 2026-10-03
---

# Consult sieve recall fixes

## Overview

The consult sieve (`consult_candidates`) missed the skill the agent finally chose in 10 of 12 unique real consult runs (`plans/reports/debugger-261004-0155-consult-sieve-recall-misses.md`). I re-ran the 13 recorded runs (12 unique) through today's engine, in-process, from `~`: 2 hits, 11 misses, externals averaging 11.5 of 20 rows, p50 42 ms. The report found three causes, and they stack:

- Raw-score MAX fusion lets one generic query take most of the slots.
- The external catalogue crowds installed skills out. It holds 1,994 of the 2,902 base points (verified by a count query).
- The agent's queries describe the domain but never the working process.

<!-- Updated: Red Team + Validation Session 1 - merged to 3 phases, no tuning, flip on pass (D3), release only if a default flips -->
This plan has three phases:

1. **Instrument and frozen case set.** Phase 1 builds the measuring tool and freezes the evaluation before any fix is judged:
   - 167 held-out cases from real turns;
   - label names resolved to exact indexed names;
   - recorded query generation through Thinh's gateway;
   - pass rules fixed in advance.
2. **Two engine flags, both default OFF and read per call.** `SKILL_CONSULT_SLOTS` gives installed skills reserved slots, with externals in their own block. `SKILL_CONSULT_RRF` orders the consult sieve by reciprocal-rank fusion (RRF). Their parameters are fixed now: installed share 0.7 and RRF k = 60. Nothing is tuned.
3. **One held-out gate run, then apply.**
   - A fix whose gate passes gets its flag turned on by default in the same run, without asking again (Thinh's D3). It stays revertible with one variable.
   - SKILL.md gets only the doctrine parts that passed.
   - The two flags are documented either way.
   - Version 0.58.0 and ADR-0078 ship only if at least one default flips.

Commit and push wait for Thinh's order.

## Goals

| # | Goal | Priority |
|---|------|----------|
| 1 | A reproducible sieve-recall instrument and a frozen held-out set with n >= 30 in every primary group | P1 |
| 2 | Installed skills keep reserved slots in the consult sieve, behind `SKILL_CONSULT_SLOTS` (default OFF) | P1 |
| 3 | Rank-based fusion in the consult path only, behind `SKILL_CONSULT_RRF` (default OFF); `search_skills`, `_fuse_ranked` and the router untouched | P1 |
| 4 | Each consult doctrine part (task sentence, process query, one sub-goal per query) tested on its own | P1 |
| 5 | One held-out gate run with pre-registered rules; passing fixes applied; release only if a default flips | P1 |

## Phases

<!-- Updated: Red Team + Validation Session 1 - 5 phases merged into 3; effort re-totalled 19h -> 17h -->
| # | Phase | Effort | Status |
|---|-------|--------|--------|
| 1 | [Sieve recall instrument, frozen case set and query generation](./phase-01-start.md) | 8h | Pending |
| 2 | [Consult engine flags: installed slots and rank fusion](./phase-02-consult-engine-flags.md) | 4h | Pending |
| 3 | [Held-out gate run and apply](./phase-03-gate-run-and-apply.md) | 5h | Pending |

Total: 8 + 4 + 5 = 17h. Phase 1 includes about 51 minutes of unattended gateway calls.

## Dependencies

```
phase 1 ──┐
          ├──> phase 3
phase 2 ──┘
```

- Phases 1 and 2 run in parallel. Their files are disjoint, and phase 2 needs no data from phase 1 now that nothing is tuned.
- One runtime rule applies while both run. Phase 1's harness imports the repo's `server.py`, so its baseline smoke run (A0) happens either before phase 2 starts editing that file or after phase 2 finishes.
- Phase 3 needs both: the frozen manifest from phase 1, and both flags implemented with their tests passing from phase 2.

**File ownership:**

| Phase | Owns |
|---|---|
| 1 | `scripts/sieve_recall.py` (new), `tests/test_sieve_recall.py` (new) |
| 2 | `vendor/skill-search/skill_search/server.py`, `vendor/skill-search/tests/test_consult_slots.py` (new), `vendor/skill-search/tests/test_consult_rrf.py` (new), `vendor/skill-search/VENDORED.md` |
| 3 | `skills/consult/SKILL.md` (only passing doctrine parts), `tests/test_consult_doctrine.py` (new, only if a doctrine part ships), `AGENTS.md`, `CLAUDE.md`, `README.md`; the flag default lines in `server.py` (after phase 2, only on a pass); if a default flips: `docs/adr/0078-*.md`, `docs/adr/README.md`, `docs/epoch-watch.md`, `CHANGELOG.md`, `openwiki/quickstart.md`, the four manifests; `plans/261003-1907-consult-sieve-recall-fixes/reports/phase-03-*` |

<!-- Updated: Red Team + Validation Session 1 - consult_fit.py no longer edited (dedupe moves into sieve_recall, F11) -->
`scripts/consult_fit.py` is not edited. The forked-transcript dedupe happens inside `sieve_recall.py`.

## Data flow

<!-- Updated: Red Team + Validation Session 1 - data flow reflects F2, F3, F5, F6, F7, F12, F13 -->
| Component | In | Transform | Out |
|---|---|---|---|
| `sieve_recall.py build` | `real-turn-labels.jsonl` (frozen; sha256 recorded); the live index's base names (read-only scroll) | eligibility, exact label resolution, router-offered grouping, cap of 5 per label, composite pairs | `sieve-eval-cases.jsonl` + `sieve-eval-manifest.json`, private dir, mode 600 |
| `sieve_recall.py queries` | redacted task text only, never labels | one gateway call per case per part through `flywheel_llm.chat`; append per record; resume; lock | `sieve-eval-queries.jsonl`, frozen by sha256 |
| `consult_candidates` (phase 2) | queries, `top_n`, two flags read per call | MAX or RRF order; mixed list or installed slots + external block | `results` rows (shape unchanged) + `blocks` when slots are on |
| `sieve_recall.py gate` | frozen cases and queries; the repo engine loaded through `precision_eval._server_for(ROOT)` | index lock; arms interleaved per case; gate rules, Holm, bootstrap | `VERDICT:` lines (doctrine lines marked "proxy"), lost cases, fidelity table |

## Non-goals

- The per-turn router (`hooks/scripts/enforcer.py` offer path and Jev router), `search_skills`, `_fuse_ranked`, keep-off, the blocklist and the utterance trigger filter.
- Tuning any parameter. Installed share 0.7 and RRF k = 60 are fixed in advance.
- Changing the 5-query cap, the 40-row `top_n` cap, or the number of sub-goals the doctrine asks for.
- Epoch-watch items W37/W38 and a `real` subcommand. W34 gets an epoch boundary if a default flips (see Risks).
- New services, new dependencies, a reindex, Jev calls.
- Commit, push and the stable-venv redeploy. These wait for Thinh's order.

## Pre-registered evaluation (summary; full rules in phase 1)

<!-- Updated: Red Team + Validation Session 1 - rules rewritten per F2, F5-F10, F14 -->
**Cases.** All mined cases are held-out; there is no dev split. The dry count under the final rules (2026-10-04) found:
- 205 eligible turns, 167 after the per-label cap;
- 82 labels and 105 sessions;
- router groups: 103 cases not offered (74 sessions), 61 offered, 3 unknown;
- 83 composite pairs.

The 12 real consult runs are not in the gate. The debugger report studied them, so they serve only the fidelity measure.

**Hit.** A case is a hit at 20 when its resolved label's full `_skill_key` (`hooks/scripts/enforcer.py:1626-1628`) equals that of a row among the first 20. Composite cases score each label separately.

**Arms.** A0 is today's doctrine queries with both flags off. Against it:
- A1: slots on;
- A2: RRF on;
- T: the task sentence added in front;
- H: a process query added in front;
- S: the one-sub-goal-per-query rewrite.

**Gate per decision** (each against A0):
- G1: n >= 30, otherwise INSUFFICIENT.
- G2: recall@20 gain >= 5.0 points.
- G3: losses <= 20% of gains, every loss listed by name.
- G4: a session-level sign test, Holm-adjusted across the five decisions at 0.05.
- G5: externals keep a median of at least 4 rows, and their share rises by no more than 10 points.
- G6: p90 latency rises by no more than 100 ms.

**Extra rules for particular decisions:**
- The task-sentence decision is judged on the not-offered group, because the router's offer can leak the answer. On the offered group it must not be worse: the lower bound of a paired bootstrap 95% CI must be at least −5 points.
- Slots and RRF must meet the same non-inferiority bound on composite cases.
- When more than one decision passes, the combination that would ship must also pass against A0.
- Doctrine verdicts are labelled "proxy", because model-generated queries stand in for agent-written ones.

## Success Criteria

Each item is a command output, not a judgement.

- [ ] `python3 -m pytest tests/test_sieve_recall.py -q` passes, and `python3 -m pytest tests/ -q` shows no new failures against a run recorded before phase 1.
- [ ] From `vendor/skill-search/`: `~/.claude/skill-concierge/venv/bin/python3 -m pytest tests/test_consult_slots.py tests/test_consult_rrf.py tests/test_fusion.py tests/test_search_complement.py -q` passes.
- [ ] `~/.claude/skill-concierge/venv/bin/python3 scripts/sieve_recall.py build` prints the case, group, composite and collision counts and the sha256 of every input.
- [ ] `sieve_recall.py queries --freeze` records the query file's sha256, the model, the temperature and the call count in the manifest.
- [ ] `sieve_recall.py gate` prints the index-lock line twice (start and end, identical), one `VERDICT: PASS|FAIL|INSUFFICIENT` line per decision (doctrine lines marked `proxy`), a `COMBINED:` line when more than one passes, and the fidelity table.
- [ ] After apply: `grep -n 'os.environ.get("SKILL_CONSULT_' vendor/skill-search/skill_search/server.py` shows default `"1"` exactly for the flags that passed.
- [ ] `python3 scripts/driftcheck.py driftcheck.json` exits 0.

## Risks

<!-- Updated: Red Team + Validation Session 1 - risks revised for F4, F5, F6, F7, F12, F14 -->
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Labels are a proxy: the skill the agent used, not the best skill | High | Medium | Every arm is scored on the same labels, so arm comparisons stay fair; stated on every verdict line |
| The router's offer leaks the answer into the prompt-based arms (the red team measured prompt-only recall 79% offered vs 16% not offered) | High | High | The task-sentence decision is gated on the not-offered group; offered group must be non-inferior |
| Short-name collisions mislabel hits (131 short names shared by 2+ base points, 84 of them across installed and external; counted 2026-10-04) | High | High | Exact resolution at build time; full-key matching; ambiguous labels dropped and listed |
| RRF hurts a niche skill that only one sub-goal serves | Medium | High | Composite cases with per-label recall; non-inferiority bound; the debugger's RRF evidence was installed-only, while arm A2 runs over both tiers |
| Generated queries differ from agent-written ones | High | Medium | Fidelity table on the 12 real runs; doctrine verdicts labelled "proxy" |
| The held-out label mix was seen in the dry count | Certain | Low | Disclosed; no parameter is tuned, so the exposure cannot shape a choice |
| A reindex or findability sweep rewrites the live index mid-gate | Medium | High | Index lock: point count + name-set hash at start and end; abort on change |
| Private prompt content leaves the machine (names, emails and client text are not removed) | Certain | Medium | Accepted by Thinh (D2); secret shapes are redacted |
| `doctor --fix` or `setup.sh` during implementation copies a half-built engine into the shared venv | Medium | High | Forbidden until release (Rollback section) |
| A default flip changes the sieve order that W34's baseline in `consult_fit.py` measures (`"b": [c["name"] for c in inp["candidates"]]`, `scripts/consult_fit.py:309`) | Certain if a flip | Medium | The 0.58.0 epoch-watch section names the flip time as W34's epoch boundary |

## Rollback and deployment

<!-- Updated: Red Team + Validation Session 1 - deployment truth (F4) -->
**How a flag change reaches a running server.** Both flags are read per call from the server process's environment. But a running stdio MCP server's environment is fixed when the harness spawns it. So changing a flag on a live machine takes two steps for each harness: edit the env source that harness passes to the server (for Claude Code, the `env` block of `.mcp.json`), then restart that harness's MCP server.

**How a code default reaches the live engine.** All harnesses share one engine copy in `~/.claude/skill-concierge/venv`. `bin/skill-search-mcp:55-116` resyncs that copy in the background when the plugin's version is newer than the venv's stamp. The spawn that triggers the resync still serves the old engine, and the next spawn serves the new one. So the first harness to start on the new version redeploys the engine for every harness.

**During implementation.** Doctor's "Engine freshness" row will WARN (`scripts/doctor.py:470-495`), because the repo's vendored source differs from the venv copy. That is expected. Do not run `doctor --fix` or `./setup.sh` until release. The fix that row offers is `setup`, and `setup.sh:113` force-reinstalls the repo's engine into the shared venv, which would deploy a half-built engine to every harness.

**Rollback.**
- A flipped default: set the variable to `0` in each harness's MCP env and restart that server. Or revert the default line in a release.
- Code: revert phase 2's flag branches, `_rrf_order` and the `VENDORED.md` entries. `_fuse_ranked` is never edited.
- SKILL.md: remove the shipped doctrine lines and delete `tests/test_consult_doctrine.py`.
- Phase 1's script and private files are standalone; archive them to `~/_ARCHIVE/`.

## Validation Log

<!-- Updated: Red Team + Validation Session 1 - Validation Log added -->
### Session 1 (2026-10-04)

| # | Question | Thinh's answer (verbatim where quoted) | Effect on the plan |
|---|---|---|---|
| D1 | Which red-team changes to apply? | "Apply all 14" | All 14 applied (table below) |
| D2 | May past typed prompts go to the gateway to generate test queries? | "Allow, secrets redacted". About 185 past typed prompts may go to the gateway (api.thinhkhuat.com, upstream currently DeepSeek via CommandCode). Secret shapes are removed by the enforcer's `_jev_typed_user_text`/`_jev_redact`. Names, emails and client content are NOT removed; he was told this explicitly | Phase 1 generation runs on redacted text. The final rules need 167 cases × 3 parts + 12 fidelity calls ≈ 513 calls over 167 distinct prompts plus the 12 real runs' prompts, within the ~185 prompts covered |
| D3 | On a pass? | "Flip on pass". A fix whose pre-registered gate passes gets its flag turned ON by default in the same run, without asking again (still one-var revertible). Commit/push still only on his order | Phase 3 flips the passing flags (only those the combined gate supports) and stops before commit |

Superseded open questions from the first draft: Q1 is answered by D2 and Q5 by D3. Q2 is decided: one `results` list, installed block first, plus `blocks`. Q3 is decided: the 5-query cap stays and the sub-goal count is not changed (F8). Q4 is decided: mined turns only, all held-out (F2).

## Red Team Review

<!-- Updated: Red Team + Validation Session 1 - findings table added -->
### Session 1 findings (three Opus reviews)

| # | Severity | Title | Phase | Disposition |
|---|---|---|---|---|
| F1 | High | Scope creep: W37/W38, `real`, `ts`, prose tests; release always; 5 phases | plan, all | Accept: merged to 3 phases, release only if a default flips |
| F2 | High | Tuning on 66 dev cases overfits and wastes data | 1, 2 | Accept: share 0.7 and k 60 pre-registered; all cases held-out |
| F3 | Critical | Harness would import the stale venv engine, not the repo | 1 | Accept: `precision_eval._server_for(ROOT)` plus path and flag-reader asserts |
| F4 | High | Rollback text wrong about live flag changes and deploy path | plan, 3 | Accept |
| F5 | Critical | Short-name label matching mislabels hits | 1 | Accept: exact resolution, full key, collisions in manifest |
| F6 | High | Router offer leaks the answer into prompt arms | 1, 3 | Accept: offered/not-offered groups; wider leak check |
| F7 | High | RRF can hurt niche single-sub-goal skills; no test for it | 1, 3 | Accept: composite cases with non-inferiority |
| F8 | High | Doctrine parts confounded; sub-goal count changed; 2-point margin arbitrary | 1, 3 | Accept: per-part tests; count unchanged; bootstrap bound −5 |
| F9 | High | Multiple comparisons; correlated cases; absolute loss cap | 1 | Accept: Holm, session-level sign test, losses <= 20% of gains |
| F10 | High | Combined configuration never gated | 3 | Accept |
| F11 | Medium | Rewrites helpers that exist; edits `_fuse_ranked` and `consult_fit.py` | 1, 2 | Accept, with two documented deviations (see sweep) |
| F12 | High | Live index can change during the gate | 1 | Accept: index lock |
| F13 | Medium | Query generation not resumable or locked; spend unnamed | 1 | Accept |
| F14 | Medium | Proxy limits undisclosed; no fidelity measure; process skills hidden | 1, 3 | Accept |

### Whole-plan consistency sweep

I searched all three phase files and this file for the following stale items: dev split, `tune`, `real`, W37, W38, `ts`, phases 4 and 5, the 2-point margin, `gold()` short names, "dev 66 / held-out 107", and `_fuse_ranked` edits. Every hit was removed or rewritten.

Two deviations from the red-team wording, made on evidence:

1. **`_cd_pairs` (`scripts/precision_eval.py:381`) is not reused as-is.** It returns `gold()` short names (`scripts/calibrate_jev_gate.py:185-186`), which F5 forbids, and it drops the session id, which the session-level sign test (F9) needs. Phase 1 reuses what `_cd_pairs` itself uses: `calibrate_jev_gate.load_corpus` and `is_positive`, plus `precision_eval.META_SKILLS` (`:69`).
2. **`_arrange_tiers` (`server.py:953-975`) is not used for slots.** It interleaves the two tiers by a 0.08 score margin. Thinh ordered reserved installed slots with externals in a separate block, and `_arrange_tiers` would put externals back among installed rows. Phase 2 reuses the complement split itself, meaning the two filtered queries per vector as in `search_skills` (`server.py:1241-1254`), but not the margin merge.

Remaining open edges:

1. If no default flips, the engine flags and any SKILL.md doctrine part that passed sit in the repo without a version bump or CHANGELOG entry until the next release. This follows F1; driftcheck stays green because no version line changes.
2. Composite cases use the first two D0 queries of each component turn. That is a fixed rule, not a model of how an agent would split a two-part task.

## Unresolved Questions

1. **Can a SKILL.md doctrine part ship when no engine default flips?** F1 says to release only if a default flips. A doctrine part that passes would then sit in the repo unreleased. Recommendation: treat a passing doctrine part as a reason to release too, because it changes agent behaviour the same way a flag does. As written, the plan follows F1 literally.
   **Resolved (AFK decision, 2026-10-04 02:45, `plans/reports/afk-decisions-261004-0245-consult-sieve-recall.md` #1):** a passing doctrine part also triggers the release.
