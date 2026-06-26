"""Tests for generate_overrides — the budget-freeing half. Previously untested;
the override mapping is what actually frees the 1% budget, so it's worth pinning."""

import json

from skill_search import generate_overrides as go


def test_compute_overrides_keeps_allowlist_on_rest_name_only():
    names = ["alpha", "beta", "skill-search"]
    ov = go.compute_overrides(names, {"skill-search"})
    assert ov == {"alpha": "name-only", "beta": "name-only", "skill-search": "on"}


def test_compute_overrides_default_keep_on():
    ov = go.compute_overrides(["skill-search", "skill-finder", "x"], go.DEFAULT_KEEP_ON)
    assert ov["skill-search"] == "on" and ov["skill-finder"] == "on"
    assert ov["x"] == "name-only"


def test_keep_on_from_argv_extra_and_stops_at_next_flag():
    # `--keep a b --global` must not swallow --global into the allowlist (old bug)
    keep = go.keep_on_from_argv(["prog", "--keep", "a", "b", "--global"])
    assert "a" in keep and "b" in keep
    assert "--global" not in keep
    assert go.DEFAULT_KEEP_ON <= keep          # defaults always included


def test_write_overrides_merges_without_clobbering(tmp_path):
    p = tmp_path / "settings.local.json"
    p.write_text(json.dumps({"enableAllProjectMcpServers": True}))
    go.write_overrides(p, {"x": "name-only"})
    data = json.loads(p.read_text())
    assert data["skillOverrides"] == {"x": "name-only"}
    assert data["enableAllProjectMcpServers"] is True   # other keys preserved


def test_main_end_to_end_writes_overrides(tmp_path, monkeypatch):
    monkeypatch.setattr(go, "discover_skills",
                        lambda: [{"name": "skill-search"}, {"name": "frontend-design"}])
    monkeypatch.setattr(go.Path, "cwd", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(go.sys, "argv", ["generate_overrides"])
    go.main()
    out = json.loads((tmp_path / ".claude" / "settings.local.json").read_text())
    assert out["skillOverrides"] == {"frontend-design": "name-only", "skill-search": "on"}
