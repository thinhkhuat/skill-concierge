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

## Unreleased — Command Code Jev tier, timeout fall-through, 7.8 s budget (ADR-0079); jevd as the bench source (ADR-0080)

**Epoch starts.** W38: the go-live of the ADR-0079 enforcer on each harness (until then an older enforcer drops the `cc:` bench entry and stays TypeSafe-first). This changes `hooks/scripts/enforcer.py` (budget cap 3.0 -> 7.8 s, timeout fall-through), so router rates (W21-W24) restart here and must be read per `tier`. The Command Code and DSH adapters run with `ENFORCER_JEV_BUDGET=1.6` and never use the `cc` tier.

| # | Watch | How | Trigger | Action |
|---|-------|-----|---------|--------|
| W38 | Command Code tier in use (the owner's interim 5.5 s span, ADR-0079) | the ledger's router events (`jev` field) filtered by `jev.tier` (`calibrate_jev_gate.py live` does not split by tier; filter the rows first); the double-bill rate = share of router events whose `fell` starts with `typesafe/jev` + `TimeoutError`, and the error share of `fell` entries for `typesafe/jev`, counting only real failures (`TimeoutError`, `URLError`, `HTTPError`) and excluding `NoTime` (every turn on the Command Code and DSH harnesses logs it, because their 1.6 s budget never fits the `cc` tier); `jev.ms` p50/p90 on tier 0 against tier 1 (`wide_ms` on a fall-through turn includes the Command Code span); read `rmodel` for the unpinned `typesafe/jev` | double-bill rate above 50 % (measured at ship: 2, 2, 3 and 6 of 12 valid-round turns missed the span, the 6 of 12 at 5.5 s), p90 `ms` > 7800, or the fit-floor skip rate on `cc`-served turns differs from the `jev-1.13.0` turns | drop `cc:typesafe/jev` from `ENFORCER_JEV_BENCH` (TypeSafe first again), or set `ENFORCER_JEV_CC_TIMEOUT=3.3` for the earlier cut-over; recalibrate the 0.30 floor if `cc` stays; the owner's call, since the 5.5 s span is "at least for now" |
| W39 | jevd path against the direct path (ADR-0080) | the ledger's router events split by `jev.bench` (`jevd` against `env`), `jev.via` (`jevd` against `relay`/`direct`; `relay` now covers Command Code too, ADR-0081) and `jev.prov` (the jevd provider that served: `commandcode`, `typesafe`, `gateway`...); `jev.ms` p50/p90 per `prov`; share of rows with `fell` naming `NoTime`, `TimeoutError` or `HTTPError` per `prov`; share of turns with no `via=jevd` row while `JEVD_URL` is set (jevd down or slow to answer `/ladder`) | `via=jevd` on under most rows while jevd should be up, `commandcode` p90 `ms` above its 5.5 s span, or a `prov` that never serves | `curl` jevd's `/health` or `/ladder` on the loopback address; fix or restart jevd; unset `JEVD_URL` to fall back to `ENFORCER_JEV_BENCH` (ADR-0080) |

---

## v0.58.0 — consult widening with Jev's top 10 (ADR-0078)

**Epoch starts.** W37: the v0.58.0 go-live of `consult_fit.py widen` in consult step 2 (`SKILL_CONSULT_JEV_WIDEN` default ON). No `hooks/`, `enforcer.py` or `server.py` change, so the per-turn offer metrics (W21-W24, W30-W33) do not restart here. Consult candidate sets change: the first 10 rows come from Jev, the rest from the sieve, 20 in total ([ADR-0078](adr/0078-consult-sieve-jev-widening.md)). The W34 readings (`jev` on consult verdict rows) now sit on a different candidate set and must window from this go-live.

| # | Watch | How | Trigger | Action |
|---|-------|-----|---------|--------|
| W37 | Live consult widening | `consult_verdict` ledger rows since go-live carry `sieve` (`widened`, `not-widened`, `off`) and `jev_added`, written by `consult_log.py --sieve/--jev-added`; `jev.ms` and the chosen primary's row `source` are on the consult card and in the `widen` output, so read the cards or transcripts for those: (a) share of cards saying `sieve: not widened`; (b) `jev.ms` p90 and `jev.failed` rate; (c) whether the chosen primary has `source` `jev` (or `both`) or `sieve`, and how many of the 11-of-13 "primary not among the sieve rows" cases from the W34 finding now find it among the 20 rows (admitted by hand at step 3 counts as a miss). Small n is "insufficient data", never a rate | (a) or (b) failure rate above 5% (the pre-registered Jev-arm bar was p90 <= 1500 ms; the gate run saw p90 969 ms, 0 failures in 57 calls); (c) the primary comes from a `jev`-only row in no run once n >= 10 consults, or manual admissions at step 3 do not fall | `SKILL_CONSULT_JEV_WIDEN=0`, check `python3 scripts/jev_client.py --probe`; a recurring primary from `jev` rows is the first live evidence for the real-consult effect the gate could not measure |

---

## v0.57.0 — Jev typed questions: consult matrix live, utterance filter inert, router history off

**Epoch starts.** W34: the v0.57.0 go-live of `consult --fast` (`SKILL_CONSULT_JEV` default ON). W35: the first `corpus_epoch` ledger event, once a future calibration passes the staging gate — none exists yet, so W35 has no epoch and nothing to measure today. W36: the moment the owner switches `ENFORCER_JEV_HISTORY` on (an env change; the router event's `hist` field marks it) — it applies only if he does.
- v0.57.0 changes `hooks/scripts/enforcer.py`: a relay-reported timeout now ends the bench chain instead of re-sending to the next tier ([ADR-0076](adr/0076-jev-typed-questions-consult-triggers-history.md)). Router rates (W21-W24) window from this go-live; the chain behaviour on a timeout differs from v0.56.0.
- The utterance filter ships inert (no live thresholds file) and the router history ships OFF, so the live trigger corpus and the router's rerank state are unchanged at the shipped defaults.

| # | Watch | How | Trigger | Action |
|---|-------|-----|---------|--------|
| W34 | Consult fit matrix | `consult_verdict` rows since go-live: share of fast consults with a `jev` field and `jev.ms` p90; plus `python3 scripts/consult_fit.py --eval` once 30 eligible runs exist. Known at ship: the first `--eval` (2026-10-03) found 13 runs, only 2 eligible (`CHECK: INSUFFICIENT`) because in 11 of 13 the primary the agent chose was not among the sieve's candidates, so the sieve's recall is itself worth reading | p90 > 4000 ms; `jev` missing on most fast consults; or the eval prints `CHECK: FAIL` | `SKILL_CONSULT_JEV=0`, then review; check `python3 scripts/jev_client.py --probe` |
| W35 | Utterance filter effect (only after a `corpus_epoch` event) | doctor's Findability row after the `corpus_epoch` reindex against the reading before it; W22 on the embedding path, windowed from that event | a new Findability warning, or a higher backlog | restore the backup, `python3 scripts/trigger_filter.py reindex`, re-run `calibrate` |
| W36 | Router history (only if the owner turns it on) | `calibrate_jev_gate.py live` W22/W23 split by rows with `jev.hist.used` against those without; count `hist.reask` | p90 `ms` > 1500, W22 below the ctx rows, or `reask` on > 10 % of rows | `ENFORCER_JEV_HISTORY=0` |

---

## v0.55.0 — findability detection; ranking unchanged (no new watch items)

**Epoch start moves to each harness's v0.55.0 go-live.**
- v0.55.0 changes `vendor/skill-search/skill_search/server.py` (the findability sweep hook and two retrieval changes that ship OFF). At the shipped defaults the index and every search result are byte-identical to v0.54.2 (0 points embedded on both staging builds; a sorted SHA-256 over 44,602 points and the raw file MD5 both matched).
- The epoch rule keys on the commit, so W30-W33 below window from the v0.55.0 go-live. Any shift across the boundary is environmental, not a design effect.
- **Findability** is watched in doctor's "Findability" row, not the ledger: a backlog count plus warnings for a new unfindable skill or a regression. The first live sweep's backlog was 113 of 149 skills.

---

## v0.54.2 — cleanup release; the v0.54.0 watch items carry on (no new watch items)

**Epoch start moves to each harness's v0.54.2 go-live.**
- v0.54.2 changes `vendor/skill-search/skill_search/index_owner.py`: a malformed port value now falls
  back to the default instead of crashing the owner at import.
- v0.54.1 changed the same file (`1ddeeca`: the missing-loopback errno carve-out narrowed to `::1`).
- `0526f6c`, `d20764d` and `0bdca97` (the same release) also changed `hooks/scripts/enforcer.py`,
  `index_owner.py` and `vendor/skill-search/skill_search/server.py` — each only in how it derives its
  ports and store URL (now through one module, `skill_search/ports.py`), never the offer-ranking,
  retrieval or gate logic the W30-W33 items below watch. The epoch rule keys on the commit, so every
  one of these files' epoch starts moves to the v0.54.2 go-live.
- All of these changes affect only how a process starts or which port it derives. None changes what
  any offer contains.
- The epoch rule keys on the commit, so W30–W33 below keep the v0.54.0 items and window from the
  latest go-live.
- `prompt_intent` after the v0.54.1 `setup.sh` rebuild: 792 points, the same count as at the switch
  (live `/collections/prompt_intent`, 2026-09-27 11:45 +07). Its sample may differ, so W32 compares
  shares, never individual hits.

**First W30-W33 reading, 2026-09-27 11:45 +07: insufficient data.**
- **W30.** `analyze.py --since "2026-09-27T09:25"` (the v0.54.1 go-live) shows 25 events, all from
  the session doing the release work. After excluding self-session traffic, n = 0. The wider 06:45
  window has 56 events: 54 from that same session and 2 from one other session. No rate is quotable.
- **W31.** Not measurable at n = 0.
- **W32.** `prompt_intent` holds 792 points. The fail-open share needs real turns, so it is not
  measurable yet.
- **W33.** No `embed_down` or `qdrant_down` offers since the switch, across all sessions. The hook's
  `python3` resolves to pyenv 3.12.11 here, not the 3.9 system interpreter, so the Python 3.9
  over-count cannot fire on this machine.
- **Next reading.** After about a day of traffic from other sessions, windowed from the v0.54.2
  go-live. Exclude self-session and subagent rows.

---

## v0.54.0 — local index owner replaces Qdrant and the Docker embed shim (ADR-0070; TASK-022)

**Deployed on Claude Code 2026-09-27 06:45 +07:** commit `dfcbb6b` (rolled up from `a8261b7` +
`c2c781a`) fast-forwarded onto `main` and pushed; dark window 06:34-06:45 (Docker Qdrant and the
embed shim stopped, then the owner started on 6333/6363); smoke PASS (`/health` `code_version`
0.54.0, only the owner listens, 64/80 saved smoke-name lists identical, the other 4 all exact
score ties). Other harness caches (OMP, Codex, ZCode) start their own windows when their plugin
cache reaches 0.54.0.

**Starts per harness** when its plugin cache reaches `0.54.0` and `doctor.py`'s "Index owner" row
is OK — every offer-level ledger rate (fallback, hit@k, embed/Qdrant latency, the `embed_down` /
`qdrant_down` shares) resets here: the answerer behind `SKILL_QDRANT_URL` and 6363 changed from
two Docker containers to one local process, so latency and outage bands from v0.53.x and earlier
are not comparable.

Two REQ-004 behavior changes, both epoch-scoped (never pooled across this line):
- **Exact search replaces Qdrant's approximate order.** The parity replay
  (`plans/reports/cutover-readiness-260926.md`) measured live Qdrant's default (HNSW-approximate)
  order against the owner's exact-cosine order on the same 540 prompts (500 ledger human prompts +
  40 EN/VN) used for TASK-016: the raw 40-row over-fetch differs on 292-295/540 (305/540 in the
  switch-day re-run, 2026-09-27 01:47 — `~/.cache/skill-search/cutover-evidence-260926/cutover-step1.log:10`,
  "approximate-vs-exact (live, retrieve shape): 305/540 prompts where Qdrant's default search order
  differed from exact"), but on the 8
  skills actually offered (`TOP_K`), order differs on 66/540 prompts (12 %) and which skills
  appear differs on 14/540 (2.6 %). So roughly 1 offer in 8 changes, toward the true nearest
  neighbours — recall can only improve, and the replay never found an approximate score beating
  an exact one.
- **Ties break by score descending, then skill name ascending** (REQ-004), replacing Qdrant's own
  arbitrary tie order.

**`prompt_intent` was rebuilt at the switch, not migrated: 792 balanced points, was 2,044.** The
migration copied `prompt_intent` bit-for-bit (2,044 points, 0 byte/payload differences) into the
staging owner for the parity replay, but the go-live's `setup.sh` run rebuilds it from source
(`build_prompt_intent.py`) instead of keeping that migrated copy — the actionability gate's
grounding collection is a smaller, freshly-balanced set (792 vs 2,044), not the pre-migration one.
The gate still fails open below its data-sufficiency floor, but any watch item reading gate hit
rates must not compare against a baseline built on the 2,044-point collection.

**Pre-existing quirk, newly load-bearing here (TASK-022): `embed_down` over-counts on Python
3.9.** The enforcer's embed call (`_embed` → `urllib.request.urlopen(..., timeout=EMBED_TIMEOUT_S)`,
`hooks/scripts/enforcer.py:1793`) is guarded by `except TimeoutError` first (`:2481`) and falls
through to `except (OSError, ...)` (`:2488`), which logs the row `embed_down`. `socket.timeout`
became an alias of `TimeoutError` only from Python 3.10 on; under Python 3.9 a plain read timeout
still raises the pre-3.10 `socket.timeout` class, which the `TimeoutError` branch misses and the
`OSError` branch catches instead — so a slow-but-alive owner is logged `embed_down` (unreachable)
rather than `embed_timeout` (busy/loading). This is not new in 0.54.0, but the owner replacing two
Docker containers with one process makes `embed_down` a more load-bearing signal now (W33):
verify the hook's own interpreter before reading a spike as an outage.

| # | Watch | Command | Trigger | Action |
|---|-------|---------|---------|--------|
| W29 | Owner up, not a revived container | `python3 scripts/doctor.py` → "Index owner" row | FAIL (answers as something other than the owner), or a Docker container listening on 6333/6363 | `doctor.py --fix` stops a revived container; `SKILL_OWNER_AUTOSTART=1` (default) lets the launcher/hook restart the owner itself |
| W30 | Offer-level rates reset at the switch | `analyze.py --since "2026-09-27 06:45 +07"` (exclude subagent + self-session traffic) | any comparison against a v0.53.x-or-earlier window | epoch-scoped only — this is the reset line, never pool backward |
| W31 | Exact-order offer shift measured, not assumed | replay live turns since the switch against the parity replay's offered-skill baseline (order differs 66/540, 12 %; which-skills differs 14/540, 2.6 %) | offer quality (hit@k, used-skill-in-offer) moves outside that baseline with no unrelated cause | re-run the parity comparison against the CURRENT catalogue (skills drift), never against the pre-switch snapshot |
| W32 | `prompt_intent` gate on its rebuilt population | the actionability gate's fail-open share since the switch | fail-open share rises (the data-sufficiency floor trips more often on 792 points than it did on 2,044) | expected right after a rebuild — re-check after the collection re-accumulates; do not compare its hit rate to the pre-switch 2,044-point baseline |
| W33 | `embed_down` interpreter check | on an `embed_down` spike, confirm which `python3` actually ran the hook (log its `sys.version` once, or check the hook's shebang resolution) | a Python 3.9 interpreter running the hook | point the hook at the venv interpreter, never a bare system `python3` — a 3.9 hook silently folds every read timeout into `embed_down` |

## v0.52.9 — installers fail closed (ADR-0072)

**No new epoch for any watch item.** Installers and doctor rows only; the standing order, the enforcer,
the engine and the audit are unchanged.

## v0.52.8 — unscored harness turns; clean miner corpus (ADR-0071)

**Starts per harness** when its plugin cache reaches `0.52.8`. No standing-order change, so no new trail
epoch: W25-W28 keep reading from the 0.52.3 deploy. The audit reader changed (list-form harness records
open unscored turns): compare skip-turn counts only within one reader version. Since 2026-09-19 the
0.52.7 and 0.52.8 readers agree.

## v0.52.7 — Codex and Claude Code installers (ADR-0069)

**No new epoch for any watch item.** The release adds installers and a doctor row; the standing order,
the enforcer and the engine are unchanged. W25-W28 keep reading from the 0.52.3 deploy.

## v0.52.6 — the harness's fields decide work; anchored negation (ADR-0068)

**Starts per harness** when its plugin cache reaches `0.52.6`. No standing-order change, so no new trail
epoch: W25-W28 keep reading from the 0.52.3 deploy (Claude Code 2026-09-26 21:20:20). The audit reader
changed again (team relays and programmatic records out of the work count; their verdict turns moved into the
previous turn until 0.52.8 — ADR-0071):
compare skip-turn and continuation counts only within one reader version. Since 2026-09-19 all three
0.52.4-0.52.6 readers give the same headline.

## v0.52.5 — work turns by prompt shape; negated continuations (ADR-0067)

**Starts per harness** when its plugin cache reaches `0.52.5`. No standing-order change, so no new trail
epoch for the rulings: W25-W28 keep reading from the 0.52.3 deploy (Claude Code 2026-09-26 21:20:20).
The audit's reader changed (list-form prompts open turns, duplicated lines read once, work turns by
shape, negated continuations): skip-turn and continuation counts across 0.52.4 → 0.52.5 readers are not
comparable where a window holds list-form prompts or duplicated lines (since 2026-09-19: identical).

## v0.52.4 — the stale gap counts work turns (ADR-0066)

**Starts per harness** when its plugin cache reaches `0.52.4`. No standing-order change, so no new trail
epoch for the rulings: W25-W28 keep reading from the 0.52.3 deploy (Claude Code 2026-09-26 21:20:20). The
continuation counter changed again (work-turn gap, parsing): continuation counts across 0.52.3 → 0.52.4
readers are not comparable.

## v0.52.3 — continuation counter reads every form; stale-continuation red flag (ADR-0065)

**Starts per harness** when its plugin cache reaches `0.52.3` and a session restarts. A **trail epoch**
(the standing order changed); W25-W28 are read from the 0.52.3 deploy. 0.52.2 was installed on Claude
Code at 2026-09-26 20:51:46. The continuation counter changed (every form; earlier use before the turn;
stale flag; organic split): continuation counts across the reader change are not comparable — the 0.52.2
baselines were form-limited. W28 now also watches the stale count.

## v0.52.2 — continuations for the same task; continuation counter (ADR-0064)

**Starts per harness** when its plugin cache reaches `0.52.2` and a session restarts. A **trail epoch**
(the standing order changed); W25-W28 are read from the 0.52.2 deploy. 0.52.1 was installed on Claude
Code at 2026-09-26 19:41:06. The audit reader changed again (search-backed now means a search before the
ruling): counts across the reader change are not comparable. From the 0.52.1 deploy on, `analyze.py`
deep-pull and external-take counts include continuation re-reads (`get_skill` rows) — not comparable
with earlier windows. W28 now reads the audit's continuations line.

## v0.52.1 — continuing a skill re-reads it; audit reader fixes (ADR-0063)

**Starts per harness** when its plugin cache reaches `0.52.1` and a session restarts. A **trail epoch**:
the standing order changed again ~20 minutes after 0.52.0 (installed 2026-09-26 19:20:51 on Claude Code),
so W25-W27 below are read from the 0.52.1 deploy, not the 0.52.0 one. The audit reader also changed
(ADR-0063): counts across the reader change are not comparable. First live `NO SKILL:` ruling seen
2026-09-26 19:33:56 (a 0.52.0 session), in the taught `hook-cleared — <reason>` form.

| # | Watch | Command | Trigger | Action |
|---|-------|---------|---------|--------|
| W28 | Continuations re-read and scoped | `audit_skill_usage.py --since "<deploy>" --continuations` → the continuations line, organic part (total; re-read in the turn; no earlier use; last used > 5 work turns ago) and the listed units for hand review | continuations without the re-read, more than a stray one per week; or organic stale continuations (last used > 5 work turns ago) that hand review finds are new work | re-read missing: the rule 3 paragraph is not landing — make the re-read the first clause, or have the enforcer name the last-used skill on short turns; stale-and-new-work: the red-flags row is not landing — move it up, or have the enforcer warn when a continued skill is absent from a high-fit offer |

## v0.52.0 — `NO SKILL:` ruling, whole-shelf label, shorter standing order (ADR-0062)

**Starts per harness** when its plugin cache reaches `0.52.0` and a session restarts (the standing order
is injected at session start). A **trail epoch**: ruling shares (USING / SEARCH / skip) and the false-skip
rate reset — never pool them with v0.51.x. Retrieval, gates and the router are unchanged, so W21-W24
(router) continue. Tuning orders carried over: `ENFORCER_ANNEX_MARGIN=0.0`, `ENFORCER_MULTI_INTENT=0`.

Baseline (2026-09-26 19:05, `audit_skill_usage.py --since "2026-09-19 00:00:00"`, v0.51.x epoch, read
with the 0.52.0 reader): skip turns 130, false 11 (8 %), search-backed 12, hook-authorized 107;
**enforcer-run turns only: 4/123 (3 %)**. Thin: 4 events. Of the 7 false skips outside the enforcer's
population (replies to Stop-hook feedback, where it never runs), 6 come from one session — a pattern of
one week, not a law. 129 organic `USING`. Compare only after the ≥ 100-turn floor below.

| # | Watch | Command | Trigger | Action |
|---|-------|---------|---------|--------|
| W25 | Doctrine effect on its own population | `audit_skill_usage.py --since "<deploy>"` → the "enforcer-run turns only" line, and organic `USING` | after ≥ 100 enforcer-run turns: false share clearly above the 3 % baseline, or organic `USING` per day clearly below the v0.51.x week | read the false-skip turns' `NO SKILL:` reasons (`--harvest`); tighten the red-flag rows that the excuses match — never restore the old length wholesale |
| W26 | Router offers searched anyway | label corpus (`extract_turn_labels.py`): English turns with a whole-shelf offer where the agent searched although a row was then used | a large share of searches on turns whose used skill was already in the offer | the offer header or rule 1 wording is not landing; rewrite that line |
| W27 | `NO SKILL:` form adoption | `audit_skill_usage.py` skip-rulings line (split since 0.52.1): `NO SKILL:` vs old `SKIPPING` | old form still dominant a week after every session restarted | a stale standing order in some harness — check its plugin cache version |

## v0.51.0 — the Jev skill router (ADR-0061; supersedes the v0.50.0 yes/no leg)

**Deployed on Claude Code 2026-09-26 10:03 +07:** commits `0b03c88` + `179cec0` pushed; plugin cache 0.51.0
(installed copy byte-identical to source); embed shim rebuilt with `/jev` (health lists `jev`). The
Claude Code window starts when each session restarts onto 0.51.0. Other harness caches were already stale
(OMP/ZCode 0.47.1, Codex 0.45.0) and start their own windows when updated.

**Starts per harness** when its plugin cache reaches `0.51.0` AND its `/health` endpoint lists `jev` —
the embed shim's `/health` before the harness's own copy reaches v0.54.0 (`setup.sh` rebuilds an older
shim), the local index owner's `/health` (`"routes": ["embed", "jev"]`) from v0.54.0 on
([ADR-0070](adr/0070-local-index-owner-replaces-qdrant-and-docker-embed-shim.md)); ledger rows carry no
version, but every routed row carries
`jev.via` (`relay` / `direct`). On English turns Jev now composes the menu (top 5) and replaces the
getaway/actionability gates, so offer-level rates (take, hit@k, fallback) reset — never pool them with
v0.50.0 or earlier. Vietnamese and other non-English turns keep the embedding path: their rates continue
the v0.49.0 series. Tuning orders carried over: `ENFORCER_ANNEX_MARGIN=0.0`, `ENFORCER_MULTI_INTENT=0`.

Replay baseline (2026-09-26, `scripts/calibrate_jev_gate.py policy`, English, live catalogue): used skill
in the offer 177/237 = 74.7 % (embedding menu 36 %); false NO 1/313 (holdout 1/105); traffic skipped 2.0 %. Re-derive, never
hand-tune: `extract_turn_labels.py` → `calibrate_jev_gate.py replay --shelf wide` → `fit` / `policy`.
Re-measured 2026-09-26 10:19 on the calibrator's new stable (hash-ordered) traffic sample: traffic
skipped 9/297 of a 300-turn sample (3.0 %; 3 turns unscored) — the 2.0 % above came from the old random sample and is not comparable; false NO
and offer recall unchanged.

**Offer tail rows (W22's filler question, answered offline 2026-09-26):** `policy` prints the cost of
cutting the rows after the lead by probability. p < 0.01 removes 8 % of tail rows on real skill turns
(3 % on traffic) and loses 1 of the 79 used skills that sat in the tail; p < 0.05 loses 14. The offer
stays at the top 5 — a near-zero row is sometimes the skill the agent uses. Re-check with `live` (its
"tail rows" line) once real traffic exists.

**TypeSafe keep-alive (measured 2026-09-26 10:14-10:21, direct HTTPS, one connection per idle gap):**
reuse after 5, 30, 60, 120 and 240 s idle succeeded (232-334 ms); after 420 s the server had closed the
connection (`RemoteDisconnected`, `Server: cloudflare`, no `Keep-Alive` timeout header). So a pooled relay
connection goes stale somewhere between 4 and 7 minutes of quiet; the relay's one fresh-connection retry
covers it — the server closed the idle connection with no response, so the failed attempt was never
processed (inference from `RemoteDisconnected`) and nothing is billed twice. A
turn after a longer pause pays one fresh handshake (the first router call only). Probe:
`plans/260926-1010-open-items-after-v0510/checks/keepalive_probe.py` (untracked plans dir).

**Whole-word deterministic routes (v0.51.1, same day):** replayed on 5,196 ledger offer rows the
fix drops 3 route hits, all `/cookbooks` URLs (4 on the full prompts of the label corpus: two
`/cookbooks` URLs, two `session handoff` inside longer words, no skill used on either) — too few to move
any W-item; no reset.

**One command for W21-W24:** `scripts/extract_turn_labels.py` (fresh turns), then
`scripts/calibrate_jev_gate.py live --harness <name> --since "<that harness's deploy, local time>"`.
Only v0.51.0 router rows count: v0.50.0 `{p, ms}` rows by shape; an unmarked `{err, ms}` row takes the
kind of its session's earlier row (router errors carry `leg: "router"` from v0.51.1); with no
earlier row it is reported as unattributed. W21/W22 read the label corpus, which is Claude Code only. The
report prints session and turn ids, never prompt text.

| # | Watch | Command | Trigger | Action |
|---|-------|---------|---------|--------|
| W21 | False NO: a `jev_skip` turn that needed a skill | `live` → W21 line (lists each `jev_skip` turn where the agent then used a skill); read those sessions for a user correction | any confirmed case on a substantial task | lower `ENFORCER_JEV_FITS_FLOOR` (env), then re-run the calibrator on a fresh extract — never add the prompt to a hand-written set |
| W22 | Offer quality on live traffic | `live` → W22 lines: used skill (USING + executed) in the offer, per slice (interactive = the replay population; SDK / `claude -p`; dev sessions), plus tail rows below p 0.01 | below ~65 % on ≥ 100 English turns (replay: 74.7 %) | re-run `calibrate_jev_gate.py replay --shelf wide` + `policy`; check `jev.ctx` (context missing?) and catalogue size `jev.n` |
| W23 | Latency, errors and the relay | `live` → W23 line (`jev.ms` p50/p90, `jev.err` share, `jev.via` split) | p90 `ms` > 1500 (read per `jev.tier`: on Command Code turns it always fires, since a whole turn there takes 0.7-7 s, ADR-0079), `err` on > 5 % of rows, or `via=direct` on most rows | `curl localhost:6363/health` must list `jev` in `routes` (else `python3 scripts/doctor.py --fix` or `setup.sh`); raise `ENFORCER_JEV_TIMEOUT` (the whole route is capped at 7.8 s by `ENFORCER_JEV_BUDGET`, ADR-0079; Claude Code's hook is killed at 10 s, other harnesses sooner, so a larger budget would get the hook killed), or `ENFORCER_JEV_ROUTER=0` while TypeSafe is degraded. If `JevModelMismatch` or `HTTPError` dominates, the pinned `ENFORCER_JEV_MODEL` may be retired: probe `jev-latest` for the current concrete id before re-pinning (a new model is a new epoch; re-run the replay) |
| W24 | Catalogue drift | `live` → W24 line (`jev.n` on rows vs the replay's catalogue snapshot; also the cwd's catalogue now — project isolation makes `n` vary by cwd) | catalogue size moves > 5 % from the replay's, or > 2 % once the catalogue exceeds 500 skills (tuned 2026-10-03 by the owner from a flat 10 %, after 494 → 542 passed unflagged; `w24_trigger` in `scripts/calibrate_jev_gate.py`; revert there) | re-run the replay on the new catalogue before trusting W22 |

## v0.50.0 — the Jev needs-a-skill gate (ADR-0060; committed 2026-09-26) — SUPERSEDED by v0.51.0

W18-W20 are retired with the leg they watched. Replayed on real traffic the leg skipped 47.8 % of turns
where the agent really used a skill (ADR-0061 *Context*); W18's "add the prompt to the tuning set" is the
hand-written-set practice ADR-0061 removed.

### v0.50.0 original watch items (historical)

**Starts per harness** when its plugin cache reaches `0.50.0` (`doctor` lists cache versions); ledger
rows carry no version. The gate removes offers from turns Jev judges skill-free, so offer-level rates
(take, hit@k, fallback) reset — never pool them with v0.49.0. Tuning orders carried over:
`ENFORCER_ANNEX_MARGIN=0.0`, `ENFORCER_MULTI_INTENT=0`.

| # | Watch | Command | Trigger | Action |
|---|-------|---------|---------|--------|
| W18 | False NO: a `jev_skip` turn that needed a skill | ledger `offer` rows with band `jev_skip` since the cache reached 0.50.0; replay each prompt's session for a later `Skill`/`search_skills` use or a user correction | any confirmed false NO on a substantial task, or 2+ on Vietnamese prompts | lower `ENFORCER_JEV_SKIP_BELOW` (env), and add the prompt to the tuning set before any question rewrite |
| W19 | Missed skips: conversation still getting a menu | ledger `offer` rows whose `jev.p` sits in 0.25-0.45 on turns that ended with a lawful SKIPPING | a steady share of go-aheads/questions in that band | raise `ENFORCER_JEV_SKIP_BELOW` in 0.05 steps, env only |
| W20 | Latency and failures | `jev.ms` and `jev.err` on ledger rows | p90 `ms` > 1000, or `err` on > 5 % of rows | raise `ENFORCER_JEV_TIMEOUT` or set `ENFORCER_JEV_GATE=0` while TypeSafe is degraded |

## v0.49.0 — harness-complete offer isolation, project isolation, echo on every harness (ADR-0059; committed 2026-09-26 00:05 local)

**When the epoch starts is per harness.** Ledger rows carry no plugin version, and each harness runs
the hooks from its own plugin cache: at commit time Claude Code's cache was still `0.48.0`, while the
venv, the Command Code mod and the DSH profiles took `0.49.0` on 2026-09-25 between 23:15 and 23:59.
Start each harness's window at the moment its cache (or adapter) reaches `0.49.0` — `doctor` lists
every cache version — never at the commit time alone.

**Offer composition resets under every harness** — rows that were never invocable (other harnesses'
exclusive roots, other projects' skills, and everything under DSH/Cline, whose filter was off) leave the
installed offer. Offer-level rates (hit@k, take, fallback) start a new epoch here; never pool them with
v0.48.0. The v0.48.0 doctrine/row-contract watches (W10, W12, W13) continue. Tuning orders carried over:
`ENFORCER_ANNEX_MARGIN=0.0`, `ENFORCER_MULTI_INTENT=0`.

| # | Watch | Command | Trigger | Action |
|---|-------|---------|---------|--------|
| W14 | Under-filled offers: the post-filter now drops more rows, and `RETRIEVE_LIMIT` (`TOP_K*5`) is headroom, not a guarantee | ledger `offer` rows since the deploy time with fewer than `TOP_K` names, by harness (exclude subagent + self-session traffic) | a harness whose short-offer share clearly exceeds its v0.48.0 level on comparable traffic | raise the `RETRIEVE_LIMIT` multiplier in `hooks/scripts/enforcer.py` (a code constant, not an env var) only with evidence; never loosen the filter |
| W15 | Project isolation false drops: a session's own project skill missing from its offers | user report, or a `Skill` invocation (ledger `auto`) of a project skill that no offer in that session listed | any confirmed case | `ENFORCER_PROJECT_ISOLATION=0` in that harness's env, then reproduce with `_project_row_verdict` from that cwd (worktree paths, `--add-dir`, `/cd` are the known blind spots) |
| W16 | Exclusion echo in use: re-rules recorded by the audit | `python3 skills/skill-usage-audit/scripts/audit_skill_usage.py --since "<deploy time>"` → `re-rules:` line | zero re-rules over a window with loads of skills that carry exclusions | read replies after an echo — the marker may be ignored rather than unneeded; tighten the echo text before the doctrine |
| W17 | DSH/Cline offers now filtered | ledger `offer` rows with `harness` dsh / cline since the deploy time | an offered row whose skill the harness cannot load, or a personal skill missing while `~/.agents/skills` is the shelf | check `_agents_shares_personal_shelf()` on that machine first (environment), then the tuples |

## v0.48.0 — off-list rule, exclusion echo, row provenance, synced default OFF (ADR-0058; deployed 2026-09-25 21:21 local)

Live epoch for the search row contract, curated-trigger targets, and the doctrine trail metrics.
Retrieval ranking and gate floors are unchanged — offer composition does **not** reset, since
`SKILL_SYNCED_ROOTS` ships OFF — so the v0.47.x ledger watches (W1–W8 below) continue uninterrupted.
Tuning orders carried over: `ENFORCER_ANNEX_MARGIN=0.0`, `ENFORCER_MULTI_INTENT=0` (both Claude
`settings.json` env).

| # | Watch | Command | Trigger | Action |
|---|-------|---------|---------|--------|
| W10 | Curated targets and the repaired skill: chronic offer-without-take for `ak-skill-creator`, `writing-for-agents`, `compound-to-skill` | `python3 scripts/build_keep_off.py --since "2026-09-25 21:21"` (proposal only, writes nothing since ADR-0077) then read the printed list for those names | any of them in `_audit` (≥15 offers at ≤5 % take) | drop the offending curated phrase and reindex; for `compound-to-skill`, re-measure the description (A6 probe) |
| W12 | Epoch health of the search contract: fallback / outage rows in the v0.48.0 window | `python3 scripts/analyze.py --since "2026-09-25 21:21"` (exclude subagent + self-session traffic) | outage share above the v0.47.x level | environmental first (shim/Qdrant), not the row contract |
| W13 | Synced flip-on readiness | `python3 scripts/doctor.py` (harness integration rows) | every harness cache ≥ 0.48.0 | a separate, reviewed step: set `SKILL_SYNCED_ROOTS=1` in every relevant descriptor + reindex |

## v0.47.1 — doctrine + enforcer-string rewrite (ADR-0056; deployed 2026-09-15 ~11:50 local)

Live epoch — **trail-side only**. `hooks/doctrine/skill-first.md` and five injected enforcer
strings (MANDATE, ranked-mandate header, getaway / intent / selfref legs, CONSULT_MANDATE) were
rewritten under the writing-for-agents levers; retrieval, gates, bands and the ledger schema are
unchanged, so the v0.47.0 ledger watches W1–W6 below continue uninterrupted. What resets is the
transcript trail: USING / SEARCH / false-SKIPPING shares and the `authorized_skip` tally
(`skill-usage-audit --since "2026-09-15 11:50"`) re-baseline here. Tuning orders carried over:
`ENFORCER_ANNEX_MARGIN=0.0`, `ENFORCER_MULTI_INTENT=0` (both Claude `settings.json` env).

| # | Watch | Trigger | Action |
|---|-------|---------|--------|
| W7 | **Doctrine effect on the trail.** After ≥100 human-prompt turns: false-SKIPPING share, SEARCH share, and — new — the *getaway follow-through*: on a `getaway` ledger row whose `q` is real work, does the same turn's transcript show a `search_skills` call? | False-SKIPPING above the v0.47.0 baseline (8 %), or getaway follow-through below 50 % on real-work rows. | Re-read the getaway line and rule 2 for the escape the agent took; sharpen wording from the replayed transcript only. Never widen the closed list. |
| W8 | **Not-invocable takes.** `get_skill` pulls on `[external:*]` / other-harness names after rule 5 was generalised beyond the external alias. | Foreign rows shown ≥20× with 0 pulls in a harness where they are legitimately unusable. | That is annex-margin territory (W5), not doctrine — leave the doctrine alone. |

## v0.47.0 — harness-message lane + audit fixes (ADR-0054; deployed 2026-09-15)

Live epoch. Offer composition resets hard: harness-generated prompts no longer receive a
preview (band `harness_skip`), named skills lead via deterministic routes, both timeouts
widened, and the keep-off map can now populate. Segment `harness_skip` rows out of every
rate; the v0.46.0 baselines for chronic-zero, ROUTE follow and fallback are void here.
Tuning orders in force: `ENFORCER_ANNEX_MARGIN=0.0` (Claude `settings.json` env; revert =
delete the line) and the code defaults `EMBED 0.5 s / QDRANT 0.25 s` (revert = the two env vars).

| # | Watch | Trigger | Action |
|---|-------|---------|--------|
| W1 | **Harness-lane precision.** Replay every `harness_skip` row's `q`; each must be harness text. Conversely, human prompts must never land in the band. | ≥1 human-typed prompt in `harness_skip`, or a recurring harness shape still reaching `band=offer` (grep the ledger for `<task-notification>` / `omp-msum` under `offer`). | Tighten/add the shape in `_HARNESS_MSG_RE` from replayed evidence only; re-pin selftest (14). Never widen from vibes. |
| W2 | **Route hits vs false pins.** Every `offered[0]` at score `1.0` on a `fallback`/`offer` row is a route hit; replay its `q`. | A route fires on a prompt that did not name the skill (e.g. "/cook" inside a URL), or a named skill is still missed. | False pin → narrow the `contains` string; miss → add the replayed phrase to `config/deterministic-routes.json`. `ENFORCER_DETERMINISTIC=0` is the kill-switch. |
| W3 | **Outage share after the wider caps.** `analyze.py --since <deploy>` fallback line (outage-only since R6). | Still ≥5 % of decisions after ≥200 decisions, or `embed_ms` clustering at 490-500 / `qdrant_ms` at 240-250 (censoring again). | Look at the shim/Qdrant load first (flywheel/reindex windows); only then widen further. Revert path unchanged. |
| W4 | **First keep-off generation.** `doctor` `Keep-off` row; the map populates once ≥40 clean offered turns exist. | The map drops a skill you actually take inline (USING without the Skill tool) — the ledger cannot see those. | Add the name to `keep-on.json` (keep-on outranks nothing here — verify in `_drop_keepoff`) or blocklist the genuine junk instead; re-run `doctor --fix`. **Note (2026-10-04): ADR-0077 made keep-off consent-only.** No map is generated automatically any more, `doctor --fix` no longer refreshes it, and a map hides nothing unless Thinh approved it (`build_keep_off.py --apply`); read this row as "first approved keep-off list". |
| W5 | **Annex-margin trial.** `xh` annex volume and `get_skill` pulls on foreign names, Claude sessions only. | Volume collapses with no pulls lost = trial working; a foreign skill you then search for manually ≥3× = starvation. | Starvation → `ENFORCER_ANNEX_MARGIN=0.02`; still starved → delete the line (0.08). Record before changing. |
| W6 | **R9 decision data.** `analyze.py --continuation --since <deploy>`: route-follow on human prompts only. **Multi-intent already decided 2026-09-15** (owner GO): the human-only v0.46.0 backtest showed 84 multi-intent offers → 5 with ≥2 takes (6 %) vs single-intent control 7/98 (7 %) — no lift, ~245 chars on about half of all offers, plus live false positives on one-intent prompts. Tuning order: `ENFORCER_MULTI_INTENT=0` in Claude `settings.json` env (backup `.bak-multiintent-20260915-*`); other harnesses keep the default ON; revert = delete the line. ROUTE projection stays ON (5 clean samples is not a verdict; named-skill chains may now make it useful). | Projection: ≥30 human-prompt projections with 0 follow → decide; <30 → wait. Multi-intent: revisit only if a later epoch shows ≥2-take lift on multi-intent offers over the control. | Projection: `ENFORCER_CHAIN_PROJECTION=0` env-first; ADR if it sticks. Chain hints stay ON (8/16 follow in v0.46.0 with the session-wide join). |

## v0.46.0 — cross-harness plugin-offer gates (ADR-0053; deployed 2026-09-06)

Live epoch. Offer composition changes mechanically in three harnesses (omp gates namespaced
plugin rows on INVOCABLE membership; dsh/cline drop them) — offer-breadth and take-rate
baselines reset here. Segment omp sessions by `harness: "omp"` ledger rows.

| # | Watch | Trigger | Action |
|---|-------|---------|--------|
| W1 | **OMP plugin-row correctness.** Plugin-scope rows leave omp offers exactly where claude layers/OMP registry disable them; enabled plugins (e.g. repo-re-enabled agent-skills) must still appear. | An ENABLED plugin stops appearing in omp offers, or a disabled one still does. | Re-run the ADR-0053 sims (disabled-plugin prompt under omp must not offer; enabled must); check `ENFORCER_PLUGIN_GATE` on in the ext hook env; re-probe INVOCABLE under omp via import. |
| W2 | **DSH/Cline offer breadth.** Namespaced plugin rows gone from MAIN offers; personal/project rows unchanged. | A dsh/cline session's main offer loses NON-plugin rows, or still shows `prefix:name` plugin rows in the main menu (annex "NOT invocable" rows are by design). | Inspect the `_plugin_gate_ok` dsh/cline branch; annex appearances are correct — do not "fix" them. |

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
