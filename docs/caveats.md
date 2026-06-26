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
venv (`~/.local/share/skill-concierge/venv`) with brew python, then rerun `setup.sh`.
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

**Do:** reindex — `skill-search --reindex` (with the `.mcp.json` env), or call the MCP
`reindex` tool. Incremental: unchanged skills are skipped (`embedded: 0, skipped: N`).
Harmless but results are stale until you do.

---

## §7 — Version-is-the-update-signal + cache/source keep-on drift

**Symptom:** a `/plugin marketplace update` does nothing; OR a cache `setup.sh` rerun reverts
the router (`skill-concierge:skill-search`) to `name-only`.

**Cause:** (a) downstream update keys on the version — if `plugin.json` and
`marketplace.json` versions aren't bumped **together**, the update is a silent no-op.
(b) The installed-cache copy of `config/keep-on.json` can lag the source; a cache `setup.sh`
re-applies the *cached* policy.

**Do:** bump **both** manifests' versions on any shippable change; keep the installed plugin
version in sync with source so the cached `keep-on.json` matches (ADR-0005).

---

## §8 — logman will DELETE the ledger after 90 days unless `RETENTION_DAYS=0`

**Symptom (latent):** the compounding invocation ledger loses history after 90 days.

**Cause:** the ledger (`~/.claude/skill-telemetry/logs/skill-invocation-ledger.log`) is
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
in `~/.claude/skill-telemetry/logs/skill-invocation-ledger.log` (`offer` events with
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
