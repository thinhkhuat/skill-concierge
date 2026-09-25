"""Unit tests for search_skills query fanout / max-pool fusion (_fuse_ranked).

Pure logic — no Qdrant or embedder needed. Runs under pytest OR standalone:
    python tests/test_fusion.py
"""
from types import SimpleNamespace

from skill_search.server import _fuse_ranked


def _grp(name, score, desc="d", scope=None, path=None):
    """Fake a Qdrant group: one best hit carrying name/description/score (+scope/path)."""
    payload = {"name": name, "description": desc}
    if scope is not None:
        payload["scope"] = scope
    if path is not None:
        payload["path"] = path
    hit = SimpleNamespace(score=score, payload=payload, id=name)
    return SimpleNamespace(hits=[hit], id=name)


def test_single_query_ranks_by_score():
    # Backward-compat: one query behaves like the old top-k path.
    groups = [_grp("a", 0.9), _grp("b", 0.7)]
    out = _fuse_ranked([groups], top_k=5)
    assert [r["name"] for r in out] == ["a", "b"]
    assert "command" not in out[0] and out[0]["origin"] == "claude"
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



# ── row provenance: origin / disabled_in / no command; SKILL_ROW_ORIGIN=0 = old shape ──
import json as _json

import pytest

from skill_search import server as _server
from skill_search import skills_discovery as _sd

_V0472 = {  # the exact rows v0.47.2 produced, per scope family (catalog shape unchanged)
    "personal": {"name": "a", "command": "/a", "description": "d", "score": 0.9},
    "catalog:x": {"name": "a", "description": "d", "score": 0.9, "external": "x",
                  "note": 'external catalog skill \u2014 NOT installed; consume by get_skill("a") '
                          "and follow its SKILL.md inline"},
}


@pytest.fixture()
def _no_claude_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(_sd, "CLAUDE_SETTINGS_JSON", tmp_path / "absent-settings.json")
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.mark.parametrize("scope,origin", [
    ("personal", "claude"), ("plugin", "claude"), ("project:/x", "claude"),
    ("claude-synced", "claude-synced"), ("codex-plugin", "codex"), ("codex-personal", "codex"),
    ("commandcode-personal", "commandcode"), ("omp-managed", "omp"), ("zcode-plugin", "zcode"),
    ("dsh-personal", "dsh"), ("cline-project:/x", "cline"), ("", "claude")])
def test_origin_per_scope_family_and_no_command(scope, origin, _no_claude_settings):
    row = _fuse_ranked([[_grp("s", 0.5, scope=scope)]], top_k=5)[0]
    assert row["origin"] == origin
    assert "command" not in row


def test_catalog_row_shape_unchanged(_no_claude_settings):
    row = _fuse_ranked([[_grp("a", 0.9, scope="catalog:x")]], top_k=5)[0]
    assert row == _V0472["catalog:x"]


@pytest.mark.parametrize("scope", ["personal", "plugin", "codex-plugin", "zcode-plugin",
                                   "claude-synced", "catalog:x"])
def test_kill_switch_restores_v0472_rows(scope, monkeypatch, _no_claude_settings):
    monkeypatch.setenv("SKILL_ROW_ORIGIN", "0")
    row = _fuse_ranked([[_grp("a", 0.9, scope=scope)]], top_k=5)[0]
    want = _V0472["catalog:x"] if scope.startswith("catalog:") else _V0472["personal"]
    assert _json.dumps(row) == _json.dumps(want)


def test_with_paths_keeps_path_on_foreign_rows(_no_claude_settings):
    row = _fuse_ranked([[_grp("s", 0.5, scope="codex-plugin", path="/p/SKILL.md")]],
                       top_k=5, with_paths=True)[0]
    assert row["path"] == "/p/SKILL.md" and row["origin"] == "codex"


def _settings(path, enabled):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json.dumps({"enabledPlugins": enabled}), encoding="utf-8")


def _claude_world(tmp_path, monkeypatch, installed, user=None, local=None):
    """Claude registry + settings layers; cwd = tmp_path (the server reads cwd layers live)."""
    reg = tmp_path / "installed_plugins.json"
    reg.write_text(_json.dumps({"plugins": {k: [{"installPath": "/x"}] for k in installed}}))
    monkeypatch.setattr(_sd, "INSTALLED_PLUGINS_JSON", reg)
    monkeypatch.setattr(_sd, "CLAUDE_SETTINGS_JSON", tmp_path / "user.json")
    _settings(tmp_path / "user.json", user or {})
    if local is not None:
        _settings(tmp_path / ".claude" / "settings.local.json", local)
    monkeypatch.chdir(tmp_path)


def _row(name, scope):
    return _fuse_ranked([[_grp(name, 0.7, scope=scope)]], 5)[0]


def test_disabled_in_marks_an_installed_plugin_claude_switched_off(tmp_path, monkeypatch):
    _claude_world(tmp_path, monkeypatch, ["skill-creator@m"], user={"skill-creator@m": False})
    row = _row("skill-creator:skill-creator", "zcode-plugin")
    assert row["disabled_in"] == ["claude"] and row["origin"] == "zcode"


def test_disabled_in_later_layer_wins(tmp_path, monkeypatch):
    _claude_world(tmp_path, monkeypatch, ["skill-creator@m"], user={"skill-creator@m": False},
                  local={"skill-creator@m": True})
    assert "disabled_in" not in _row("skill-creator:x", "plugin")


def test_disabled_in_any_installed_marketplace_on_keeps_it_on(tmp_path, monkeypatch):
    _claude_world(tmp_path, monkeypatch, ["foo@m1", "foo@m2"], user={"foo@m1": False, "foo@m2": True})
    assert "disabled_in" not in _row("foo:bar", "plugin")


def test_disabled_in_ignores_a_stale_key_for_an_uninstalled_marketplace(tmp_path, monkeypatch):
    # settings still say foo@oldmkt: false, but Claude now runs foo from newmkt (no key = on)
    _claude_world(tmp_path, monkeypatch, ["foo@newmkt"], user={"foo@oldmkt": False})
    assert "disabled_in" not in _row("foo:bar", "plugin")


def test_disabled_in_never_without_knowledge(tmp_path, monkeypatch):
    _claude_world(tmp_path, monkeypatch, ["x@m"], user={"x@m": False})
    assert "disabled_in" not in _row("x", "personal")                 # bare name
    assert "disabled_in" not in _row("x:y", "catalog:x")              # catalog row unchanged
    assert "disabled_in" not in _row("notinstalled:y", "plugin")      # no installed key
    (tmp_path / "installed_plugins.json").write_text("{not json")
    assert "disabled_in" not in _row("x:y", "plugin")                 # unreadable registry


def test_synced_rows_are_marked_off_in_every_other_harness(tmp_path, monkeypatch):
    _claude_world(tmp_path, monkeypatch, [])
    row = _row("anthropic-skills:skill-creator", "claude-synced")
    assert row["origin"] == "claude-synced"
    assert set(row["disabled_in"]) == {"codex", "commandcode", "omp", "zcode", "dsh", "cline"}


def _search(monkeypatch, groups):
    monkeypatch.setattr(_server, "embed_batch", lambda qs: [[0.0] for _ in qs])
    monkeypatch.setattr(_server._qdrant, "query_points_groups",
                        lambda **kw: SimpleNamespace(groups=groups))
    monkeypatch.setattr(_server, "_staleness_warning", lambda: None)
    return _json.loads(_server.search_skills("q"))


def test_search_response_note_once_and_absent_with_flag_off(monkeypatch, _no_claude_settings):
    out = _search(monkeypatch, [_grp("a", 0.9, scope="personal"), _grp("b", 0.8, scope="zcode-plugin")])
    assert "get_skill(name)" in out["note"] and "disabled_in" in out["note"]
    assert _json.dumps(out, ensure_ascii=False).count(out["note"]) == 1
    monkeypatch.setenv("SKILL_ROW_ORIGIN", "0")
    out = _search(monkeypatch, [_grp("a", 0.9, scope="personal")])
    assert "note" not in out and out["results"][0]["command"] == "/a"


def test_every_visible_scope_has_known_origin_head():
    for s in _sd.visible_scopes():
        if s.startswith("catalog:"):
            continue
        known = s == "claude-synced" or _server._origin_head(s) in _server._ORIGIN_HEADS
        assert known, f"scope {s!r} has no origin head — extend _ORIGIN_HEADS"


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print(f"ok  {_name}")
    print("all fusion tests passed")
