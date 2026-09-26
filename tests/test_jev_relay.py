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
import queue
import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import embed_server as es  # noqa: E402


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
