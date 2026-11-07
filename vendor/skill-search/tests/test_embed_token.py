"""The embedder sends a bearer token only when SKILL_EMBED_TOKEN is set.

A bare local Ollama must keep working with no Authorization header at all (the default,
and the behaviour before this key existed). A protected endpoint — a proxy in front of a
remote GPU host — answers 401 to an unauthenticated /api/embed, so the token has to ride
both the batch and the legacy single-item path.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from skill_search import server


@pytest.fixture()
def stub(monkeypatch):
    """A stub that echoes the Authorization header it received back in the body."""
    seen = {}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *_a):
            pass

        def _send(self, code, obj):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(n) or b"{}")
            seen["auth"] = self.headers.get("Authorization")
            seen["path"] = self.path
            if self.path.endswith("/api/embed"):
                texts = payload.get("input") or []
                self._send(200, {"embeddings": [[0.1, 0.2, 0.3] for _ in texts]})
            else:
                self._send(200, {"embedding": [0.1, 0.2, 0.3]})

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    monkeypatch.setattr(server, "OLLAMA_URL", f"http://127.0.0.1:{srv.server_port}")
    # conftest pins the backend to fastembed; take the Ollama path explicitly.
    monkeypatch.setattr(server, "EMBED_BACKEND", "ollama")
    yield seen
    srv.shutdown()


def test_no_token_sends_no_authorization_header(stub, monkeypatch):
    """The default. A local Ollama needs nothing, and sending a blank bearer would be a lie."""
    monkeypatch.setattr(server, "EMBED_TOKEN", "")
    assert server.embed_batch(["one", "two"]) == [[0.1, 0.2, 0.3], [0.1, 0.2, 0.3]]
    assert stub["path"].endswith("/api/embed")
    assert stub["auth"] is None


def test_token_is_sent_on_the_batch_path(stub, monkeypatch):
    monkeypatch.setattr(server, "EMBED_TOKEN", "tok-123")
    server.embed_batch(["one", "two"])
    assert stub["auth"] == "Bearer tok-123"


def test_token_is_sent_on_the_single_item_fallback(stub, monkeypatch):
    """The fallback fires when the batch endpoint fails; it must carry the same auth."""
    monkeypatch.setattr(server, "EMBED_TOKEN", "tok-123")
    server._ollama_embed_one("one")
    assert stub["path"].endswith("/api/embeddings")
    assert stub["auth"] == "Bearer tok-123"


def test_token_is_engine_env_forwarded():
    """A reindex must build against the same authenticated endpoint the server serves."""
    import importlib.util
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location("ee", root / "scripts" / "engine_env.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert "SKILL_EMBED_TOKEN" in mod.ENGINE_ENV_KEYS
