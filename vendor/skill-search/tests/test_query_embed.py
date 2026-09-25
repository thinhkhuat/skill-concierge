"""Query vectors come from the index owner's /embed when it serves the engine's model,
from the in-process model when it does not, and from nowhere when the store is down."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from skill_search import server


def _stub(model, embed_status=200, health_status=200):
    calls = []

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

        def do_GET(self):        # /health on the embed port, / on the store port
            self._send(health_status, {"status": "ok", "model": model, "dim": 3})

        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            calls.append((self.headers.get("Content-Type"), json.loads(self.rfile.read(n))))
            self._send(embed_status, {"vector": [0.5, 0.25, 1.0]})

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}", calls


DOWN = "http://127.0.0.1:1"


@pytest.fixture
def owner_stub(monkeypatch):
    started = []
    local = []

    def make(model, store="same", **kw):
        srv, url, calls = _stub(model, **kw)
        started.append(srv)
        if store == "separate":                      # a Qdrant that stays up on its own
            other, store_url, _ = _stub(None)
            started.append(other)
        else:
            store_url = url if store == "same" else DOWN
        monkeypatch.setattr(server, "EMBED_BASE", url)
        monkeypatch.setattr(server, "QDRANT_URL", store_url)
        monkeypatch.setattr(server, "_owner_ok", False)
        monkeypatch.setattr(server, "EMBED_BACKEND", "fastembed")
        monkeypatch.setattr(server, "embed_batch",
                            lambda texts: local.append(texts) or [["local"] for _ in texts])
        return calls, local

    yield make
    for s in started:
        s.shutdown()


def test_owner_serving_same_model_answers_queries(owner_stub):
    calls, local = owner_stub(server.EMBED_MODEL)
    assert server.embed_queries(["a", "b"]) == [[0.5, 0.25, 1.0]] * 2
    assert calls == [("application/json", {"text": "a"}), ("application/json", {"text": "b"})]
    assert local == []


def test_owner_with_another_model_is_not_used(owner_stub):
    calls, _ = owner_stub("some/other-model")
    assert server.embed_queries(["a"]) == [["local"]]
    assert calls == []
    assert server._owner_ok is False                 # a "no" is asked again next query


def test_embed_service_still_loading_is_not_used(owner_stub):
    calls, _ = owner_stub(server.EMBED_MODEL, health_status=503, store="separate")
    assert server.embed_queries(["a"]) == [["local"]]
    assert calls == []


def test_embed_failure_after_good_health_falls_back(owner_stub):
    _, local = owner_stub(server.EMBED_MODEL, embed_status=500)
    assert server.embed_queries(["a"]) == [["local"]]
    assert local == [["a"]]


def test_owner_loading_as_the_store_loads_no_model(owner_stub):
    # after the cutover the owner is also the store: 503 on both while it loads
    _, local = owner_stub(server.EMBED_MODEL, health_status=503)
    with pytest.raises(RuntimeError, match="not answering"):
        server.embed_queries(["a"])
    assert local == []


def test_owner_and_store_down_loads_no_model(owner_stub, monkeypatch):
    _, local = owner_stub(server.EMBED_MODEL, store="down")
    monkeypatch.setattr(server, "EMBED_BASE", DOWN)
    with pytest.raises(RuntimeError, match="not answering"):
        server.embed_queries(["a"])
    assert local == []                               # nothing to search: no 1.4 GB load


def test_other_backends_never_ask_the_owner(owner_stub, monkeypatch):
    calls, _ = owner_stub(server.EMBED_MODEL)
    monkeypatch.setattr(server, "EMBED_BACKEND", "ollama")
    assert server.embed_queries(["a"]) == [["local"]]
    assert calls == []
