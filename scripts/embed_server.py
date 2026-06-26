#!/usr/bin/env python3
"""
skill-concierge — warm embed shim.

A persistent HTTP service that holds the fastembed mpnet-768 model in memory so
the per-turn enforcer hook can embed a query in ~tens of ms instead of paying the
multi-second cold model load on every prompt.

PARITY CONTRACT (make-or-break). The shim's vectors MUST be comparable to the
live Qdrant index, or retrieval silently degrades to garbage with NO error. It
guarantees this by reusing the EXACT embedding path the index was built with —
`skill_search.server.embed` — under the SAME env the MCP uses:
  SKILL_EMBED_MODEL   = sentence-transformers/paraphrase-multilingual-mpnet-base-v2
  SKILL_EMBED_BACKEND = fastembed
  fastembed pinned to 0.8.0 (the index's build version; 0.5.1 is a trap — it
  switches to CLS pooling and mismatches the 0.8.0-built index).
Do NOT re-instantiate TextEmbedding here. Validate parity with the cosine ≈ 1.0
check against the live index (phase-01 Success Criteria).

Routes:
  POST /embed  {"text": "..."}  -> {"vector": [...768]}
  GET  /health                  -> {"status":"ok","model":..., "dim":768}

# ThreadingHTTPServer: live dogfooding showed a single-threaded shim serialized
# concurrent hits (multiple UserPromptSubmit hooks per turn + overlapping sessions),
# pushing the per-turn embed POST past the client timeout ~60% of turns. onnxruntime
# releases the GIL during inference, so per-request threads run concurrently and cut
# that queuing. The model object is shared+stateless across requests (ORT Run is
# thread-safe). # ponytail: threaded stdlib server; reach for gunicorn only if this
# is measured insufficient, not before.
"""
import os
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Set the deployed embed env BEFORE importing the engine, so it reads mpnet-768
# (NOT the engine's bge-small-en-v1.5 384-dim default). SKILL_QDRANT_URL forces
# the engine's QdrantClient into lazy url-mode at import: the shim never queries
# Qdrant, but url-mode avoids creating a stray embedded on-disk store. None of
# this couples shim startup to Qdrant reachability (url-mode connects lazily).
os.environ.setdefault("SKILL_EMBED_BACKEND", "fastembed")
os.environ.setdefault(
    "SKILL_EMBED_MODEL",
    "sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
)
os.environ.setdefault("SKILL_QDRANT_URL", "http://localhost:6333")

from skill_search.server import embed, EMBED_MODEL  # noqa: E402  (env must precede import)

HOST = os.environ.get("EMBED_SHIM_HOST", "127.0.0.1")
PORT = int(os.environ.get("EMBED_SHIM_PORT", "6363"))

_DIM = None


def _dim() -> int:
    global _DIM
    if _DIM is None:
        _DIM = len(embed("dimension probe"))
    return _DIM


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802 (http.server API)
        if self.path == "/health":
            self._send(200, {"status": "ok", "model": EMBED_MODEL, "dim": _dim()})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802 (http.server API)
        if self.path != "/embed":
            self._send(404, {"error": "not found"})
            return
        try:
            n = int(self.headers.get("Content-Length", 0) or 0)
            payload = json.loads(self.rfile.read(n) or b"{}")
            text = payload.get("text", "")
            if not isinstance(text, str) or not text:
                self._send(400, {"error": "missing 'text'"})
                return
            self._send(200, {"vector": embed(text)})
        except Exception as e:  # never crash the service on a bad request
            self._send(500, {"error": str(e)})

    def log_message(self, *_a):
        pass  # quiet: runs as a service, not interactively


def main() -> None:
    # Warm-up so the first REAL request isn't the cold model load.
    embed("warm up")
    print(
        f"embed-shim: model={EMBED_MODEL} dim={_dim()} listening on {HOST}:{PORT} (threaded)",
        flush=True,
    )
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
