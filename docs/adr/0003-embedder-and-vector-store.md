# ADR-0003: Multilingual mpnet-768 embedder + Qdrant server tier

**Status:** Accepted
**Date:** 2026-06-26
**Deciders:** owner (thinhkhuat)

## Context

Semantic retrieval needs (a) an embedding model and (b) a vector store. Two constraints
shaped the choice:

1. The owner works in **English and Vietnamese**. Queries like an EN description of a
   VN-described skill must still match — a monolingual/English-only embedder would miss them.
2. The model that builds the index and the model that embeds a query **must be identical**,
   or the vectors are incomparable and search silently returns garbage.

## Decision

- **Embedder:** `sentence-transformers/paraphrase-multilingual-mpnet-base-v2` (768-dim),
  served via **fastembed**. Multilingual → EN↔VN cross-language retrieval works.
- **Vector store:** **Qdrant, server tier** — a Docker container (`skill-search-qdrant`)
  on `localhost:6333` (+6334), `--restart unless-stopped`. Not the embedded/in-process tier.
- **Single source of truth for the embedder:** the model id + Qdrant URL live in
  `.mcp.json` `env` (`SKILL_EMBED_MODEL`, `SKILL_EMBED_BACKEND=fastembed`,
  `SKILL_QDRANT_URL`). `setup.sh` reads them **from `.mcp.json`** so the built index can
  never diverge from what the live MCP queries with.

## Implementation (P1)

Approach **A** was chosen (see ADR-0002 / plan.md): A warm **fastembed-mpnet HTTP shim** (`scripts/embed_server.py`) runs as a Docker sidecar (`127.0.0.1:6363`) next to Qdrant. Receives POST {text} → returns vector in tens of ms (vs seconds cold-load). The hook embeds queries via this shim (90ms hard timeout, client-side), then queries Qdrant. Parity verified: cosine distance 1.000000 between the index-build path and the live shim (EN + VN).

## Consequences

### Positive
- EN↔VN retrieval (the reason for "multilingual"); a persistent Qdrant survives restarts.
- One declared embedder everywhere → no index/query model mismatch.
- Warm embedding endpoint enables fast, semantic per-turn retrieval without cold-loading the model.

### Negative / caveats
- **The embedder choice is load-bearing for the index.** Changing `SKILL_EMBED_MODEL`
  requires a **full reindex** (vectors from a different model are incomparable). This is the
  cost that made ADR-0004's warm-shim approach **A** ("keep this exact model, add a shim")
  win over "switch to an Ollama-served model" (which would force a rebuild + parity
  re-validation).
- Qdrant is an always-on dependency. If it's down, search fails — the fusion's fallback
  (ADR-0002) degrades to mandate-only rather than breaking the turn.
- fastembed emits a one-time `UserWarning` (mean- vs CLS-pooling for this model). Benign —
  consistent pooling on both index and query sides is what matters, and both use fastembed.

## Related

- ADR-0002 (the warm shim must serve *this exact* model).
- ADR-0004 (stable venv holds fastembed + the model).
- `../caveats.md` §3 (Qdrant must be up), §6 (`disk changed → reindex`).
