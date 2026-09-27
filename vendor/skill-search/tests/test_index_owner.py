"""Index owner: the Qdrant REST subset, search semantics, guards and lifecycle,
exercised over HTTP against owners started on free ports with temp SQLite files."""

import http.client
import json
import math
import os
import random
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "qdrant_exact_groups.json"
SRC = Path(__file__).resolve().parents[1]   # vendor/skill-search: PYTHONPATH for raw subprocess tests


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def api(owner, method, path, body=None, headers=None, host=None):
    conn = http.client.HTTPConnection("127.0.0.1", owner.qport, timeout=10)
    h = {"Host": host or f"127.0.0.1:{owner.qport}"}
    if method != "GET":
        h["Content-Type"] = "application/json"
    h.update(headers or {})
    data = None if body is None else json.dumps(body).encode()
    try:
        conn.request(method, path, body=data, headers=h)
        r = conn.getresponse()
        raw = r.read()
        try:
            return r.status, json.loads(raw)
        except ValueError:
            return r.status, raw.decode()
    finally:
        conn.close()


def ok(owner, method, path, body=None):
    status, res = api(owner, method, path, body)
    assert status == 200, (status, res)
    return res["result"]


def vec(*xs):
    return list(xs) + [0.0] * (4 - len(xs))


def seed(owner, points, coll="t", dim=4):
    ok(owner, "PUT", f"/collections/{coll}", {"vectors": {"size": dim, "distance": "Cosine"}})
    ok(owner, "PUT", f"/collections/{coll}/points?wait=true", {"points": points})


def pt(i, name, v, **payload):
    return {"id": i, "vector": v, "payload": {"name": name, **payload}}


def groups(owner, q, flt=None, limit=10, coll="t"):
    body = {"query": q, "group_by": "name", "limit": limit, "group_size": 1, "with_payload": True}
    if flt is not None:
        body["filter"] = flt
    res = ok(owner, "POST", f"/collections/{coll}/points/query/groups", body)
    return [(g["id"], round(g["hits"][0]["score"], 6)) for g in res["groups"]]


def count(owner, flt, coll="t"):
    return ok(owner, "POST", f"/collections/{coll}/points/count", {"filter": flt, "exact": True})["count"]


@pytest.fixture
def owner(owner_factory):
    o = owner_factory().wait_ready()
    seed(o, [
        pt(1, "alpha", vec(1, 0), scope="personal", tier="external", flag=True),
        pt(2, "alpha", vec(0.9, 0.1), scope="personal", kind="trigger"),
        pt(3, "beta", vec(0, 1), scope="codex-plugin", flag=1),
        pt(4, "gamma", vec(1, 1), scope="omp-plugin", nullable=None),
        pt(5, "delta", vec(0.5, 0.5, 0.5), scope=["personal", "extra"]),
    ])
    return o


# -- filter grammar -------------------------------------------------------------------

def test_match_value(owner):
    assert count(owner, {"must": [{"key": "scope", "match": {"value": "personal"}}]}) == 3


def test_match_value_on_array_payload_matches_any_element(owner):
    assert count(owner, {"must": [{"key": "scope", "match": {"value": "extra"}}]}) == 1


def test_boolean_match_never_equals_one(owner):
    assert count(owner, {"must": [{"key": "flag", "match": {"value": True}}]}) == 1
    assert count(owner, {"must": [{"key": "flag", "match": {"value": 1}}]}) == 1
    got = ok(owner, "POST", "/collections/t/points/scroll",
             {"filter": {"must": [{"key": "flag", "match": {"value": True}}]}})
    assert [p["id"] for p in got["points"]] == [1]


def test_must_not(owner):
    assert count(owner, {"must_not": [{"key": "tier", "match": {"value": "external"}}]}) == 4


def test_should_is_any_of(owner):
    flt = {"should": [{"key": "scope", "match": {"value": "codex-plugin"}},
                      {"key": "scope", "match": {"value": "omp-plugin"}}]}
    assert count(owner, flt) == 2


def test_match_any(owner):
    flt = {"must": [{"key": "scope", "match": {"any": ["codex-plugin", "omp-plugin", "nope"]}}]}
    assert count(owner, flt) == 2


def test_is_null_matches_present_null_only(owner):
    assert count(owner, {"must": [{"is_null": {"key": "nullable"}}]}) == 1
    # a key that no point carries must NOT match is_null (Qdrant semantics)
    assert count(owner, {"must": [{"is_null": {"key": "nonexistent"}}]}) == 0


def test_nested_filter_and_combined_clauses(owner):
    flt = {"must": [{"should": [{"key": "name", "match": {"value": "alpha"}},
                                {"key": "name", "match": {"value": "beta"}}]}],
           "must_not": [{"key": "kind", "match": {"value": "trigger"}}]}
    assert count(owner, flt) == 2


def test_unsupported_condition_is_400(owner):
    status, _ = api(owner, "POST", "/collections/t/points/count",
                    {"filter": {"must": [{"key": "x", "range": {"gt": 1}}]}})
    assert status == 400


# -- grouped search -------------------------------------------------------------------

def test_best_point_per_skill_and_tie_break(owner):
    # alpha's best point is id 1 (1,0); gamma and delta tie on exact cosine only by
    # chance, so check the ordering rule on real ties separately below
    res = groups(owner, vec(1, 0))
    assert res[0] == ("alpha", 1.0)
    assert [n for n, _ in res] == ["alpha", "gamma", "delta", "beta"]


def test_match_any_with_fewer_matching_skills_than_limit(owner):
    flt = {"must": [{"key": "scope", "match": {"any": ["codex-plugin"]}}]}
    assert [n for n, _ in groups(owner, vec(1, 0), flt, limit=10)] == ["beta"]


def test_fully_filtered_out_skills_are_dropped(owner):
    flt = {"must_not": [{"key": "name", "match": {"value": "alpha"}}]}
    assert "alpha" not in [n for n, _ in groups(owner, vec(1, 0), flt)]
    # only alpha's trigger point survives: alpha stays, scored by that point
    flt = {"must_not": [{"key": "tier", "match": {"value": "external"}}]}
    res = dict(groups(owner, vec(1, 0), flt))
    assert res["alpha"] == pytest.approx(0.9 / math.hypot(0.9, 0.1), abs=1e-6)


def test_ties_at_the_limit_boundary_break_by_name(owner_factory):
    o = owner_factory().wait_ready()
    seed(o, [pt(i, n, vec(1, 1)) for i, n in enumerate(["zeta", "eta", "theta", "iota"], 1)]
         + [pt(9, "top", vec(1, 0.9))])
    assert groups(o, vec(1, 1), limit=3) == [("eta", 1.0), ("iota", 1.0), ("theta", 1.0)]


def test_point_query_ties_break_by_id_and_ids_keep_json_type(owner_factory):
    o = owner_factory().wait_ready()
    uid = "8a2e7b4c-0000-4000-8000-000000000001"
    seed(o, [{"id": 7, "vector": vec(1), "payload": {"label": "a"}},
             {"id": 3, "vector": vec(2), "payload": {"label": "b"}},
             {"id": uid, "vector": vec(1, 1), "payload": {"label": "c"}}], coll="prompt_intent")
    res = ok(o, "POST", "/collections/prompt_intent/points/query",
             {"query": vec(1), "limit": 3, "with_payload": ["label"], "params": {"exact": True}})
    assert [p["id"] for p in res["points"]] == [3, 7, uid]
    assert res["points"][0]["payload"] == {"label": "b"} and res["points"][0]["vector"] is None


def test_scores_match_qdrant_exact_fixture_after_normalization(owner_factory):
    fx = json.loads(FIXTURE.read_text())
    o = owner_factory().wait_ready()
    rnd = random.Random(3)
    # stored unnormalized (random scale) to prove the owner normalizes on write
    scale = [rnd.uniform(0.2, 5.0) for _ in fx["points"]]
    pts = [{"id": p["id"], "vector": [x * k for x in p["vector"]],
            "payload": {"name": p["name"], "kind": "base"}} for p, k in zip(fx["points"], scale)]
    seed(o, pts, coll="fx", dim=fx["dim"])
    res = ok(o, "POST", "/collections/fx/points/query/groups",
             {"query": fx["query"], "group_by": "name", "limit": 12, "group_size": 1,
              "with_payload": ["name"], "params": {"exact": True}})
    got = [(g["id"], g["hits"][0]["score"]) for g in res["groups"]]
    assert [n for n, _ in got] == [e["name"] for e in fx["expected"]]
    for (_, s), e in zip(got, fx["expected"]):
        assert abs(s - e["score"]) < 1e-4


def test_unit_vectors_are_stored_bit_for_bit(owner_factory):
    """An already-normalized vector (what Qdrant hands back on scroll) is kept as sent,
    the way Qdrant's own cosine preprocess keeps it; renormalizing would flip low bits."""
    import numpy as np
    rnd = np.random.default_rng(5)
    o = owner_factory().wait_ready()
    raw = rnd.standard_normal((50, 16)).astype(np.float32)
    unit = raw / np.linalg.norm(raw, axis=1, keepdims=True).astype(np.float32)
    seed(o, [pt(i, f"n{i}", [float(x) for x in v]) for i, v in enumerate(unit)], coll="u", dim=16)
    back = ok(o, "POST", "/collections/u/points",
              {"ids": list(range(50)), "with_vector": True})
    got = {r["id"]: np.asarray(r["vector"], dtype=np.float32).tobytes() for r in back}
    assert all(got[i] == unit[i].tobytes() for i in range(50))


# -- REST shape -----------------------------------------------------------------------

def test_collection_info_and_title(owner):
    info = ok(owner, "GET", "/collections/t")
    assert info["points_count"] == 5
    assert info["config"]["params"]["vectors"] == {"size": 4, "distance": "Cosine"}
    status, root = api(owner, "GET", "/")
    assert status == 200 and root["title"].startswith("skill-concierge index owner")
    assert api(owner, "GET", "/collections/missing")[0] == 404


def test_collection_exists_route(owner):
    # qdrant-client's collection_exists(): engines older than the owner call it on every reindex
    assert ok(owner, "GET", "/collections/t/exists") == {"exists": True}
    assert ok(owner, "GET", "/collections/missing/exists") == {"exists": False}


def test_with_vector_default_and_alias(owner):
    rec = ok(owner, "POST", "/collections/t/points", {"ids": [4]})
    assert rec[0]["vector"] is None and rec[0]["payload"]["name"] == "gamma"
    rec = ok(owner, "POST", "/collections/t/points", {"ids": [4], "with_vectors": True})
    assert rec[0]["vector"] == pytest.approx([2 ** -0.5, 2 ** -0.5, 0, 0], abs=1e-6)


def test_wrong_dimension_upsert_is_400(owner):
    status, _ = api(owner, "PUT", "/collections/t/points", {"points": [pt(9, "x", [1.0, 2.0])]})
    assert status == 400
    assert ok(owner, "GET", "/collections/t")["points_count"] == 5


def test_scroll_paging_is_id_ordered_and_stable_across_a_write(owner_factory):
    o = owner_factory().wait_ready()
    seed(o, [pt(i, f"s{i:02d}", vec(1, i)) for i in range(0, 50, 2)])
    page1 = ok(o, "POST", "/collections/t/points/scroll", {"limit": 10, "with_payload": ["name"]})
    assert [p["id"] for p in page1["points"]] == list(range(0, 20, 2))
    assert page1["next_page_offset"] == 20
    ok(o, "PUT", "/collections/t/points?wait=true", {"points": [pt(21, "new", vec(1))]})
    page2 = ok(o, "POST", "/collections/t/points/scroll",
               {"limit": 10, "offset": page1["next_page_offset"]})
    assert [p["id"] for p in page2["points"]] == [20, 21] + list(range(22, 38, 2))
    seen, nxt = [], None
    while True:
        body = {"limit": 7} if nxt is None else {"limit": 7, "offset": nxt}
        page = ok(o, "POST", "/collections/t/points/scroll", body)
        seen += [p["id"] for p in page["points"]]
        nxt = page["next_page_offset"]
        if nxt is None:
            break
    assert seen == sorted(list(range(0, 50, 2)) + [21])


def test_read_your_write(owner):
    ok(owner, "PUT", "/collections/t/points?wait=true", {"points": [pt(42, "omega", vec(0, 0, 1))]})
    assert groups(owner, vec(0, 0, 1), limit=1) == [("omega", 1.0)]
    ok(owner, "POST", "/collections/t/points/delete?wait=true", {"points": [42]})
    assert "omega" not in [n for n, _ in groups(owner, vec(0, 0, 1))]
    ok(owner, "POST", "/collections/t/points/delete",
       {"filter": {"must": [{"key": "name", "match": {"value": "beta"}}]}})
    assert count(owner, None) == 4
    assert ok(owner, "DELETE", "/collections/t") is True
    assert api(owner, "GET", "/collections/t")[0] == 404


def test_writes_rebuild_the_search_matrix_once_at_the_next_read(tmp_path, monkeypatch):
    # a full reindex is hundreds of writes; one fresh full-size matrix per write churned
    # tens of GB through the allocator and peaked at several GB resident
    from skill_search import index_owner as io_
    built = []
    real = io_.Snapshot
    monkeypatch.setattr(io_, "Snapshot", lambda *a: built.append(1) or real(*a))
    st = io_.Store(tmp_path / "t.sqlite")
    st.create("c", {"vectors": {"size": 3, "distance": "Cosine"}})
    for i in range(20):
        st.upsert("c", {"points": [{"id": i, "vector": [1.0, float(i), 0.5], "payload": {"name": f"n{i}"}}]})
    st.delete_points("c", {"points": [0]})
    before_read = len(built)
    assert st.count("c", {}) == {"count": 19}
    assert st.retrieve("c", {"ids": [19]})[0]["payload"] == {"name": "n19"}
    assert (before_read, len(built)) == (1, 2)       # the empty collection's, then one rebuild
    st.close()


def test_acknowledged_writes_survive_a_restart(owner_factory, tmp_path):
    db = tmp_path / "persist.sqlite"
    o = owner_factory(db).wait_ready()
    seed(o, [pt(1, "keep", vec(1)), pt(2, "gone", vec(0, 1))])
    ok(o, "POST", "/collections/t/points/delete", {"points": [2]})
    o.stop()
    o2 = owner_factory(db).wait_ready()
    assert [n for n, _ in groups(o2, vec(1, 1))] == ["keep"]


# -- guards ---------------------------------------------------------------------------

def test_host_guard_rejects_foreign_host(owner):
    assert api(owner, "GET", "/collections/t", host="evil.example")[0] == 403
    assert api(owner, "GET", "/collections/t", host=f"evil.example:{owner.qport}")[0] == 403
    assert api(owner, "GET", "/collections/t", host=f"localhost:{owner.qport}")[0] == 200


def test_write_without_json_content_type_is_415(owner):
    status, _ = api(owner, "POST", "/collections/t/points/count", {"exact": True},
                    headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert status == 415
    status, _ = api(owner, "DELETE", "/collections/t", headers={"Content-Type": "text/plain"})
    assert status == 415
    assert ok(owner, "GET", "/collections/t")["points_count"] == 5


def test_embed_port_serves_health_without_a_model(owner):
    conn = http.client.HTTPConnection("127.0.0.1", owner.eport, timeout=5)
    conn.request("GET", "/health", headers={"Host": f"127.0.0.1:{owner.eport}"})
    r = conn.getresponse()
    assert r.status == 200 and json.loads(r.read())["model"] is None
    conn.close()


# -- concurrency and lifecycle --------------------------------------------------------

def test_concurrent_readers_during_writes_never_error(owner_factory):
    o = owner_factory().wait_ready()
    seed(o, [pt(i, f"s{i % 40}", vec(1, i % 7, i % 3)) for i in range(400)])
    errors, stop = [], threading.Event()

    def reader():
        while not stop.is_set():
            try:
                status, res = api(o, "POST", "/collections/t/points/query/groups",
                                  {"query": vec(1, 2, 3), "group_by": "name", "limit": 8,
                                   "filter": {"must_not": [{"key": "tier", "match": {"value": "x"}}]}})
            except OSError as e:
                errors.append(repr(e))
                continue
            if status != 200 or len(res["result"]["groups"]) != 8:
                errors.append((status, res))
    threads = [threading.Thread(target=reader) for _ in range(6)]
    for t in threads:
        t.start()
    for b in range(30):
        ok(o, "PUT", "/collections/t/points",
           {"points": [pt(1000 + b * 10 + j, f"w{b}", vec(j, 1, b)) for j in range(10)]})
    stop.set()
    for t in threads:
        t.join()
    assert not errors, errors[:3]
    assert ok(o, "GET", "/collections/t")["points_count"] == 700


def test_duplicate_start_exits_before_model_load(owner_factory):
    first = owner_factory().wait_ready()
    t0 = time.monotonic()
    dup = owner_factory(first.db, qport=first.qport, eport=first.eport,
                        env={"SKILL_OWNER_NO_MODEL": "0"})
    assert dup.proc.wait(10) == 0
    assert time.monotonic() - t0 < 1.5
    assert "duplicate start" in first.read_log()
    assert api(first, "GET", "/collections/missing")[0] == 404   # first keeps serving


def test_port_held_by_a_non_owner_is_a_logged_conflict(owner_factory, tmp_path):
    class Other(BaseHTTPRequestHandler):
        def do_GET(self):
            body = b'{"title":"qdrant - vector search engine"}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_a):
            pass
    srv = HTTPServer(("127.0.0.1", 0), Other)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        o = owner_factory(tmp_path / "c.sqlite", qport=srv.server_address[1])
        assert o.proc.wait(10) == 1
        assert "PORT CONFLICT" in o.read_log()
    finally:
        srv.shutdown()
        srv.server_close()


def test_stamp_rewrite_triggers_exit_and_downgrade_does_not(owner_factory, tmp_path):
    db = tmp_path / "stamp.sqlite"
    Path(f"{db}.stamp").write_text("0.49.0")
    o = owner_factory(db, env={"SKILL_OWNER_STAMP_INTERVAL": "0.1"}).wait_ready()
    seed(o, [pt(1, "keep", vec(1))])
    o.stamp.write_text("0.47.1")                  # an old harness copy downgraded the venv
    time.sleep(0.6)
    assert o.proc.poll() is None and "downgraded" in o.read_log()
    o.stamp.write_text("0.49.0")                  # a resync reinstalled the code
    assert o.proc.wait(10) == 0
    assert "exiting for the new code" in o.read_log()
    # the lock was released: the next owner starts on the same file with the data intact
    o2 = owner_factory(db).wait_ready()
    assert [n for n, _ in groups(o2, vec(1))] == ["keep"]


# -- track B review fixes --------------------------------------------------------------

def test_health_reports_routes_for_setup_sh_parity(owner):
    """M3: an old harness copy's setup.sh greps /health for '"jev"' to decide whether the
    Docker embed shim is still needed. The owner must keep answering that probe."""
    conn = http.client.HTTPConnection("127.0.0.1", owner.eport, timeout=5)
    conn.request("GET", "/health", headers={"Host": f"127.0.0.1:{owner.eport}"})
    r = conn.getresponse()
    body = json.loads(r.read())
    conn.close()
    assert r.status == 200
    assert body["routes"] == ["embed", "jev"]


def test_health_reports_routes_while_loading():
    """N5 regression: an old harness copy's setup.sh greps '/health' for '"jev"' to decide
    whether the Docker embed shim is still needed. The 503 body served WHILE the owner is
    still loading must carry the same routes key as the 200 body, or that grep sees an
    incomplete answer during every model load (D3: this fix previously shipped with no
    test — exercised at the handler level, not over a real load-timing race)."""
    from skill_search import index_owner as io_

    class _FakeOwner:
        ready = False
        code_version = "0.54.0"

        def check_stamp(self):
            pass

    sent = {}

    class _FakeHandler:
        def _send(self, code, obj, ctype="application/json"):
            sent["code"], sent["obj"] = code, obj

    io_.Handler._embed_route(_FakeHandler(), _FakeOwner(), "GET", "/health", 0.0)
    assert sent["code"] == 503
    assert sent["obj"]["routes"] == ["embed", "jev"]


def test_code_version_survives_a_stamp_downgrade(owner_factory, tmp_path):
    """L1: /health's code_version must report the RUNNING code even after an older
    harness copy downgrades the venv stamp on disk — only stamp_version should move."""
    db = tmp_path / "downgrade.sqlite"
    Path(f"{db}.stamp").write_text("0.54.0")
    o = owner_factory(db, env={"SKILL_OWNER_STAMP_INTERVAL": "0.1"}).wait_ready()

    def health():
        conn = http.client.HTTPConnection("127.0.0.1", o.eport, timeout=5)
        conn.request("GET", "/health", headers={"Host": f"127.0.0.1:{o.eport}"})
        body = json.loads(conn.getresponse().read())
        conn.close()
        return body

    before = health()
    assert before["code_version"] == "0.54.0"
    assert before["stamp_version"] == "0.54.0"

    o.stamp.write_text("0.52.9")               # an older harness copy downgraded the venv
    time.sleep(0.6)

    after = health()
    assert after["code_version"] == "0.54.0"    # still the code that is actually running
    assert after["stamp_version"] == "0.52.9"    # the on-disk value the owner last observed
    assert "downgraded" in o.read_log()


def test_probe_treats_accept_then_reset_as_other(tmp_path):
    """L2: a foreign listener that ACCEPTS a connection and then resets it (a wildcard
    port proxy still warming up) must be reported as 'other', never as 'nobody' —
    otherwise the owner's startup probe binds right over it (bindtest.py)."""
    from skill_search import index_owner as io_

    port = _free_port()
    f = socket.socket()
    f.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    f.bind(("127.0.0.1", port))
    f.listen(16)
    stop = threading.Event()

    def rst():
        f.settimeout(0.2)
        while not stop.is_set():
            try:
                c, _addr = f.accept()
                c.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, b"\x01\x00\x00\x00\x00\x00\x00\x00")
                c.close()
            except OSError:
                pass

    t = threading.Thread(target=rst, daemon=True)
    t.start()
    try:
        assert io_._probe(port) == "other"
    finally:
        stop.set()
        t.join(2)
        f.close()


def test_probe_treats_a_refused_port_as_nobody(tmp_path):
    """Control for L2: an actually-free port (nothing accepted the connection) must
    still report None, so the fix does not turn every free port into 'other'."""
    from skill_search import index_owner as io_
    port = _free_port()
    assert io_._probe(port) is None


@pytest.mark.parametrize("err", ["EADDRNOTAVAIL", "EAFNOSUPPORT", "ENETUNREACH", "EHOSTUNREACH"])
def test_probe_treats_a_missing_ipv6_loopback_as_nobody(monkeypatch, err):
    """A host without ::1 fails the connect with an address error, not a refusal. That
    must read as 'nobody there' (as _bind assumes), or every start ends in PORT CONFLICT."""
    import errno
    import http.client
    from skill_search import index_owner as io_
    real_connect = http.client.HTTPConnection.connect

    def connect(self):
        if self.host == "::1":
            raise OSError(getattr(errno, err), err)
        return real_connect(self)

    monkeypatch.setattr(http.client.HTTPConnection, "connect", connect)
    assert io_._probe(_free_port()) is None


@pytest.mark.parametrize("err", ["EADDRNOTAVAIL", "EAFNOSUPPORT", "ENETUNREACH", "EHOSTUNREACH"])
def test_probe_does_not_carve_out_the_same_errno_on_127_0_0_1(monkeypatch, err):
    """The ::1 carve-out (missing IPv6 loopback) must not extend to 127.0.0.1: a real
    IPv4 loopback failing with the same errno (e.g. ephemeral-port exhaustion racing a
    foreign wildcard listener) has to stay 'other', never read as nobody there."""
    import errno
    import http.client
    from skill_search import index_owner as io_
    real_connect = http.client.HTTPConnection.connect

    def connect(self):
        if self.host == "127.0.0.1":
            raise OSError(getattr(errno, err), err)
        return real_connect(self)

    monkeypatch.setattr(http.client.HTTPConnection, "connect", connect)
    assert io_._probe(_free_port()) == "other"


class _FlakyDB:
    """Proxies a real sqlite3.Connection but fails partway through the FIRST
    executemany() called on it, after really applying its first row/param-set —
    simulating a genuinely partial batch, uncommitted. `with self.db:` (the context
    manager protocol) still forwards to the real connection, so its commit/rollback
    on __exit__ is the real thing under test."""

    def __init__(self, real):
        self._real = real
        self._armed = True

    def executemany(self, sql, seq):
        if not self._armed:
            return self._real.executemany(sql, seq)
        self._armed = False
        seq = list(seq)
        self._real.executemany(sql, seq[:1])   # really applied, still uncommitted
        raise sqlite3.OperationalError("simulated mid-batch failure")

    def __enter__(self):
        return self._real.__enter__()

    def __exit__(self, *exc):
        return self._real.__exit__(*exc)

    def __getattr__(self, name):
        return getattr(self._real, name)


def test_failed_upsert_batch_rolls_back_and_leaves_no_partial_rows(tmp_path):
    """L3: Store.upsert's executemany must be atomic. Without `with self.db:`, a row
    genuinely applied before a mid-batch failure stays uncommitted-but-present in the
    connection's implicit transaction, and a LATER unrelated successful write's commit()
    would persist it."""
    from skill_search import index_owner as io_
    st = io_.Store(tmp_path / "t.sqlite")
    st.create("c", {"vectors": {"size": 2, "distance": "Cosine"}})

    real_db = st.db
    st.db = _FlakyDB(real_db)
    with pytest.raises(sqlite3.OperationalError):
        st.upsert("c", {"points": [
            {"id": 1, "vector": [1.0, 0.0], "payload": {}},
            {"id": 2, "vector": [0.0, 1.0], "payload": {}},
        ]})
    st.db = real_db

    st.upsert("c", {"points": [{"id": 99, "vector": [1.0, 1.0], "payload": {}}]})
    st.close()

    st2 = io_.Store(tmp_path / "t.sqlite")
    ids = sorted(r[0] for r in st2.colls["c"].rows.values())
    assert ids == [99]      # row 1's partial insert never survived to the later commit
    st2.close()


def test_failed_delete_batch_rolls_back_and_leaves_no_partial_state(tmp_path):
    """L3, delete_points side: same atomicity requirement for the DELETE executemany."""
    from skill_search import index_owner as io_
    st = io_.Store(tmp_path / "t.sqlite")
    st.create("c", {"vectors": {"size": 2, "distance": "Cosine"}})
    st.upsert("c", {"points": [
        {"id": 1, "vector": [1.0, 0.0], "payload": {}},
        {"id": 2, "vector": [0.0, 1.0], "payload": {}},
    ]})

    real_db = st.db
    st.db = _FlakyDB(real_db)
    with pytest.raises(sqlite3.OperationalError):
        st.delete_points("c", {"points": [1, 2]})
    st.db = real_db

    st.upsert("c", {"points": [{"id": 99, "vector": [1.0, 1.0], "payload": {}}]})
    st.close()

    st2 = io_.Store(tmp_path / "t.sqlite")
    ids = sorted(r[0] for r in st2.colls["c"].rows.values())
    assert ids == [1, 2, 99]      # id 1's partial delete never survived to the later commit
    st2.close()


def _spawn_owner(env_overrides, extra_env_pop=()):
    env = dict(os.environ, PYTHONPATH=str(SRC))
    for k in extra_env_pop:
        env.pop(k, None)
    env.update(env_overrides)
    return subprocess.Popen([sys.executable, "-m", "skill_search.index_owner"],
                            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _stop(proc):
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def test_ports_derive_from_qdrant_url_and_embed_shim_port_when_unset(tmp_path):
    """L4: with SKILL_OWNER_QUERY_PORT/SKILL_OWNER_EMBED_PORT unset, the owner must land
    on the ports every caller (doctor.py, the launcher, the enforcer) already derives
    from SKILL_QDRANT_URL / EMBED_SHIM_PORT, not the hardcoded 6333/6363."""
    qport, eport = _free_port(), _free_port()
    db = tmp_path / "portderive.sqlite"
    proc = _spawn_owner(
        {"SKILL_INDEX_DB": str(db), "SKILL_OWNER_NO_MODEL": "1",
         "SKILL_OWNER_LOG": f"{db}.log", "SKILL_OWNER_STAMP": f"{db}.stamp",
         "SKILL_QDRANT_URL": f"http://127.0.0.1:{qport}", "EMBED_SHIM_PORT": str(eport)},
        extra_env_pop=("SKILL_OWNER_QUERY_PORT", "SKILL_OWNER_EMBED_PORT"))
    try:
        end = time.monotonic() + 20
        ready = False
        while time.monotonic() < end:
            if proc.poll() is not None:
                raise RuntimeError(f"owner exited {proc.returncode}")
            try:
                conn = http.client.HTTPConnection("127.0.0.1", qport, timeout=0.5)
                try:
                    conn.request("GET", "/", headers={"Host": f"127.0.0.1:{qport}"})
                    ready = conn.getresponse().status == 200
                finally:
                    conn.close()
                if ready:
                    break
            except OSError:
                pass
            time.sleep(0.05)
        assert ready, "owner never bound the SKILL_QDRANT_URL-derived query port"

        conn = http.client.HTTPConnection("127.0.0.1", eport, timeout=5)
        conn.request("GET", "/health", headers={"Host": f"127.0.0.1:{eport}"})
        assert conn.getresponse().status == 200   # EMBED_SHIM_PORT-derived embed port
        conn.close()
    finally:
        _stop(proc)


def test_default_ports_fall_back_to_6333_6363_with_nothing_configured(tmp_path):
    """L4 control: with every port env var unset, 6333/6363 remain the final fallback."""
    env = dict(os.environ)
    for k in ("SKILL_OWNER_QUERY_PORT", "SKILL_OWNER_EMBED_PORT", "SKILL_QDRANT_URL", "EMBED_SHIM_PORT"):
        env.pop(k, None)
    script = (
        "import os, json, sys\n"
        "from skill_search import index_owner as io_\n"
        "print(json.dumps([io_.QUERY_PORT, io_.EMBED_PORT]))\n")
    script_path = tmp_path / "port_defaults_probe.py"
    script_path.write_text(script, encoding="utf-8")
    env["PYTHONPATH"] = str(SRC)
    r = subprocess.run([sys.executable, str(script_path)], env=env,
                       capture_output=True, text=True, timeout=20)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == [6333, 6363]


@pytest.mark.parametrize("bad_env", [
    {"SKILL_QDRANT_URL": "http://127.0.0.1:notaport"},
    {"SKILL_OWNER_QUERY_PORT": "notaport"},
    {"EMBED_SHIM_PORT": "notaport"},
    {"SKILL_OWNER_EMBED_PORT": "notaport"},
])
def test_malformed_port_env_falls_back_instead_of_crashing_at_import(tmp_path, bad_env):
    """A malformed port in any of the four port-shaping env vars must not raise at
    import — importing the module is the owner's whole startup path, so a raise there
    crashes the owner before it can even log anything useful."""
    env = dict(os.environ)
    for k in ("SKILL_OWNER_QUERY_PORT", "SKILL_OWNER_EMBED_PORT", "SKILL_QDRANT_URL", "EMBED_SHIM_PORT"):
        env.pop(k, None)
    env.update(bad_env)
    script = (
        "import json\n"
        "from skill_search import index_owner as io_\n"
        "print(json.dumps([io_.QUERY_PORT, io_.EMBED_PORT]))\n")
    script_path = tmp_path / "port_malformed_probe.py"
    script_path.write_text(script, encoding="utf-8")
    env["PYTHONPATH"] = str(SRC)
    r = subprocess.run([sys.executable, str(script_path)], env=env,
                       capture_output=True, text=True, timeout=20)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == [6333, 6363]
    assert "notaport" in r.stderr


@pytest.mark.parametrize("bad_value", [" 7363", "7363 ", "+7363", "7_363", "７３６３"])
def test_strict_grammar_rejects_whitespace_sign_underscore_and_full_width_digits(tmp_path, bad_value):
    """Plain int() silently accepts all five of these — stripping whitespace, accepting a
    leading sign, and normalizing an underscore digit-group separator or a full-width
    digit — so a caller using bare int() would derive 7363 from every one of them while
    bash's `_safe_port` (ASCII `[0-9]+` only) and `urlsplit().port` both reject them. The
    strict grammar must reject them too, on both port-shaping override env vars."""
    env = dict(os.environ)
    for k in ("SKILL_OWNER_QUERY_PORT", "SKILL_OWNER_EMBED_PORT", "SKILL_QDRANT_URL", "EMBED_SHIM_PORT"):
        env.pop(k, None)
    env["SKILL_OWNER_QUERY_PORT"] = bad_value
    env["EMBED_SHIM_PORT"] = bad_value
    script = (
        "import json\n"
        "from skill_search import index_owner as io_\n"
        "print(json.dumps([io_.QUERY_PORT, io_.EMBED_PORT]))\n")
    script_path = tmp_path / "port_strict_grammar_probe.py"
    script_path.write_text(script, encoding="utf-8")
    env["PYTHONPATH"] = str(SRC)
    r = subprocess.run([sys.executable, str(script_path)], env=env,
                       capture_output=True, text=True, timeout=20)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == [6333, 6363], \
        f"{bad_value!r} must fall back to the defaults, not be silently accepted as 7363"


@pytest.mark.parametrize("bad_env,bad_value", [
    ({"SKILL_OWNER_QUERY_PORT": "70000"}, "70000"),
    ({"SKILL_OWNER_QUERY_PORT": "-5"}, "-5"),
    ({"EMBED_SHIM_PORT": "70000"}, "70000"),
    ({"SKILL_OWNER_EMBED_PORT": "-5"}, "-5"),
])
def test_out_of_range_port_env_falls_back_instead_of_crashing_at_bind(tmp_path, bad_env, bad_value):
    """int() alone accepts "70000" or "-5" with no error — the crash used to happen much
    later, inside socket.bind(), with no useful message. "70000" is caught by the explicit
    1-65535 range check; "-5" is caught earlier, by the strict ASCII-digit-only grammar
    (a '-' sign is not a digit) — both land on the same default, with the bad value named
    in one stderr line either way."""
    env = dict(os.environ)
    for k in ("SKILL_OWNER_QUERY_PORT", "SKILL_OWNER_EMBED_PORT", "SKILL_QDRANT_URL", "EMBED_SHIM_PORT"):
        env.pop(k, None)
    env.update(bad_env)
    script = (
        "import json\n"
        "from skill_search import index_owner as io_\n"
        "print(json.dumps([io_.QUERY_PORT, io_.EMBED_PORT]))\n")
    script_path = tmp_path / "port_out_of_range_probe.py"
    script_path.write_text(script, encoding="utf-8")
    env["PYTHONPATH"] = str(SRC)
    r = subprocess.run([sys.executable, str(script_path)], env=env,
                       capture_output=True, text=True, timeout=20)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == [6333, 6363]
    assert bad_value in r.stderr
    assert "out of range" in r.stderr or "not a strictly ASCII-digit port" in r.stderr


def test_log_lines_are_not_duplicated_when_stderr_shares_the_log_file(tmp_path):
    """L9: a launcher (doctor.start_owner, the enforcer, setup.sh) that redirects the
    owner's stderr into the SAME file as SKILL_OWNER_LOG must not see every line twice."""
    db = tmp_path / "dup.sqlite"
    log_path = tmp_path / "dup.log"
    env = dict(os.environ, PYTHONPATH=str(SRC), SKILL_INDEX_DB=str(db),
               SKILL_OWNER_QUERY_PORT=str(_free_port()), SKILL_OWNER_EMBED_PORT=str(_free_port()),
               SKILL_OWNER_NO_MODEL="1", SKILL_OWNER_LOG=str(log_path),
               SKILL_OWNER_STAMP=f"{db}.stamp")
    with open(log_path, "ab") as f:
        proc = subprocess.Popen([sys.executable, "-m", "skill_search.index_owner"],
                                env=env, stdin=subprocess.DEVNULL, stdout=f, stderr=f)
    try:
        end = time.monotonic() + 20
        text = ""
        while time.monotonic() < end:
            text = log_path.read_text(encoding="utf-8", errors="replace")
            if "ready:" in text or proc.poll() is not None:
                break
            time.sleep(0.05)
        assert "ready:" in text, text
        ready_lines = [ln for ln in text.splitlines() if "ready:" in ln]
        listening_lines = [ln for ln in text.splitlines() if "listening query=" in ln]
        assert len(ready_lines) == 1, ready_lines            # not doubled by the shared redirect
        assert len(listening_lines) == 1, listening_lines
    finally:
        _stop(proc)


def test_log_still_reaches_stderr_when_it_is_not_the_log_file(tmp_path):
    """L9 control: stderr must keep receiving log lines when it is NOT redirected into
    LOG_PATH (e.g. an interactive run) — the fix must only suppress the true duplicate."""
    db = tmp_path / "nodup.sqlite"
    log_path = tmp_path / "nodup.log"
    env = dict(os.environ, PYTHONPATH=str(SRC), SKILL_INDEX_DB=str(db),
               SKILL_OWNER_QUERY_PORT=str(_free_port()), SKILL_OWNER_EMBED_PORT=str(_free_port()),
               SKILL_OWNER_NO_MODEL="1", SKILL_OWNER_LOG=str(log_path),
               SKILL_OWNER_STAMP=f"{db}.stamp")
    proc = subprocess.Popen([sys.executable, "-m", "skill_search.index_owner"],
                            env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    try:
        end = time.monotonic() + 20
        err = ""
        while time.monotonic() < end:
            if proc.poll() is not None:
                break
            try:
                err = log_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                err = ""
            if "ready:" in err:
                break
            time.sleep(0.05)
        assert "ready:" in err, err
    finally:
        _stop(proc)
        stderr_out = proc.stderr.read() if proc.stderr else ""
        assert "ready:" in stderr_out, stderr_out   # still echoed — stderr is not the log file
