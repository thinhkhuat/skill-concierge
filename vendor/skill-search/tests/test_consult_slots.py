"""SKILL_CONSULT_SLOTS (default OFF, read per call): consult_candidates gives installed
skills reserved slots and returns externals in their own block after them. Offline: the
embedder, staleness check, capsules and query_groups are faked; query_groups routes by the
tier filter exactly as the two separate queries would see.
"""
import json
from pathlib import Path

from skill_search import server as _server

_REPO_SERVER = Path(__file__).resolve().parents[1] / "skill_search" / "server.py"


def _grp(name, score, scope=None):
    payload = {"name": name, "description": "d", "path": f"/p/{name}"}
    if scope is not None:
        payload["scope"] = scope
    return {"id": name, "hits": [{"id": name, "score": score, "payload": payload}]}


def _inst(n, score=0.5, prefix="home"):
    return [_grp(f"{prefix}{i}", score - 0.001 * i, scope="personal") for i in range(n)]


def _ext(n, score=0.9, prefix="ext"):
    return [_grp(f"{prefix}{i}", score - 0.001 * i, scope="catalog:x") for i in range(n)]


class Rig:
    def __init__(self, monkeypatch, installed, external, mixed=None):
        self.calls = []          # (kind, filter) per query_groups call
        self.embed_calls = []
        monkeypatch.setattr(_server, "embed_queries",
                            lambda qs: self.embed_calls.append(list(qs)) or [[0.0] for _ in qs])
        monkeypatch.setattr(_server, "_staleness_warning", lambda: None)
        monkeypatch.setattr(_server, "_capsules", lambda: {})
        monkeypatch.setattr(_server, "_blocked", lambda n: False)

        def fake(collection, vector, group_by, limit, group_size=1, filter=None):
            f = filter or {}
            if any(c.get("key") == "tier" for c in f.get("must", [])):
                kind = "external"
                out = external
            elif any(c.get("key") == "tier" for c in f.get("must_not", [])):
                kind = "installed"
                out = installed
            else:
                kind = "mixed"
                out = mixed if mixed is not None else sorted(
                    installed + external, key=lambda g: -g["hits"][0]["score"])
            self.calls.append((kind, f))
            return out[:limit]

        monkeypatch.setattr(_server._qdrant, "query_groups", fake)


def _run(top_n=20, queries=("a",)):
    return json.loads(_server.consult_candidates(list(queries), top_n=top_n))


def test_engine_under_test_is_the_repo_source():
    assert Path(_server.__file__).resolve() == _REPO_SERVER


def test_installed_rows_keep_their_slots_against_stronger_externals(monkeypatch):
    # 30 externals at ~0.90 and 20 installed at ~0.50: a raw-score sieve would be all external.
    Rig(monkeypatch, _inst(20), _ext(30))
    monkeypatch.setenv("SKILL_CONSULT_SLOTS", "1")
    out = _run(top_n=20)
    names = [r["name"] for r in out["results"]]
    assert len(names) == 20
    assert names[:14] == [f"home{i}" for i in range(14)]
    assert all(n.startswith("ext") for n in names[14:])
    # flag off: the same data is all external (the problem being fixed)
    monkeypatch.setenv("SKILL_CONSULT_SLOTS", "0")
    assert all(r["name"].startswith("ext") for r in _run(top_n=20)["results"])


def test_slot_path_queries_each_tier_with_its_filter(monkeypatch):
    rig = Rig(monkeypatch, _inst(5), _ext(5))
    monkeypatch.setenv("SKILL_CONSULT_SLOTS", "1")
    _run(queries=("a", "b"))
    kinds = sorted(k for k, _ in rig.calls)
    assert kinds == ["external", "external", "installed", "installed"]
    for kind, f in rig.calls:
        if kind == "installed":
            assert f["must_not"] == [{"key": "tier", "match": {"value": "external"}}]
        else:
            assert f["must"] == [{"key": "tier", "match": {"value": "external"}}]


def test_a_short_tier_lends_its_unused_slots(monkeypatch):
    monkeypatch.setenv("SKILL_CONSULT_SLOTS", "1")
    Rig(monkeypatch, _inst(3), _ext(30))
    out = _run(top_n=20)
    assert out["blocks"] == {"installed": 3, "external": 17}
    Rig(monkeypatch, _inst(30), _ext(2))
    out = _run(top_n=20)
    assert out["blocks"] == {"installed": 18, "external": 2}
    assert len(out["results"]) == 20


def test_blocks_count_rows_after_the_blocklist(monkeypatch):
    rig = Rig(monkeypatch, _inst(20), _ext(30))
    monkeypatch.setattr(_server, "_blocked", lambda n: n == "home0")
    monkeypatch.setenv("SKILL_CONSULT_SLOTS", "1")
    out = _run(top_n=20)
    assert out["blocks"] == {"installed": 13, "external": 6}
    assert "home0" not in [r["name"] for r in out["results"]]
    assert rig  # rig kept alive


def test_vectors_are_embedded_once_on_the_slot_path(monkeypatch):
    rig = Rig(monkeypatch, _inst(5), _ext(5))
    monkeypatch.setenv("SKILL_CONSULT_SLOTS", "1")
    _run(queries=("a", "b", "c"))
    assert rig.embed_calls == [["a", "b", "c"]]


def test_slots_flag_is_read_per_call(monkeypatch):
    Rig(monkeypatch, _inst(20), _ext(30))
    monkeypatch.setenv("SKILL_CONSULT_SLOTS", "1")
    on = _run(top_n=20)
    monkeypatch.delenv("SKILL_CONSULT_SLOTS")
    off = _run(top_n=20)
    assert "blocks" in on and "blocks" not in off
    assert [r["name"] for r in on["results"]] != [r["name"] for r in off["results"]]


def test_flags_off_reproduce_todays_output_exactly(monkeypatch):
    mixed = _ext(12) + _inst(12)
    rig = Rig(monkeypatch, _inst(12), _ext(12), mixed=mixed)
    monkeypatch.delenv("SKILL_CONSULT_SLOTS", raising=False)
    monkeypatch.delenv("SKILL_CONSULT_RRF", raising=False)
    out = _run(top_n=15, queries=("a", "b"))
    expected = _server._fuse_ranked([mixed[:15], mixed[:15]], 15, with_paths=True)
    assert out["results"] == expected
    assert set(out) == {"queries", "results", "capsule_coverage", "note"}
    assert [k for k, _ in rig.calls] == ["mixed", "mixed"]
