# ADR-0070 — A local index owner replaces the Qdrant container and the Docker embed shim

Status: Accepted (2026-09-27)
Supersedes: the vector-store half of ADR-0003 (Qdrant server tier via Docker) and the Docker-sidecar
half of ADR-0008 (the warm embed shim's deployment vehicle). The embedder choice (ADR-0003) and the
warm-in-memory-model decision (ADR-0008) both stand unchanged. Relates to: ADR-0002 (the fusion
fallback this owner still honors on any outage), ADR-0004 (the stable venv the owner runs from),
ADR-0018 (the self-healing launcher, extended here to autostart the owner), ADR-0061 (the Jev router's
warm `/jev` relay, moved from the shim onto the owner's embed port).
Evidence: `plans/260925-2349-vector-store-hardening-and-migration/architecture-vector-store-3.md`
(the full plan, decisions D1-D10); `plans/reports/cutover-readiness-260926.md` (verification, memory
measurements, findings 1-4); `plans/reports/shadow-collection-archive-260926.md` (D3 archive/delete);
`plans/reports/orchestrate-260926-2100/jev-port/result.md` (the `/jev` relay port).

## Context

skill-concierge ran two always-on Docker containers: Qdrant (the vector index — three collections,
tens of thousands of points) and a warm embed shim that kept the embedding model loaded so the
per-turn hook could get a query vector in tens of milliseconds instead of paying a multi-second cold
load. Qdrant was reachable from the whole local network with no password and the container ran an
untagged, floating image (`qdrant/qdrant:latest`) rather than the pin `setup.sh` intended (Qdrant image
tags carry a `v` prefix, so the pin never matched). Both containers together cost about 2 GB of images
and Docker itself as a hard install requirement, for an index that a warm numpy process searches in
under a millisecond.

Benchmarked at real scale (43,146 × 768 float32), the owner's hook-shaped search measured over HTTP
came to p99 6.77 ms against Qdrant's own 87 ms p90 approximate search — the vector store's job did not
need a server, concurrent-writer locking, or a network protocol; it needed one process holding the
vectors in memory.

## Decision

1. **One local process, the index owner** (`vendor/skill-search/skill_search/index_owner.py`), grown
   from the existing warm embed shim (`scripts/embed_server.py`). It holds the embedding model and
   every collection's vectors in memory, persists them to one SQLite file (stdlib `sqlite3`), and
   searches with exact cosine math (`numpy`, already a fastembed dependency and now a declared direct
   one). It answers on the **same two addresses as before** — port 6333 in Qdrant's own REST JSON
   shape (`GET/PUT/DELETE /collections/{c}`, `points/scroll`, `points/query`, `points/query/groups`,
   etc.) and port 6363 for `/embed` + `/health` + `/jev` — on both `127.0.0.1` and `::1`. Because the
   addresses and request format are unchanged, no hook, adapter, installed harness config, or script
   needed a new setting.
2. **`server.py` drops `qdrant-client`** for a small stdlib `urllib` client (`_Store`, ~80 lines)
   talking the same REST subset, and the engine's embedded on-disk Qdrant mode
   (`QdrantClient(path=…)`) is deleted — it locked the store to one process and nothing in this
   deployment used it.
3. **Autostart replaces Docker's restart policy.** `bin/skill-search-mcp` starts the owner when
   `/health` does not answer; the enforcer hook starts it only on a refused connection (never on a
   timeout or a 503, which mean busy or loading, not down); `setup.sh` stops and restarts it after
   reinstalling so a same-version code change still takes effect. A duplicate start is harmless — the
   loser of the owner's file lock exits in milliseconds.
4. **`doctor.py` drops every automatic Docker-start path** (`setup.sh`'s `docker start`/`run`, the old
   `fix_docker_start`) and gains owner-specific checks: `/health` + `code_version`, a SQLite
   `PRAGMA integrity_check`, point counts, and an embed-parity probe (English + Vietnamese, cosine
   ≥ 0.9999). It FAILs when any container still publishes 6333 or 6363, when the answerer on 6333 is
   not the owner, or when the owner's log holds a downgrade or port-conflict line; `--fix` stops and
   disables a revived container before starting the owner.
5. **What stays the same (D2, decided 2026-09-25):** the environment variable `SKILL_QDRANT_URL` and
   port 6333 keep their Qdrant-era names permanently. Renaming would touch every harness's env channel
   for no functional gain — hooks get no configuration channel from `.mcp.json`, and installed Command
   Code and DSH configs already hardcode `localhost:6333`. The owner's `GET /` names itself
   (`"skill-concierge index owner (Qdrant-compatible subset)"`) so nothing mistakes it for real Qdrant.
6. **Retired alongside (D3, decided 2026-09-25):** `enrich_index.py`, `multivector_experiment.py`, and
   the `claude_skills_shadow` collection. Each depended on four Qdrant-only request paths
   (`/points/search`, `/points/vectors`, `/points/payload`, `/snapshots`) nothing else called, and the
   live index held zero enriched points from the legacy overlay. The collection (7,080 points) was
   archived to `~/_ARCHIVE/` and verified byte-for-byte before deletion
   (`scripts/archive_qdrant_collection.py`; `plans/reports/shadow-collection-archive-260926.md`).

## Alternatives considered

- **sqlite-vec.** Adds a dependency, pre-1.0 (0.1.9), macOS system Python cannot load it, is
  brute-force search anyway, and has no group-by (best-per-skill would still need Python). Rejected —
  stdlib `sqlite3` + `numpy` does the same job with nothing new to install.
- **`qdrant-client` embedded/local mode** (`QdrantClient(path=…)`). A second process cannot open the
  store while another holds it (reproduced live). Disqualified — this deployment runs several MCP
  server processes at once.
- **Every process reads the SQLite file itself** (the plan's first version). Each of up to seven MCP
  servers would hold its own ~130 MB matrix, WAL commits do not change the file's mtime (so change
  detection needs extra machinery), and two locking systems would be needed. Rejected — a single owner
  removes all three problems.
- **A new port and a new variable** (`SKILL_SEARCH_URL`) instead of taking over 6333. Rejected for the
  switch-over: hooks have no config channel from `.mcp.json`, and installed Command Code/DSH configs
  already contain `localhost:6333`; every harness would need an env-propagation change for no gain
  (kept open as a possible later rename, D2).
- **`.npy` + JSON files instead of SQLite.** Workable under a single owner, but SQLite's incremental
  upserts/deletes and crash safety come free from the standard library.
- **LanceDB / DuckDB-vss / Chroma.** Heavier (pyarrow, OpenTelemetry, grpc stacks) with documented
  multi-process write problems.
- **Ollama for embeddings.** Swaps one background service for another; the separately-tracked bge-m3
  migration is operator-deferred and not reopened here.
- **Qdrant Edge** (`qdrant-edge-py`). Watch item only: GA since June 2026, concurrency unverified.
- **Keep Docker, harden it fully** (network binding, image pin, resource limits, an API key). Viable,
  and the hardening steps were applied as Track A regardless (see Consequences), but this keeps Docker
  as a hard install requirement and ~2 GB of images for an index that searches in under a millisecond
  once warm.

## Consequences

- **Memory (D5, accepted 2026-09-26).** The owner costs about 1.8-2.1 GB steady after a restart (the
  model alone is 1,464 MB — higher than the plan's ~600 MB estimate, which was taken from the Linux
  shim container; vectors add ~132 MB held twice; payload objects add ~50 MB) and 3.0 GB at startup
  (index and model loading overlap). A write-time defect that rebuilt the full search matrix after
  every write — peaking at 8.9 GB across 670 writes — was found and fixed: the owner now marks a
  collection stale on write and rebuilds it once, under the write lock, on the next read, dropping the
  same 670-write peak to 1.59 GB. Under a load test's nonstop read stream during a forced reindex the
  owner still peaked at 6.0 GB (every read after a write rebuilds once); real hook traffic — a few
  reads a minute — stays near the 3.0 GB startup peak. Traded against this: each of up to seven MCP
  server processes that search stops loading its own 1.4 GB model copy (measured 54 MB vs 1,483 MB per
  search process), which the previous two-container deployment paid on every session that searched.
- **Old engines and session restarts (D6, accepted 2026-09-26).** An engine build older than the owner
  cannot create a collection on it — it calls `PUT /collections/{c}/index`, a route the owner does not
  serve — though incremental reindex against the owner works from an old engine. Rather than add a
  compatibility route, every Claude Code session is restarted onto the release at the switch, and
  doctor's "Running engine" row must be green (the cutover precondition, `doctor.py --cutover`).
- **Switch-over order and dark window (D10, decided 2026-09-26).** Docker is stopped **before** the
  release reaches `main`, because a push to `main` auto-installs on Claude Code (marketplace
  `autoUpdate: true` plus `FORCE_AUTOUPDATE_PLUGINS=1`) and the new code must never run against the old
  Qdrant. Order: a short parity replay against a staging owner while Docker is still live; `docker
  update --restart=no` + `docker stop` on both containers (the dark window starts — the hook fails
  open, search is unavailable); the staging owner is stopped and its SQLite file moved into place; the
  release is fast-forwarded onto `main` and pushed; the owner starts on 6333/6363, an incremental
  reindex catches up, and a smoke check confirms `/health` `code_version` matches the release (the dark
  window ends); the other harnesses (OMP, Codex, ZCode) update; every session is restarted. This
  reverses the plan's earlier precondition that every harness copy reach the release **before** the
  switch (D9/0c) — going dark for a few minutes was accepted in exchange for never running the new
  engine against Docker Qdrant.
- **What is kept (D2).** `SKILL_QDRANT_URL` and port 6333 remain the permanent compatibility names —
  no harness, adapter, or installed config anywhere needed to change.
- **A small behavior change, to be epoch-noted at the switch (TASK-022, REQ-004).** Search is now always exact (no more HNSW
  approximate search — recall can only improve; the parity replay never found an approximate score
  beating an exact one), and the deterministic tie-break is score descending, then skill name
  ascending, replacing Qdrant's own arbitrary tie order.
- **Retired alongside (D3):** `enrich_index.py`, `multivector_experiment.py`, and the
  `claude_skills_shadow` collection are gone; the collection is archived at
  `~/_ARCHIVE/skill-concierge-claude-skills-shadow-260926/` with a verified snapshot and point export.

## Revert

Stop the index owner; `docker start` both containers; `docker update --restart=unless-stopped` on both;
restore the previous `setup.sh` and `scripts/doctor.py` from git; run a reindex so Qdrant catches up on
anything written to the owner in between. `qdrant-client` is already removed from
`vendor/skill-search/pyproject.toml` (this branch), so a revert to Docker Qdrant needs no engine
downgrade: the engine's `_Store` (`vendor/skill-search/skill_search/server.py`) speaks the same plain
Qdrant REST paths (`/collections/{c}`, `points/scroll`, `points/query/groups`, …) against
`SKILL_QDRANT_URL` whether the answerer is the owner or a real Qdrant server. The Phase 6 cleanup
(deleting `Dockerfile`/`.dockerignore` and the retired containers/images) has not run, so both
container images and the vendored `Dockerfile` remain on disk — a revert needs no re-provisioning step
beyond restarting them.
