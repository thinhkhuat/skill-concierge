"""ADR-0074 findability sweep hook: build_index launches a detached
`python -m skill_search.findability --sweep` subprocess whenever a reindex actually
changed the index (embedded or deleted > 0). SKILL_FINDABILITY=0 disables it, and a
launch failure must never raise. The sibling `skill_search.findability` module (owned
by a parallel worktree, per the build plan's interface contract) does not need to exist
for these tests — they only assert the Popen call itself via monkeypatch, never a real
subprocess."""
import sys
from pathlib import Path

from skill_search import server


DESC = "does alpha things when the user needs alpha"


def test_launch_findability_sweep_skips_when_nothing_changed(monkeypatch):
    calls = []
    monkeypatch.setattr(server, "SKILL_FINDABILITY", True)
    monkeypatch.setattr(server.subprocess, "Popen", lambda *a, **kw: calls.append((a, kw)))
    server._launch_findability_sweep(0, 0)
    assert calls == []


def test_launch_findability_sweep_fires_on_embedded_or_deleted(monkeypatch):
    calls = []
    monkeypatch.setattr(server, "SKILL_FINDABILITY", True)
    monkeypatch.setattr(server.subprocess, "Popen", lambda *a, **kw: calls.append((a, kw)))
    server._launch_findability_sweep(3, 0)
    server._launch_findability_sweep(0, 2)
    assert len(calls) == 2
    args, kwargs = calls[0]
    assert args[0] == [sys.executable, "-m", "skill_search.findability", "--sweep"]
    assert kwargs["cwd"] == str(Path.home())
    assert kwargs["start_new_session"] is True
    assert kwargs["stdout"] is server.subprocess.DEVNULL
    assert kwargs["stderr"] is server.subprocess.DEVNULL
    assert kwargs["stdin"] is server.subprocess.DEVNULL


def test_launch_findability_sweep_disabled_by_flag(monkeypatch):
    calls = []
    monkeypatch.setattr(server, "SKILL_FINDABILITY", False)
    monkeypatch.setattr(server.subprocess, "Popen", lambda *a, **kw: calls.append(1))
    server._launch_findability_sweep(5, 5)
    assert calls == []


def test_launch_findability_sweep_never_raises_on_launch_failure(monkeypatch):
    monkeypatch.setattr(server, "SKILL_FINDABILITY", True)

    def boom(*a, **kw):
        raise OSError("sandboxed, no fork")

    monkeypatch.setattr(server.subprocess, "Popen", boom)
    server._launch_findability_sweep(1, 0)   # must not raise


def test_build_index_fires_sweep_hook_only_on_real_change(tmp_path, monkeypatch):
    skill = {"name": "sweep-x", "description": DESC, "path": str(tmp_path / "SKILL.md"),
             "body": "b", "scope": "personal"}
    monkeypatch.setattr(server, "discover_skills", lambda: [dict(skill)])
    monkeypatch.setattr(server, "COLLECTION", "sweep_hook_test")
    monkeypatch.setattr(server, "embed_batch",
                        lambda texts: [[float(len(t) % 7 + 1)] + [0.0] * 383 for t in texts])
    monkeypatch.setattr(server, "_write_next_skills_sidecar", lambda s: None)
    monkeypatch.setattr(server, "_write_manifest", lambda n: None)
    monkeypatch.setattr(server, "SKILL_FINDABILITY", True)
    calls = []
    monkeypatch.setattr(server.subprocess, "Popen", lambda *a, **kw: calls.append((a, kw)))

    server.build_index(force=True)           # first build: everything is new -> fires
    assert len(calls) == 1

    calls.clear()
    server.build_index()                     # nothing changed -> must NOT fire
    assert calls == []
