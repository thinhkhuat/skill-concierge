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
  POST /jev    <TypeSafe System One request body>  -> the upstream response, verbatim
  GET  /health                  -> {"status":"ok","model":..., "dim":768, "routes":[...]}

/jev (ADR-0061) exists for latency, not function: a hook is a new process every turn, so a
direct call pays DNS + TCP + TLS each time (measured 735 ms for a tiny call vs 230 ms on a
reused connection, 1110 vs 391 ms for the whole-catalogue call). The shim keeps a small pool
of warm HTTPS connections shared by every request thread (ThreadingHTTPServer starts a new
thread per request, so a per-thread connection would never be reused). It is a
fixed-destination relay, not a proxy: the upstream host and path are constants, the
caller's Authorization header is forwarded and never stored, and the shim itself holds no key.

# ThreadingHTTPServer: live dogfooding showed a single-threaded shim serialized
# concurrent hits (multiple UserPromptSubmit hooks per turn + overlapping sessions),
# pushing the per-turn embed POST past the client timeout ~60% of turns. onnxruntime
# releases the GIL during inference, so per-request threads run concurrently and cut
# that queuing. The model object is shared+stateless across requests (ORT Run is
# thread-safe). # ponytail: threaded stdlib server; reach for gunicorn only if this
# is measured insufficient, not before.
"""
import http.client
import json
import os
import queue
import ssl
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

from skill_search.server import EMBED_MODEL, embed

HOST = os.environ.get("EMBED_SHIM_HOST", "127.0.0.1")
PORT = int(os.environ.get("EMBED_SHIM_PORT", "6363"))

_DIM = None

JEV_HOST = "api.typesafe.ai"
JEV_PATH = "/v1/systemone"
JEV_MAX_TIMEOUT = 10.0
_TLS = ssl.create_default_context()
_POOL = queue.LifoQueue(maxsize=8)   # warm connections, most recently used first


def _jev_relay(body: bytes, auth: str, timeout: float):
    """POST body to TypeSafe on a pooled warm connection -> (status, response bytes). A pooled
    connection the server has since closed fails at once (reset / remote closed); that case alone
    retries once on a fresh connection. A timeout is never retried: the request may already be
    billed and the hook has stopped waiting. A connection returns to the pool only after a
    complete exchange."""
    for attempt in (0, 1):
        try:
            if attempt:   # the retry never takes a second pooled connection: after an idle spell
                raise queue.Empty   # every pooled one may be stale
            conn, reused = _POOL.get_nowait(), True
        except queue.Empty:
            conn, reused = http.client.HTTPSConnection(JEV_HOST, context=_TLS), False
        conn.timeout = timeout
        if conn.sock is not None:
            conn.sock.settimeout(timeout)
        try:
            conn.request("POST", JEV_PATH, body=body,
                         headers={"Authorization": auth, "Content-Type": "application/json"})
            resp = conn.getresponse()
            out = resp.status, resp.read()
        except (ConnectionResetError, BrokenPipeError, http.client.RemoteDisconnected,
                http.client.BadStatusLine):
            conn.close()
            if attempt or not reused:
                raise
            continue
        except (http.client.HTTPException, OSError):
            conn.close()
            raise
        try:
            _POOL.put_nowait(conn)
        except queue.Full:
            conn.close()
        return out
    raise RuntimeError("unreachable")


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

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send(200, {"status": "ok", "model": EMBED_MODEL, "dim": _dim(), "routes": ["embed", "jev"]})
        else:
            self._send(404, {"error": "not found"})

    def _jev(self) -> None:
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            self._send(401, {"error": "missing bearer token"})
            return
        try:
            timeout = min(float(self.headers.get("X-Jev-Timeout", "5") or 5), JEV_MAX_TIMEOUT)
            n = int(self.headers.get("Content-Length", 0) or 0)
            status, raw = _jev_relay(self.rfile.read(n), auth, timeout)
        except (OSError, ValueError, http.client.HTTPException) as exc:
            self._send(502, {"error": type(exc).__name__})
            return
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self) -> None:
        if self.path == "/jev":
            self._jev()
            return
        if self.path != "/embed":
            self._send(404, {"error": "not found"})
            return
        try:
            n = int(self.headers.get("Content-Length", 0) or 0)
            payload = json.loads(self.rfile.read(n) or b"{}")
            if not isinstance(payload, dict):
                self._send(400, {"error": "request body must be a JSON object"})
                return
            text = payload.get("text", "")
            if not isinstance(text, str) or not text:
                self._send(400, {"error": "missing 'text'"})
                return
            self._send(200, {"vector": embed(text)})
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            self._send(500, {"error": str(exc)})

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
