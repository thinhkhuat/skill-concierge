# ADR-0076: Jev typed questions beyond the router — consult fit matrix, utterance filter, rerank history

- **Status:** Accepted (2026-10-04, owner's order, plan `plans/261003-1601-jev-fit-matrix-trigger-filter-router-history/`). Shipped as 0.57.0. Of the three features, only the consult matrix is live; the utterance filter is inert and the router history is OFF (see Decision and Evidence).
- **Extends:** ADR-0061 (Jev router), ADR-0075 (Jev bench), ADR-0049 (consult).

## Context

The fast-jev-compaction plugin (MIT, commit `e3f262a7f4d4`) rests on one idea: do not ask a model to write text. Ask Jev many small typed questions in one request (`noul` = P(yes), `choice` = pick one), take the numbers back, and let plain code decide. On any failure, fall back to the old path.

The per-turn router already works this way (ADR-0061, ADR-0075). This ADR applies the idea in three more places, in the order the owner set: the consult fit matrix and the utterance filter first, the router history last and OFF unless a replay proves it. Credit and licence: see Credit below and `THIRD_PARTY_NOTICES`.

## Decision

1. **Shared client.** `scripts/jev_client.py` is the one way offline scripts ask Jev. It loads the enforcer's own `_jev_call`, so host pinning, key routing and model checks stay the hook's. It splits questions under Jev's two limits (64k tokens per request; 32k for state plus the longest question), sends batches in parallel under a process-wide cap (`JEV_CLIENT_MAX_TPS` default 30000, `JEV_CLIENT_MAX_RPS` default 20), walks the bench per batch (a fast failure moves on, a timeout ends that batch's chain), and calls Jev directly, not through the owner's relay, which drops `Retry-After` and serves the live hook. The enforcer gains `_jev_tokens` (token estimate), `_jev_typed_user_text` (the allow-list for transcript user records) and `_jev_redact` (secret shapes).
2. **Relay-timeout fix.** The owner's relay turns an upstream timeout into HTTP 502 with body `{"error": "TimeoutError"}`. The enforcer's chain logic only recognised a raw `TimeoutError`, so a relay timeout counted as a fast failure and the turn was re-sent to the next bench tier: double billing, and a break of ADR-0075 decision 3 ("a timeout ends the chain"). `_jev_call` now maps a relay-reported timeout to `TimeoutError` (`_jev_relay_timeout`). Test `tests/test_jev_relay_timeout.py` fails without the fix (mutation-checked).
3. **Consult fit matrix — `SKILL_CONSULT_JEV`, default ON, evidence only.** `scripts/consult_fit.py` (called from `skills/consult/SKILL.md` on `--fast`) asks one `choice` per sub-goal over the candidates to rank them, one `fits` noul per candidate and sub-goal for an absolute floor (`FITS_FLOOR` 0.30, the router's), and an `avoid` noul where a capsule has `avoid_when`. Candidate text sits in a named state field, never inside a question, and steering phrases set a `suspect` marker. Jev output is evidence; the agent still composes the chain. Any failure exits non-zero and the skill falls back to inline analysis. `=0` exits 3 before any I/O. The verdict row can carry the matrix (`consult_log.py --jev`). Default ON is the owner's decision D4.
4. **Utterance filter — `SKILL_TRIGGER_JEV_FILTER`, code default on but inert.** `scripts/trigger_filter.py` scores every flywheel utterance against its own skill and its 3 nearest installed siblings (`margin = p(own) - max(p(sibling))`); code drops a phrase whose margin is under a threshold measured for the answering model. Thresholds are keyed by the exact model id Jev returned; a model with no threshold stores `pending` and keeps the phrase (D3). Dropped phrases, scores and the answering model stay in `triggers.json` under `llm_triggers.jev`. The filter runs inside `llm_triggers.run` only while the flag is not `0` AND a live thresholds file exists (`active()`); no live thresholds file exists, so the filter is inert (see Evidence). All four writers of `triggers.json` (`llm_triggers.py`, `build_triggers.py`, `doctor.py --fix`, the backfill) now hold the flywheel lock; `auto_reindex` skips while it is held; the vendored engine's `build_index` resets `_LLM_TRIG_CACHE` so a reindex re-reads the corpus (`vendor/skill-search/VENDORED.md`). `build_triggers.py` carries every existing `llm_triggers` block over instead of erasing it (test `test_build_triggers_keeps_utterance_layer`).
5. **Router history — `ENFORCER_JEV_HISTORY`, default `0`.** With `=1`, the rerank call (not the wide call) sees redacted, text-only conversation history, fitted to `ENFORCER_JEV_HISTORY_TOKENS` (default 10000) from the last `ENFORCER_JEV_HISTORY_BYTES` (default 2097152) of the transcript. Content follows D2: typed user text and assistant text blocks, secrets redacted, tool names only, never tool inputs or outputs, never command output or harness records. History is fitted in a thread alongside the wide call; the rerank waits for it at most 0.2 s. A skip given on the history state is re-asked on today's state when 0.5 s of budget remain, else the embedding path decides, so a skip only ever comes from today's state. Any history error returns to today's state. With the flag on, `recent_context` in the wide state is also redacted. Flag off: no history code path runs.

### Thinh's decisions (plan Validation Log, session 1, 2026-10-03)

Rows copied verbatim from `plans/261003-1601-jev-fit-matrix-trigger-filter-router-history/plan.md`:

| # | Question | Thinh's answer (verbatim where quoted) | Effect on the plan |
|---|---|---|---|
| D2 | What may the router history contain, and where may it go? | Text only: his typed user text and assistant text blocks, secret-shaped strings redacted, tool names allowed, never tool inputs/outputs, never bash/local-command stdout or task-notification/system-reminder records. Destinations: "#1 but do not limit where to send. every endpoint in the bench (4 at the moment, including my own gateway endpoints, as well as openrouter too - they are all valid to send over)". Covers the live hook (flag ON) and the one-time replay over past transcripts | Phase 1 adds the allow-list and redactor; phase 4 sends text-only history to every bench tier; phase 2's eval uses the same filter |
| D3 | Which endpoints may offline Jev runs use (consult matrix, backfill, calibration)? | "Full bench" | No TypeSafe-only default. Every score records its answering model; one threshold per answering model; scores from uncalibrated models are stored as pending and keep the phrase |
| D4 | Consult flag default? | "ON as evidence only" | `SKILL_CONSULT_JEV` ships default ON; the strict eval runs after shipping and feeds W34 |

## Evidence

All blocks are copied from the named files; none is retyped.

### Consult fit matrix — live `--eval`, 2026-10-03 (`logs/phase2-eval-261003.log`)

```
extracted 13 runs -> /Users/thinhkhuat/.claude/skill-concierge/jev-calibration/consult-eval.jsonl
eligible n=2 (jev failed: 0)
  choice    top-1 1/2  top-3 1/2
  max-noul  top-1 1/2  top-3 1/2
  baseline  top-1 2/2  top-3 2/2
  latency p50 436 ms  p90 521 ms
CHECK: INSUFFICIENT
Caveat: the recorded primary is a proxy label; the agent that chose it saw the sieve order (and, on the deep path, the analyst's ranking), so the baseline is favoured. Claude Code transcripts only.
exit 0
```

Eligible n=2 of 13 extracted runs, so the pre-registered check is `INSUFFICIENT`, not a pass. In 11 of 13 runs the primary the agent finally chose was not among the sieve's candidate rows (checked row by row; admitted by hand at consult step 3), so those runs are ineligible. That is a finding about the sieve, recorded as a W34 observation. The extractor was fixed before this run to unwrap the MCP `{"result": "<json>"}` shape (`_result_rows` in `scripts/consult_fit.py`; test `test_eval_reads_the_mcp_wrapped_result_shape`). The flag stays ON under D4; the eval does not gate shipping.

### Utterance filter — calibration, 2026-10-04 (`logs/phase3-calibrate-261004.log`)

```
tier ts:jev-1.13.0: 288/300 skills scored
tier gw:openrouter/typesafe/jev-1.13: 300/300 skills scored
tier gw:oc/jev-1.13-free: 248/300 skills scored
tier gw:ocz/jev-1.13-free: 77/300 skills scored
model                            lang      n  auc_sib auc_rand    thr drop@thr gate
jev-1.13-free                    en     2122    0.835    0.998  -0.10    0.096 True
jev-1.13-free                    vn     1097    0.808    0.998  -0.10    0.098 True
jev-1.13.0                       en     1885    0.827    0.998  -0.10    0.100 True
jev-1.13.0                       vn      960    0.799    0.998  -0.10    0.097 True
typesafe/jev-1.13-20260917       en     1965    0.826    0.998  -0.10    0.102 True
typesafe/jev-1.13-20260917       vn      996    0.799    0.998  -0.10    0.103 True
wrote /Users/thinhkhuat/.claude/skill-concierge/staging/261004/trigger-jev-thresholds.json
exit 0
```

All six (model, language) rows pass the calibration gate, threshold -0.10.

### Utterance filter — staging backfill, 2026-10-04 (`logs/phase3-staging-backfill-261004.log`)

```
selected 2895 skills (745 skipped: no live description)
scored 2895  skipped 745  failed(err) 0  pending skills 0  at MIN_TRIGGERS guard 39
  jev-1.13.0                       en  kept 18310  dropped 1449
  jev-1.13.0                       vn  kept 8502  dropped 676
requests 2895  est. input tokens 11545943
exit 0
```

### Utterance filter — staging findability gate, 2026-10-04 (from `reports/phase-03-implementation-report.md`, "Staging findability gate")

Control (base against base):

```
W: 174 probes  base top-3 46  candidate top-3 46  leavers 0  -> PASS
  (bar: net >= 0 AND no significant loss, i.e. loss_p > 0.1 — an earlier implementation of this harness gated on gain_p instead, which required evidence of GAIN rather than merely the absence of significant loss; both are reported below)
C [mcp]: n=390 +0/-0 net +0 loss_p=1.0 gain_p=0.0  -> PASS
C [enforcer]: n=390 +0/-0 net +0 loss_p=1.0 gain_p=0.0  -> PASS
D [mcp]: n=53 +0/-0 net +0 loss_p=1.0 gain_p=0.0  -> PASS
D [enforcer]: n=53 +0/-0 net +0 loss_p=1.0 gain_p=0.0  -> PASS
  (English rows gate the bar; Vietnamese reported separately: C=15, D=4)
N: 0/3368 violations (bar <= 1% AND <= 1/3 of the recall gains 0)  -> PASS
G (name, #1 bar): base [1, 1, 1] -> candidate [1, 1, 1]  -> PASS
G (paraphrase — reported only, never gated): candidate rank 1

PASS/FAIL by bar: W=PASS  C_mcp=PASS  C_enforcer=PASS  D_mcp=PASS  D_enforcer=PASS  N=PASS  G=PASS
OVERALL: PASS (7/7 bars)
```

Real (base against candidate built from the staging corpus):

```
W: 174 probes  base top-3 46  candidate top-3 51  leavers 0  -> PASS
  (bar: net >= 0 AND no significant loss, i.e. loss_p > 0.1 — an earlier implementation of this harness gated on gain_p instead, which required evidence of GAIN rather than merely the absence of significant loss; both are reported below)
C [mcp]: n=390 +1/-0 net +1 loss_p=1.0 gain_p=0.5  -> PASS
C [enforcer]: n=390 +7/-4 net +3 loss_p=0.8867 gain_p=0.2744  -> PASS
  C [enforcer] LOST cases (4):
    LOST  'rg_history' <- 'it finished its entire validating. use /rg_history to retrieve what it did with session-id: agent-ae5f118737ceb57f5'
    LOST  'rg_history' <- 'use /rg_history to mine the transcript from prev session: 0b5ca409-5ba9-4120-961e-aeb637c77a73\nanalyze and find the valuable lessons, caveats, thing we should pay attention and should notice, things should be fixed and propose a complete set of plan to tackle them properly'
    LOST  'whereami' <- 'updated - reloaded. now - report the overall progress made this session thus far'
    LOST  'which-skills' <- "save it to docs/ideas/consult-mode.md - and start practicing the consulting job with this very task - its a good way to compound what you've experienced to the task you're working at hand directly"
D [mcp]: n=53 +0/-0 net +0 loss_p=1.0 gain_p=0.0  -> PASS
D [enforcer]: n=53 +0/-0 net +0 loss_p=1.0 gain_p=0.0  -> PASS
  (English rows gate the bar; Vietnamese reported separately: C=15, D=4)
N: 11/3368 violations (bar <= 1% AND <= 1/3 of the recall gains 6)  -> FAIL
    VIOLATION  'ak-deep-swe' <- 'Use our internal eval harness to score the agent.': 4 -> 3
    VIOLATION  'ak-security' <- 'Review the compliance of our software with PCI-DSS and GDPR standards.': 11 -> 2
    VIOLATION  'ak-shader' <- 'Write me a CSS animation for a bouncing ball with a gradient background.': 5 -> 3
    VIOLATION  'ak-threejs' <- 'Make a physics simulation using plain JavaScript with collisions.': 5 -> 3
    VIOLATION  'article-illustrations' <- 'Vẽ một bức tranh màu nước về phong cảnh núi rừng, không cần nhân vật.': 11 -> 1
    VIOLATION  'cli-framework-oclif-ink' <- 'How do I create a CLI tool using just commander.js without any terminal UI components?': 4 -> 3
    VIOLATION  'firecrawl-scrape' <- "Convert this local HTML file on my disk to markdown, I don't need a URL.": 4 -> 3
    VIOLATION  'mattpocock-skills:tdd' <- 'Explain what test-driven development is as a concept, just the theory please.': 4 -> 3
    VIOLATION  'officecli-soffice-pdf-pipeline' <- 'Use pandoc to convert markdown to PDF with a custom LaTeX template on Linux.': 4 -> 3
    VIOLATION  'omp-custom-gateway-registration' <- "List all the providers currently configured in omp so I can see what's available.": 4 -> 3
    VIOLATION  'vercel:vercel-firewall' <- "How do I add authentication with Vercel's password protection or integrate Clerk/Auth.js for protecting routes?": 4 -> 3
G (name, #1 bar): base [1, 1, 1] -> candidate [1, 1, 1]  -> PASS
G (paraphrase — reported only, never gated): candidate rank 1

PASS/FAIL by bar: W=PASS  C_mcp=PASS  C_enforcer=PASS  D_mcp=PASS  D_enforcer=PASS  N=FAIL  G=PASS
OVERALL: FAIL (6/7 bars)
```

| Sub-condition | Evidence | Holds |
|---|---|---|
| (a) at least one C or D view net > 0 | C [mcp] +1/-0 net +1; C [enforcer] +7/-4 net +3; D views net 0 | yes |
| (b) every bar passing in the control also passes in the real run | control 7/7 PASS; real 6/7, N FAIL | NO |
| (c) W has 0 leavers | W leavers 0 (base top-3 46, candidate 51) | yes |
| (d) N violations real <= control | real 11/3368, control 0/3368 | NO |
| (e) every C/D view loss_p > 0.10 | 1.0, 0.8867, 1.0, 1.0 | yes |

The filter shows a small gain (C enforcer net +3, but with 4 losses; C mcp +1) and 11 name-neighbour violations that the control does not have, against only 6 recall gains for the bar's one-third rule. Per the pre-registered gate the thresholds stay in staging and the filter stays inert. The N violations are negative-control queries on which a skill moved up 1-10 ranks (e.g. 'article-illustrations' 11 -> 1); the cause (which phrases the filter kept or dropped for those skills) was not investigated in this step.

Per the pre-registered gate the thresholds stayed in staging. There was no live backfill, no live reindex, and no `corpus_epoch` event; `active()` is false because no live thresholds file exists, so the live corpus is untouched. The cause of the 11 name-neighbour violations (which phrases the filter kept or dropped for those skills) was not investigated.

### Router history — `hist-compare`, 2026-10-04 (`logs/phase4-replay-261004.log` and `reports/phase-04-implementation-report.md`, "Live replay verdict")

Replay tail:

```
done: 1657 requests sent; run `hist-compare` for the verdict
exit 0
```

Verdict output:

```
gate answers: 566 turns, model jev-1.13.0, catalogue aca49852da94d986; 218 positives with the used skill installed (87 follow-up: previous assistant message, <= 20 words); call failures counted as misses: {'ctx': 2, 'hist': 1, 'adv-hist': 1, 'wide': 2}; turns with no cached record at all: 0; turns whose wide call failed (no rerank, a miss at the timeout): 2
ceiling: used skill inside the wide shortlist on 86.2% of follow-up positives (ctx recall 79.3%); offered follow-up positives n=87
                      overall recall   follow-up recall   false NO
  ctx                       72.5%             79.3%   0/218
  hist                      76.1%             80.5%   0/218
  follow-up turns hist gets and ctx misses: 3; the reverse: 2
  wide          ms p50 578 p90 743 (n=566)
  fit           ms p50 15 p90 40 (n=564)
  hist rerank   ms p50 385 p90 513 (n=489)
  route (hist)  ms p50 1001 p90 1348 (n=566)
  hist fell back to today's state on 75 turns
  adversarial row: 20 planted-text turns, history-caused skips 0
VERDICT: FAIL (follow-up recall gain)
```

FAIL on one criterion only: follow-up recall gain +1.2 points against the +3.0 required. The adversarial row (20 planted-text turns) shows 0 history-caused skips, false NO is 0/218 on both sides, and every latency bar holds. `ENFORCER_JEV_HISTORY` stays `0`.

### Relay-timeout fix and shared client

A live probe (`scripts/jev_client.py --probe`) answered on all four bench tiers (p(yes) 0.96; a single call 410 ms). Source of these figures: the orchestrator's phase 1 record in the task brief; phase 1 wrote no report file, so this item is not backed by a log in the repository.

### Also fixed in this release

`tests/test_port_env_guard.py` now scans only files git does not ignore; it had failed on a stale git-ignored `vendor/skill-search/build/` copy (owner's order, this session).

## Consequences

- **Metered channels.** The consult matrix, calibration, backfill and replay send requests to every bench endpoint (D3), including TypeSafe and OpenRouter, which bill per use. Counts from the logs above: staging backfill 2895 requests, 11545943 estimated input tokens; history replay 1657 requests sent. The `hist-compare` run itself sends nothing.
- **Corpus epoch.** A ledger event `{"ev": "corpus_epoch"}` (written by `trigger_filter.py backfill` and `reindex`) starts an epoch for retrieval metrics, because the trigger corpus changes without a code commit. None has been written; the first one will be the W35 epoch start, once a future calibration passes the staging gate.
- **Watch items.** Epoch-watch v0.57.0 adds W34 (consult matrix), W35 (utterance filter; applies after a `corpus_epoch` event) and W36 (router history; applies only if the owner turns it on).
- **Corpus protection.** `build_triggers.py` run by hand used to erase every utterance layer; that is fixed (it carries each `llm_triggers` block over, audit included) and all four `triggers.json` writers take the flywheel lock.
- **Threshold keys.** Thresholds are keyed by the exact returned model id, so when the gateway rolls a new dated snapshot its scores stay `pending` and its phrases are kept until a calibrate run covers it.
- **Not decided here.** Whether to re-key thresholds by model family, and whether to investigate the N violations and calibrate again, are left to the owner.

## Credit

Ideas, the token estimator and the fitting stage order ported from fast-jev-compaction (MIT License, Copyright (c) 2025), commit e3f262a. See `THIRD_PARTY_NOTICES`. Ported pieces: `estimateTokens` (as `_jev_tokens`) and the stage order of `fitState` (in `_jev_history_lines`), both from `src/state.ts`.

## Revert

One variable per change: `SKILL_CONSULT_JEV=0`; `SKILL_TRIGGER_JEV_FILTER=0` (set in `~/.config/harness-env.sh` so the detached `auto_flywheel` sees it); `ENFORCER_JEV_HISTORY=0` (already the default). The relay-timeout fix reverts as a code revert of the `_jev_call` change. If a filtered corpus is ever written: restore the backup file under `~/.claude/skill-concierge/backups/`, reindex from the CLI (`trigger_filter.py reindex`), and check that the reindex's `deleted`/`embedded` counts match the `corpus_epoch` event.
