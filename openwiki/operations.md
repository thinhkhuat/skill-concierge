# Operations — setup, health, telemetry, config & deploy

Everything needed to install, keep healthy, measure, configure, and ship skill-concierge. The
loud landmine list is [`docs/caveats.md`](../docs/caveats.md) (canonical — read it before
operating); this page maps the tooling and flags and points into it.

## Bootstrap — `setup.sh`

[`setup.sh`](../setup.sh) is idempotent and safe to re-run; the **`skill-concierge:setup`** skill
runs the same thing and verifies it. Four steps:

1. **[1/4] Stable venv.** Build a venv at `~/.claude/skill-concierge/venv` (outside the
   wipe-on-reinstall plugin cache — [ADR-0004](../docs/adr/0004-bundled-mcp-launcher-stable-venv.md)),
   pip-install the vendored engine + deps, then `--force-reinstall --no-deps` the engine (the
   vendored version is a static `0.1.0`, so plain pip would see "already satisfied" and skip
   copying changed code — this is the stale-engine trap; see below). Stamps
   `$VENV/.engine-plugin-version` so the launcher can auto-resync after a `/plugin update`.
2. **[2/4] Qdrant.** Start the `skill-search-qdrant` Docker container (image `qdrant/qdrant:1.18.2`,
   `localhost:6333`). **[2b/4]** Build + run the warm embed shim as a Docker sidecar
   (`skill-concierge-embed-shim`, bound `127.0.0.1:6363`; skipped if already listening).
3. **[3/4] Index.** `skill-search --reindex` (multi-vector built by the reindex itself).
   **[3b/4]** Build the actionability-gate `prompt_intent` corpus (fail-soft).
4. **[4/4] Overrides.** `apply-overrides.py` writes the curated always-on policy to
   `~/.claude/settings.json`.

The model and store are read from [`.mcp.json`](../.mcp.json) as the single source of truth, so
the built index can never diverge from the model the live MCP server uses.

> **`setup.sh` picks the first `python3.12` on PATH** — which on some machines has a broken
> `ensurepip`. If venv creation fails, point the build at a known-good interpreter (`SKILL_PYTHON`)
> or pre-create the stable venv, then re-run. [caveats §4](../docs/caveats.md).

## Health — `doctor.py`

[`scripts/doctor.py`](../scripts/doctor.py) (or the **`skill-concierge:doctor`** skill) is the
read-only deployment health check; a green `status: OK` is the bar to claim "done". It runs **14
checks** (`check_python` returns N/A once the venv exists, so a healthy deploy shows 13) and
delegates the retrieval diagnostic to `skill-search --health` (DRY): Python, venv, **engine
freshness**, MCP wiring, Qdrant, engine health (stale-but-serving = WARN, not FAIL), enrichment,
multi-vector layer, prompt-intent corpus, corpus health (reads `eval/thresholds.json`), **retrieval
flywheel** (configured? / reachable? / utterance coverage), overrides, ledger dir, and
duplicate-MCP. Exit 0 unless a check FAILs.

`--fix` performs only **fast, safe** repairs (`AUTO_FIXERS`): start a stopped Qdrant, reindex,
re-apply the enrichment overlay, re-apply overrides, rebuild the prompt-intent corpus. It **never**
rebuilds the venv or the container — heavy bootstrap is handed off to `setup.sh`.
[ADR-0007](../docs/adr/0007-maintenance-skills-setup-doctor.md), [ADR-0013](../docs/adr/0013-doctor-engine-freshness-check.md).

## Telemetry — `analyze.py`

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
ledger measures — gate floors, the retrieval engine, the doctrine, the embed shim — *almost
daily*, so the ledger is a **sequence of short config epochs, not one dataset**. An all-time rate
describes *no real configuration*. Before quoting any rate:

1. Find the current epoch start — the last commit touching `hooks/scripts/enforcer.py`,
   `hooks/doctrine/skill-first.md`, `vendor/skill-search/skill_search/server.py`, or
   `scripts/embed_server.py`.
2. Window `analyze.py --since "<that datetime>"`. Never quote the all-time number.
3. Exclude contamination — subagent / harness / `<task-notification>` traffic and your own
   meta/self-session turns are not representative.
4. Respect sample size — a fresh epoch may be too small; say **"insufficient data"** rather than
   pool backward.
5. Design vs environment — a shift not aligned to a config commit is environmental (shim/Docker/
   load), not a property of the code.

An epoch-pooled or tiny-sample rate is **UNMEASURED**, never "measured". This exact mistake once
invalidated a whole multi-agent analysis. Full rule: [`AGENTS.md` → Guardrails](../AGENTS.md). And
remember the ledger measures **gate compliance only** — for real *usage* use the
**`skill-usage-audit`** skill against the transcript SKILL-FIRST trail, not this ledger
([enforcement-gate.md](architecture/enforcement-gate.md#ledger--usage-a-hard-line)). Its script
(`skills/skill-usage-audit/scripts/audit_skill_usage.py`) also takes `--harvest [PATH]` (v0.14.0,
H1, [ADR-0021](../docs/adr/0021-rationalization-harvest-loop.md)): writes the deduped, secret-
scrubbed corpus of verbatim false-skip `SKIPPING:` excuses to a gitignored sink (default
`./logs/skill-rationalizations.txt`), to feed future doctrine authoring — never counts a lawful
hook-authorized skip as a rationalization.

## The warm embed shim

The per-turn enforcer must embed the prompt in ≲ its budget, so the model is held warm in memory
by a Docker sidecar rather than cold-loaded per turn:

- **Server** [`scripts/embed_server.py`](../scripts/embed_server.py): a `ThreadingHTTPServer`
  holding the fastembed mpnet-768 model; `POST /embed {text}` → `{vector[768]}`, `GET /health`. It
  reuses the engine's **exact** embed function under the deployed env (a parity contract) so its
  vectors match the live index — otherwise retrieval degrades with no error. Threaded because a
  single-threaded shim timed out ~60% of turns under contention. **fastembed pinned at 0.8.0.**
- **Launcher** [`bin/embed-shim`](../bin/embed-shim): execs the stable venv's python with the
  deployed embed env.
- **Container:** `skill-concierge-embed-shim` on `127.0.0.1:6363`, `--restart unless-stopped`.

Verify health with `docker ps --filter name=skill-concierge-embed-shim` (the name is
env-overridable via `SKILL_EMBED_CONTAINER`, [`setup.sh:21`](../setup.sh)). A stopped/slow shim
shows up as a sustained `fallback: true` rate in the ledger's `offer` events; `doctor --fix`
restarts it. See [caveats §9](../docs/caveats.md).

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
| `ENFORCER_AUTHORIZED_SKIP` | `1` | enforcer injects a `SKILL-CHECK:` authorization on its two formerly-silent verdict legs instead of nothing; `=0` restores the old silence | [0015](../docs/adr/0015-authorized-skip-tier-and-library-doctrine.md) |
| `SKILL_BODY_TRIGGERS` | `1` | engine mines each skill body's labeled decision-sections into extra MAX-pool trigger points; `=0` **+ a reindex** reverts to description-only | [0016](../docs/adr/0016-body-derived-trigger-points.md) |
| `SKILL_LLM_TRIGGERS` | `0` | layers offline flywheel-generated natural-utterance phrases (EN+VN) FIRST in the MAX-pool trigger layer; `=1` **+ a reindex** enables (needs `SKILL_TRIGGERS` → `eval/triggers.json`) | [0026](../docs/adr/0026-llm-utterance-trigger-layer.md) |
| `TRIGGERS_MAX` | `12` | per-skill COMBINED cap across all trigger sources; live deploy uses `16` so utterances add slots rather than evict desc/body | [0026](../docs/adr/0026-llm-utterance-trigger-layer.md) |
| `ENFORCER_SELFREF_SKIP` | `1` | enforcer pre-authorizes a 3rd AUTHORIZED-SKIP leg for pure self-referential recap turns ("explain your last answer"); `=0` restores the old 2-leg behavior | [0019](../docs/adr/0019-over-fire-lane-and-gate-legibility.md) |
| `SKILL_SUBAGENT_STOP` | `1` | doctrine hook suppresses SessionStart injection inside subagent sessions (positive `agent_id` proof); `=0` injects unconditionally | [0020](../docs/adr/0020-subagent-session-scoping.md) |
| `SKILL_TRIGGER_PURITY` | `shadow` | engine flags workflow-summary body triggers; `shadow` only logs would-drops (index unchanged), `active` drops them (**needs a full reindex**), `off` skips the check | [0023](../docs/adr/0023-trigger-purity-lint.md) |
| `SKILL_PLUGIN_FILTER` | `1` | index **only** the installed + enabled plugin version (read from Claude Code's own `installed_plugins.json` / `enabledPlugins`) instead of every cached version — 548 → 427 skills, nothing invocable lost; `=0` reverts to the unfiltered cache. Fails open on an unreadable manifest | [0028](../docs/adr/0028-multi-session-index-scoping-and-installed-plugin-filter.md) |

Several enforcer levers are additionally **default-inert** and env-gated (`ENFORCER_DETERMINISTIC`,
`ENFORCER_PER_SKILL_TAU`, `ENFORCER_DOMINANCE_RATIO`) — see
[enforcement-gate.md](architecture/enforcement-gate.md#the-authorized-skip-tier-three-legs-two-formerly-silent).

> **Utterance-layer deploy caveat.** [`.mcp.json`](../.mcp.json) ships `SKILL_LLM_TRIGGERS=1` +
> `TRIGGERS_MAX=16`, but the utterance **corpus** (`eval/triggers.json`, ~733 KB, **gitignored** —
> it regenerates from the flywheel scripts) is **not** in the repo, and its path is read from
> `SKILL_TRIGGERS`, which lives **machine-local** in `~/.claude/settings.json` `env` — not in
> `.mcp.json`. So a fresh clone enables the flag but degrades gracefully to desc/body triggers
> until `SKILL_TRIGGERS` points at a generated `triggers.json`. **v0.16.1 fix:** the detached
> SessionStart `auto_reindex` hook ([`hooks/scripts/auto_reindex.py`](../hooks/scripts/auto_reindex.py)
> `_mcp_env()`) now forwards `SKILL_LLM_TRIGGERS`/`TRIGGERS_MAX`/`SKILL_TRIGGERS`/`SKILL_BODY_TRIGGERS`
> to the background reindex — before that it rebuilt at engine defaults and **pruned the utterance
> points on every session** ([ADR-0026](../docs/adr/0026-llm-utterance-trigger-layer.md), CHANGELOG
> [0.16.1]).
## The retrieval flywheel (v0.17.0+, ADR-0027)

The flywheel generates **natural-utterance trigger phrases** (EN+VN) for each skill offline via a
local LLM, then layers them FIRST in the MAX-pool trigger layer (ADR-0026). Without it, retrieval
relies on description + body triggers only — the graceful fallback is unchanged.

**Configuration** (all machine-local, none in the repo):

| Variable | Default | Effect |
|----------|---------|--------|
| `FLYWHEEL_LLM_ENDPOINT` | `http://localhost:4310/v1/chat/completions` | the OpenAI-compatible chat endpoint. **This is what "configured" means:** `auto_flywheel.py` treats the presence of `FLYWHEEL_LLM_ENDPOINT` *or* `FLYWHEEL_LLM_MODEL` in the env as the signal to run at all — with neither set it silently no-ops |
| `FLYWHEEL_LLM_API_KEY` | *(unset)* | optional `Authorization: Bearer` → any OpenAI-compatible gateway (LM-Studio, Ollama `/v1`, 3rd-party) |
| `FLYWHEEL_LLM_MODEL` | `gemma-4-e4b-it-qat-optiq` | the generation model (swapped in v0.20.0 from `gemma-4-12b-it-qat-optiq`; MRR `0.231 → 0.462`) |
| `FLYWHEEL_LLM_SCHEMA_MODE` | `json_schema` | `json_schema` / `json_object` / `off` (for endpoints that don't honor strict schemas) |
| `SKILL_AUTO_FLYWHEEL` | `1` | the SessionStart `auto_flywheel` hook generates utterances for new skills when the endpoint is reachable; `=0` disables |
| `AUTO_FLYWHEEL_THROTTLE_S` | `21600` (6h) | minimum interval between auto-flywheel runs |
| `AUTO_FLYWHEEL_MAX_PER_RUN` | `25` | per-run skill cap (avoids one long GPU burn) |

**Usage:**
- **`skill-concierge:flywheel`** skill — status mode (default, read-only) shows endpoint health +
  per-skill utterance coverage; `--generate` runs the incremental generator (only new/changed
  skills call the LLM) then reindexes.
- **`auto_flywheel`** SessionStart hook — runs the same generator detached + throttled when a
  local LLM endpoint is configured + reachable. Every run is recorded in the global manifest
  (`~/.claude/skill-concierge/flywheel-manifest.json`). The regeneration cache lives in the
  canonical durable home (`~/.claude/skill-concierge/.flywheel-cache.json`, v0.18.1 fix — was under
  the versioned cache dir that `/plugin update` wipes).

**v0.20.0 hardening:** `flywheel_llm.chat()` now raises `TruncatedCompletion` on any explicit
`finish_reason != "stop"` — a truncated completion previously surfaced as an opaque `JSONDecodeError`
that the catch-loop silently swallowed, costing that skill its triggers. See
`references/flywheel-llm-providers.md` for provider setup.

## Configuration files

| File | Purpose |
|------|---------|
| [`.mcp.json`](../.mcp.json) | registers the MCP; single source of truth for embed backend/model, Qdrant URL, `SKILL_TOP_K=10` |
| [`config/keep-on.json`](../config/keep-on.json) | the **shipped SEED** for the curated always-on allowlist (**32 entries** in `keep_on`); on first run it is seeded once into the canonical durable home `~/.claude/skill-concierge/keep-on.json` (survives `/plugin update`, [ADR-0025](../docs/adr/0025-autonomous-override-freshness-and-keep-on-management.md)). [`scripts/apply-overrides.py`](../scripts/apply-overrides.py) writes the policy to `~/.claude/settings.json` (atomic, backs up, refuses empty). Curate it with the `keep-on` skill / `scripts/keep-on.py`. **Do not** run the upstream `generate_overrides.py` — [caveats §2](../docs/caveats.md), [ADR-0005](../docs/adr/0005-overrides-target-and-applier.md) |
| [`config/keep-off.json`](../config/keep-off.json) | ledger-derived offer-suppression — chronic never-take skills dropped from the enforcer menu ([ADR-0011](../docs/adr/0011-ledger-derived-offer-suppression.md)) |
| [`config/deterministic-routes.json`](../config/deterministic-routes.json) | optional exact-route overrides — **inert unless `ENFORCER_DETERMINISTIC` is set** |

`apply-overrides.py` uses the **same** discovery module as the index, so overrides and the
retriever never drift, and it reports any `keep_on` entry missing on the target machine (the list
is catalogue-specific). It stays fresh on its own: the SessionStart `auto_overrides.py` hook runs
`apply-overrides.py --if-changed` on catalogue drift, and `doctor` flags drift via `--check`
([ADR-0025](../docs/adr/0025-autonomous-override-freshness-and-keep-on-management.md)). Curate the
allowlist with the `keep-on` skill / `scripts/keep-on.py` (`list` / `add` / `remove`, reconciles
immediately).

## Commit guardrails — two `PreToolUse(Bash)` hooks

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

- **Bump BOTH `.claude-plugin/plugin.json` AND `.claude-plugin/marketplace.json` versions
  together, plus a `CHANGELOG.md` entry.** Never bump one alone — the downstream update keys on the
  version, so a mismatch is a silent no-op ([caveats §7](../docs/caveats.md)).
- **A repo edit does not go live by itself:** bump the manifests, push to GitHub, then
  `/plugin update` + restart — the runtime reads a version-pinned cache. As of v0.13.1 the launcher
  auto-resyncs the venv engine on an engine-code change; a **dependency** change still needs a
  `setup.sh` rerun (see [the stale-engine trap](#the-stale-engine-trap-post-update)).
- **Drift guard:** `python3 scripts/driftcheck.py driftcheck.json` (exit 0 = synced) checks the
  version triple (`plugin.json` ↔ `marketplace.json` ↔ latest `CHANGELOG.md` heading), that every
  doc-referenced path exists, and that `AGENTS.md` / `CLAUDE.md` name the same scratch dirs. Run it
  after a version bump or after editing a fact shared across docs.
- **ADRs are immutable** — supersede with a new one, never edit an accepted record.
- **Tool state is not source:** `.ijfw/`, `ijfw/`, `.handoff/`, `logs/`, `graphify-out/` are gitignored scratch.
- **The vendored engine** must not diverge from upstream silently — log any customization in
  [`vendor/skill-search/VENDORED.md`](../vendor/skill-search/VENDORED.md).

## See also

- [`docs/caveats.md`](../docs/caveats.md) — the full 15-item landmine list (canonical).
- [`docs/adr/README.md`](../docs/adr/README.md) — the decisions behind these choices.
- [`README.md` → Troubleshooting](../README.md) — the symptom→fix table.
