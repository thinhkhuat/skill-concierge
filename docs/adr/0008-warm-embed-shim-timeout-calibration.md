# ADR-0008: Warm embed shim infrastructure + 90ms timeout calibration

**Status:** Accepted
**Date:** 2026-06-26
**Deciders:** owner (thinhkhuat)

## Context

ADR-0003 chose the multilingual mpnet-768 embedder. ADR-0002 requires the fusion hook to embed queries semantically at **every prompt**. Cold-loading the mpnet model per prompt is seconds-scale — unacceptable for a per-turn hook (~71ms budget today, ≲150ms target with 3.75x headroom).

The solution: keep the model **warm** in memory between prompts. Three approaches existed:

1. **A (chosen):** tiny persistent fastembed-mpnet HTTP shim on localhost, sidecar to Qdrant.
2. **B:** switch embedder to an Ollama-served multilingual model (Ollama is already a warm daemon); rebuild index on new model, re-validate parity.
3. **C (rejected):** accept cold-load latency (unacceptable UX).

## Decision

**A**: Deploy a warm embedding endpoint (`scripts/embed_server.py`) as a Docker sidecar on `127.0.0.1:6363`. The shim:
- Holds mpnet-768 in memory after first load (~2.5s startup).
- Serves `POST /embed {text}` → JSON vector in **tens of ms**.
- Exposes `GET /health` for liveness checks.
- Auto-starts via `setup.sh` alongside the Qdrant container.

The hook queries this shim with a **hard client-side timeout** (socket timeout via urllib): **90ms** (not the design-nominal ~120ms — see "Calibration" below).

## Calibration (90ms, not 120ms)

The original design specified ~120ms timeout to leave headroom for Qdrant search + overhead on top of the ≲150ms per-turn budget. Live measurement changed this:

- Python cold-start (hook process start → first call): ~50ms.
- Embed call (hit shim, return vector): p50 ~15ms, p95 ~25ms, pathological (GC pause) ~80ms.
- Qdrant search + overhead: ~30–40ms (top-k in-memory search).
- Total per-turn: baseline ~70ms, p95 ~100ms, pathological ~150ms (at budget cap).

**120ms timeout leaves only ~30ms for embed latency before falling into Qdrant slot, risking timeout-driven fallback on normal load.** 90ms timeout:
- Covers pathological embed calls (p99 ~85ms observed over 1000 samples).
- Leaves ~60ms for Qdrant + overhead at the budget cap.
- 3.75x headroom over warm p95 (25ms).

90ms is **environment-overridable** via `ENFORCER_EMBED_TIMEOUT` (milliseconds, integer).

## Consequences

### Positive
- The index stays valid (no rebuild on model change).
- Fast semantic retrieval (tens of ms) vs cold-load (seconds).
- Hard client-side timeout enforces ≲150ms per-turn budget regardless of shim state (GC pause, contention, cold page).
- A new always-on dependency (shim), but degradation is graceful: timeout → fallback to mandate-only (never silence, never crash).

### Negative / caveats
- **fastembed pin required:** vendor `pyproject.toml` pins fastembed ==0.8.0 (not >=0.3). Version 0.5.1 switches mean→CLS pooling for this model, silently corrupting the index/query vector parity (ADR-0003). The pin is load-bearing.
- **Container is a dependency:** the shim is a persistent Docker sidecar (`skill-search-embed-shim` container, `--restart unless-stopped`). If the container is stopped or crashed, the hook falls back to mandate-only (visible in telemetry via `fallback` tags in `offer` events).
- **Health check is soft:** `GET /health` liveness is checked but timeout is the real gatekeeper; a degraded/slow shim is caught by the socket timeout, not the health endpoint.

## Verification

**Parity:** cosine distance = 1.000000 between the live shim and the index-build path (sentence-transformers library context) for both EN and VN queries. Verified via side-by-side embeddings on a corpus of skill descriptions.

**Timeout enforcement:** deliberately-injected latency (500ms `sleep` in the shim endpoint) confirmed that the client-side 90ms timeout fires → request fails → hook injects mandate-only → turn completes within budget (measured ≲150ms).

## Related

- ADR-0002 (the fusion architecture; enforcer hook that calls this shim).
- ADR-0003 (the mpnet-768 embedder this shim serves).
- `../plan.md` (P1 build log; warm shim completion entry).
- `../caveats.md` §10 (latent: verify Docker sidecar health before blaming search performance).
