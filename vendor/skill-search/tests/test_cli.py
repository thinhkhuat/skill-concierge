"""Tests for server.main() CLI dispatch. The underlying build_index/_health are
mocked so these stay fast and offline — they verify flag routing, not embedding."""

import json

import pytest

from skill_search import server


def test_cli_reindex_prints_stats(monkeypatch, capsys):
    monkeypatch.setattr(server, "build_index",
                        lambda force=False: {"indexed": 5, "embedded": 2, "deleted": 0, "skipped": 3})
    monkeypatch.setattr(server.sys, "argv", ["skill-search", "--reindex"])
    server.main()
    out = json.loads(capsys.readouterr().out)
    assert out["indexed"] == 5 and out["collection"] == server.COLLECTION


def test_cli_rebuild_forces_full_rebuild(monkeypatch, capsys):
    seen = {}
    monkeypatch.setattr(server, "build_index",
                        lambda force=False: seen.update(force=force) or {"indexed": 0, "embedded": 0, "deleted": 0, "skipped": 0})
    monkeypatch.setattr(server.sys, "argv", ["skill-search", "--rebuild"])
    server.main()
    assert seen["force"] is True


def test_cli_health_exit_code_reflects_status(monkeypatch):
    monkeypatch.setattr(server, "_health", lambda: {"status": "degraded", "issues": ["x"]})
    monkeypatch.setattr(server.sys, "argv", ["skill-search", "--health"])
    with pytest.raises(SystemExit) as exc:
        server.main()
    assert exc.value.code == 1            # non-zero on degraded → cron/CI-safe


def test_cli_health_ok_exits_zero(monkeypatch):
    monkeypatch.setattr(server, "_health", lambda: {"status": "ok", "issues": []})
    monkeypatch.setattr(server.sys, "argv", ["skill-search", "--health"])
    with pytest.raises(SystemExit) as exc:
        server.main()
    assert exc.value.code == 0
