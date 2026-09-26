"""M5: `delete` must refuse unless the archive's manifest names the collection being
deleted AND the live point count still matches what was exported — otherwise a stale or
mismatched archive could authorize deleting the wrong (or since-changed) collection.

No real Qdrant: `_req` is monkeypatched to a fake in-memory HTTP layer throughout.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import archive_qdrant_collection as A  # noqa: E402


def _make_archive(dest: Path, collection: str = "claude_skills", n: int = 3) -> dict:
    dest.mkdir(parents=True, exist_ok=True)
    points_path = dest / "points.jsonl"
    with points_path.open("w") as f:
        for i in range(n):
            f.write(json.dumps({"id": str(i), "vector": [0.1, 0.2], "payload": {"k": i}}) + "\n")
    snap_path = dest / "snap.snapshot"
    snap_path.write_bytes(b"fake-snapshot-bytes")
    manifest = {
        "collection": collection,
        "source": A.DEFAULT_URL,
        "collection_info": {"config": {"params": {"vectors": {"size": 2}}}},
        "points_file": points_path.name,
        "points_exported": n,
        "points_sha256": A._sha256(points_path),
        "snapshot_file": snap_path.name,
        "snapshot_size": snap_path.stat().st_size,
        "snapshot_sha256": A._sha256(snap_path),
        "snapshot_server_checksum": A._sha256(snap_path),
    }
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def test_verify_passes_on_well_formed_archive(tmp_path):
    _make_archive(tmp_path, n=3)
    assert A.verify(tmp_path, 3) == 0


def test_verify_fails_on_count_mismatch(tmp_path, capsys):
    _make_archive(tmp_path, n=3)
    assert A.verify(tmp_path, 5) != 0
    assert "expected 5" in capsys.readouterr().err


def test_delete_refuses_on_collection_mismatch(tmp_path, monkeypatch, capsys):
    _make_archive(tmp_path, collection="claude_skills", n=3)

    def _boom(*a, **k):
        raise AssertionError("_req must never be called when the manifest collection mismatches")

    monkeypatch.setattr(A, "_req", _boom)
    rc = A.delete(A.DEFAULT_URL, "some_other_collection", tmp_path, 3)
    assert rc == 1
    assert "not 'some_other_collection'" in capsys.readouterr().err


def test_delete_refuses_on_live_count_mismatch(tmp_path, monkeypatch, capsys):
    _make_archive(tmp_path, collection="claude_skills", n=3)
    calls = []

    def _fake_req(url, method="GET", body=None, timeout=120):
        calls.append((url, method))
        if method == "DELETE":
            raise AssertionError("must never DELETE when live count mismatches")
        return {"result": {"points_count": 999}}

    monkeypatch.setattr(A, "_req", _fake_req)
    rc = A.delete(A.DEFAULT_URL, "claude_skills", tmp_path, 3)
    assert rc == 1
    err = capsys.readouterr().err
    assert "live points_count=999" in err
    assert "points_exported=3" in err
    assert not any(m == "DELETE" for _, m in calls)


def test_delete_succeeds_when_manifest_and_live_count_match(tmp_path, monkeypatch):
    _make_archive(tmp_path, collection="claude_skills", n=3)
    calls = []

    def _fake_req(url, method="GET", body=None, timeout=120):
        calls.append((url, method))
        if method == "DELETE":
            return {"result": True}
        return {"result": {"points_count": 3}}

    monkeypatch.setattr(A, "_req", _fake_req)
    rc = A.delete(A.DEFAULT_URL, "claude_skills", tmp_path, 3)
    assert rc == 0
    assert calls[-1][1] == "DELETE"


def test_delete_refuses_when_archive_verification_fails(tmp_path, monkeypatch):
    manifest = _make_archive(tmp_path, collection="claude_skills", n=3)
    # Corrupt the points file after the manifest was written (still valid JSONL, but its
    # sha256 no longer matches the manifest), so verify() fails cleanly.
    (tmp_path / manifest["points_file"]).write_text(
        json.dumps({"id": "0", "vector": [0.9, 0.9], "payload": {"k": "tampered"}}) + "\n"
    )

    def _boom(*a, **k):
        raise AssertionError("_req must never be called when verify() already failed")

    monkeypatch.setattr(A, "_req", _boom)
    assert A.delete(A.DEFAULT_URL, "claude_skills", tmp_path, 3) == 1


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
