"""Index owner: the Qdrant REST subset, search semantics, guards and lifecycle,
exercised over HTTP against owners started on free ports with temp SQLite files."""

import http.client
import json
import math
import random
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "qdrant_exact_groups.json"


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


# -- REST shape -----------------------------------------------------------------------

def test_collection_info_and_title(owner):
    info = ok(owner, "GET", "/collections/t")
    assert info["points_count"] == 5
    assert info["config"]["params"]["vectors"] == {"size": 4, "distance": "Cosine"}
    status, root = api(owner, "GET", "/")
    assert status == 200 and root["title"].startswith("skill-concierge index owner")
    assert api(owner, "GET", "/collections/missing")[0] == 404


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
