# ADR-0008: Warm embed shim infrastructure + 90ms timeout calibration

**Status:** Accepted
**Date:** 2026-06-26
**Deciders:** owner (thinhkhuat)

> **Update (2026-06-29):** the **90ms** client-side cap below was later relaxed to **200ms** after
> the shim went threaded and live dogfooding showed ~60% of turns hitting `embed_timeout` under
> in-turn CPU contention. The shim-sidecar *decision* (approach A) stands; only the calibrated cap
> moved. Current value + history: `hooks/scripts/enforcer.py` `EMBED_TIMEOUT_S` (lines 55-62). This
> note amends the title's "90ms"; it does not reopen the decision.

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

The hook queries this shim with a **hard client-side timeout** (socket timeout via urllib): **200ms**, within a **≲300ms** per-turn total budget. The shim is **threaded** (`ThreadingHTTPServer`) so concurrent requests don't serialize. See "Calibration" for how this evolved.

## Calibration (200ms / ≲300ms / threaded — evolved from live dogfooding)

The timeout went through three values; the final one is dogfooding-driven, not desk-tuned:

1. **Design nominal ~120ms** — left headroom for Qdrant + overhead on a ≲150ms budget.
2. **Tuned to 90ms** — measured python cold-start ~50ms meant 120ms breached the ≲150ms budget; 90ms kept the slow-path ~140ms. Looked safe in **isolated** latency tests (idle embed p50 ~15ms, p95 ~25ms).
3. **Raised to 200ms + budget relaxed to ≲300ms + shim threaded** — **live dogfooding contradicted the isolated tests.** The plugin's own ledger showed **~60% of real turns hit `embed_timeout`** (mandate-only fallback). Root cause: idle the embed POST is ~18ms, but *during* a real `UserPromptSubmit` the single-threaded shim's CPU-bound mpnet inference competed with the busy host (≈4 concurrent UserPromptSubmit hooks + the working model + active MCP servers, sometimes overlapping sessions hitting the one shim) and slipped past 90ms. Isolated p95 (~25ms) never saw this contention.

**Fix (owner-approved, 2026-06-26):**
- **Threaded shim** (`embed_server.py` → `ThreadingHTTPServer`): onnxruntime releases the GIL during inference, so per-request threads run concurrently. Measured: 8 parallel embeds dropped from **288ms serial → 65ms wall (4.4×)** — the serialization that drove the timeouts is gone.
- **200ms embed cap within a ≲300ms total budget** (relaxes the original ≲150ms): the hook is *non-blocking additive context* injected before the user reads the reply, so ~250ms worst-case is imperceptible. Worst slow-path ≈ 50ms cold-start + 200ms cap ≈ 250ms ≲ 300ms; happy path stays ~100ms.

Both knobs are **environment-overridable**: `ENFORCER_EMBED_TIMEOUT` (float **seconds**, default `0.20`) and `ENFORCER_QDRANT_TIMEOUT`. Watch the ledger's fallback rate (`analyze.py`) and re-tune if real load shifts.

**Lesson:** isolated micro-benchmarks underestimate a per-turn hook's real cost — the binding latency is in-turn contention, not the idle path. The plugin's own telemetry (the `offer`/`fallback` ledger) is what surfaced it; trust the dogfooding signal over the bench.

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
