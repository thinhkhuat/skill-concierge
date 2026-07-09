"""Tests for the auto_flywheel SessionStart hook's staleness guard.

The hook and auto_reindex both fire detached and unordered at SessionStart. If the
flywheel measures utterance coverage BEFORE the reindex lands, it sees the old,
smaller skill set, concludes "0 missing", writes its throttle stamp, and goes
silent for THROTTLE_S (6h by default). Observed 2026-07-09: a dozen freshly
installed skills received no utterances because of exactly this race.

The fix is not to reorder the hooks (they are independent by design) but to make
the flywheel refuse to draw a conclusion from an index that lags disk — and,
crucially, to skip WITHOUT stamping so the next session tries again.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks" / "scripts"))
import auto_flywheel as af  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Point the hook's stamp/log at a temp dir and satisfy its cheap preconditions."""
    monkeypatch.setattr(af, "LOGDIR", tmp_path)
    monkeypatch.setattr(af, "STAMP", tmp_path / ".auto-flywheel-stamp")
    monkeypatch.setattr(af, "LOGFILE", tmp_path / "auto-flywheel.log")
    monkeypatch.setenv("FLYWHEEL_LLM_MODEL", "test-model")
    monkeypatch.setenv("SKILL_AUTO_FLYWHEEL", "1")
    # Preconditions the hook checks before doing any work: point them at real files.
    for attr in ("SS_BIN", "PY_BIN", "FLYWHEEL_PY"):
        f = tmp_path / attr.lower()
        f.write_text("")
        monkeypatch.setattr(af, attr, f)
    monkeypatch.setattr(af, "_mcp_env", lambda: ({}, "http://localhost:6333"))
    monkeypatch.setattr(af, "_qdrant_up", lambda _u: True)


def test_defers_without_stamping_when_index_lags_disk(monkeypatch, tmp_path):
    """The whole bug: a stale index means '0 missing' is a lie. Skip, don't stamp."""
    monkeypatch.setattr(af, "_indexed_count", lambda: 533)
    monkeypatch.setattr(af, "_disk_count", lambda: 548)
    spawned = []
    monkeypatch.setattr(af.subprocess, "Popen", lambda *a, **k: spawned.append(a))

    assert af.main() == 0
    assert not af.STAMP.exists(), "throttle armed against a stale index"
    assert spawned == [], "generated against a stale index"


def test_proceeds_when_index_matches_disk(monkeypatch):
    monkeypatch.setattr(af, "_indexed_count", lambda: 548)
    monkeypatch.setattr(af, "_disk_count", lambda: 548)
    monkeypatch.setattr(af, "_ping_ok", lambda: True)
    spawned = []
    monkeypatch.setattr(af.subprocess, "Popen", lambda *a, **k: spawned.append(a))

    assert af.main() == 0
    assert af.STAMP.exists()
    assert len(spawned) == 1


def test_proceeds_when_index_exceeds_disk(monkeypatch):
    """Index larger than this session's disk view is normal on a shared collection
    (another session's project skills). It is not a reason to defer."""
    monkeypatch.setattr(af, "_indexed_count", lambda: 600)
    monkeypatch.setattr(af, "_disk_count", lambda: 548)
    monkeypatch.setattr(af, "_ping_ok", lambda: True)
    monkeypatch.setattr(af.subprocess, "Popen", lambda *a, **k: None)

    assert af.main() == 0
    assert af.STAMP.exists()


def test_unknown_counts_fail_open(monkeypatch):
    """No manifest yet (fresh install) must not wedge the flywheel off forever."""
    monkeypatch.setattr(af, "_indexed_count", lambda: None)
    monkeypatch.setattr(af, "_disk_count", lambda: 548)
    monkeypatch.setattr(af, "_ping_ok", lambda: True)
    monkeypatch.setattr(af.subprocess, "Popen", lambda *a, **k: None)

    assert af.main() == 0
    assert af.STAMP.exists()
