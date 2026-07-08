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
read-only deployment health check; a green `status: OK` is the bar to claim "done". It runs **13
checks** and delegates the retrieval diagnostic to `skill-search --health` (DRY): Python, venv,
**engine freshness**, MCP wiring, Qdrant, engine health (stale-but-serving = WARN, not FAIL),
enrichment, multi-vector layer, prompt-intent corpus, corpus health (reads `eval/thresholds.json`),
overrides, ledger dir, and duplicate-MCP. Exit 0 unless a check FAILs.

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

> ⚠ **Doc drift:** [caveats §9](../docs/caveats.md) names this container `skill-search-embed-shim`
> — that is **stale**. The code truth ([`setup.sh:21`](../setup.sh)) is
> **`skill-concierge-embed-shim`** (env-overridable via `SKILL_EMBED_CONTAINER`). Verify health
> with `docker ps --filter name=skill-concierge-embed-shim`. A stopped/slow shim shows up as a
> sustained `fallback: true` rate in the ledger's `offer` events; `doctor --fix` restarts it.

## The stale-engine trap (post-update)

Historically the most dangerous silent failure — **self-healing since v0.13.1, and the settled
behavior on every release since (current: v0.16.0).** The v0.13.1 tags below mark where each fix
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

All are one-var reverts; all default ON except `SKILL_TRIGGER_PURITY`, which defaults to a
non-boolean `shadow` mode (log-only, ships inert).

| Variable | Default | Effect | ADR |
|----------|---------|--------|-----|
| `ENFORCER_AUTHORIZED_SKIP` | `1` | enforcer injects a `SKILL-CHECK:` authorization on its two formerly-silent verdict legs instead of nothing; `=0` restores the old silence | [0015](../docs/adr/0015-authorized-skip-tier-and-library-doctrine.md) |
| `SKILL_BODY_TRIGGERS` | `1` | engine mines each skill body's labeled decision-sections into extra MAX-pool trigger points; `=0` **+ a reindex** reverts to description-only | [0016](../docs/adr/0016-body-derived-trigger-points.md) |
| `SKILL_LLM_TRIGGERS` | `0` | layers offline flywheel-generated natural-utterance phrases (EN+VN) FIRST in the MAX-pool trigger layer; `=1` **+ a reindex** enables (needs `SKILL_TRIGGERS` → `eval/triggers.json`) | [0026](../docs/adr/0026-llm-utterance-trigger-layer.md) |
| `TRIGGERS_MAX` | `12` | per-skill COMBINED cap across all trigger sources; live deploy uses `16` so utterances add slots rather than evict desc/body | [0026](../docs/adr/0026-llm-utterance-trigger-layer.md) |
| `ENFORCER_SELFREF_SKIP` | `1` | enforcer pre-authorizes a 3rd AUTHORIZED-SKIP leg for pure self-referential recap turns ("explain your last answer"); `=0` restores the old 2-leg behavior | [0019](../docs/adr/0019-over-fire-lane-and-gate-legibility.md) |
| `SKILL_SUBAGENT_STOP` | `1` | doctrine hook suppresses SessionStart injection inside subagent sessions (positive `agent_id` proof); `=0` injects unconditionally | [0020](../docs/adr/0020-subagent-session-scoping.md) |
| `SKILL_TRIGGER_PURITY` | `shadow` | engine flags workflow-summary body triggers; `shadow` only logs would-drops (index unchanged), `active` drops them (**needs a full reindex**), `off` skips the check | [0023](../docs/adr/0023-trigger-purity-lint.md) |

Several enforcer levers are additionally **default-inert** and env-gated (`ENFORCER_DETERMINISTIC`,
`ENFORCER_PER_SKILL_TAU`, `ENFORCER_DOMINANCE_RATIO`) — see
[enforcement-gate.md](architecture/enforcement-gate.md#the-authorized-skip-tier-three-legs-two-formerly-silent).

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
- **Tool state is not source:** `.ijfw/`, `ijfw/`, `.handoff/`, `logs/` are gitignored scratch.
- **The vendored engine** must not diverge from upstream silently — log any customization in
  [`vendor/skill-search/VENDORED.md`](../vendor/skill-search/VENDORED.md).

## Open items

- **caveats §9 names a stale container** (`skill-search-embed-shim`); the code truth is
  `skill-concierge-embed-shim`.

## See also

- [`docs/caveats.md`](../docs/caveats.md) — the full 11-item landmine list (canonical).
- [`docs/adr/README.md`](../docs/adr/README.md) — the decisions behind these choices.
- [`README.md` → Troubleshooting](../README.md) — the symptom→fix table.
