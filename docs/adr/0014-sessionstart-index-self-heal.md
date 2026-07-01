# ADR-0014 — SessionStart index self-heal (`auto_reindex.py`)

Status: Accepted (2026-07-01)
Relates to: ADR-0012 (multi-vector reindex is incremental + reindex-safe), ADR-0007 (doctor `--fix` reindex), caveats §6.

## Context
The retrieval index goes stale whenever skills change on disk (added / removed / edited) since
the last build — `--health` then reports `degraded` and `search_skills` carries a `skills changed
on disk since last index` warning (caveats §6). Until now the remedy was **manual**: someone had
to remember to run `skill-search --reindex` / the MCP `reindex` tool / `doctor --fix`. That makes
freshness depend on human-or-agent discipline, which is exactly the kind of latent staleness the
project's "no staleness of any kind" posture rejects. In practice the index sat stale for hours
across sessions.

Two properties make a cheap automatic refresh safe:
- The reindex is **incremental** (ADR-0012 / `server.build_index`): only skills whose content
  changed are re-embedded; a no-change run is `embedded: 0, skipped: N` and just refreshes the
  freshness stamp.
- It is **reindex-safe** with the multi-vector layer (stable per-(skill,slot) ids; no overlay to
  reapply).

## Decision
Add a **SessionStart hook** `hooks/scripts/auto_reindex.py` that fires the reindex automatically:
- **Detached + non-blocking:** spawns `skill-search --reindex` with `start_new_session=True`,
  output to `logs/auto-reindex.log`, and returns immediately — session start is never blocked.
- **Throttled:** at most one background reindex per `AUTO_REINDEX_THROTTLE_S` (default **1800s**),
  tracked by a stamp file (`logs/.auto-reindex-stamp`) written BEFORE the spawn (so a crash-looping
  engine can't re-spawn every session). Rapid restarts don't churn the engine.
- **Guarded + fail-silent:** no-ops if the engine bin is missing (setup not run) or Qdrant is
  unreachable; any exception exits 0. Mirrors the doctrine/enforcer/ledger hook contract
  (fail-silent, never block).
- Registered alongside `doctrine.py` in the SessionStart array of `hooks/hooks.json` (timeout 10s).

Lives as a **hook** (cache-run → ships with `/plugin update`), NOT in the engine: putting it in
`vendor/skill-search/` would make it venv-resident and require a `setup.sh` rerun to deploy (the
ADR-0013 stale-engine trap).

## Consequences
- Index staleness now **self-heals** in the background; caveats §6 downgraded from "do this
  manually" to "nothing — self-heals." doctor's `Retrieval health` WARN should no longer be a
  chronic resident.
- Cost: one detached engine spawn per ≤30 min of active sessions; incremental so usually a no-op
  (fastembed load + a skip pass). Negligible, off the session-start hot path.
- Manual reindex (`doctor --fix`, MCP `reindex`) still available for an immediate refresh.
- Disable by raising `AUTO_REINDEX_THROTTLE_S` or removing the hook entry.
