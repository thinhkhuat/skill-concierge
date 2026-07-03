# Changelog

All notable changes to **skill-concierge**. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); this project is pre-1.0 and evolving.

## [Unreleased]

## [0.12.0] — 2026-07-04

Usefulness-rate upgrades — surface the verdict the enforcer already computes, and get
each skill's BODY-level "when to use" signal into retrieval. Implements the Opus-validated
proposal `plans/reports/proposal-260704-0244-…`. **Operator directive: everything ships
DEFAULT-ON**, each behind an ON-default env kill-switch (rationale + the ADR-0009 risk this
overrides are recorded in `plans/260704-0415-usefulness-rate-upgrades/decisions-audit-log.md`).

### Added
- **AUTHORIZED-SKIP enforcer tier** (`hooks/scripts/enforcer.py`, ADR-0015). The two silent
  verdict legs (getaway `top<floor`, intent_skip conversational) now inject a one-line
  `SKILL-CHECK:` authorization instead of nothing, so the agent stops re-running
  `search_skills` to re-derive a verdict the hook already made. The getaway line keeps the
  burden of proof on SKIP (escalate real/ambiguous work to `find-skills`; `get_skill` nudge).
  Env `ENFORCER_AUTHORIZED_SKIP` (default ON). Fail-silent, additive.
- **Library doctrine** (`hooks/doctrine/skill-first.md`, ADR-0015). Skip = reasoning-based
  intent classification with asymmetric cost; burden of proof on SKIP; ambiguous/no-fit
  escalates to `find-skills`, never a self-declared skip.
- **Body-derived trigger points** (`vendor/skill-search/…`, ADR-0016). Each skill body's
  labeled decision sections (`## When to Use`, `Triggers:`, `Use when:`) are mined for short
  phrases and folded into the existing MAX-pool trigger layer (previously description-only) —
  separate points, deduped, capped COMBINED at `_TRIG_MAX`. Env `SKILL_BODY_TRIGGERS`
  (default ON). Live reindex added +1339 points (2231→3570). Recorded in `VENDORED.md`.

### Changed
- **skill-usage audit** (`skills/skill-usage-audit/…`) now recognises the `SKILL-CHECK:`
  marker: a hook-authorized skip is tallied as `authorized_skip`, excluded from
  false-SKIPPING, keeping the doctrine's hardest-rule metric honest.

## [0.11.1] — 2026-07-01

Staleness self-guards — make two latent staleness vectors impossible to miss, so freshness
never depends on someone remembering to run a command.

### Added
- **doctor `Engine freshness` check** (`scripts/doctor.py`, ADR-0013). Content-hashes the engine
  COPIED into the stable venv against the deployed `vendor/skill-search/skill_search` source. The
  MCP launcher EXECs the engine from that venv (built once by `setup.sh`, not editable), so a
  `/plugin update` ships new code to the cache but never refreshes the venv copy — the MCP could
  serve STALE engine code while `Engine venv ✓`. A mismatch now WARNs → rerun `setup.sh`. Pinned
  by `--selftest`.
- **SessionStart index self-heal** (`hooks/scripts/auto_reindex.py`, ADR-0014). A detached,
  throttled (`AUTO_REINDEX_THROTTLE_S`, default 1800s), incremental reindex fires on session start,
  so a stale index re-freshens itself — no manual reindex, no reliance on discipline. Fail-silent,
  non-blocking; guarded on engine-present + Qdrant-up.

### Changed
- **doctor** SKILL.md (→ 0.2.0): documents the `Engine freshness` row + the "search behaves like an
  old version after an update" symptom shortcut.
- **caveats §6** downgraded to "self-heals" (auto_reindex); new **§11** documents the stale-engine
  landmine + the `diff -rq` decisive test + the `setup.sh` remedy.
- **README** refreshed to `0.11.1` (badge + status), recent trajectory (`0.5.0`→`0.11.1`) and the
  compliance open-question filled in.

### Fixed
- **Docs staleness:** the ADR index was missing `0011` and `0012` (existed on disk, unlisted) —
  added, along with `0013`/`0014`.

## [0.11.0] — 2026-07-01

Gate-prompt upgrade driven by a 5-day transcript analysis: the SKILL-FIRST gate was
~93% compliant on *form* (the line-1 token) but only ~47% on *behavior*. This release
closes the dominant failure modes and adds the telemetry to keep measuring them.

### Changed
- **SKILL-FIRST doctrine rewritten** (`hooks/doctrine/skill-first.md`):
  - **Task-gated the obligation.** `SKIPPING: none` is now lawful on a genuinely no-task turn
    (harness/system notification, await-only ping, an inbound message that hands you no work)
    *without* a search. The old absolute "every reply, no exception" rule was being routed
    around — most skips classified a real task as "exempt" and skipped the required search.
  - **Named the dodges that are NOT exemptions** — self-confident domain judgment, a prior
    turn's search, "you told me to use <tool>" — and stated that a shown candidate means a
    task is present (the no-task class then does not apply). Hardened the agent-dispatch case:
    dispatching work *to* another agent is itself a task.
  - **`SEARCH:` now requires the `search_skills` call in the SAME reply.** Narrating an
    imagined or earlier search ("Search returned nothing…") is a disguised skip.
  - **Prohibited `USING: none`** — an invalid hybrid token agents were emitting; a no-skill
    outcome is `SKIPPING: none`.
  - Welded the skip-bar to the take-bar (a loosely-adaptable fit is a `USING:`, not a skip);
    replaced the unbacked "no token = no reply" line with a self-imposed-protocol framing.
- **Per-turn enforcer strings trimmed** (`hooks/scripts/enforcer.py` `MANDATE` /
  `_ranked_mandate`) toward the per-turn budget — the reasoning lives in the SessionStart
  doctrine. The candidate %-share is relabeled as RELATIVE rank, not confidence.

### Added
- **False-SKIPPING telemetry** (`skills/skill-usage-audit/scripts/audit_skill_usage.py`):
  per-turn detection of a `SKIPPING` declared with no same-turn `search_skills` call — the
  doctrine's hardest rule — plus a `--selftest`. Reproduces the independent diagnostic (~68%).
- **Substantive-compliance line** in `scripts/analyze.py` (used-or-searched vs pure dodge).

### Notes
- **`config/keep-off.json` unchanged by design.** Re-running the auto-generator over its
  post-enrichment window yields no suppressions: the v0.5.0 enrichment already resolved the
  chronic 0-take offers. Hand-editing the auto-generated map is contraindicated (ADR-0011).

## [0.10.2] — 2026-06-30

### Fixed
- **Plugin skills no longer double-prefixed (`ck:ck:…`).** `skills_discovery._namespaced_name`
  unconditionally prepended the plugin id, so a plugin whose frontmatter `name:` already self-namespaces
  (ClaudeKit ships `name: ck:plan`) was indexed as `ck:ck:plan` — 81 live skills, invisible to anything
  keying the correct `ck:<skill>` name (eval corpus, per-skill τ, search/enforcer display). Now skips the
  prefix when the name already starts with `<plugin_id>:`. A reindex applies it (drops the doubles).
- **Per-skill τ calibration now mirrors live MAX-pool.** `calibrate_thresholds.py` scored each prompt
  against a skill's single `base` vector — no longer matching live retrieval (max over base+trigger
  points). Now takes the max cosine over all of a skill's indexed points, and drops the prior `limit:50`
  fetch truncation. With the double-prefix fixed, the eval corpus resolves 14/14 skills (was 4):
  12 ok · 1 weak · 1 no-signal. Per-skill τ stays default-INERT (`ENFORCER_PER_SKILL_TAU` off) — only
  1 of the 12 ok skills clears the 0.45 floor.

## [0.10.1] — 2026-06-30

### Fixed
- **`setup.sh` no longer corrupts the multi-vector index.** It ran `enrich_index.py --reapply`
  unconditionally; on a multi-vector index that MEAN-enriches (corrupts) the base vectors on top of
  the trigger layer. Now guarded behind `SKILL_MULTIVECTOR=0`, mirroring `doctor`'s `fix_reindex`.
  This mattered because re-running `setup.sh` is REQUIRED to refresh the stable venv after the 0.10.0
  update (the venv holds a non-editable COPY of the engine — ADR-0004), so without the guard the very
  step that activates 0.10.0 would have corrupted the index.

### Changed (docs)
- `doctor` SKILL.md check-matrix: added the Enrichment overlay, Multi-vector layer, and Corpus-health
  rows (the table had drifted behind the actual checks).
- `skill-usage-audit` SKILL.md: caveat that the "cosine anti-correlated with adoption" findings were
  measured on the single-vector index; multi-vector ~doubled separation, so re-measure before reuse.

### Notes
- **Activation reality:** the stable venv at `~/.local/share/skill-concierge/venv` is a COPY, refreshed
  only by `setup.sh` — `/plugin marketplace update` + `/reload-plugins` do NOT refresh it. So 0.10.0's
  new retrieval code reaches the live MCP only after re-running `setup.sh` (now safe) + reloading.

## [0.10.0] — 2026-06-30

### Added
- **Multi-vector MAX-pool retrieval — ADR-0012 (the headline).** Each skill is now indexed as a base
  point (`name+desc+body`) PLUS one trigger point per intent phrase from its description, and scored at
  query time by its single BEST point (Qdrant `query/groups`, `group_by=name`, `group_size=1`). This
  imports the BM25-routing design's MAX-pool mechanism the project had missed (it shipped the opposite —
  a dormant MEAN-centroid overlay). Validated on a shadow A/B: **rank-1 2.2×, top-5 1.8×, separation
  2.2×, false-fire flat**. Live index 500→2312 points; groups query ~2 ms. `build_index` builds the
  trigger layer natively (reindex-safe, per-chunk upsert), with a keyword payload index on `name`.
  Gated by `SKILL_MULTIVECTOR` (default ON; `=0` + reindex reverts to one bare vector per skill).
- **`doctor` checks: Multi-vector layer + Corpus health.** The former counts trigger points (and WARNs
  if `SKILL_MULTIVECTOR` is on but the index has none — silent single-vector degradation); the latter
  surfaces the per-skill calibration `ok`/`weak`/`no-signal` fix-list from `eval/thresholds.json`.
- **Per-skill calibrated τ + deterministic route tier — wired, default-INERT.** `enforcer.py` can gate
  an `ok`-calibrated skill on its own τ (`ENFORCER_PER_SKILL_TAU`) or guarantee an exact-substring →
  skill route (`ENFORCER_DETERMINISTIC`, `config/deterministic-routes.json`). Both OFF by default and
  selftested: on the current compressed-cosine band all 5 `ok`-τ sit below the 0.45 floor, so arming τ
  today would add false offers — recalibrate against multi-vector scores first.

### Changed
- **`analyze.py` offered-turn denominator unified to `band=="offer"` — ADR-0011 Open→Resolved.**
  `_offer_conversion` now counts only actually-SHOWN menus (getaway/intent_skip excluded), matching
  `build_keep_off.py`; the shared band-filter is stamped in build_keep_off's window builder so the two
  can never diverge. The global all-turn `dodge` line is unchanged (still a labelled proxy).
- **Getaway floor kept at 0.45.** A floor sweep showed the multi-vector "flooding" was a 0.20-floor
  artifact; at 0.45 crowd-median is 11 (< bare's 34 @0.20) with 64.9% positive-clear, so no re-tune.
- The legacy MEAN enrichment overlay is superseded by the trigger layer; `doctor --fix` no longer runs
  the reapply step when `SKILL_MULTIVECTOR` is on (it would mean-corrupt base vectors).

### Notes
- **Activation:** the persistent skill-search MCP must restart/reconnect to load the new groups code —
  until then its `search_skills` returns duplicate points on the multi-vector index (the enforcer, a
  per-prompt subprocess, already uses the new code).
- Recall lever is proven; the adoption payoff (offered-turn conversion) needs a post-deployment traffic
  window to judge. Independent code-review: no blockers; tester: all selftests green.

## [0.9.0] — 2026-06-29

### Added
- **Ledger-derived offer suppression ("keep-off" map) — ADR-0011.** `scripts/build_keep_off.py`
  derives chronic never-take skills (offered ≥15, take-rate ≤5%) from a POST-ENRICHMENT clean
  window into `config/keep-off.json`; `enforcer.py` hard-drops those names from the offer menu
  (still search-reachable), fail-open. Reuses `analyze._offer_conversion` and counts only
  `band=="offer"` (actually-shown) menus. Ships INERT — on the current clean window zero skills
  qualify (the never-takers were a pre-enrichment artifact), so `keep_off: []`.
- **Runner-up-gap menu collapse (default-OFF).** `enforcer.py` can collapse the offer to the top
  skill when its raw-score gap over the runner-up ≥ `ENFORCER_DOMINANCE_RATIO` (off unless the env
  is set; %-share never concentrates). Collapse decided in `_apply_dominance` so the ledger logs the
  post-collapse menu.

### Notes
- Both features are behavior-inert on merge. Independent review: SHIP-WITH-FIXES (all applied).
  Auto-regen wiring and the `analyze.py` headline-denominator question are deferred operator
  decisions (see ADR-0011 → Open).

## [0.8.0] — 2026-06-29

### Added
- **Vietnamese support in the actionability gate's imperative-veto.** `_is_imperative` now recognizes
  Vietnamese task prompts — a Unicode+NFC tokenizer that keeps diacritics, a VN single-verb +
  two-syllable-bigram lexicon, and VN polite openers (hãy / xin / làm ơn / vui lòng). It was
  English-only, so Vietnamese commands could be wrongly suppressed by the intent gate. (commit 0b065e0)

### Changed
- **Word floor `MAX_SHORT_WORDS` 5 → 3 — ADR-0010 (supersedes ADR-0009's word floor).** Prompts of
  4–5 words now reach the language-aware veto instead of a silent getaway, so short commands (incl.
  Vietnamese) get skill offers; ≤3-word ultra-short trivia is still skipped. Score floor 0.45 unchanged.

## [0.7.1] — 2026-06-29

### Fixed
- **Docs reconciled with the 0.7.0 runtime.** README "How a request flows" now includes the
  enforcer / doctrine / actionability-gate layer (it described only the pre-0.6 ledger→retrieve→curate
  path); Status 0.4.2→0.7.0; AGENTS.md now lists four bundled skills + the in-generation hook layer
  (was "three skills" / "ledger capture").
- **Gate-knob comments de-footgunned** — `enforcer.py` GETAWAY_FLOOR / MAX_SHORT_WORDS no longer say
  "revert to 0.40 / 2" (which invited silently undoing ADR-0009); they point to the ADR.
- **ADR-0008 timeout reconciled** — note added for the 90ms→200ms relaxation (no decision reopened).
- **`build_prompt_intent.py`** documents the in-sample caveat for threshold tuning.

### Added
- **driftcheck guards the prose that drifted** — README Status is now a version mirror, and a
  `skill-list-parity` command-check asserts AGENTS.md names exactly the on-disk bundled skills.

## [0.7.0] — 2026-06-29

### Added
- **`skill-usage-audit` bundled skill — a *valid* usage-measurement arm.** The invocation
  ledger measures gate compliance (offer→take), which the operator flagged INVALID for
  skill-USAGE analysis. This skill ships the correction beside the ledger that tempts the
  misuse: it routes usage questions to the transcript SKILL-FIRST declaration trail
  (`USING`/`SEARCH`/`SKIPPING`) — the signal that captures inline skill use the ledger and
  the usage-tracker both miss — and bundles `scripts/audit_skill_usage.py` (windowed by
  ship-time, self/meta dogfood sessions flagged, builtin slashes excluded). Auto-discovered
  on install; no manifest wiring needed.

## [0.6.1] — 2026-06-29

### Changed
- **Gate thresholds re-tuned by operator order (ADR-0009), against the data-backed
  recommendation.** `MAX_SHORT_WORDS` 2→5 (pre-gate now skips ≤5-word prompts) and
  `GETAWAY_FLOOR` 0.40→0.45 (an offer needs top cosine ≥0.45). Both floors raised to cut
  perceived offer-noise. The ledger+corpus analysis argued against both: the score floor is
  anti-correlated with adoption (taken offers score lower than dodged), and the word floor
  misses the long-form noise (~93% of it is >5 words) while nicking short commands. See
  ADR-0009 for the evidence and the one-line revert (set 2 / 0.40, or
  `ENFORCER_GETAWAY_FLOOR=0.40`). Behaviour change only; both stay env-overridable.

## [0.6.0] — 2026-06-28

### Added
- **Actionability gate (the headline).** A new per-turn gate in the enforcer suppresses an offer
  when the prompt is non-imperative AND leans CONVERSATIONAL over ACTIONABLE in embedding space —
  the conversational/status/meta turns that clear the relevance floor topically but reliably get
  dodged. Prior-independent class-margin rule (mean top-K cosine to each class over a *balanced*
  `prompt_intent` corpus), tuned to ~2% false-suppression of actionable turns on a held-out
  transcript backtest and validated to fire on out-of-distribution prompts. Fail-OPEN everywhere
  (missing collection / imperative / any error -> offer). Logs a new `intent_skip` ledger band.
  Tunable via `ENFORCER_INTENT_MARGIN` / `ENFORCER_INTENT_K`.
- **`scripts/build_prompt_intent.py`** — reproducible build of the gate's grounding corpus: mines
  the transcript store for (prompt -> agent-action) pairs, labels by outcome (Edit/Write or >=3
  tools = actionable; 0 tools = conversational), balances the classes, embeds via the warm shim,
  and (re)builds the `prompt_intent` Qdrant collection. Stdlib, idempotent, fail-soft (too little
  history -> gate fails-open). Wired into `setup.sh` and `doctor.py --fix`.
- `doctor.py` — "Actionability gate" health check (warns when `prompt_intent` is missing/empty and
  the gate is silently failing-open; auto-fixable by rebuilding).

## [0.5.0] — 2026-06-28

### Added
- **Retrieval enrichment (the headline).** Each skill's indexed vector is now enriched with
  query-style trigger phrases (centroid of the stored vector + per-phrase embeddings), so the
  router discriminates the right skill far better. `scripts/build_triggers.py` derives per-skill
  prose-phrase triggers from each skill's description; `scripts/enrich_index.py` applies them via
  the engine fastembed path with an embed-parity gate (cos=1.0 vs the live index), vector-only
  updates (never payload-wiping upsert), a Qdrant snapshot before any live swap, and
  `--shadow`/`--live`/`--revert`/`--reapply` modes. Measured on the eval corpus: correct-skill
  rank-1 ~12%->30% (prose floor; utterance ceiling ~67%), clears-floor and offer quality up.
- `scripts/precision_eval.py` — full 495-way recall + offer-set crowding gate (cross-skill
  confusion matrix + cross-domain true-negatives).
- `eval/scenarios/` labeled corpus + `scripts/calibrate_thresholds.py` per-skill separation harness.
- **Reindex-safe enrichment re-apply.** `enrich_index.py --reapply` (idempotent; recomputes the
  bare base from source text so it cannot double-enrich) is wired into `doctor.py --fix`
  (reindex -> reapply) and `setup.sh`, so a reindex never silently drops the enrichment overlay.
- `doctor.py` — "Enrichment overlay" freshness check (warns when points are un-enriched after a
  reindex, auto-fixable).
- **Drift guard.** `scripts/driftcheck.py` + `driftcheck.json` verify the version triple
  (`plugin.json` <-> `marketplace.json` <-> latest CHANGELOG), that doc-referenced paths exist, and
  that `CLAUDE.md` and `AGENTS.md` name the same scratch dirs (`scripts/check_doc_parity.py`).

### Changed
- **Enforcer offer floor `GETAWAY_FLOOR` 0.20 -> 0.40**, tuned for the enriched score distribution
  (centroid enrichment shifts cosines up; at 0.20 the enriched index over-offers ~2/3 of all
  skills per query). At 0.40 the enriched index offers a live-comparable set with ~79%
  correct-skill-offered vs ~54% before enrichment.

### Fixed
- `doctor.py` duplicate-MCP false positive: the repo's own root `.mcp.json` (unexpanded
  `${CLAUDE_PLUGIN_ROOT}`, auto-loaded as a project MCP only when CWD is the source repo) was
  miscounted as a second install, and the line parser split namespaced server names on the first
  colon. Now excludes template projections and splits on the name/command separator.
- `.gitignore`: added `.handoff/`, generated `eval/` artifacts (`triggers.json`, `thresholds.json`),
  `.pytest_cache/`, `.env`.

## [0.4.2] — 2026-06-27

### Added
- `scripts/analyze.py` — `--since WHEN` / `--until WHEN` flags window the ledger by event
  time (`WHEN` = epoch seconds or local ISO `YYYY-MM-DD[ HH:MM:SS]`), so before/after
  compares (e.g. around a fix or go-live commit time) no longer need hand-splitting the
  ledger. Prints a `window` header; positional-path and no-flag invocations are unchanged;
  stays stdlib-only. Documented in `README.md`, `AGENTS.md`, and the mental-model doc.

### Fixed
- `README.md` ledger example claimed `hit@k` was "pending (needs offer events)" — stale:
  `offer` events land and hit@k computes. Updated the example line and the note.

## [0.4.1] — 2026-06-27

### Fixed
- **`search` events were never logged (0% across all ledger history).** The PostToolUse
  matcher (`hooks/hooks.json`) and the `SEARCH_TOOL` constant (`hooks/scripts/ledger.py`)
  expected the bare `mcp__skill-search__search_skills`, but the live MCP tool is
  plugin-namespaced `mcp__plugin_skill-concierge_skill-search__search_skills` — so the hook
  never fired on searches, blinding the gate's primary "SEARCH before SKIP" lever. Now matches
  by suffix (`endswith`) + a namespace-tolerant matcher regex, so a future namespace change
  can't silently break logging again.
- `analyze.py` docstring freshened: hit@k computes once `offer` events land (they do), no
  longer "pending".

## [0.4.0] — 2026-06-27

### Changed
- **EFFORT decoupled into its own standalone `effort-gate` plugin.** The EFFORT doctrine was
  promoted to a universal plugin applicable to every task, not just skill selection. Removed
  from skill-concierge: the `EFFORT — STANDING ORDER` section of `hooks/doctrine/skill-first.md`,
  the `EFFORT_TRIGGER` from `hooks/scripts/enforcer.py` (per-turn message is SKILL-FIRST only
  again), with the extraction noted in the mental-model doc as design origin. Division of labor:
  **skill-concierge governs which/whether a skill; effort-gate governs how much work.**

## [0.3.1] — 2026-06-27

### Changed
- EFFORT given co-equal per-turn presence: a shared `EFFORT_TRIGGER` re-asserted its gate every
  turn (run every step, cutting work to "save tokens" forbidden, a cut must be named and halted)
  on both the fallback and offer paths. In-generation only, no detection. (Superseded in 0.4.0,
  which extracted EFFORT entirely.)

## [0.3.0] — 2026-06-27

### Added
- **Caveman-style SKILL-FIRST doctrine gate — the other half of caveman's split.** A SessionStart
  hook (`hooks/scripts/doctrine.py`, mirrors `caveman-activate.js`) injects the rich SKILL-FIRST
  standing order, read at runtime from a single-source doctrine file (`hooks/doctrine/skill-first.md`).
  The per-turn enforcer message was reworded from soft persuasion into a cheap **gate trigger**
  (forced line-1 token; "previewed few don't fit → SEARCH the full index, never skip"). Retrieval,
  fallback, and telemetry paths untouched.

### Notes
- Governance is **in-generation only** — no Stop/PostToolUse detection gate. A post-hoc gate was
  rejected by design because it polices already-spent tokens instead of shaping disposition (the
  anti-caveman). The hard finding driving this redesign: retrieval was never the bottleneck —
  compliance is. See `docs/skill-first-enforcement-mental-model.md`.

## [0.2.1] — 2026-06-26

### Changed
- **Enforcer embed timeout 90ms → 200ms, total per-turn budget ≲150ms → ≲300ms**, and the
  embed shim is now **threaded** (`ThreadingHTTPServer`). Live dogfooding (the plugin's own
  ledger) showed ~60% of real turns were hitting `embed_timeout` → mandate-only: the
  single-threaded shim's mpnet inference, under real in-turn CPU contention (concurrent
  UserPromptSubmit hooks + overlapping sessions), slipped past 90ms even though it's ~18ms idle.
  Threading flattens concurrent embeds (8 parallel: 288ms serial → 65ms wall) and the wider
  budget recovers the semantic candidates on the common path; the hook is non-blocking additive
  context so ~250ms worst-case is imperceptible. Both knobs env-overridable
  (`ENFORCER_EMBED_TIMEOUT` float-seconds, `ENFORCER_QDRANT_TIMEOUT`). See ADR-0008.

## [0.2.0] — 2026-06-26

### Added
- **P1 fusion — semantic skill-enforcement (the headline of 0.2.0).** Retires the lexical
  per-turn enforcement hook and points it at the SAME semantic Qdrant index `skill-search` serves:
  - **Warm embed shim** — `scripts/embed_server.py` (stdlib http.server holding fastembed
    mpnet-768 in memory; `POST /embed`, `GET /health`), shipped as a Docker sidecar next to the
    Qdrant container on `127.0.0.1:6363` (`Dockerfile`, `bin/embed-shim`, `setup.sh`). Reuses the
    engine embed path; `vendor/skill-search/pyproject.toml` pins `fastembed==0.8.0` for index
    parity (cosine 1.000000 verified, EN+VN).
  - **Semantic enforcer** — `hooks/scripts/enforcer.py` (UserPromptSubmit): embed → Qdrant top-k →
    inject mandate + semantic candidates; fail-silent, additive-only, never blocks. Hard ~90ms
    client-side embed timeout → mandate-only fallback on embed/Qdrant down or slow (see ADR-0008
    for the 90ms calibration). Replaces the lexical scorer + `library.json`.
  - **Telemetry** — `scripts/analyze.py` catalogue repointed off `library.json` onto the Qdrant
    index; now reports hit@k / fallback rate / bands from new `offer` events.
  - Go-live: lexical `skill_first_nudge.py` deregistered from `~/.claude/settings.json`; this
    plugin version is the live enforcement layer.
- **Maintenance skills** — `skill-concierge:setup` and `skill-concierge:doctor`:
  - `setup` — wraps the idempotent `setup.sh` bootstrap (stable venv, Qdrant, index,
    overrides) for first-time install and post-update refresh, then verifies with doctor.
  - `doctor` — `scripts/doctor.py`, a pure-stdlib deployment-layer health check with safe
    `--fix` (start Qdrant, reindex, re-apply overrides). Delegates the retrieval diagnostic
    to the engine's own `skill-search --health` so the two never drift.
- `scripts/doctor.py` — the diagnostic engine behind the doctor skill (has a `--selftest`).
- `docs/adr/` — Architecture Decision Records (0001–0006) capturing the design rationale:
  model-invocable-only indexing, the WHICH×WHETHER fusion, embedder/Qdrant choice, the MCP
  launcher + stable venv, the overrides applier, and the compounding ledger.
- `docs/caveats.md` — operational landmines (wrong-universe eval, override-generator nuke,
  Qdrant dependency, python-picker, namespacing, reindex, version sync, logman retention).
- `vendor/skill-search/eval/README-LOCAL.md` — loud note that the vendored eval is calibrated
  to the upstream author's environment and its recall@k is not a quality bar here.
- `CHANGELOG.md`.

### Notes
- Both maintenance skills declare `name:` (matching the directory) so Claude Code registers
  them as `skill-concierge:setup` / `skill-concierge:doctor` — the registration pattern proven
  by the existing `skill-search` skill in this deployment (158/159 installed plugin skills use
  it). Descriptions are single-line because the vendored engine parses frontmatter with a regex,
  not a YAML parser, so a `>-` block scalar would leak into the indexed text.
- The ADR/caveats docs slice documents existing reality; the P1 fusion (above) is the
  behavioural change in 0.2.0 — the enforcement organ moved from the lexical scorer to the
  semantic index. See `docs/plan.md` build log, ADR-0002, and ADR-0008.

## [0.1.2] — 2026-06-26

### Fixed
- Keep the bundled router skill `skill-concierge:skill-search` always-on: added it to
  `config/keep-on.json` (32-skill keep-on policy). Without it a cache `setup.sh` rerun could
  revert the router to `name-only`.

## [0.1.1] — 2026-06-26

### Fixed
- Bundled MCP failed to connect (`-32000` / ENOENT). `.mcp.json` had pointed at a venv inside
  the plugin **cache** (wiped on every reinstall). Now `.mcp.json` points at a launcher
  (`bin/skill-search-mcp`) that execs a **stable** venv at `~/.local/share/skill-concierge/venv`,
  surviving plugin cache wipes. (See ADR-0004.)

## [0.1.0] — 2026-06-26

### Added
- Initial scaffold: plugin manifests, README, `.gitignore`.
- Vendored skill-search MCP engine (MIT · sowhan/skill-search) under `vendor/skill-search/`
  with `LICENSE` + `VENDORED.md` attribution and customization log.
- Router skill `skills/skill-search/SKILL.md`.
- Telemetry ledger: `hooks/scripts/ledger.py` + `scripts/analyze.py` (reviewed + tested).
- Reproduction layer: `.mcp.json`, `setup.sh`, `scripts/apply-overrides.py`,
  `config/keep-on.json`.
- Build plan + ops docs under `docs/`.

[Unreleased]: https://github.com/thinhkhuat/skill-concierge/compare/v0.4.2...HEAD
[0.4.2]: https://github.com/thinhkhuat/skill-concierge/compare/v0.4.1...v0.4.2
[0.4.1]: https://github.com/thinhkhuat/skill-concierge/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/thinhkhuat/skill-concierge/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/thinhkhuat/skill-concierge/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/thinhkhuat/skill-concierge/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/thinhkhuat/skill-concierge/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/thinhkhuat/skill-concierge/releases/tag/v0.2.0
[0.1.2]: https://github.com/thinhkhuat/skill-concierge/releases/tag/v0.1.2
[0.1.1]: https://github.com/thinhkhuat/skill-concierge/releases/tag/v0.1.1
[0.1.0]: https://github.com/thinhkhuat/skill-concierge/releases/tag/v0.1.0
