"""ADR-0061 warm-connection relay in the embed shim (`scripts/embed_server.py` POST /jev), pinned
offline: HTTPSConnection is replaced, no network.

Covered:
  • a completed exchange returns its connection to the pool and the next call reuses it;
  • a pooled connection the server closed is retried ONCE, on a FRESH connection — never on a
    second pooled one, which may be just as stale after an idle spell;
  • a fresh connection that fails is not retried;
  • a timeout is never retried (the request may already be billed);
  • the destination is fixed and the caller's Authorization header is forwarded as given.
"""

import http.client
import os
import queue
import socket
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

# The shim sets the deployed embed env and imports the engine when it loads. In the shared pytest
# process that would leave the live model in os.environ and a live-configured engine module in
# sys.modules for every later test (the engine suite expects its own 384-dim default).
_SHIM_ENV = ("SKILL_EMBED_BACKEND", "SKILL_EMBED_MODEL", "SKILL_QDRANT_URL")
_ENGINE_WAS_LOADED = "skill_search.server" in sys.modules
_ENV_BEFORE = {k: os.environ.get(k) for k in _SHIM_ENV}


def _import_shim():
    """Import the shim against a stub engine, then put os.environ and sys.modules back."""
    env = {k: os.environ.get(k) for k in _SHIM_ENV}
    before = set(sys.modules)
    stub = types.ModuleType("skill_search.server")
    stub.EMBED_MODEL, stub.embed = "stub", lambda text: []   # the relay tests never embed
    real = sys.modules.get("skill_search.server")
    sys.modules["skill_search.server"] = stub
    try:
        import embed_server
    finally:
        if real is not None:
            sys.modules["skill_search.server"] = real
        for name in set(sys.modules) - before:
            if name == "skill_search" or name.startswith("skill_search."):
                del sys.modules[name]
        if real is None:
            sys.modules.pop("skill_search.server", None)
        for k, v in env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return embed_server


es = _import_shim()
# Recorded right after the import: later tests may load the engine or set env legitimately.
_AFTER = ("skill_search.server" in sys.modules, {k: os.environ.get(k) for k in _SHIM_ENV})


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
    monkeypatch.setattr(es, "_POOL", queue.LifoQueue(maxsize=8))
    monkeypatch.setattr(es.http.client, "HTTPSConnection", FakeConn)
    return es


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
        relay._POOL.put_nowait(FakeConn("api.typesafe.ai", fail=http.client.RemoteDisconnected("closed")))
    FakeConn.made = []
    assert relay._jev_relay(b"{}", "Bearer k", 2.0)[0] == 200
    assert len(FakeConn.made) == 1 and not FakeConn.made[0].fail     # the retry was a NEW connection


def test_fresh_connection_failure_is_not_retried(relay, monkeypatch):
    monkeypatch.setattr(es.http.client, "HTTPSConnection",
                        lambda *a, **k: FakeConn(*a, fail=ConnectionResetError("reset"), **k))
    with pytest.raises(ConnectionResetError):
        relay._jev_relay(b"{}", "Bearer k", 2.0)
    assert len(FakeConn.made) == 1


@pytest.mark.parametrize("err", [socket.timeout("slow"), TimeoutError("slow")])
def test_timeout_is_never_retried(relay, err):
    relay._POOL.put_nowait(FakeConn("api.typesafe.ai", fail=err))
    FakeConn.made = []
    with pytest.raises(OSError):
        relay._jev_relay(b"{}", "Bearer k", 2.0)
    assert FakeConn.made == []                                        # no second request was sent


def test_importing_the_shim_leaks_nothing_into_the_test_process():
    """Its import-time env and engine import must not reach later tests in this process."""
    assert _AFTER == (_ENGINE_WAS_LOADED, _ENV_BEFORE)
