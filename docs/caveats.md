# Caveats & Landmines — read before operating

The loud list. Each item is a real trap that has bitten (or is one config-slip from biting).
Symptom → cause → what to do. ADRs hold the *why*; this holds the *don't*.

> **Before reading the whole list:** run `skill-concierge:doctor` (or `python3 scripts/doctor.py`).
> It mechanically checks the deployment layer + retrieval health and auto-fixes the common
> ones (§3 Qdrant down, §6 reindex, the overrides applier) with `--fix`. This file is the
> human reference for what doctor can't or won't touch. (ADR-0007.)

---

## §1 — The vendored eval is calibrated to a DIFFERENT machine (do not trust its recall@k)

**Symptom:** `vendor/skill-search/eval/run_eval.py` prints recall@1/@3/@6 ≈ `0.00 / 0.08 / 0.08`.
Looks like the retriever is broken.

**Cause:** `eval/labeled_queries.jsonl` is the **upstream author's** label set. Its expected
answers target skills **not in this index** — both the author's plugins (`gsd-*`,
`superpowers:*`, `claude-mem:*`, `chrome-devtools-mcp:*`) and **built-in slash-commands**
(`loop`, `schedule`, `verify`, `run`, `code-review`, `update-config`, `keybindings-help`).
This engine **deliberately** indexes only model-invocable `SKILL.md` skills (ADR-0001), so
those labels can never be retrieved here. The number measures the wrong universe.

**Do:** Treat the vendored eval as a **harness smoke-test only** (does the pipeline run?), not
a quality bar. For a real number, **relabel** with ground truth drawn *only* from the indexed
catalogue (`get_skill` / `search_skills` to confirm membership; use **namespaced** ids — §5).
A near-zero score here is **not** evidence the embedder is weak.

> This one cost a whole analysis detour. It is the reason the ADRs and this file exist.

---

## §2 — Never run upstream `generate_overrides.py` against this deployment

**Symptom:** the curated always-on set collapses to ~2 skills; overrides appear in
`settings.local.json`.

**Cause:** `vendor/skill-search/skill_search/generate_overrides.py` targets
`~/.claude/settings.local.json` with a **2-item keep-on default**. A rerun nukes the curated
set and writes the wrong file.

**Do:** Apply overrides ONLY via `scripts/apply-overrides.py` (writes `~/.claude/settings.json`,
atomic, backs up, refuses empty keep-on — ADR-0005). Guard/avoid the upstream generator.

---

## §3 — Qdrant must be up

**Symptom:** search/health errors; MCP returns nothing useful.

**Cause:** the engine needs the `skill-search-qdrant` container (`localhost:6333`).

**Do:** `docker ps --filter name=skill-search-qdrant` → expect `Up`. Container is
`--restart unless-stopped`; if absent, `setup.sh` recreates it. In the live fusion, a Qdrant
outage degrades to mandate-only fallback (ADR-0002), not a crash.

---

## §4 — `setup.sh` picks the first `python3.12` — which may have broken `ensurepip`

**Symptom:** `setup.sh` venv creation fails on a fresh machine.

**Cause:** the picker takes the first `python3.12` on `PATH`. On this machine
`~/.local/bin/python3.12` has a **broken `ensurepip`**; the working build used
`/opt/homebrew/bin/python3.12`.

**Do (workaround):** point the build at a known-good interpreter, or pre-create the stable
venv (`~/.claude/skill-concierge/venv`) with brew python, then rerun `setup.sh`.
**Deferred fix:** harden the picker to test `venv`+`pip` per candidate and fall through
(portability-only — the owner's machine already works).

---

## §5 — Plugin skills are NAMESPACED in the index

**Symptom:** `get_skill('worktree')` → not found, even though the skill exists.

**Cause:** plugin-bundled skills are indexed as `<plugin>:<skill>` (e.g. `ck:worktree`),
matching how Claude Code references them (`skills_discovery.py:35-52`).

**Do:** look up / label with the prefix — `get_skill('ck:worktree')`, `ck:deploy`,
`skill-concierge:skill-search`. Personal/project skills keep their bare name.

---

## §6 — `disk changed since last index — run reindex()`

**Symptom:** `--health` reports `degraded`; `search_skills` results carry a
`skills changed on disk since last index` warning.

**Cause:** skill files changed/were re-touched on disk since the last index build
(e.g. after `/reload-plugins` re-attaches skills).

**Do:** **nothing — this now self-heals.** The SessionStart `auto_reindex.py` hook
(ADR-0014) fires a detached, throttled, incremental reindex every session, so a stale index
re-freshens on its own without anyone remembering. Manual paths still exist if you want it
*now*: `skill-search --reindex` (with the `.mcp.json` env), the MCP `reindex` tool, or
`doctor --fix`. Incremental either way: unchanged skills are skipped (`embedded: 0, skipped: N`).
Throttle: `AUTO_REINDEX_THROTTLE_S` (default 1800s).

---

## §7 — Version is the update signal (keep-on drift now self-heals)

**Symptom:** a `/plugin marketplace update` does nothing.

**Cause:** downstream update keys on the version — if `plugin.json` and `marketplace.json`
versions aren't bumped **together**, the update is a silent no-op.

**Do:** bump **both** manifests' versions on any shippable change.

> **The old cache/source keep-on drift is gone (v0.15.0, [ADR-0025](adr/0025-autonomous-override-freshness-and-keep-on-management.md)).**
> The live allowlist no longer lives in the wipe-on-update plugin cache — it is seeded once into
> the canonical home `~/.claude/skill-concierge/keep-on.json`, and the SessionStart
> `auto_overrides.py` hook reconciles `settings.json` whenever the installed catalogue drifts, so
> a new/removed skill no longer leaks its full description until someone re-runs the applier.

---

## §8 — logman will DELETE the ledger after 90 days unless `RETENTION_DAYS=0`

**Symptom (latent):** the compounding invocation ledger loses history after 90 days.

**Cause:** the ledger (`~/.claude/skill-concierge/logs/skill-invocation-ledger.log`) is
designed to compound forever (ADR-0006), but its downstream archiver **logman** defaults to
`RETENTION_DAYS=90`, which **deletes** old archives.

**Do:** when wiring logman to this `logs/` dir, run it with **`RETENTION_DAYS=0`** (unlimited).
The ledger code itself never rotates/caps/deletes — the risk is entirely in logman's default.

---

## §9 — Embed shim must be running (Docker sidecar, `skill-search-embed-shim`)

**Symptom:** per-turn latency spikes over budget (≲150ms); enforcer telemetry shows
high `fallback: true` rate in `offer` events.

**Cause:** the warm embedding shim (`scripts/embed_server.py`) runs as a Docker sidecar
(`skill-search-embed-shim` container, `127.0.0.1:6363`). If the container is stopped or
crashed, or the model fails to load in-memory, the enforcer hook hits the 90ms timeout and
falls back to mandate-only. The fallback works (never crashes), but enforcement degrades.

**Do:** `docker ps --filter name=skill-search-embed-shim` → expect `Up`. Container is
`--restart unless-stopped`, so restart Docker or run `setup.sh` to recreate it.
`skill-concierge:doctor --fix` auto-restarts the container if down. Monitor fallback rate
in `~/.claude/skill-concierge/logs/skill-invocation-ledger.log` (`offer` events with
`fallback: true`); sustained high rate signals a shim health problem.

---

## §10 — This repo is workbench-write-guarded

**Symptom:** an agent's `Write` into `skill-concierge/` is blocked
(`Root-anchoring: artifacts are inert data`).

**Cause:** MY-WORKBENCH treats any dir with its own `.git/` as an inert **artifact** and
blocks writes; the `.ckignore` also blocks Bash commands containing the literal `.git`.

**Do:** the owner's bypass is to rename `.git` → `git` (no-dot) while editing, then back to
`.git` before committing. (Context for agents operating from the workbench root; irrelevant
once the repo is cloned standalone elsewhere.)

---

## §11 — The MCP can serve STALE engine code after a `/plugin update` (venv ≠ cache)

**Symptom:** a plugin update + restart is done, the new version is installed, `doctor` shows
`Engine venv ✓` — yet the MCP *behaves like the old version* (a retrieval/engine fix you
shipped isn't live). `/mcp` shows skill-search connected; nothing looks broken.

**Cause:** the MCP launcher EXECs `skill-search` from the **stable venv**
(`~/.claude/skill-concierge/venv`, ADR-0004), where the engine is **COPIED into
site-packages by `setup.sh` — not an editable install.** `/plugin update` ships new code into
the version-pinned **cache** but **never touches the venv copy**. So the cache is new and the
venv engine is old; the MCP runs the old one. `Engine venv ✓` only proves the bin *exists*,
not that it's *current* — the original blind spot.

**Detect:** `doctor` now has an **`Engine freshness`** check (ADR-0013) that content-hashes the
venv's installed engine against the deployed vendored source and WARNs on a mismatch. Manual
equivalent — the decisive test:

```bash
diff -rq \
  "$CLAUDE_PLUGIN_ROOT/vendor/skill-search/skill_search" \
  "$HOME/.claude/skill-concierge/venv/lib/python3.*/site-packages/skill_search"
```

Empty output = fresh; any difference = stale.

**Do:** rerun **`setup.sh`** (the `skill-concierge:setup` skill) — it rebuilds/refreshes the
stable venv from the deployed source — then **restart Claude Code**. Rule of thumb: a
`/plugin update` that changed engine code under `vendor/skill-search/` requires a `setup.sh`
rerun; a change that only touched hooks/doctrine/scripts (cache-run) does not. (Hooks read
their code straight from the cache, so they update with the plugin; only the venv-resident
engine needs the rerun.)

---

## §12 — bge-m3/Ollama dense-embedder migration: built, measured, then explicitly SUSPENDED by the operator — do not re-propose without new evidence

**Symptom:** someone (agent or human) proposes swapping the embedder to a dense/Ollama model
(bge-m3 or similar), assuming the idea is unexplored or was merely a technical dead end.

**Cause:** it was already fully built and measured end-to-end on `feat/bge-m3-ollama-migration`
(`a86d3d6`) — **feasible** on latency (159ms p95 warm, under the 200ms enforcer cap) but
**lateral, not a win**, on retrieval quality (mean 0.738 vs mpnet's 0.734; the targeted
cross-lingual EN→VN win never materialized), and it **weakens the getaway-suppression floor**
(measured 10/10 non-task fire on bge-m3's cosine band vs mpnet's 4/10). **The operator personally
decided to suspend/defer** the migration on that evidence — a human call, not an automated verdict
or an agent's own judgment. `main` was reverted to clean mpnet 0.13.1; nothing was ever cut over
live.

**Do:** read the full journal
(`docs/journals/journal-2026-07-06-bge-m3-migration-built-measured-lateral-archived.md`) and the
archive plan (`plans/260706-0024-bge-m3-archive-to-feat-and-revert-main/plan.md`) before
re-raising this migration. The work is **preserved, not abandoned** — deployable later via the
runbook on the feat branch — but re-proposing it needs new evidence, not a repeat of the same
measurement. A verified operator decision does not reverse on an abstract concern alone.
