"""Findability sweep and ratchet (ADR-0074, design plans/260927-1450-findability-at-the-root).

Ratchet math, token/document-frequency selection, owner-URL derivation and lock/throttle are
pure or against a stub — no network. The leave-one-out exclusion and the name-word rank query
are proven against a REAL (ephemeral, model-less) index owner from `owner_factory`
(conftest.py) — never the live 6333/6363.
"""
import http.client
import json
import time

import pytest

from skill_search import findability as fnd


# ── owner helpers (mirrors test_index_owner.py's pattern) ──────────────────────────────────
def api(owner, method, path, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", owner.qport, timeout=10)
    headers = {"Content-Type": "application/json"} if method != "GET" else {}
    data = None if body is None else json.dumps(body).encode()
    try:
        conn.request(method, path, body=data, headers=headers)
        r = conn.getresponse()
        return r.status, json.loads(r.read())
    finally:
        conn.close()


def ok(owner, method, path, body=None):
    status, res = api(owner, method, path, body)
    assert status == 200, (status, res)
    return res["result"]


def vec(*xs, dim=4):
    return list(xs) + [0.0] * (dim - len(xs))


def pt(i, name, v, **payload):
    return {"id": i, "vector": v, "payload": {"name": name, **payload}}


def seed(owner, points, coll="t", dim=4):
    ok(owner, "PUT", f"/collections/{coll}", {"vectors": {"size": dim, "distance": "Cosine"}})
    ok(owner, "PUT", f"/collections/{coll}/points?wait=true", {"points": points})


# ── ratchet: pure, no I/O ────────────────────────────────────────────────────────────────────
def test_first_sweep_seeds_baseline_with_no_warnings():
    measured = {
        "a": {"name_word": {"token": "alpha", "rank": 1, "winner": "a"}},
        "b": {"name_word": {"token": "beta", "rank": 9, "winner": "z"}},  # backlog, but no baseline yet
        "c": {"own_phrase": {"score": 0.4}},
    }
    out, warnings, backlog = fnd.apply_ratchet(None, measured, now=1000.0)
    assert warnings == []
    assert out["a"]["name_word"] == {"token": "alpha", "rank": 1, "best": 1}
    assert out["b"]["name_word"] == {"token": "beta", "rank": 9, "best": 9}
    assert out["c"]["own_phrase"] == {"score": 0.4, "best": 0.4}
    assert all(e["first_seen"] == 1000.0 for e in out.values())
    assert backlog == 1                        # only "b" is outside the top 3


def test_new_skill_not_top3_warns_naming_the_winner():
    prev = {"skills": {"old": {"name_word": {"token": "old", "rank": 1, "best": 1},
                               "first_seen": 500.0}}}
    measured = {"old": {"name_word": {"token": "old", "rank": 1, "winner": "old"}},
                "fresh": {"name_word": {"token": "fresh", "rank": 7, "winner": "rival"}}}
    out, warnings, backlog = fnd.apply_ratchet(prev, measured, now=1000.0)
    assert len(warnings) == 1
    assert "fresh" in warnings[0] and "rival" in warnings[0] and "7" in warnings[0]
    assert out["fresh"]["first_seen"] == 1000.0        # new skill: first_seen = now
    assert out["old"]["first_seen"] == 500.0           # known skill: first_seen carries over
    assert backlog == 1


def test_new_skill_already_top3_does_not_warn():
    measured = {"fresh": {"name_word": {"token": "fresh", "rank": 2, "winner": "fresh"}}}
    out, warnings, backlog = fnd.apply_ratchet({"skills": {}}, measured, now=1000.0)
    assert warnings == []
    assert backlog == 0
    assert out["fresh"]["name_word"]["best"] == 2


def test_known_skill_regresses_out_of_top3_warns():
    prev = {"skills": {"s": {"name_word": {"token": "tok", "rank": 2, "best": 2},
                             "first_seen": 1.0}}}
    measured = {"s": {"name_word": {"token": "tok", "rank": 5, "winner": "other"}}}
    out, warnings, backlog = fnd.apply_ratchet(prev, measured, now=2.0)
    assert len(warnings) == 1 and "fell out of the top 3" in warnings[0] and "s" in warnings[0]
    assert out["s"]["name_word"] == {"token": "tok", "rank": 5, "best": 2}   # best moves up only
    assert backlog == 1


def test_known_skill_never_top3_regressing_further_does_not_warn():
    """WARN(b) fires only when the skill EVER held the top-3 (best<=3), matching design's
    "falls FROM the top 3 TO outside it" — a skill that was already outside never re-warns
    on every fluctuation below the line."""
    prev = {"skills": {"s": {"name_word": {"token": "tok", "rank": 6, "best": 6},
                             "first_seen": 1.0}}}
    measured = {"s": {"name_word": {"token": "tok", "rank": 9, "winner": "other"}}}
    _, warnings, _ = fnd.apply_ratchet(prev, measured, now=2.0)
    assert warnings == []


def test_baseline_moves_up_only_a_worse_rank_never_lowers_best():
    prev = {"skills": {"s": {"name_word": {"token": "tok", "rank": 1, "best": 1},
                             "first_seen": 1.0}}}
    measured = {"s": {"name_word": {"token": "tok", "rank": 2, "winner": "other"}}}
    out, warnings, _ = fnd.apply_ratchet(prev, measured, now=2.0)
    assert out["s"]["name_word"]["best"] == 1       # best cannot regress: 1 stays 1
    assert warnings == []                            # rank 2 is still inside the top 3


def test_probe_token_change_restarts_the_ratchet_without_a_false_regression():
    """A renamed / DF-shifted probe word is a different question, not a regression."""
    prev = {"skills": {"s": {"name_word": {"token": "old", "rank": 1, "best": 1},
                             "first_seen": 1.0}}}
    measured = {"s": {"name_word": {"token": "new", "rank": 40, "winner": "other"}}}
    out, warnings, _ = fnd.apply_ratchet(prev, measured, now=2.0)
    assert warnings == []                            # different word: no continuity, no warning
    assert out["s"]["name_word"] == {"token": "new", "rank": 40, "best": 40}   # restarts at current


def test_own_phrase_hysteresis_warns_on_a_big_enough_drop_below_half():
    prev = {"skills": {"s": {"own_phrase": {"score": 0.9, "best": 0.9}, "first_seen": 1.0}}}
    measured = {"s": {"own_phrase": {"score": 0.4}}}          # 0.5 below best, AND < 0.5
    _, warnings, _ = fnd.apply_ratchet(prev, measured, now=2.0)
    assert len(warnings) == 1 and "s" in warnings[0] and "0.40" in warnings[0]


def test_own_phrase_drop_above_the_floor_does_not_warn():
    """Falling >= 0.25 below best but staying >= 0.5 does not warn (both conditions required)."""
    prev = {"skills": {"s": {"own_phrase": {"score": 0.9, "best": 0.9}, "first_seen": 1.0}}}
    measured = {"s": {"own_phrase": {"score": 0.6}}}          # 0.3 below best, but >= 0.5
    _, warnings, _ = fnd.apply_ratchet(prev, measured, now=2.0)
    assert warnings == []


def test_own_phrase_small_drop_below_half_does_not_warn():
    """Below 0.5 but the drop from best is < 0.25 (both conditions required)."""
    prev = {"skills": {"s": {"own_phrase": {"score": 0.55, "best": 0.55}, "first_seen": 1.0}}}
    measured = {"s": {"own_phrase": {"score": 0.45}}}
    _, warnings, _ = fnd.apply_ratchet(prev, measured, now=2.0)
    assert warnings == []


def test_own_phrase_new_high_never_warns_and_becomes_the_new_best():
    prev = {"skills": {"s": {"own_phrase": {"score": 0.3, "best": 0.3}, "first_seen": 1.0}}}
    measured = {"s": {"own_phrase": {"score": 0.95}}}
    out, warnings, _ = fnd.apply_ratchet(prev, measured, now=2.0)
    assert warnings == []
    assert out["s"]["own_phrase"]["best"] == 0.95


def test_backlog_counts_only_skills_with_a_name_word_probe():
    measured = {"a": {"name_word": {"token": "a", "rank": 9, "winner": "x"}},
                "b": {"own_phrase": {"score": 0.1}}}          # no name_word at all -> excluded
    _, _, backlog = fnd.apply_ratchet(None, measured, now=1.0)
    assert backlog == 1


# ── token selection / document frequency ────────────────────────────────────────────────────
def test_name_tokens_split_generic_and_short_words():
    assert fnd._name_tokens("tk-gdelt-doctor") == ["gdelt"]    # "doctor" is generic
    assert fnd._name_tokens("plugin:ak-repomix") == ["repomix"]
    assert fnd._name_tokens("skill-search") == ["search"]     # "skill" is generic
    assert fnd._name_tokens("v2-x9") == []                     # too short / digit-only


def test_document_frequency_counts_distinct_skills_not_occurrences():
    skills = [{"name": "tk-gdelt-doctor", "description": "gdelt news archive gdelt gdelt"},
             {"name": "other-thing", "description": "unrelated"},
             {"name": "another-gdelt-tool", "description": "also about gdelt"}]
    df = fnd.document_frequency(skills)
    assert df["gdelt"] == 2                # two SKILLS mention it, however many times each


def test_probe_token_picks_the_rarest_qualifying_word():
    df = {"gdelt": 1, "doctor": 50}
    assert fnd.probe_token("tk-gdelt-doctor", df) == "gdelt"


def test_probe_token_none_when_nothing_qualifies():
    df = {"common": 100}
    assert fnd.probe_token("the-common-tool", df) is None


def test_probe_token_ties_break_by_position_in_the_name():
    df = {"alpha": 2, "gamma": 2}
    assert fnd.probe_token("alpha-gamma", df) == "alpha"


# ── owner URL derivation: the same malformed-value fallback index_owner.py uses ────────────
def test_owner_urls_default(monkeypatch):
    monkeypatch.delenv("SKILL_QDRANT_URL", raising=False)
    monkeypatch.delenv("EMBED_SHIM_PORT", raising=False)
    q, e = fnd._owner_urls()
    assert q == "http://127.0.0.1:6333" and e == "http://127.0.0.1:6363"


def test_owner_urls_honors_a_configured_port(monkeypatch):
    monkeypatch.setenv("SKILL_QDRANT_URL", "http://localhost:6433")
    monkeypatch.setenv("EMBED_SHIM_PORT", "6463")
    q, e = fnd._owner_urls()
    assert q == "http://127.0.0.1:6433" and e == "http://127.0.0.1:6463"


def test_owner_urls_falls_back_on_a_malformed_value(monkeypatch):
    monkeypatch.setenv("SKILL_QDRANT_URL", "not a url at all")
    monkeypatch.setenv("EMBED_SHIM_PORT", "not-a-port")
    q, e = fnd._owner_urls()
    assert q == "http://127.0.0.1:6333" and e == "http://127.0.0.1:6363"


# ── lock / throttle ──────────────────────────────────────────────────────────────────────────
def test_lock_contention_is_a_quiet_no_op(tmp_path, monkeypatch):
    monkeypatch.setenv("SKILL_FINDABILITY_PATH", str(tmp_path / "findability.json"))
    held = fnd._acquire_lock()
    assert held is not None
    try:
        assert fnd._acquire_lock() is None         # a concurrent sweep must not double-acquire
    finally:
        fnd._release_lock(held)
    reacquired = fnd._acquire_lock()               # released -> acquirable again
    assert reacquired is not None
    fnd._release_lock(reacquired)


def test_sweep_is_a_quiet_no_op_when_throttled(tmp_path, monkeypatch, owner_factory):
    """A REAL, reachable owner (proving the short-circuit is the THROTTLE, not incidentally
    an unreachable-owner exit that would fire anyway once the throttle check is removed)."""
    o = owner_factory().wait_ready()
    path = tmp_path / "findability.json"
    monkeypatch.setenv("SKILL_FINDABILITY_PATH", str(path))
    monkeypatch.setenv("SKILL_QDRANT_URL", o.url)
    monkeypatch.setenv("EMBED_SHIM_PORT", str(o.eport))
    seeded = {"version": 1, "swept_at": time.time(), "harness": "claude",
              "skills": {}, "warnings": [], "backlog": 0}
    path.write_text(json.dumps(seeded), encoding="utf-8")
    before = path.read_text(encoding="utf-8")
    assert fnd.cmd_sweep() == 0
    assert path.read_text(encoding="utf-8") == before      # untouched: no re-sweep happened


def test_sweep_is_a_quiet_no_op_when_the_owner_is_unreachable(tmp_path, monkeypatch):
    monkeypatch.setenv("SKILL_FINDABILITY_PATH", str(tmp_path / "findability.json"))
    monkeypatch.setenv("SKILL_QDRANT_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("EMBED_SHIM_PORT", "9")
    assert fnd.cmd_sweep() == 0
    assert not (tmp_path / "findability.json").exists()    # never written on a down owner


# ── --accept ─────────────────────────────────────────────────────────────────────────────────
def test_accept_resets_the_baseline_to_the_current_state(tmp_path, monkeypatch):
    path = tmp_path / "findability.json"
    monkeypatch.setenv("SKILL_FINDABILITY_PATH", str(path))
    data = {"version": 1, "swept_at": 1.0, "harness": "claude",
            "skills": {"s": {"name_word": {"token": "tok", "rank": 9, "best": 1},
                             "own_phrase": {"score": 0.2, "best": 0.9},
                             "first_seen": 1.0}},
            "warnings": ["s regressed"], "backlog": 1}
    path.write_text(json.dumps(data), encoding="utf-8")
    assert fnd.cmd_accept("s") == 0
    out = json.loads(path.read_text(encoding="utf-8"))
    assert out["skills"]["s"]["name_word"]["best"] == 9      # reset to the current rank
    assert out["skills"]["s"]["own_phrase"]["best"] == 0.2   # reset to the current score


def test_accept_unknown_skill_fails_without_writing(tmp_path, monkeypatch):
    path = tmp_path / "findability.json"
    monkeypatch.setenv("SKILL_FINDABILITY_PATH", str(path))
    path.write_text(json.dumps({"skills": {}}), encoding="utf-8")
    assert fnd.cmd_accept("ghost") == 1


# ── real-owner integration: the leave-one-out exclusion, and the name-word rank shape ──────
def test_own_phrase_score_excludes_the_probes_own_point(owner_factory):
    """Without excluding the probe's own point, a point's self-cosine (1.0) would ALWAYS
    win its own group — this proves the exclusion, not just the arithmetic around it."""
    o = owner_factory().wait_ready()
    seed(o, [
        pt(1, "s", vec(1, 0), kind="trigger"),      # the probe point itself
        pt(2, "s", vec(0.99, 0.01), kind="trigger"),  # s's OTHER point: nearly identical, must win
        pt(3, "rival", vec(0, 1)),                    # far away: never competes here
    ])
    score = fnd.own_phrase_score(o.url, "t", "s", [(1, vec(1, 0))])
    assert score == 1.0    # s's OTHER point still lands top-6 once the probe itself is excluded


def test_own_phrase_score_zero_when_no_other_point_is_close(owner_factory):
    o = owner_factory().wait_ready()
    seed(o, [
        pt(1, "s", vec(1, 0), kind="trigger"),
        pt(2, "rival", vec(0.99, 0.01)),     # beats s's remaining (none) once the probe is excluded
    ])
    score = fnd.own_phrase_score(o.url, "t", "s", [(1, vec(1, 0))])
    assert score == 0.0    # s has no OTHER point at all: its group cannot appear once excluded


def test_own_phrase_score_excludes_external_tier_competitors(owner_factory):
    o = owner_factory().wait_ready()
    seed(o, [
        pt(1, "s", vec(1, 0), kind="trigger"),
        pt(2, "external-rival", vec(0.999, 0.001), tier="external"),
    ])
    score = fnd.own_phrase_score(o.url, "t", "s", [(1, vec(1, 0))])
    assert score == 0.0    # the external competitor must not count toward s's own top-6 check


def test_own_phrase_score_none_with_no_trigger_points():
    assert fnd.own_phrase_score("http://127.0.0.1:9", "t", "s", []) is None


def test_name_word_rank_reports_position_and_the_current_winner(owner_factory):
    o = owner_factory().wait_ready()
    seed(o, [
        pt(1, "winner", vec(0, 1)),         # exact match: cosine 1.0
        pt(2, "target", vec(0.1, 0.9)),     # close second
        pt(3, "third", vec(1, 0)),          # orthogonal: far last
    ])
    rank, winner = fnd.name_word_rank(o.url, "t", None, vec(0, 1), "target", depth=10)
    assert rank == 2 and winner == "winner"


def test_name_word_rank_beyond_depth_is_depth_plus_one(owner_factory):
    o = owner_factory().wait_ready()
    seed(o, [pt(i, f"skill{i}", vec(1.0 - i * 0.01, i * 0.01)) for i in range(20)])
    rank, _ = fnd.name_word_rank(o.url, "t", None, vec(0.0, 1.0), "skill0", depth=5)
    assert rank == 6           # not found within depth=5 -> depth + 1


# ── complement_rank / search_skills_rank (ADR-0075 integration: search_skills() itself
# arranges installed-before-external via TWO separate queries, which a single mixed-tier
# groups query — name_word_rank's own shape — can never observe) ──────────────────────────
def _allow_catalog(monkeypatch, alias):
    """`_scope_filter`'s "should" list only admits a catalog scope this session's config
    actually names (conftest pins `SKILL_CONCIERGE_CATALOG_ROOTS` to a nonexistent path, so
    every catalog scope is invisible by default) — the same seam the engine suite's own 6
    catalog tests monkeypatch, applied here so a seeded external-tier point is not silently
    filtered out before it ever reaches the complement arrangement."""
    from skill_search import skills_discovery as sd
    monkeypatch.setattr(sd, "catalog_roots", lambda: {alias: f"/tmp/{alias}"})


def test_complement_rank_keeps_installed_first_when_no_external_clears_the_margin(owner_factory, monkeypatch):
    from skill_search import server as srv
    # complement_rank itself does not read the flag (only search_skills_rank/search_skills
    # do); turned on explicitly here since the default shipped OFF in v0.55.0.
    monkeypatch.setenv("SKILL_SEARCH_COMPLEMENT", "1")
    _allow_catalog(monkeypatch, "x")
    o = owner_factory().wait_ready()
    seed(o, [
        pt(1, "target", vec(0.8, 0.2), scope="personal"),
        # cosine ~0.999 vs target's exact self-match 1.0: well within the 0.08 margin
        pt(2, "ext-close", vec(0.83, 0.17), scope="catalog:x", tier="external"),
        pt(3, "ext-far", vec(0.1, 0.9), scope="catalog:x", tier="external"),
    ])
    rank, winner = fnd.complement_rank(o.url, "t", srv, vec(0.8, 0.2), "target", depth=10)
    assert rank == 1 and winner == "target"    # installed leads unless an external clears the margin


def test_complement_rank_lets_a_strong_external_lead(owner_factory, monkeypatch):
    from skill_search import server as srv
    monkeypatch.setenv("SKILL_SEARCH_COMPLEMENT", "1")
    _allow_catalog(monkeypatch, "x")
    o = owner_factory().wait_ready()
    seed(o, [
        pt(1, "target", vec(0.5, 0.5), scope="personal"),
        # cosine ~0.999 vs target's ~0.743 for this query: a ~0.26 gap, far past the 0.08 margin
        pt(2, "dominant-ext", vec(0.99, 0.01), scope="catalog:x", tier="external"),
    ])
    # query near "dominant-ext": it must render ABOVE the installed target, still findable
    rank, winner = fnd.complement_rank(o.url, "t", srv, vec(0.95, 0.05), "target", depth=10)
    assert winner == "dominant-ext" and rank == 2


def test_search_skills_rank_falls_back_to_plain_shape_without_the_complement_machinery(owner_factory):
    """A pre-ADR-0075 `srv` (no _search_complement_on at all) must use the plain single-query
    shape — the exact case a BASE checkout that predates X hits."""
    o = owner_factory().wait_ready()
    seed(o, [pt(1, "winner", vec(0, 1)), pt(2, "target", vec(0.1, 0.9))])

    class NoComplementServer:
        pass

    rank, winner = fnd.search_skills_rank(o.url, "t", None, NoComplementServer(), vec(0, 1),
                                          "target", depth=10)
    assert rank == 2 and winner == "winner"


def test_search_skills_rank_uses_the_complement_shape_when_srv_has_it_and_it_is_on(owner_factory, monkeypatch):
    from skill_search import server as srv
    # "it is on" is the test's premise — set explicitly since v0.55.0 ships the flag OFF.
    monkeypatch.setenv("SKILL_SEARCH_COMPLEMENT", "1")
    _allow_catalog(monkeypatch, "x")
    o = owner_factory().wait_ready()
    seed(o, [
        pt(1, "target", vec(0.5, 0.5), scope="personal"),
        pt(2, "dominant-ext", vec(0.99, 0.01), scope="catalog:x", tier="external"),
    ])
    rank, winner = fnd.search_skills_rank(o.url, "t", None, srv, vec(0.95, 0.05),
                                          "target", depth=10)
    assert winner == "dominant-ext"    # only the complement shape can surface this


def test_search_skills_rank_respects_the_flag_being_off(owner_factory, monkeypatch):
    """SKILL_SEARCH_COMPLEMENT=0 must fall back to the plain shape even though `srv` carries
    the machinery — search_skills_rank reads the LIVE flag, never just attribute presence."""
    from skill_search import server as srv
    monkeypatch.setenv("SKILL_SEARCH_COMPLEMENT", "0")
    o = owner_factory().wait_ready()
    seed(o, [pt(1, "winner", vec(0, 1)), pt(2, "target", vec(0.1, 0.9))])
    rank, winner = fnd.search_skills_rank(o.url, "t", None, srv, vec(0, 1), "target", depth=10)
    assert rank == 2 and winner == "winner"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
