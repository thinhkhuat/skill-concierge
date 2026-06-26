# skill-concierge — warm embed shim, run as a Docker sidecar next to the
# skill-search-qdrant container (owner decision, Validation S1).
#
# PARITY: pins fastembed==0.8.0 — the exact version the live Qdrant index was
# built with. A different fastembed can change pooling (mean vs CLS) and silently
# desync query vectors from indexed vectors. Do NOT follow fastembed's runtime
# "pin 0.5.1" warning: 0.5.1 uses CLS pooling and mismatches the 0.8.0 index.
FROM python:3.12-slim

WORKDIR /app

# Install the vendored engine (brings mcp/qdrant-client/requests) with fastembed
# pinned to the index's build version. Reusing the engine gives the shim the same
# embed() code path the index was built with.
COPY vendor/skill-search /app/skill-search
RUN pip install --no-cache-dir /app/skill-search "fastembed==0.8.0"
COPY scripts/embed_server.py /app/embed_server.py

ENV SKILL_EMBED_BACKEND=fastembed \
    SKILL_EMBED_MODEL=sentence-transformers/paraphrase-multilingual-mpnet-base-v2 \
    SKILL_QDRANT_URL=http://localhost:6333 \
    EMBED_SHIM_HOST=0.0.0.0 \
    EMBED_SHIM_PORT=6363 \
    FASTEMBED_CACHE_PATH=/models

# Bake the model into the image so the container boots warm (no first-request
# multi-second download). Imports the same path the server uses; SKILL_QDRANT_URL
# keeps the engine's client in lazy url-mode (no stray embedded store written).
RUN python -c "from skill_search.server import embed; v=embed('bake model'); assert len(v)==768, len(v); print('baked dim', len(v))"

EXPOSE 6363
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:6363/health',timeout=3).status==200 else 1)"
CMD ["python", "/app/embed_server.py"]
