"""The index owner's SystemOne relay (ADR-0061, widened by ADR-0081): fixed destinations TypeSafe (/jev) and
Command Code (/jev/cc), warm pools, keyless keep-warm. Offline: the destinations are fake providers on 127.0.0.1.

Covered:
  • each destination gets its own path, pool and User-Agent; the caller's Authorization is forwarded as given;
  • a request the provider received is never sent again (the review defect: a drop after the full send
    used to re-send it);
  • a pooled connection the provider closed is discarded before use, so the request goes out once;
  • keep-warm: a destination never used is never contacted; a used one gets one keyless GET and keeps it;
  • routing: /jev -> TypeSafe, /jev/cc -> Command Code, any other /jev/<x> -> 404.
"""
import http.client
import json
import queue
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "vendor" / "skill-search"))
from skill_search import index_owner as io  # noqa: E402


class Fake:
    """A SystemOne look-alike. mode: ok | ok-then-drop (answers the first POST, reads later ones in full and
    hangs up without answering) | silent-close (answers, then closes the connection without saying so)."""

    def __init__(self, mode="ok"):
        self.mode, self.posts, self.gets, self.conns = mode, [], [], 0
        self.closed = queue.Queue()     # one item per connection the server has finished closing
        owner = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def setup(self):
                owner.conns += 1
                super().setup()

            def log_message(self, *a):
                pass

            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                owner.posts.append({"path": self.path, "auth": self.headers.get("Authorization"),
                                    "ua": self.headers.get("User-Agent")})
                if owner.mode == "ok-then-drop" and len(owner.posts) > 1:
                    self.close_connection = True
                    self.connection.shutdown(2)
                    return
                self._send(200, b'{"answers": {}}')
                if owner.mode == "silent-close":
                    self.close_connection = True

            def do_GET(self):
                owner.gets.append({"path": self.path, "auth": self.headers.get("Authorization")})
                self._send(401, b'{"error": "unauthorized"}')

            def _send(self, code, out):
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

        class Srv(ThreadingHTTPServer):
            def shutdown_request(self, request):
                super().shutdown_request(request)
                owner.closed.put(request)

        self.srv = Srv(("127.0.0.1", 0), H)
        self.srv.daemon_threads = True
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.port = self.srv.server_address[1]

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


@pytest.fixture
def fakes(monkeypatch):
    made = {"ts": Fake(), "cc": Fake()}
    monkeypatch.setattr(io, "_jev_conn", lambda ep, timeout: http.client.HTTPConnection(
        "127.0.0.1", made[ep].port, timeout=timeout))
    monkeypatch.setattr(io, "_JEV_POOLS", {ep: queue.LifoQueue(maxsize=8) for ep in io.JEV_DESTS})
    monkeypatch.setattr(io, "_JEV_LAST_USED", {ep: 0.0 for ep in io.JEV_DESTS})
    yield made
    for f in made.values():
        f.close()


def test_each_destination_has_its_own_path_pool_and_user_agent(fakes):
    for _ in range(2):
        assert io._jev_relay(b"{}", "Bearer cc-key", 2.0, "cc") == (200, b'{"answers": {}}')
    assert io._jev_relay(b"{}", "Bearer ts-key", 2.0) == (200, b'{"answers": {}}')     # default: TypeSafe
    cc, ts = fakes["cc"], fakes["ts"]
    assert [p["path"] for p in cc.posts] == ["/provider/v1/systemone"] * 2 and cc.conns == 1
    assert [p["path"] for p in ts.posts] == ["/v1/systemone"]
    assert {p["auth"] for p in cc.posts} == {"Bearer cc-key"} and ts.posts[0]["auth"] == "Bearer ts-key"
    assert {p["ua"] for p in cc.posts + ts.posts} == {"skill-concierge"}


def test_a_request_the_provider_received_is_never_sent_again(fakes, monkeypatch):
    fakes["cc"].mode = "ok-then-drop"
    assert io._jev_relay(b"{}", "Bearer k", 2.0, "cc")[0] == 200          # pools a live connection
    with pytest.raises((http.client.HTTPException, OSError)):
        io._jev_relay(b"{}", "Bearer k", 2.0, "cc")                       # sent in full, then dropped
    assert len(fakes["cc"].posts) == 2                                     # was 3: it used to be re-sent


def test_a_pooled_connection_the_provider_closed_is_discarded_before_use(fakes):
    fakes["ts"].mode = "silent-close"
    for _ in range(3):
        assert io._jev_relay(b"{}", "Bearer k", 2.0)[0] == 200
        # The handler thread closes the socket after the reply is on the wire, so the client can win that race
        # and reuse the connection while it is still open at the provider's end. That is not the case under
        # test (a provider that had already closed): wait until the close has happened.
        fakes["ts"].closed.get(timeout=5)
    assert len(fakes["ts"].posts) == 3 and fakes["ts"].conns == 3          # each request went out once


def test_keep_warm_touches_only_used_destinations_with_one_keyless_get(fakes):
    io._jev_warm_step()
    assert fakes["ts"].conns == fakes["cc"].conns == 0                     # never used: never contacted
    io._JEV_LAST_USED["cc"] = time.time()
    io._jev_warm_step()
    assert fakes["cc"].gets == [{"path": "/provider/v1/systemone", "auth": None}] and fakes["cc"].posts == []
    io._jev_warm_step()
    assert len(fakes["cc"].gets) == 1                                      # already warm: nothing new
    assert io._jev_relay(b"{}", "Bearer k", 2.0, "cc")[0] == 200
    assert fakes["cc"].conns == 1                                          # the warmed connection served it


def test_routing_by_path(fakes, monkeypatch):
    handler = type("EmbedHandler", (io.Handler,), {"kind": "embed"})
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        port = srv.server_address[1]

        def post(path):
            req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", b"{}",
                                         {"Content-Type": "application/json", "Authorization": "Bearer k"})
            try:
                with urllib.request.urlopen(req, timeout=5) as r:
                    return r.status
            except urllib.error.HTTPError as e:
                return e.code
        assert post("/jev") == 200 and post("/jev/cc") == 200 and post("/jev/xx") == 404
        assert len(fakes["ts"].posts) == 1 and len(fakes["cc"].posts) == 1
    finally:
        srv.shutdown()
        srv.server_close()


# ── the hook's side (hooks/scripts/enforcer.py) ─────────────────────────────────────────────────────────────
ENFORCER = Path(__file__).resolve().parents[1] / "hooks" / "scripts" / "enforcer.py"


def _enforcer(tmp_path, monkeypatch, **env):
    import importlib.util
    for k in ("ENFORCER_JEV_CC_URL", "JEVD_URL", "EMBED_SHIM_HOST"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("SKILL_CONCIERGE_LOG", str(tmp_path))
    spec = importlib.util.spec_from_file_location(f"enf_ccrelay_{abs(hash(str(env)))}", ENFORCER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CC_TIER = {"ep": "cc", "model": "typesafe/jev", "url": "https://api.commandcode.ai/provider/v1/systemone",
           "timeout": 5.5, "span": 5.5}


def test_the_hooks_command_code_tier_uses_the_owners_cc_route(tmp_path, monkeypatch):
    mod = _enforcer(tmp_path, monkeypatch)
    assert mod.JEV_CC_RELAY_URL and mod.JEV_CC_RELAY_URL.endswith("/jev/cc")
    seen = []

    def post(url, body, timeout, headers=None):
        seen.append((url, headers.get("X-Jev-Timeout"), headers.get("Authorization")))
        return {"model": "typesafe/jev", "answers": {"a": 1}}
    monkeypatch.setattr(mod, "_post_json", post)
    assert mod._jev_call({}, {}, CC_TIER, "cc-key", 5.5) == ({"a": 1}, "relay", "typesafe/jev")
    assert seen == [(mod.JEV_CC_RELAY_URL, "5.5", "Bearer cc-key")]


def test_an_owner_without_the_cc_route_means_one_direct_call(tmp_path, monkeypatch):
    mod = _enforcer(tmp_path, monkeypatch)
    seen = []

    def post(url, body, timeout, headers=None):
        seen.append(url)
        if url == mod.JEV_CC_RELAY_URL:   # an owner that predates /jev/cc
            raise urllib.error.HTTPError(url, 404, "not found", {}, None)
        return {"model": "typesafe/jev", "answers": {}}
    monkeypatch.setattr(mod, "_post_json", post)
    assert mod._jev_call({}, {}, CC_TIER, "k", 5.5)[1] == "direct"
    assert seen == [mod.JEV_CC_RELAY_URL, CC_TIER["url"]]


def test_a_non_command_code_cc_url_never_uses_the_relay(tmp_path, monkeypatch):
    assert _enforcer(tmp_path, monkeypatch, ENFORCER_JEV_CC_URL="http://127.0.0.1:9/x").JEV_CC_RELAY_URL is None


def test_the_offline_client_keeps_both_relays_off(monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "jev_client_ccrelay", Path(__file__).resolve().parents[1] / "scripts" / "jev_client.py")
    jc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(jc)
    enf = jc.load_enforcer()
    assert enf.JEV_RELAY_URL is None and enf.JEV_CC_RELAY_URL is None
