---
phase: 1
title: "Warm Embed Endpoint"
status: done
priority: P1
effort: "0.5-1d"
dependencies: []
---

# Phase 1: Warm Embed Endpoint

## Overview

A tiny persistent HTTP service holding the fastembed mpnet-768 model in memory: `POST {text}` →
`{vector}`, health-checkable, auto-started as a sidecar next to Qdrant. It exists so the cold
per-turn hook can embed a query in ~tens of ms instead of paying a multi-second cold model load.
It MUST serve the **exact** model + backend + fastembed version the Qdrant index was built with,
or query vectors are incomparable to indexed vectors (see Risks — this is the make-or-break point).

## Related Code Files

- Create: `bin/embed-shim` — launcher that execs the stable venv (`~/.local/share/skill-concierge/venv`),
  mirroring `bin/skill-search-mcp` so it survives plugin reinstalls.
- Create: `scripts/embed_server.py` — the HTTP service. Import the embedding path from
  `vendor/skill-search/` rather than re-instantiating, to guarantee model/version parity.
- Modify: `setup.sh` — start the shim during bring-up (only if not already listening).
- Create: `Dockerfile` + a compose/run entry for the shim, run as a **Docker sidecar** next to the
  Qdrant container (owner decision, Validation S1). <!-- Updated: Validation Session 1 - Docker sidecar over launchd -->

## Implementation Steps

1. **Surface:** stdlib `http.server` with a single `POST /embed` + `GET /health` is enough. No
   FastAPI/uvicorn — the stable venv already has fastembed. `# ponytail: one-file service.`
2. **Load once:** instantiate `fastembed.TextEmbedding(model_name=SKILL_EMBED_MODEL)` at process
   start, reading the SAME env the MCP uses (`SKILL_EMBED_MODEL=...mpnet-base-v2`,
   `SKILL_EMBED_BACKEND=fastembed`). Use the DEPLOYED mpnet-768 env explicitly — NOT the engine
   default `bge-small-en-v1.5` (384-dim). Pin `fastembed==0.8.0` (the index's build version).
   <!-- Updated: Validation Session 1 - deployed mpnet env + pin 0.8.0 -->
3. **Routes:** `POST /embed {"text": "..."}` → `{"vector": [...768]}`; `GET /health` →
   `{status, model, dim}`.
4. **Bind localhost** on a fixed free port (e.g. 6363, adjacent to Qdrant 6333 — confirm free).
   Single-threaded is acceptable once warm; document the throughput ceiling with a `ponytail:` note.
5. **Launcher:** `bin/embed-shim` execs the stable-venv python on `scripts/embed_server.py`.
6. **Auto-start:** run the shim as a **Docker sidecar** next to the Qdrant container with
   `--restart unless-stopped` (matches Qdrant's policy). Add it to `setup.sh` bring-up. Co-locating
   with Qdrant keeps both embed-stack services under one runtime (owner decision, Validation S1).
7. **Warm-up:** embed a dummy string at startup so the first real request isn't the cold one.

## Success Criteria

- [x] `GET /health` → `status:ok`, correct model name, `dim:768`.
- [x] `POST /embed` returns a 768-vector in <~50ms warm (measured).
- [x] **Parity check:** embedding a known skill description via the shim vs via the index-build path
      yields cosine ≈ 1.0 — proves shim vectors are comparable to the live index.
- [x] Shim runs as a Docker sidecar with `--restart unless-stopped`; survives daemon/host restart.

## Risk Assessment

- **Pooling/version drift (VERIFIED RISK).** The live engine emits
  `UserWarning: ...paraphrase-multilingual-mpnet-base-v2 now uses mean pooling instead of CLS
  embedding ... pin fastembed 0.5.1 or use add_custom_model`. If the shim's fastembed version uses
  a different pooling than the indexed vectors, retrieval silently degrades to garbage with NO error.
  Mitigation: pin `fastembed==0.8.0` (the index's build version) in BOTH the engine install and the
  shim; do NOT follow the warning's 0.5.1 suggestion — that switches to CLS pooling and mismatches
  the 0.8.0-built index. The `fastembed>=0.3` range in `pyproject.toml` must be pinned. Gate go-live
  on the parity cosine ≈ 1.0 check above. <!-- Updated: Validation Session 1 - pin 0.8.0, 0.5.1 is a trap -->
- New always-on dependency (like Qdrant). Mitigated downstream by the Phase 3 mandate-only fallback —
  an outage degrades the hook, never breaks it.
