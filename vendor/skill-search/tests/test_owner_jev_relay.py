"""ADR-0061 warm-connection relay ported into the index owner (`skill_search.index_owner`
`_jev_relay` + `Handler._jev`, POST /jev on the embed port), pinned offline: HTTPSConnection
is replaced, no network. Mirrors tests/test_jev_relay.py's cases against the retired Docker
embed shim this was ported from.

Covered at the function level (mirrors test_jev_relay.py exactly):
  * a completed exchange returns its connection to the pool and the next call reuses it;
  * a pooled connection the server closed is retried ONCE, on a FRESH connection -- never on
    a second pooled one, which may be just as stale after an idle spell;
  * a fresh connection that fails is not retried;
  * a timeout is never retried (the request may already be billed).

Covered end-to-end, against a real `Handler` on a real loopback socket:
  * a completed exchange over a real HTTP POST to /jev, connection reused across two calls;
  * a missing bearer token is a 401 with no relay attempt;
  * a relay failure maps to a 502 naming the exception's class, matching the shim;
  * the Authorization header is never written to the owner's log, on success or failure.

Not `owner_factory`/`OwnerProc` (`vendor/skill-search/tests/conftest.py`): those start the
owner in a SEPARATE PROCESS, so an in-process `HTTPSConnection` mock can never reach it, and
safely faking that boundary for a subprocess would need a new env-switchable host/scheme
override on the one TLS leg that carries the TypeSafe bearer key over the real network -- a
materially bigger, security-relevant change than porting the relay itself. This instead
mirrors `tests/test_query_embed.py`'s own established pattern in this repo: a real
`BaseHTTPRequestHandler` bound to a real loopback socket, in-process, with the one outbound
call it makes replaced.
"""

import http.client
import json
import queue
import socket
import threading

import pytest

from skill_search import index_owner as owner_mod


class FakeConn:
    made = []

    def __init__(self, host, timeout=None, context=None, fail=None):
        self.host, self.timeout, self.sock, self.fail, self.sent = host, timeout, None, fail, []
        FakeConn.made.append(self)

    def request(self, method, path, body=None, headers=None):
        self.sent.append((method, path, body, headers))
        if self.fail:
            raise self.fail

    def getresponse(self):
        class R:
            status = 200

            def read(self):
                return b'{"answers": {}}'
        return R()

    def close(self):
        self.closed = True


@pytest.fixture
def relay(monkeypatch):
    FakeConn.made = []
    monkeypatch.setattr(owner_mod, "_JEV_POOL", queue.LifoQueue(maxsize=8))
    monkeypatch.setattr(owner_mod.http.client, "HTTPSConnection", FakeConn)
    return owner_mod


# -- function-level: mirrors tests/test_jev_relay.py -------------------------------------

def test_completed_exchange_is_pooled_and_reused(relay):
    assert relay._jev_relay(b"{}", "Bearer k", 2.0) == (200, b'{"answers": {}}')
    first = FakeConn.made[0]
    relay._jev_relay(b"{}", "Bearer k", 2.0)
    assert len(FakeConn.made) == 1 and len(first.sent) == 2          # one connection, two requests
    method, path, _body, headers = first.sent[0]
    assert (first.host, method, path) == ("api.typesafe.ai", "POST", "/v1/systemone")
    assert headers["Authorization"] == "Bearer k"


def test_stale_pooled_connection_retries_once_on_a_fresh_one(relay):
    for _ in range(2):   # two stale connections left in the pool after an idle spell
        relay._JEV_POOL.put_nowait(
            FakeConn("api.typesafe.ai", fail=http.client.RemoteDisconnected("closed")))
    FakeConn.made = []
    assert relay._jev_relay(b"{}", "Bearer k", 2.0)[0] == 200
    assert len(FakeConn.made) == 1 and not FakeConn.made[0].fail     # the retry was a NEW connection


def test_fresh_connection_failure_is_not_retried(relay, monkeypatch):
    monkeypatch.setattr(owner_mod.http.client, "HTTPSConnection",
                        lambda *a, **k: FakeConn(*a, fail=ConnectionResetError("reset"), **k))
    with pytest.raises(ConnectionResetError):
        relay._jev_relay(b"{}", "Bearer k", 2.0)
    assert len(FakeConn.made) == 1


@pytest.mark.parametrize("err", [socket.timeout("slow"), TimeoutError("slow")])
def test_timeout_is_never_retried(relay, err):
    relay._JEV_POOL.put_nowait(FakeConn("api.typesafe.ai", fail=err))
    FakeConn.made = []
    with pytest.raises(OSError):
        relay._jev_relay(b"{}", "Bearer k", 2.0)
    assert FakeConn.made == []                                        # no second request was sent


# -- end-to-end: a real Handler on a real loopback socket --------------------------------

@pytest.fixture
def jev_server(relay):
    """A real `Handler` (kind='embed') bound to a real loopback socket. `OWNER` stays
    None -- /jev never touches it. Torn down at test end."""
    handler = type("EmbedHandler", (relay.Handler,), {"kind": "embed"})
    srv = relay._Server4(("127.0.0.1", 0), handler)
    t = threading.Thread(target=srv.serve_forever, args=(0.05,), daemon=True)
    t.start()
    try:
        yield srv.server_address[1]
    finally:
        srv.shutdown()
        srv.server_close()


def _post_jev(port, body=b"{}", auth="Bearer k", timeout_hdr="5", ctype="application/json"):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    headers = {"Host": f"127.0.0.1:{port}", "Content-Type": ctype}
    if auth is not None:
        headers["Authorization"] = auth
    if timeout_hdr is not None:
        headers["X-Jev-Timeout"] = timeout_hdr
    try:
        conn.request("POST", "/jev", body=body, headers=headers)
        r = conn.getresponse()
        return r.status, r.read()
    finally:
        conn.close()


def test_e2e_successful_relay_reuses_the_pooled_connection(jev_server):
    assert _post_jev(jev_server) == (200, b'{"answers": {}}')
    assert _post_jev(jev_server) == (200, b'{"answers": {}}')
    assert len(FakeConn.made) == 1     # the second POST reused the first's pooled connection


def test_e2e_missing_bearer_is_401_with_no_relay_attempt(jev_server):
    status, raw = _post_jev(jev_server, auth=None)
    assert status == 401 and json.loads(raw) == {"error": "missing bearer token"}
    assert FakeConn.made == []


def test_e2e_relay_failure_maps_to_a_502(jev_server, monkeypatch):
    monkeypatch.setattr(owner_mod.http.client, "HTTPSConnection",
                        lambda *a, **k: FakeConn(*a, fail=ConnectionResetError("reset"), **k))
    status, raw = _post_jev(jev_server)
    assert status == 502 and json.loads(raw) == {"error": "ConnectionResetError"}


def test_e2e_the_bearer_key_is_never_logged(jev_server, monkeypatch):
    logged = []
    monkeypatch.setattr(owner_mod, "log", lambda msg: logged.append(msg))
    _post_jev(jev_server, auth="Bearer top-secret-key")                         # success path
    monkeypatch.setattr(owner_mod.http.client, "HTTPSConnection",
                        lambda *a, **k: FakeConn(*a, fail=ConnectionResetError("reset"), **k))
    _post_jev(jev_server, auth="Bearer top-secret-key")                         # failure path
    assert all("top-secret-key" not in m for m in logged)
