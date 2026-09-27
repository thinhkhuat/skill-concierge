"""doctor.py's Findability row (ADR-0074) — read-only over a crafted findability.json.

This check must NEVER sweep, NEVER talk to the owner, and NEVER crash on a broken file: it
only reads whatever `python -m skill_search.findability --sweep` last wrote.
"""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def dr():
    return _load("doctor_findability_t", ROOT / "scripts" / "doctor.py")


def test_registered_in_checks(dr):
    assert any(getattr(fn, "__name__", "") == "check_findability" for fn in dr.CHECKS)


def test_not_yet_swept_is_ok_not_warn(dr, tmp_path, monkeypatch):
    """Design: "not yet swept" (no file at all — a fresh install, or nothing has changed
    the index since) is the healthy OK state, never a WARN."""
    monkeypatch.setenv("SKILL_FINDABILITY_PATH", str(tmp_path / "findability.json"))
    row = dr.check_findability()
    assert row["status"] == dr.OK
    assert "not yet swept" in row["detail"]
    assert row["fix"] is None


def test_ok_with_backlog_and_no_warnings(dr, tmp_path, monkeypatch):
    path = tmp_path / "findability.json"
    path.write_text(json.dumps({"version": 1, "swept_at": 1758960000.0, "harness": "claude",
                                "skills": {}, "warnings": [], "backlog": 4}), encoding="utf-8")
    monkeypatch.setenv("SKILL_FINDABILITY_PATH", str(path))
    row = dr.check_findability()
    assert row["status"] == dr.OK
    assert "backlog 4" in row["detail"]


def test_warn_lists_the_warnings(dr, tmp_path, monkeypatch):
    path = tmp_path / "findability.json"
    path.write_text(json.dumps({"version": 1, "swept_at": 1758960000.0, "harness": "claude",
                                "skills": {}, "warnings": ["a fell out", "b fell out"],
                                "backlog": 2}), encoding="utf-8")
    monkeypatch.setenv("SKILL_FINDABILITY_PATH", str(path))
    row = dr.check_findability()
    assert row["status"] == dr.WARN
    assert "a fell out" in row["detail"] and "b fell out" in row["detail"]
    assert "2 warning" in row["detail"]


def test_warn_truncates_a_long_warning_list(dr, tmp_path, monkeypatch):
    path = tmp_path / "findability.json"
    warnings = [f"skill{i} fell out" for i in range(8)]
    path.write_text(json.dumps({"swept_at": 1.0, "warnings": warnings, "backlog": 8}),
                    encoding="utf-8")
    monkeypatch.setenv("SKILL_FINDABILITY_PATH", str(path))
    row = dr.check_findability()
    assert row["status"] == dr.WARN
    assert "+3 more" in row["detail"]


def test_malformed_json_is_warn_not_fail(dr, tmp_path, monkeypatch):
    path = tmp_path / "findability.json"
    path.write_text("{ not valid json", encoding="utf-8")
    monkeypatch.setenv("SKILL_FINDABILITY_PATH", str(path))
    row = dr.check_findability()
    assert row["status"] == dr.WARN
    assert "malformed" in row["detail"]


def test_unexpected_shape_is_warn_not_a_crash(dr, tmp_path, monkeypatch):
    path = tmp_path / "findability.json"
    path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")     # a list, not an object
    monkeypatch.setenv("SKILL_FINDABILITY_PATH", str(path))
    row = dr.check_findability()
    assert row["status"] == dr.WARN


def test_default_path_is_the_durable_home(dr, monkeypatch):
    monkeypatch.delenv("SKILL_FINDABILITY_PATH", raising=False)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: Path("/tmp/no-such-home-findability")))
    row = dr.check_findability()
    assert row["status"] == dr.OK and "not yet swept" in row["detail"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))


@pytest.mark.parametrize("fields", [
    {"warnings": {"x": 1}},            # a dict where a list belongs: slicing it used to raise
    {"warnings": "one warning"},
    {"swept_at": "yesterday"},         # time.localtime() raised on a string
    {"swept_at": True},
    {"backlog": "many"},
    {"backlog": None},
])
def test_malformed_nested_field_warns_instead_of_crashing(dr, tmp_path, monkeypatch, fields):
    doc = {"version": 1, "swept_at": 1758960000.0, "harness": "claude", "skills": {},
           "warnings": [], "backlog": 1}
    doc.update(fields)
    path = tmp_path / "findability.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    monkeypatch.setenv("SKILL_FINDABILITY_PATH", str(path))
    row = dr.check_findability()
    assert row["status"] == dr.WARN
    assert "unexpected shape" in row["detail"]


def test_a_crashing_check_becomes_a_fail_row_and_the_rest_still_run(dr, monkeypatch):
    def check_boom():
        raise KeyError("nested")

    def check_fine():
        return {"id": "fine", "label": "Fine", "status": dr.OK, "detail": "ok", "fix": None}

    monkeypatch.setattr(dr, "CHECKS", [check_boom, check_fine])
    monkeypatch.setattr(dr, "CUTOVER", False)
    rows = dr.run_all()
    assert [r["id"] for r in rows] == ["boom", "fine"]
    assert rows[0]["status"] == dr.FAIL
    assert "KeyError" in rows[0]["detail"]
    assert dr.overall(rows) == dr.FAIL
