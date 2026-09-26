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
| W27 | `NO SKILL:` form adoption | audit trail: skip rulings written as `NO SKILL:` vs the old `SKIPPING` | old form still dominant a week after every session restarted | a stale standing order in some harness — check its plugin cache version |

## v0.51.0 — the Jev skill router (ADR-0061; supersedes the v0.50.0 yes/no leg)

**Deployed on Claude Code 2026-09-26 10:03 +07:** commits `0b03c88` + `179cec0` pushed; plugin cache 0.51.0
(installed copy byte-identical to source); embed shim rebuilt with `/jev` (health lists `jev`). The
Claude Code window starts when each session restarts onto 0.51.0. Other harness caches were already stale
(OMP/ZCode 0.47.1, Codex 0.45.0) and start their own windows when updated.

**Starts per harness** when its plugin cache reaches `0.51.0` AND the embed shim's `/health` lists
`jev` (`setup.sh` rebuilds an older shim); ledger rows carry no version, but every routed row carries
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
| W23 | Latency, errors and the relay | `live` → W23 line (`jev.ms` p50/p90, `jev.err` share, `jev.via` split) | p90 `ms` > 1500, `err` on > 5 % of rows, or `via=direct` on most rows | `curl localhost:6363/health` must list `jev` (else `setup.sh`); raise `ENFORCER_JEV_TIMEOUT` (the whole route stays capped at 3.0 s — a larger budget would get the hook killed at 5 s), or `ENFORCER_JEV_ROUTER=0` while TypeSafe is degraded |
| W24 | Catalogue drift | `live` → W24 line (`jev.n` on rows vs the replay's catalogue snapshot; also the cwd's catalogue now — project isolation makes `n` vary by cwd) | catalogue size moves > 10 % from the replay's | re-run the replay on the new catalogue before trusting W22 |

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
| W10 | Curated targets and the repaired skill: chronic offer-without-take for `ak-skill-creator`, `writing-for-agents`, `compound-to-skill` | `python3 scripts/build_keep_off.py --since "2026-09-25 21:21" --out "$(mktemp)"` then read `_audit` for those names | any of them in `_audit` (≥15 offers at ≤5 % take) | drop the offending curated phrase and reindex; for `compound-to-skill`, re-measure the description (A6 probe) |
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
| W4 | **First keep-off generation.** `doctor` `Keep-off` row; the map populates once ≥40 clean offered turns exist. | The map drops a skill you actually take inline (USING without the Skill tool) — the ledger cannot see those. | Add the name to `keep-on.json` (keep-on outranks nothing here — verify in `_drop_keepoff`) or blocklist the genuine junk instead; re-run `doctor --fix`. |
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
