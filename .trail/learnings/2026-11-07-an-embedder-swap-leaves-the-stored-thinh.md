---
title: "An embedder swap leaves the stored index built by the old backend, and health stays green"
author: Thinh
date: 2026-11-07
branch: main
id: l-e32ad666
scope: repo
status: active
src: agent
---

## Decided
After the skill-concierge embedder moved from this Mac's local Ollama to the rtx
endpoint, the stored index was still MAC-BUILT: queries embed through rtx
(Q8_0 quantized) while every stored vector was produced by local Ollama
(nvfp4). `skill_search/server.py` has no guard for this — its dimension check in
`build_index` fires only when the DIM changes, not when the model or its
quantization changes.

Fix: rebuild into a SEPARATE collection through the override seams
`SKILL_COLLECTION`, `SKILL_META_PATH` and `NEXT_SKILLS_PATH`, all read at import
time in `skill_search/server.py`, so the live collection, its manifest and the
next-skills sidecar are never touched during the rebuild.

## Tried and ruled out
- **`build_index(force=True)` against the live collection**: it calls
  `_qdrant.delete_collection(COLLECTION)` before re-embedding, so the index is
  empty for the whole run and a crash mid-build leaves no index at all. Use it
  only when a dark window is acceptable.
- **`_health()` as proof the index moved**: it probes
  `embed_queries(["health probe"])`, which reports the QUERY backend. A healthy
  query path over a stale-built index reads as fully green.
- **`SKILL_EMBED_MODEL` as the backend signal**: the model name is identical on
  both hosts; only the quantization differs, so the name cannot distinguish them.

## Watch out
- **Proving which backend built the index**: sample points with `with_vector:
  true` from `/collections/<name>/points/scroll`, re-derive each point's text via
  `_doc_embed_text(_skill_text(s))`, confirm `_content_hash` matches the stored
  `content_hash` (skip drifted skills), then re-embed through BOTH backends.
  `cos(stored, backend) == 1.000000` on one and ~0.985 on the other identifies
  the builder. Sample a mix of scopes.
- **`SKILL_EMBED_BACKEND` is per-process**: `skill_search/server.py` defaults it
  to `fastembed`; `.mcp.json` and `index_owner.py` set `ollama` (the owner via
  `os.environ.setdefault`). A script importing `skill_search` without that env
  var dies with "Model embeddinggemma-2:270m is not supported in TextEmbedding" —
  a backend-selection error, not a missing model.
- **`SKILL_EMBED_TOKEN` gates the rtx endpoint**: `/api/embed` returns 401
  without it. Check `bool(token)`; never print the value.
- Measured through rtx: 43.2 ms/doc at `SKILL_EMBED_BATCH=64`.

In the code:
- seams: `SKILL_COLLECTION`, `SKILL_META_PATH`, `NEXT_SKILLS_PATH` in
  `skill_search/server.py` (import-time, set before import)
- dim guard that does NOT catch this: `build_index` in `skill_search/server.py`
- numbers observed: `cos(stored, local Ollama) = 1.000000` vs
  `cos(stored, rtx) = 0.984998` over 6 hash-verified points
