"""ADR-0075: search_skills applies the ADR-0048 complement rule between installed
and external-catalog rows — installed rows come first; an external row ranks above the
installed top only if it beats that row's score by ENFORCER_ANNEX_BEAT. Pure-logic tests
run offline: query_groups is faked to return different rows for the installed-only vs
external-only filter, exactly as the two separate queries in search_skills would see.
"""
import json

from skill_search import server as _server


def _grp(name, score, scope=None):
    """Fake a query/groups group (wire JSON): one best hit carrying name/description/score."""
    payload = {"name": name, "description": "d"}
    if scope is not None:
        payload["scope"] = scope
    return {"id": name, "hits": [{"id": name, "score": score, "payload": payload}]}


def _rig(monkeypatch, installed_groups, external_groups):
    """Route the installed-only query (must_not tier=external) to `installed_groups` and
    the external-only query (must tier=external) to `external_groups` — mirroring the
    two separate calls search_skills issues under the complement rule."""
    monkeypatch.setattr(_server, "embed_batch", lambda qs: [[0.0] for _ in qs])
    monkeypatch.setattr(_server, "_staleness_warning", lambda: None)

    def fake_query_groups(collection, vector, group_by, limit, group_size=1, filter=None):
        f = filter or {}
        if any(c.get("key") == "tier" for c in f.get("must", [])):
            return external_groups
        return installed_groups

    monkeypatch.setattr(_server._qdrant, "query_groups", fake_query_groups)


def test_installed_row_comes_first_over_six_strong_externals(monkeypatch):
    """6 strong externals + 1 weaker installed: none of the externals clears the
    installed top by the ANNEX_BEAT margin, so the installed row still comes first.
    A single mixed top-6 query could otherwise drop it entirely; the separate
    installed-only query fixes that."""
    installed = [_grp("home-skill", 0.50, scope="personal")]
    external = [_grp(f"ext{i}", 0.50 + 0.005 * i, scope="catalog:x") for i in range(1, 7)]
    _rig(monkeypatch, installed, external)
    out = json.loads(_server.search_skills("q"))
    names = [r["name"] for r in out["results"]]
    assert names[0] == "home-skill"
    assert any(r.get("external") for r in out["results"])


def test_external_beating_by_more_than_beat_stays_above(monkeypatch):
    installed = [_grp("home-skill", 0.50, scope="personal")]
    external = [_grp("dominant-ext", 0.60, scope="catalog:x")]   # beats by 0.10 > 0.04
    _rig(monkeypatch, installed, external)
    out = json.loads(_server.search_skills("q"))
    names = [r["name"] for r in out["results"]]
    assert names == ["dominant-ext", "home-skill"]


def test_external_just_under_beat_margin_stays_below(monkeypatch):
    installed = [_grp("home-skill", 0.50, scope="personal")]
    external = [_grp("near-ext", 0.539, scope="catalog:x")]   # 0.039 < 0.04 beat margin
    _rig(monkeypatch, installed, external)
    out = json.loads(_server.search_skills("q"))
    names = [r["name"] for r in out["results"]]
    assert names == ["home-skill", "near-ext"]


def test_arrange_tiers_with_no_installed_rows_falls_back_to_external_order():
    rows = _server._arrange_tiers([], [
        {"name": "b", "score": 0.5}, {"name": "a", "score": 0.9}], top_k=5)
    assert [r["name"] for r in rows] == ["b", "a"]   # order as given (already fused/sorted)


def test_flag_off_restores_todays_single_query_order(monkeypatch):
    monkeypatch.setattr(_server, "embed_batch", lambda qs: [[0.0] for _ in qs])
    monkeypatch.setattr(_server, "_staleness_warning", lambda: None)
    mixed = [_grp("ext-a", 0.9, scope="catalog:x"), _grp("home-skill", 0.5, scope="personal")]
    monkeypatch.setattr(_server._qdrant, "query_groups", lambda *a, **kw: mixed)
    monkeypatch.setenv("SKILL_SEARCH_COMPLEMENT", "0")
    out = json.loads(_server.search_skills("q"))
    names = [r["name"] for r in out["results"]]
    assert names == ["ext-a", "home-skill"]     # pure score order, no tier arrangement
