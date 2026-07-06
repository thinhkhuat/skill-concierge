# Journal — 2026-07-06 — bge-m3/Ollama migration: built, measured lateral, archived + deferred

## What happened

Executed the red-teamed plan `plans/260705-2240-bge-m3-ollama-dense-migration/` (from a prior session) via `/ck:cook --auto` with an explicit operator Phase-1 GO. Built the full dense migration, **measured** it end-to-end, found it a net-lateral move with a real precision cost, and — on the operator's call — **archived** the complete work to a feat branch and reverted `main` to clean mpnet. Nothing was ever cut over live.

`/ck:team` was attempted first but Agent Teams is unavailable in this harness (`TeamCreate` absent under `TERM_PROGRAM=Orca`, non-TTY) — aborted per the skill's pre-flight rather than falling back to subagents.

## Design (the migration, now on feat)

Repoint the existing warm embed-shim into an **Ollama proxy** for `bge-m3` (1024-dim dense), preserving its `{"text"}→{"vector"}` HTTP contract so the three shim consumers (enforcer, prompt_intent build, calibration) need zero change. Engine (`skill_search.server`, vendored) already has native Ollama dispatch — the swap is env-only, no engine edit. Backend read from `.mcp.json` SSOT; `setup.sh` force-`--rebuild` (dim guard); Docker sidecar reaches host Ollama via `host.docker.internal`; doctor gains an Ollama-tier daemon/model/dim-parity + digest check.

## Two plan corrections found by reading the actual code (verify-before-assert)

- `auto_reindex.py` does **not** hardcode fastembed (plan claimed it did) — it already reads the backend from `.mcp.json`. No edit needed; editing it would have been wrong.
- macOS: `--network host` does **not** reach host Ollama (Docker VM); must use `host.docker.internal` (verified reachable from the running container).

## Measurements (the decisive part)

- **Feasible.** Warm p95 through the full enforcer path (HTTP shim → engine → Ollama) = **159 ms** ≤ 200 ms cap; dim 1024; Ollama loopback-bound; even a cold reload ~156 ms stays under cap → `keep_alive` eviction low-risk. Reindex window ~103 s for 3625 points.
- **Retrieval quality LATERAL, not a win.** 22-intent at-scale test (real body+multivector pipeline): bge-m3 ≈ mpnet on top-1 band (mean **0.738 vs 0.734**). The targeted cross-lingual EN→VN edge did **not** materialize — mpnet (already multilingual) beat bge-m3's margin on a native-VN query. An early desc-only toy test suggested worse "smearing," but that **did not reproduce** at scale — cleared honestly rather than shipped as an alarm.
- **Getaway suppression weakens (the real cost).** bge-m3's cosine band is lifted: trivia/chitchat score as high as tasks (0.57–0.71 vs task 0.65–0.82). No absolute `GETAWAY_FLOOR` separates them → 0.45 goes near-inert (measured 10/10 non-task fire vs mpnet's 4/10). Suppression falls entirely on the **relative** actionability gate (`INTENT_MARGIN`), which survives the band shift (measured **15/19** correct vs mpnet 17/19) — so behavior is *preservable* but with more skill-offers on conversational turns. Floors kept unchanged (no ADR-0009 change triggered; raising the floor kills real tasks).

## Decision

**The operator personally made the call to suspend this migration.** Measurements below informed the call, but the deferral was an explicit operator decision — not an automated verdict, not the agent's own judgment call.

**Defer deploy.** The migration's premise (cross-lingual win) evaporated; net is a lateral quality move that *dents* the enforcer's precision, at real always-on-daemon + ~2× compute + telemetry-epoch-reset cost. The repo's own doctrine says the adoption lever is index content + the gate, not the embedder. Preserved (not abandoned) — bge-m3 is the substrate to revisit for sparse-hybrid later.

## Code review (advisory, ck:code-reviewer subagent)

FAIL-to-land as-shipped: **C1** `setup.sh` health-gate leaves a stale shim container on cutover (dim desync → mandate-only); **I1** `--rebuild` drops the live collection on every rerun; **I2** doctor false-OK when collection dim unreadable; **I3** driftcheck RED (README not bumped); **M1** `auto_reindex` dropped `SKILL_OLLAMA_URL`. Cheap ones (I2/I3/M1 + comments) fixed on feat before archiving; C1/I1 are cutover-design items documented as deploy-blockers.

## Outcome

- **feat/bge-m3-ollama-migration** (`a86d3d6`, local, unpushed) — full hardened migration, ADR-0019, original plan, 6 reports. Deployable later via the runbook.
- **main** (`51516f5`) — clean mpnet 0.13.1, doctor OK, live system untouched; archive-plan committed as the record.

## Lesson

A "config + reindex" framing hid a backend-rewiring blast radius across ~12 sites + a live per-turn hot-path dependency — the red-team caught it, and reading the actual vendored engine + running real latency/quality/gate measurements (not assuming) is what turned a plausible migration into an evidence-based *defer*. Measure the whole path, not the engine call in isolation.
