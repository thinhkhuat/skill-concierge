# Operations — setup, health, telemetry, config & deploy

Everything needed to install, keep healthy, measure, configure, and ship skill-concierge. The
loud landmine list is [`docs/caveats.md`](../docs/caveats.md) (canonical — read it before
operating); this page maps the tooling and flags and points into it.

## Bootstrap — `setup.sh`

[`setup.sh`](../setup.sh) is idempotent and safe to re-run; the **`skill-concierge:setup`** skill
runs the same thing and verifies it. Four numbered steps (with sub-steps):

1. **[1/4] Stable venv.** Build a venv at `~/.claude/skill-concierge/venv` (outside the
   wipe-on-reinstall plugin cache — [ADR-0004](../docs/adr/0004-bundled-mcp-launcher-stable-venv.md)),
   pip-install the vendored engine + deps, then `--force-reinstall --no-deps` the engine (the
   vendored version is a static `0.1.0`, so plain pip would see "already satisfied" and skip
   copying changed code — this is the stale-engine trap; see below). Stamps
   `$VENV/.engine-plugin-version` so the launcher can auto-resync after a `/plugin update`.
2. **[2/4] Index owner.** Start the local index owner (`python -m skill_search.index_owner`, from
   the stable venv) — no Docker, no container. It binds `127.0.0.1`/`::1` on port `6333`
   (Qdrant-compatible REST) and `6363` (`/embed`+`/health`+`/jev`); a running owner is stopped and
   restarted first so freshly-reinstalled code takes effect
   ([ADR-0070](../docs/adr/0070-local-index-owner-replaces-qdrant-and-docker-embed-shim.md)).
3. **[3/4] Index.** `skill-search --reindex` (multi-vector built by the reindex itself).
   **[3b/4]** Build the actionability-gate `prompt_intent` corpus (fail-soft).
   The keep-off map is not built here: it is consent-only
   ([ADR-0077](../docs/adr/0077-keep-off-map-is-consent-only.md)).
4. **[4/4] Overrides.** `apply-overrides.py` writes the curated always-on policy to
   `~/.claude/settings.json` (Claude Code's `skillOverrides`). In Codex this step is a harmless
   no-op — Codex doesn't use `skillOverrides`; governance works via the hooks alone.

The model and store are read from [`.mcp.json`](../.mcp.json) as the single source of truth, so
the built index can never diverge from the model the live MCP server uses.

> **`setup.sh` picks the first `python3.12` on PATH** — which on some machines has a broken
> `ensurepip`. If venv creation fails, point the build at a known-good interpreter (`SKILL_PYTHON`)
> or pre-create the stable venv, then re-run. [caveats §4](../docs/caveats.md).

## Health — `doctor.py`

[`scripts/doctor.py`](../scripts/doctor.py) (or the **`skill-concierge:doctor`** skill) is the
read-only deployment health check; a green `status: OK` is the bar to claim "done". The check
list is owned by `CHECKS` in [`scripts/doctor.py`](../scripts/doctor.py) (`check_python` returns
N/A once the venv exists) and delegates the retrieval diagnostic to `skill-search --health` (DRY):
Python, venv, **engine freshness**, running engine, MCP wiring, **the index owner** (`/health` +
`code_version` + its SQLite file's integrity/point counts, ADR-0070), owner ports (FAIL if any
container still publishes 6333/6363), owner log (FAIL on a downgrade or port-conflict line), embed
parity, engine health (stale-but-serving = WARN, not FAIL), multi-vector layer, prompt-intent
corpus, corpus health (reads `eval/thresholds.json`), **retrieval flywheel** (configured? /
reachable? / utterance coverage), trigger hygiene, overrides, blocklist, **keep-off** (report only: no
approved map / unapproved map ignored / approved map active), external catalogs, one row per harness integration, ledger dir,
duplicate-MCP, and MCP reachability. Exit 0 unless a check FAILs.

`--fix` performs only **fast, safe** repairs (`AUTO_FIXERS`): start a stopped index owner (also
stopping + disabling a revived `skill-search-qdrant`/`skill-concierge-embed-shim` container on the
owner's ports), reindex, re-apply overrides, rebuild the prompt-intent corpus, purge junk
utterances. It never builds or refreshes the keep-off map — that is consent-only
([ADR-0077](../docs/adr/0077-keep-off-map-is-consent-only.md)). It **never** rebuilds the
venv or the owner from scratch — heavy bootstrap is handed off to `setup.sh`.
[ADR-0007](../docs/adr/0007-maintenance-skills-setup-doctor.md), [ADR-0013](../docs/adr/0013-doctor-engine-freshness-check.md).

## Telemetry — `analyze.py`

The standing per-epoch watch items (what to monitor, triggers, env-first actions) live in
**[`docs/epoch-watch.md`](../docs/epoch-watch.md)** — the single canonical watching reference;
this section governs the measurement tooling.

[`scripts/analyze.py`](../scripts/analyze.py) is a read-only, **stdlib-only** analyzer over the
append-only ledger at `~/.claude/skill-concierge/logs/skill-invocation-ledger.log`. It reports:
**uptake** (turn used a skill), **search rate**, **dodge** (no skill + no search — the behavior
Enforce exists to kill), **substantive**, **hit@k** (used skill was in the offered set),
**fallback rate** (offers degraded to mandate-only), **offered-turn conversion/dodge** (the clean
compliance denominator — `band=="offer"` turns only), and per-skill offer→take rollups. It pairs
each enforcer `offer` back to its `turn` by `(sid, q-prefix)`, and pulls the real-skill catalogue
live from Qdrant so the real-vs-builtin split can't drift.

```bash
python3 scripts/analyze.py                 # whole ledger (see epoch warning below)
python3 scripts/analyze.py --since "2026-07-05 21:00:00"   # window from a boundary
python3 scripts/analyze.py --until "$T"    # the "before" side of a fix/go-live compare
```

`--since`/`--until` accept epoch seconds or local ISO (`YYYY-MM-DD [HH:MM:SS]`) and filter by
event time; a commit time makes a clean boundary. **Events without a timestamp are dropped in a
windowed run** — only a full-ledger run counts them.

### Reading the ledger: the epoch-scoped trap

**Never cite a ledger rate pooled across config changes.** This repo changes the very things the
ledger measures — gate floors, the retrieval engine, the doctrine, the index owner — *almost
daily*, so the ledger is a **sequence of short config epochs, not one dataset**. An all-time rate
describes *no real configuration*. Before quoting any rate:

1. Find the current epoch start — the last commit touching `hooks/scripts/enforcer.py`,
   `hooks/doctrine/skill-first.md`, `vendor/skill-search/skill_search/server.py`, or
   `vendor/skill-search/skill_search/index_owner.py` (the local index owner, ADR-0070;
   `scripts/embed_server.py` is retired).
2. Window `analyze.py --since "<that datetime>"`. Never quote the all-time number.
3. Exclude contamination — subagent / harness / `<task-notification>` traffic and your own
   meta/self-session turns are not representative.
4. Respect sample size — a fresh epoch may be too small; say **"insufficient data"** rather than
   pool backward.
5. Design vs environment — a shift not aligned to a config commit is environmental (owner
   load/contention), not a property of the code.

An epoch-pooled or tiny-sample rate is **UNMEASURED**, never "measured". This exact mistake once
invalidated a whole multi-agent analysis. Full rule: [`AGENTS.md` → Guardrails](../AGENTS.md). And
remember the ledger measures **gate compliance only** — for real *usage* use the
**`skill-usage-audit`** skill against the transcript SKILL-FIRST trail, not this ledger
([enforcement-gate.md](architecture/enforcement-gate.md#ledger--usage-a-hard-line)). Its script
(`skills/skill-usage-audit/scripts/audit_skill_usage.py`) also takes `--harvest [PATH]` (v0.14.0,
H1, [ADR-0021](../docs/adr/0021-rationalization-harvest-loop.md)): writes the deduped, secret-
scrubbed corpus of verbatim false-skip excuses (`NO SKILL:` clauses, and `SKIPPING:` from before v0.52.0) to a gitignored sink (default
`./logs/skill-rationalizations.txt`), to feed future doctrine authoring — never counts a lawful
hook-authorized skip as a rationalization.

## The local index owner

The per-turn enforcer must embed the prompt in ≲ its budget, and the store must answer in
sub-millisecond time — one local process holds the model **and** the vectors warm in memory,
replacing both the Docker `skill-search-qdrant` container and the Docker warm embed shim with
zero config changes anywhere ([ADR-0070](../docs/adr/0070-local-index-owner-replaces-qdrant-and-docker-embed-shim.md)):

- **Server** [`vendor/skill-search/skill_search/index_owner.py`](../vendor/skill-search/skill_search/index_owner.py):
  a `ThreadingHTTPServer` holding the fastembed mpnet-768 model and every collection's vectors.
  On port `6333` it answers a Qdrant-compatible REST subset (`GET/PUT/DELETE /collections/{c}`,
  `points/scroll`, `points/query`, `points/query/groups`, …) backed by one SQLite file (default
  `~/.cache/skill-search/index.sqlite`, `SKILL_INDEX_DB`), which it alone writes (an exclusive
  `fcntl` lock). On port `6363` it answers `POST /embed {text}` → `{vector[768]}`, `GET /health`,
  and `POST /jev` (the Jev skill router's relay, ported from the retired shim — ADR-0061). It
  reuses the engine's **exact** embed function under the deployed env (a parity contract) so its
  vectors match the live index — otherwise retrieval degrades with no error. Threaded because a
  single-threaded process timed out ~60% of turns under contention when this was still a bare
  embed shim. **fastembed pinned at 0.8.0.**
- **Autostart replaces Docker's restart policy:** [`bin/skill-search-mcp`](../bin/skill-search-mcp)
  starts it when `/health` doesn't answer; the enforcer hook starts it on a refused connection
  (never on a timeout or a 503, which mean busy or loading); `setup.sh` stops and restarts it
  after (re)install. A duplicate start is harmless — the loser of the owner's file lock exits in
  milliseconds. `SKILL_OWNER_AUTOSTART=0` disables both hook-side autostarts.
- **`scripts/embed_server.py`/`bin/embed-shim`** (the old shim) are retired from the live
  deployment path — nothing starts them anymore; their code lives on only as the historical
  starting point `index_owner.py` was grown from (`VENDORED.md`).

Verify health with `curl -s http://127.0.0.1:6363/health` — there is no container to check. A
stopped/slow owner shows up as a sustained `fallback: true` rate in the ledger's `offer` events;
`doctor --fix` starts it (and stops/disables a revived legacy container first, if one is found on
the owner's ports). See [caveats §3, §9](../docs/caveats.md).

## The stale-engine trap (post-update)

Historically the most dangerous silent failure — **self-healing since v0.13.1, and the settled
behavior on every release since (current: v0.20.0).** The v0.13.1 tags below mark where each fix
*shipped*, not the deployed version — confirm the live state with `doctor` (`Engine freshness`),
never by reading a version out of this section. The MCP
launcher ([`bin/skill-search-mcp`](../bin/skill-search-mcp)) execs `skill-search` from the **stable
venv**, where the engine is **copied** into site-packages by `setup.sh` (not an editable install).
A `/plugin update` ships new code into the version-pinned **cache** but historically **never touched
the venv copy** — so the MCP would silently serve old engine code while every surface looked green
(`Engine venv ✓` only proves the bin *exists*, not that it's *current*). This is what left
v0.13.0's query fanout dark after an update.

**v0.13.1 auto-repairs it** ([ADR-0018](../docs/adr/0018-self-healing-launcher-engine-resync.md),
which amends ADR-0013): the launcher stamps the deployed plugin version at
`$VENV/.engine-plugin-version` and, on a version mismatch at spawn, resyncs the engine into the venv
(`pip install --force-reinstall --no-deps`) before exec — an O(1) guard on the fast path, once per
update, best-effort and **fail-open** (a failed resync never blocks the MCP connect). `setup.sh`
force-reinstalls the engine for the same reason: the vendored package's static `0.1.0` version made
a plain `pip install` "already satisfied"-skip the changed copy.

- **Detect (belt-and-suspenders):** `doctor`'s **Engine freshness** check still content-hashes the
  venv engine against the deployed source and WARNs on mismatch ([ADR-0013](../docs/adr/0013-doctor-engine-freshness-check.md)).
- **Residual manual case:** a **dependency** change (not just engine code) still needs a `setup.sh`
  rerun — the launcher resync is `--no-deps`.
- Full symptom→fix background: [caveats §11](../docs/caveats.md).

## Runtime governance flags

All are one-var reverts. Most default ON, with three exceptions: `SKILL_LLM_TRIGGERS` is **off in
code** (but shipped **on** via `.mcp.json` — see the deploy caveat below), `TRIGGERS_MAX` is a
number rather than a boolean, and `SKILL_TRIGGER_PURITY` defaults to a non-boolean `shadow` mode
(log-only, ships inert).

| Variable | Default | Effect | ADR |
|----------|---------|--------|-----|
| `ENFORCER_AUTHORIZED_SKIP` | `1` | enforcer injects a `SKILL-CHECK:` authorization on its silent verdict legs (four since ADR-0054: score-floor miss, conversational, self-recap, harness message) instead of nothing; `=0` restores the old silence | [0015](../docs/adr/0015-authorized-skip-tier-and-library-doctrine.md) |
| `SKILL_BODY_TRIGGERS` | `1` | engine mines each skill body's labeled decision-sections into extra MAX-pool trigger points; `=0` **+ a reindex** reverts to description-only | [0016](../docs/adr/0016-body-derived-trigger-points.md) |
| `SKILL_LLM_TRIGGERS` | `0` | layers offline flywheel-generated natural-utterance phrases (EN+VN) FIRST in the MAX-pool trigger layer; `=1` **+ a reindex** enables (needs `SKILL_TRIGGERS` → the canonical `~/.claude/skill-concierge/triggers.json`) | [0026](../docs/adr/0026-llm-utterance-trigger-layer.md) |
| `TRIGGERS_MAX` | `12` | per-skill COMBINED cap across all trigger sources; live deploy uses `16` so utterances add slots rather than evict desc/body | [0026](../docs/adr/0026-llm-utterance-trigger-layer.md) |
| `ENFORCER_SELFREF_SKIP` | `1` | enforcer pre-authorizes a 3rd AUTHORIZED-SKIP leg for pure self-referential recap turns ("explain your last answer"); `=0` restores the old 2-leg behavior | [0019](../docs/adr/0019-over-fire-lane-and-gate-legibility.md) |
| `ENFORCER_HARNESS_SKIP` | `1` | enforcer pre-authorizes a 4th AUTHORIZED-SKIP leg for harness-generated prompts (`<task-notification>`, `<system-reminder>`, cross-session/teammate messages, interrupted/continued banners, OMP `omp-msum` wrappers) BEFORE any I/O — ledger band `harness_skip`, no chain hint; `=0` routes them like any prompt | [0054](../docs/adr/0054-harness-message-lane-and-audit-fixes.md) |
| `ENFORCER_JEV_ROUTER` | `1` | Jev skill router for English prompts (`TYPESAFE_API_KEY`): whole-catalogue Jev ranking + per-candidate `fits` re-check → top-5 offer; best fit < `ENFORCER_JEV_FITS_FLOOR` (0.30) → 5th AUTHORIZED-SKIP leg (band `jev_skip`); per call `ENFORCER_JEV_TIMEOUT` 1.5 s, whole route `ENFORCER_JEV_BUDGET` 7.8 s (ADR-0079; was 3.0 s); goes through the local index owner's warm `/jev` relay (ADR-0070; ported from the retired Docker embed shim), or through jevd when `JEVD_URL` names one, whose `/ladder` is then the tier list (ADR-0080); the owner's relay also serves Command Code on `/jev/cc` (ADR-0081); any failure → embedding path; `=0` (or `ENFORCER_JEV_GATE=0`) restores the 4-leg ladder | [0061](../docs/adr/0061-jev-skill-router.md) |
| `ENFORCER_DETERMINISTIC` | `1` | `config/deterministic-routes.json` phrases, matched as whole words, pin the named skill to the top of the offer (score 1.0, retrieved twin dropped), computed before embed so a timeout cannot lose it; `=0` disables (was default-inert before v0.47.0) | [0054](../docs/adr/0054-harness-message-lane-and-audit-fixes.md) |
| `ENFORCER_EMBED_TIMEOUT` / `ENFORCER_QDRANT_TIMEOUT` | `0.5` / `0.25` | per-leg hard caps in seconds (0.35 / 0.1 before v0.47.0 — every epoch "outage" was censoring at the old caps) | [0054](../docs/adr/0054-harness-message-lane-and-audit-fixes.md) |
| `SKILL_SUBAGENT_STOP` | `1` | doctrine hook suppresses SessionStart injection inside subagent sessions (positive `agent_id` proof); `=0` injects unconditionally | [0020](../docs/adr/0020-subagent-session-scoping.md) |
| `SKILL_TRIGGER_PURITY` | `shadow` | engine flags workflow-summary body triggers; `shadow` only logs would-drops (index unchanged), `active` drops them (**needs a full reindex**), `off` skips the check | [0023](../docs/adr/0023-trigger-purity-lint.md) |
| `SKILL_PLUGIN_FILTER` | `1` | index **only** the installed + enabled plugin version (read from Claude Code's own `installed_plugins.json` / `enabledPlugins`) instead of every cached version — 548 → 427 skills, nothing invocable lost; `=0` reverts to the unfiltered cache. Fails open on an unreadable manifest | [0028](../docs/adr/0028-multi-session-index-scoping-and-installed-plugin-filter.md) |
| `SKILL_ROW_ORIGIN` | `1` | `search_skills`/`consult_candidates` rows drop `command` and gain `origin` (which harness's roots hold the copy — 8 families incl. `claude-synced`) + `disabled_in` (when an installed Claude Code plugin has every installed copy switched off in its merged `enabledPlugins` layers — the per-turn hook's own rule, so a plugin Claude can run is never marked; account-synced rows list every non-Claude harness) + one response `note`; read per call (query-time, not index-shaping — NOT in the `ENGINE_ENV_KEYS` forward list); `=0` restores the pre-`0.48.0` row shape | [0058](../docs/adr/0058-off-list-rule-exclusion-echo-row-provenance-synced-default-off.md) |
| `SKILL_CONSULT_JEV_WIDEN` | `1` | the consult skill adds Jev's whole-catalogue top 10 for the user's request ahead of the `consult_candidates` rows (top_n 40), deduped, cut to 20 (`scripts/consult_fit.py widen`); script-side, read per call, NOT in `ENGINE_ENV_KEYS`; any Jev failure falls back to the sieve rows; `=0` = sieve rows only, no Jev I/O | [0078](../docs/adr/0078-consult-sieve-jev-widening.md) |
| `SKILL_SYNCED_ROOTS` | `0` | indexes Claude account-synced skills (`~/.claude/skills/synced/<bucket>/<name>/SKILL.md`, exact depth, manifest-listed only) as `anthropic-skills:<name>`, scope `claude-synced`; gated on scope, never the spoofable name; foreign to every harness but Claude, excluded from the cross-harness annex; `=1` **+ a reindex** enables — ships OFF until every harness cache is ≥`0.48.0` (a separate, reviewed step) | [0058](../docs/adr/0058-off-list-rule-exclusion-echo-row-provenance-synced-default-off.md) |

Two enforcer levers are additionally **default-inert** and env-gated (`ENFORCER_PER_SKILL_TAU`,
`ENFORCER_DOMINANCE_RATIO`); `ENFORCER_DETERMINISTIC` is default ON since v0.47.0 (ADR-0054,
config-driven, `=0` disables) and `ENFORCER_HARNESS_SKIP` (default ON) is the harness-message
lane — see
[enforcement-gate.md](architecture/enforcement-gate.md#the-authorized-skip-tier-three-legs-two-formerly-silent).

> **Utterance-layer deploy caveat.** [`.mcp.json`](../.mcp.json) ships `SKILL_LLM_TRIGGERS=1` +
> `TRIGGERS_MAX=16`, but the utterance **corpus** (`~/.claude/skill-concierge/triggers.json`,
> machine-local, **not in the repo** — the repo is public and the corpus is personal data,
> 0.37.0) regenerates only via the flywheel scripts. Its path is pinned in `.mcp.json`
> `SKILL_TRIGGERS` (also the env-less default in every generator and in the vendored engine),
> so a fresh clone enables the flag but degrades gracefully to desc/body triggers until a
> flywheel run generates the corpus. **v0.16.1 fix, unified in v0.48.0:** every index-shaping engine
> setting `.mcp.json` can pin now lives in ONE list (query-time ones such as `SKILL_TOP_K` stay out), `ENGINE_ENV_KEYS` in
> [`scripts/engine_env.py`](../scripts/engine_env.py) — `SKILL_LLM_TRIGGERS`/`TRIGGERS_MAX`/
> `SKILL_TRIGGERS`/`SKILL_BODY_TRIGGERS` plus every other index-shaping setting (store and embedder,
> every harness-root flag, `SKILL_CONCIERGE_CATALOG_ROOTS`, `SKILL_SYNCED_ROOTS`, the plugin-enablement
> seams, the sidecar path) — and all five reindex paths (the detached SessionStart
> [`hooks/scripts/auto_reindex.py`](../hooks/scripts/auto_reindex.py), `auto_flywheel.py`,
> `flywheel.py`, `doctor.py`'s repairs, and `setup.sh`'s `env_run()`) call through it instead of
> each keeping its own copy of the key tuple. Before v0.16.1 the detached reindex rebuilt at engine
> defaults and **pruned the utterance points on every session**
> ([ADR-0026](../docs/adr/0026-llm-utterance-trigger-layer.md), CHANGELOG [0.16.1]); before v0.48.0
> the five copies of that key list had already begun to drift
> ([ADR-0058](../docs/adr/0058-off-list-rule-exclusion-echo-row-provenance-synced-default-off.md)).
## The retrieval flywheel (v0.17.0+, ADR-0027)

The flywheel generates **natural-utterance trigger phrases** (EN+VN) for each skill offline via a
local LLM, then layers them FIRST in the MAX-pool trigger layer (ADR-0026). Without it, retrieval
relies on description + body triggers only — the graceful fallback is unchanged.

**Configuration** (all machine-local, none in the repo):

| Variable | Default | Effect |
|----------|---------|--------|
| `FLYWHEEL_LLM_ENDPOINT` | `http://localhost:4310/v1/chat/completions` | **Set all four `FLYWHEEL_LLM_*` vars in `~/.config/harness-env.sh`** (the cross-harness env file, sourced from `~/.zshenv` + bash entry files) — a `settings.json` `env` entry reaches Claude sessions only and left the flywheel invisible from Codex ([caveats §20](../docs/caveats.md)). The OpenAI-compatible chat endpoint. **This is what "configured" means:** `auto_flywheel.py` treats the presence of `FLYWHEEL_LLM_ENDPOINT` *or* `FLYWHEEL_LLM_MODEL` in the env as the signal to run at all — with neither set it silently no-ops |
| `FLYWHEEL_LLM_API_KEY` | *(unset)* | optional `Authorization: Bearer` → any OpenAI-compatible gateway (LM-Studio, Ollama `/v1`, 3rd-party) |
| `FLYWHEEL_LLM_MODEL` | `gemma-4-e4b-it-qat-optiq` | the generation model (swapped in v0.20.0 from `gemma-4-12b-it-qat-optiq`; MRR `0.231 → 0.462`) |
| `FLYWHEEL_LLM_SCHEMA_MODE` | `json_schema` | `json_schema` / `json_object` / `off` (for endpoints that don't honor strict schemas) |
| `SKILL_AUTO_FLYWHEEL` | `1` | the SessionStart `auto_flywheel` hook generates utterances for new skills when the endpoint is reachable; `=0` disables |
| `AUTO_FLYWHEEL_THROTTLE_S` | `21600` (6h) | minimum interval between auto-flywheel runs |
| `AUTO_FLYWHEEL_MAX_PER_RUN` | `25` | per-run skill cap (avoids one long GPU burn) |

**Usage:**
- **`skill-concierge:flywheel`** skill — status mode (default, read-only) shows endpoint health +
  per-skill utterance coverage; `--generate` runs the incremental generator (only new/changed
  skills call the LLM) then reindexes. A bare `--generate` covers installed skills only (the
  v0.38.0 every-scope default was reverted by ADR-0047);
  `--catalog <alias>` (v0.35.0, ADR-0043) runs ONE catalog's `<alias>:*` skills. `--workers <N>` (v0.35.0,
  default 1 = sequential) fans only the LLM network phase out over N concurrent calls; all file
  writes stay single-writer, and effective gateway load scales with N (measured 16.0 → 1.9
  s/skill at N=4).
- **`auto_flywheel`** SessionStart hook — runs the same generator detached + throttled when a
  local LLM endpoint is configured + reachable; it runs installed skills first, then each
  configured catalog via the v0.35.1 per-alias serial loop (reinstated by ADR-0047), with
  `--workers` (`AUTO_FLYWHEEL_WORKERS`, default 4).
  Every run is recorded in the global manifest
  (`~/.claude/skill-concierge/flywheel-manifest.json`, records carry an explicit `scope` since
  v0.37.0). The regeneration cache lives in the
  canonical durable home (`~/.claude/skill-concierge/.flywheel-cache.json`, v0.18.1 fix — was under
  the versioned cache dir that `/plugin update` wipes).

**v0.35.0 hardening:** `flywheel_llm.chat()` detects the gateway's HTTP-200-wrapped upstream 503
envelope (`[CommandCode error: {… "isRetryable":true}]` with `finish_reason: "stop"`), retries it
on the existing 3-attempt ladder, and raises `URLError` on exhaustion — a sustained outage fails
the skill, never the pass.

**v0.20.0 hardening:** `flywheel_llm.chat()` now raises `TruncatedCompletion` on any explicit
`finish_reason != "stop"` — a truncated completion previously surfaced as an opaque `JSONDecodeError`
that the catch-loop silently swallowed, costing that skill its triggers. See
`references/flywheel-llm-providers.md` for provider setup.

## Configuration files

| File | Purpose |
|------|---------|
| [`.mcp.json`](../.mcp.json) | registers the MCP; single source of truth for embed backend/model, the local index owner's Qdrant-compatible URL, `SKILL_TOP_K=10` |
| [`config/keep-on.json`](../config/keep-on.json) | the **shipped SEED** for the curated always-on allowlist (**32 entries** in `keep_on`); on first run it is seeded once into the canonical durable home `~/.claude/skill-concierge/keep-on.json` (survives `/plugin update`, [ADR-0025](../docs/adr/0025-autonomous-override-freshness-and-keep-on-management.md)). [`scripts/apply-overrides.py`](../scripts/apply-overrides.py) writes the policy to `~/.claude/settings.json` (atomic, backs up, refuses empty). Curate it with the `keep-on` skill / `scripts/keep-on.py`. **Do not** run the upstream `generate_overrides.py` — [caveats §2](../docs/caveats.md), [ADR-0005](../docs/adr/0005-overrides-target-and-applier.md) |
| [`config/keep-off.json`](../config/keep-off.json) | the **empty seed** for ledger-derived offer-suppression — chronic never-take skills dropped from the enforcer menu ([ADR-0011](../docs/adr/0011-ledger-derived-offer-suppression.md)); since v0.47.0 the generated map lives in `~/.claude/skill-concierge/keep-off.json` (durable home; consent-only — saved by `build_keep_off.py --apply` after Thinh's yes, honoured only with `"approved_by_user": true`, never regenerated by `doctor --fix` or `setup.sh`; harness-shaped offers excluded, keep-on members exempt — [ADR-0077](../docs/adr/0077-keep-off-map-is-consent-only.md), [ADR-0054](../docs/adr/0054-harness-message-lane-and-audit-fixes.md)) |
| `~/.claude/skill-concierge/blocklist.json` | the **user-ordered disable tier** ([ADR-0046](../docs/adr/0046-blocklist-disable-tier.md)) — flat `{"blocked": [...]}`, absent = no-op, **never seeded**. Enforced at four layers: PreToolUse(Skill) **deny** (`hooks/scripts/skill_guard.py`, the plugin-level gate), enforcer offers/hints/routes, engine search-filter + `get_skill` refusal (live-read, index-neutral), and an apply-overrides strip of blocked keep-on names. Bare entry blocks every qualified twin; qualified entry is exact-only. Manage with the `blocklist` skill / `scripts/blocklist.py`; kill-switch `SKILL_BLOCKLIST=0` |
| `~/.claude/skill-concierge/reputation.json` | the **owner's ranking** ([ADR-0083](../docs/adr/0083-owner-reputation-badges.md)) — `{"heart": [...], "star": [...]}`, exact names or patterns, never seeded. Renders ❤️/⭐ next to menu rows without moving them and pulls a ranked skill Jev placed 6th-10th (`fits` ≥ 0.5) under the five rows. Manage with the `reputation` skill / `scripts/reputation.py`; kill-switch `SKILL_REPUTATION=0` |
| `~/.claude/skill-concierge/proven.json` | the 🔥 digest ([ADR-0083](../docs/adr/0083-owner-reputation-badges.md)) — skills invoked in ≥ 5 distinct sessions in 30 days, written by `auto_promote.py` at session start (throttled); advisory, fail-open |
| [`config/deterministic-routes.json`](../config/deterministic-routes.json) | exact-route overrides — **default ON since v0.47.0** ([ADR-0054](../docs/adr/0054-harness-message-lane-and-audit-fixes.md)): a named skill leads the offer at 1.0, computed before embed; `ENFORCER_DETERMINISTIC=0` disables; seeded with the audited named-and-missed prompts |
| `triggers-curated.json` (beside `SKILL_TRIGGERS`, no env var of its own) | operator-curated trigger phrases — `{"<skill>": ["phrase", …]}` replayed from real routing misses, take the FIRST trigger slots within `TRIGGERS_MAX` ([ADR-0058](../docs/adr/0058-off-list-rule-exclusion-echo-row-provenance-synced-default-off.md)); absent file is byte-identical, a malformed one fails open with one stderr line; no doctor row (the ADR-0030 operator-owned-file precedent) |

`apply-overrides.py` uses the **same** discovery module as the index, so overrides and the
retriever never drift, and it reports any `keep_on` entry missing on the target machine (the list
is catalogue-specific). It stays fresh on its own: the SessionStart `auto_overrides.py` hook runs
`apply-overrides.py --if-changed` on catalogue drift, and `doctor` flags drift via `--check`
([ADR-0025](../docs/adr/0025-autonomous-override-freshness-and-keep-on-management.md)). Curate the
allowlist with the `keep-on` skill / `scripts/keep-on.py` (`list` / `add` / `remove`, reconciles
immediately).

The **blocklist** is the third list and the only *disable*: keep-on and keep-off curate
attention, the blocklist removes the skill from every concierge surface and denies its
invocation ([ADR-0046](../docs/adr/0046-blocklist-disable-tier.md)). It is the sole mechanism
that also covers command-files surfaced as skills (`~/.claude/commands/*.md`), which the index
deliberately excludes (ADR-0001) — only the invocation guard can catch those. Edits apply
live (read at call time; no reindex, no restart) and the list is index-neutral, so unblocking
is instant.

## Commit guardrails — two `PreToolUse(Bash)` hooks

(A third denying gate exists at the PLUGIN level, not project scope: the ADR-0046
`skill_guard.py` `PreToolUse(Skill)` blocklist guard in `hooks/hooks.json` — covered in
*Configuration files* above.)

Both are wired in [`.claude/settings.json`](../.claude/settings.json) (project scope, **not** the
plugin's `hooks/hooks.json` — a plugin hook would fire in every project the plugin is enabled in,
where these paths don't exist). `.claude/settings.json` is un-ignored on purpose (`.gitignore`:
`.claude/*` + `!.claude/settings.json`) so the wiring exists on every clone.

They intercept the **agent's own `git commit` tool call**, not the shell — a `PreToolUse` verdict
lands in the agent's context with the reason and the fix, so it corrects course. Both match on
`Bash` (not `Bash(git commit*)`, which would miss the compound `git add . && git commit`), let
non-commit calls pass silently, and **fail open** on any internal error.

| Hook | Verdict | Checks | Override |
|------|---------|--------|----------|
| [`scripts/openwiki_parity_guard.py`](../scripts/openwiki_parity_guard.py) | **DENY** | version parity (delegated to `driftcheck.py` — the wiki's `**Version:**` line is registered as one more mirror, so there is no second version checker to drift) + every relative link under `openwiki/` resolves on disk | `OPENWIKI_GUARD=0` |
| [`scripts/graph_staleness_notice.py`](../scripts/graph_staleness_notice.py) | **WARN — never blocks** | which **git-tracked** files are new/modified since `graphify-out/manifest.json`, via graphify's own `detect_incremental()` | `GRAPH_NOTICE=0` |

**Why one denies and the other only warns.** `openwiki/` is *committed*: a stale wiki ships to
every clone and gets read as authoritative, and the fix is a sub-second text edit — blocking is
proportionate. `graphify-out/` is *gitignored*: it never ships, so a stale graph harms only the
local session, and the fix is asymmetric — code drift rebuilds via AST for free, but doc drift
costs LLM calls. This repo is doc-heavy and writes plans/reports constantly, so a deny there would
tax every commit and buy nothing the post-commit rebuild already gives. **A gate must be
proportionate to the harm and the cost of the fix.**

Two further design notes, both load-bearing:

- The notice never emits `permissionDecision`. An `"allow"` there would auto-approve *every*
  `git commit` and silently disable the permission prompt — a far worse bug than a stale graph.
  It uses `additionalContext` (reaches the agent) + `systemMessage` (reaches the user).
- It is scoped to **git-tracked files only**. graphify indexes scratch dirs (`.remember/`,
  `.memsearch/`, `.gjc/`) that churn every turn; unscoped, it would fire on *every* commit forever,
  and a warning that always fires is one you train yourself to ignore.

Neither guard judges whether prose is *semantically* current — nothing cheap can, and a guard
pretending to would be theater. They enforce what is mechanically decidable; refreshing the
content is what `/openwiki:wiki update` and `/graphify . --update` are for.

**Graph freshness** is otherwise maintained by graphify's own git hooks (`graphify hook install`
→ post-commit + post-checkout): after each commit it re-runs AST on changed **code** files and
rebuilds the graph — free, no LLM. It deliberately ignores doc changes, which is exactly the gap
the notice covers. Check with `graphify hook status`.

This section reconciles with the repo's fail-silent hook doctrine: the notice is telemetry and
never blocks; the openwiki guard is the **sole deliberate exception** that denies.

## Versioning & deploy discipline

- **Bump ALL OF `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `.codex-plugin/plugin.json`, AND root `package.json` versions together, plus a `CHANGELOG.md` entry.** Never bump one
  alone — the downstream update keys on the version, so a mismatch is a silent no-op
  ([caveats §7](../docs/caveats.md)). `package.json` carries the OMP extension hook
  (`omp.extensions`) and is versioned in lockstep even though `driftcheck` does not regex it.
- **A repo edit does not go live by itself:** bump the manifests, push to GitHub, then
  `/plugin update` + restart — the runtime reads a version-pinned cache. As of v0.13.1 the launcher
  auto-resyncs the venv engine on an engine-code change; a **dependency** change still needs a
  `setup.sh` rerun (see [the stale-engine trap](#the-stale-engine-trap-post-update)).
- **Drift guard:** `python3 scripts/driftcheck.py driftcheck.json` (exit 0 = synced) checks the
  version across all six sources (`plugin.json` ↔ `marketplace.json` ↔ `.codex-plugin/plugin.json`
  ↔ latest `CHANGELOG.md` heading ↔ `README.md` ↔ `openwiki/quickstart.md`), that every
  doc-referenced path exists, and that `AGENTS.md` / `CLAUDE.md` name the same scratch dirs. Run it
  after a version bump or after editing a fact shared across docs.
- **ADRs are immutable** — supersede with a new one, never edit an accepted record.
- **Tool state is not source:** `.ijfw/`, `ijfw/`, `.handoff/`, `logs/`, `graphify-out/` are gitignored scratch.
- **The vendored engine** must not diverge from upstream silently — log any customization in
  [`vendor/skill-search/VENDORED.md`](../vendor/skill-search/VENDORED.md).
- **Non-Claude adapters are copies, not live links — a repo change needs a reinstall to reach
  them.** Command Code's mod (`adapters/commandcode/skill-concierge.mod.ts`) is copied into
  `~/.commandcode/…` by [`adapters/commandcode/install.sh`](../adapters/commandcode/install.sh);
  a repo-side change — such as `0.49.0`'s exclusion echo reaching Command Code
  ([ADR-0059](../docs/adr/0059-harness-complete-offer-isolation-echo-everywhere.md)) — does not
  take effect there until that installer reruns (since `0.49.0`, `doctor`'s Command Code row warns
  when the installed mod differs from the repo copy). Cline's hook shims `require()` the repo's
  bridge, so it picks up a change immediately; OMP loads the adapter from its plugin cache, so it
  needs that cache refreshed. **DSH** loads everything through its profile patch layer:
  [`adapters/dsh/install.sh`](../adapters/dsh/install.sh) writes the skill-search MCP server, the unlazy
  stop-hook and the enforcement plugin into each profile's `cordis.patch.yml` as `- insert:` patches
  (a bare `- id:` only overrides an existing entry and is skipped), then checks each file with DSH's own
  YAML parser; `doctor`'s DSH row flags a patch file DSH cannot load. Re-run the installer after
  changing it; DSH picks the plugin up at its next start
  ([ADR-0050](../docs/adr/0050-dsh-hexa-harness-parity.md) §5, ADR-0059 §4).
- **Codex and Claude Code plugin caches are also copies, refreshed only by their own installer.**
  [`adapters/codex/install.sh`](../adapters/codex/install.sh) refreshes the Codex marketplace
  clone under `~/.codex/plugins/cache/skill-concierge/skill-concierge/<ver>/` to the SSOT version
  via `codex plugin marketplace upgrade` then `codex plugin add` — there is no
  `codex plugin upgrade` verb, and this installer never calls `remove`: a bare `add` refreshes
  an existing install in place, and a failed `add` never uninstalls the previous copy (both
  verified live). The CLI installs whatever is pushed to the git remote, and a successful `add`
  was verified live to wipe the plugin's ENTIRE cache dir (every version and staging dir) before
  installing the fresh one. A remaining version gap falls back to a `git archive HEAD` export
  into a NEW version-named cache dir instead — this fallback step itself never deletes anything
  (Codex resolves the semver-newest by scanning, not a registry) — with a loud unpushed-content
  notice; a live session actually loading hooks/MCP from that dir is unverified beyond
  `codex plugin list`. Codex also has no CLI to disable a plugin or keep one disabled through a
  refresh, so if the plugin is already disabled the installer refuses right away, before
  `marketplace upgrade` or `add` runs — no mutating CLI call is made — rather than refreshing it
  first and only complaining afterward.
  [`adapters/claude-code/install.sh`](../adapters/claude-code/install.sh) refreshes
  `~/.claude/plugins/cache/skill-concierge/skill-concierge/<ver>/` via
  `claude plugin update skill-concierge@skill-concierge --json -y`, refusing a downgrade both before
  and after that call, falling back to a local `git archive` sync plus a backed-up,
  atomically-written `installed_plugins.json` repoint when the marketplace remote hasn't caught
  up to this checkout yet (never touching `enabledPlugins` or the shared venv — a session
  restart is required either way). Whether Claude Code accepts a hand-repointed registry entry
  is unverified (the tests use a fake `claude`). `doctor`'s Codex and Claude Code rows both warn
  when the cached content lags the SSOT.

## See also

- [`docs/caveats.md`](../docs/caveats.md) — the landmine list (canonical).
- [`docs/adr/README.md`](../docs/adr/README.md) — the decisions behind these choices.
- [`README.md` → Troubleshooting](../README.md) — the symptom→fix table.
