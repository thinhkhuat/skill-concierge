"""SKILL_CONSULT_RRF (default OFF, read per call): consult_candidates orders the sieve by
reciprocal-rank fusion (k = 60) instead of each skill's best raw score. `score` stays the
best raw score; `_fuse_ranked` and search_skills are untouched.
"""
import json

from skill_search import server as _server


def _grp(name, score, scope="personal"):
    return {"id": name, "hits": [{"id": name, "score": score,
            "payload": {"name": name, "description": "d", "path": f"/p/{name}", "scope": scope}}]}


def _rig(monkeypatch, per_query, slots_tiers=None):
    """per_query: list (one per query) of group lists. Routes the i-th mixed call to it.
    slots_tiers: {"installed": [...per query], "external": [...per query]} for the slot path."""
    monkeypatch.setattr(_server, "embed_queries", lambda qs: [[float(i)] for i, _ in enumerate(qs)])
    monkeypatch.setattr(_server, "_staleness_warning", lambda: None)
    monkeypatch.setattr(_server, "_capsules", lambda: {})
    monkeypatch.setattr(_server, "_blocked", lambda n: False)

    def fake(collection, vector, group_by, limit, group_size=1, filter=None):
        f = filter or {}
        i = int(vector[0])
        if slots_tiers and any(c.get("key") == "tier" for c in f.get("must", [])):
            return slots_tiers["external"][i][:limit]
        if slots_tiers and any(c.get("key") == "tier" for c in f.get("must_not", [])):
            return slots_tiers["installed"][i][:limit]
        return per_query[i][:limit]

    monkeypatch.setattr(_server._qdrant, "query_groups", fake)


def _names(top_n=5, queries=("a", "b")):
    out = json.loads(_server.consult_candidates(list(queries), top_n=top_n))
    return [r["name"] for r in out["results"]], out


def _flooding():
    a = [_grp(f"generic{i}", 0.80 - 0.01 * i) for i in range(6)]
    b = [_grp("niche", 0.55)]
    return [a, b]


def test_rrf_lets_a_niche_first_place_beat_a_flooding_query(monkeypatch):
    _rig(monkeypatch, _flooding())
    monkeypatch.setenv("SKILL_CONSULT_RRF", "0")
    max_names, _ = _names(top_n=5)
    monkeypatch.setenv("SKILL_CONSULT_RRF", "1")
    rrf_names, _ = _names(top_n=5)
    assert "niche" not in max_names
    assert "niche" in rrf_names


def test_rrf_rows_keep_the_best_raw_score(monkeypatch):
    _rig(monkeypatch, _flooding())
    monkeypatch.setenv("SKILL_CONSULT_RRF", "1")
    _, out = _names(top_n=5)
    by = {r["name"]: r["score"] for r in out["results"]}
    assert by["niche"] == 0.55
    assert by["generic0"] == 0.8


def test_rrf_ties_break_by_best_score_then_name(monkeypatch):
    # Each query's rank-1 skill gets the same fused value; best raw score decides first,
    # then the name when scores also tie.
    lists = [[_grp("zeta", 0.60)], [_grp("alpha", 0.70)], [_grp("beta", 0.60)]]
    _rig(monkeypatch, lists)
    monkeypatch.setenv("SKILL_CONSULT_RRF", "1")
    names, _ = _names(top_n=5, queries=("a", "b", "c"))
    assert names == ["alpha", "beta", "zeta"]


def test_rrf_order_uses_the_documented_formula():
    lists = [[_grp("x", 0.9), _grp("y", 0.8)], [_grp("y", 0.7)]]
    assert _server._rrf_order(lists, 60) == ["y", "x"]   # y: 1/62 + 1/61 > x: 1/61


def test_rrf_orders_each_tier_when_slots_are_on(monkeypatch):
    inst = [[_grp(f"gi{i}", 0.60 - 0.01 * i) for i in range(6)], [_grp("ni", 0.30)]]
    ext = [[_grp(f"ge{i}", 0.90 - 0.01 * i, "catalog:x") for i in range(6)],
           [_grp("ne", 0.40, "catalog:x")]]
    _rig(monkeypatch, None, {"installed": inst, "external": ext})
    monkeypatch.setenv("SKILL_CONSULT_SLOTS", "1")
    monkeypatch.setenv("SKILL_CONSULT_RRF", "0")
    out = json.loads(_server.consult_candidates(["a", "b"], top_n=10))
    max_inst = [r["name"] for r in out["results"]][:7]
    monkeypatch.setenv("SKILL_CONSULT_RRF", "1")
    out = json.loads(_server.consult_candidates(["a", "b"], top_n=10))
    names = [r["name"] for r in out["results"]]
    assert out["blocks"] == {"installed": 7, "external": 3}
    # RRF-ordered installed block: gi0 and ni both rank 1 in a query, ni is second on best score
    assert names[:2] == ["gi0", "ni"]
    # external block likewise starts with the same RRF pattern
    assert names[7:9] == ["ge0", "ne"]
    assert max_inst[1] != "ni"


def test_rrf_flag_is_read_per_call(monkeypatch):
    _rig(monkeypatch, _flooding())
    monkeypatch.setenv("SKILL_CONSULT_RRF", "1")
    on, _ = _names(top_n=5)
    monkeypatch.delenv("SKILL_CONSULT_RRF")
    off, _ = _names(top_n=5)
    assert on != off
