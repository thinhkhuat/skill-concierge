"""Unit tests for search_skills query fanout / max-pool fusion (_fuse_ranked).

Pure logic — no Qdrant or embedder needed. Runs under pytest OR standalone:
    python tests/test_fusion.py
"""
from types import SimpleNamespace

from skill_search.server import _fuse_ranked


def _grp(name, score, desc="d"):
    """Fake a Qdrant group: one best hit carrying name/description/score."""
    hit = SimpleNamespace(score=score, payload={"name": name, "description": desc}, id=name)
    return SimpleNamespace(hits=[hit], id=name)


def test_single_query_ranks_by_score():
    # Backward-compat: one query behaves like the old top-k path.
    groups = [_grp("a", 0.9), _grp("b", 0.7)]
    out = _fuse_ranked([groups], top_k=5)
    assert [r["name"] for r in out] == ["a", "b"]
    assert out[0]["command"] == "/a"
    assert out[0]["score"] == 0.9


def test_maxpool_surfaces_buried_skill():
    # 'onboard' is buried under 'generic' in q1 (0.62 < 0.70) but wins in q2 (0.81).
    # Fusion must lift it to #1 by its BEST score across both queries.
    q1 = [_grp("generic", 0.70), _grp("onboard", 0.62)]
    q2 = [_grp("onboard", 0.81), _grp("generic", 0.68)]
    out = _fuse_ranked([q1, q2], top_k=2)
    assert [r["name"] for r in out] == ["onboard", "generic"]
    assert out[0]["score"] == 0.81   # MAX across queries, not last-seen (0.62)


def test_empty_hits_skipped():
    empty = SimpleNamespace(hits=[], id="x")
    out = _fuse_ranked([[empty, _grp("a", 0.5)]], top_k=5)
    assert [r["name"] for r in out] == ["a"]


def test_top_k_truncates_after_fusion():
    q1 = [_grp("a", 0.9), _grp("b", 0.5)]
    q2 = [_grp("c", 0.8), _grp("b", 0.85)]  # b lifted to 0.85 by q2
    out = _fuse_ranked([q1, q2], top_k=2)
    assert [r["name"] for r in out] == ["a", "b"]  # c (0.8) dropped below the cut


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print(f"ok  {_name}")
    print("all fusion tests passed")
