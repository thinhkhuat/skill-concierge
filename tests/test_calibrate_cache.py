"""`scripts/calibrate_jev_gate.py` cache and snapshot integrity — offline (Jev, the corpus and the
catalogue are replaced; every path points into tmp_path).

Covered:
  • a keyless `wide` run that has rows left to score exits WITHOUT touching the catalogue snapshot
    (it used to overwrite W24's baseline before checking the key);
  • a run that scores keeps one snapshot file per catalogue hash; only a replay points W24's snapshot
    at it (`wide` scores recall, not the policy W22 relies on);
  • `curve`/`fit`/`rank`/`policy` fail loudly when no cached record matches today's catalogue,
    naming the catalogues the cache does hold, and `--catalog-hash` scores a named one;
  • cached answers are reused only while the live builders ask the same questions (wording,
    description cuts, chunk size); records from before the shape was stored count as LEGACY_SHAPE.
"""

import importlib.util
import json
import os
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import calibrate_jev_gate as C  # noqa: E402

CATALOG = [["a", "first skill"], ["b", "second skill"]]
ROW = {"uuid": "u1", "prompt": "do the thing", "final_names": ["a"], "ts_local": "2026-09-30T10:00:00+07:00"}


def _real_enforcer(tmp_path):
    old = dict(os.environ)
    os.environ["SKILL_CONCIERGE_LOG"] = str(tmp_path)
    try:
        spec = importlib.util.spec_from_file_location("enforcer_cal_cache", ROOT / "hooks" / "scripts" / "enforcer.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        os.environ.clear()
        os.environ.update(old)


@pytest.fixture
def cal(tmp_path, monkeypatch):
    enf = _real_enforcer(tmp_path / "log")
    monkeypatch.setattr(enf, "_jev_catalog", lambda: [tuple(x) for x in CATALOG])
    monkeypatch.setattr(C, "load_enforcer", lambda: enf)
    monkeypatch.setattr(C, "CAL_DIR", tmp_path)
    monkeypatch.setattr(C, "CATALOG_SNAPSHOT", tmp_path / "invocable-catalog.json")
    monkeypatch.setattr(C, "WIDE_CACHE", tmp_path / "wide-scores.jsonl")
    monkeypatch.setattr(C, "CACHE", tmp_path / "suite-scores.jsonl")
    monkeypatch.setattr(C, "load_corpus", lambda path: [])
    monkeypatch.setattr(C, "pick", lambda enf, corpus, n, seed: ([ROW], []))
    return enf


def _args(**kw):
    base = dict(corpus=Path("x"), model="jev-1.13.0", unlabelled=0, seed=1, shelf="wide", variant="ctx",
                jobs=1, timeout=1.0, endpoint="ts", catalog_hash=None, holdout_from="2026-09-01", target=0.03)
    return types.SimpleNamespace(**(base | kw))


def test_keyless_wide_with_rows_to_score_leaves_the_snapshot_alone(cal, tmp_path, monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    C.CATALOG_SNAPSHOT.write_text(json.dumps([["kept", "baseline"]]))
    with pytest.raises(SystemExit):
        C.cmd_wide(_args())
    assert json.loads(C.CATALOG_SNAPSHOT.read_text()) == [["kept", "baseline"]]
    assert not list(tmp_path.glob("catalog-*.json"))


def test_a_scoring_run_keeps_one_snapshot_per_catalogue_hash(cal, tmp_path, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "dummy")
    ans = {"wide::0": {"type": "choice", "probabilities": {"a": 0.9, "b": 0.1}}}
    monkeypatch.setattr(C, "call", lambda *a, **k: (ans, 5, None, None))
    assert C.cmd_wide(_args()) == 0
    h = C.catalog_hash(CATALOG)
    assert json.loads((tmp_path / f"catalog-{h}.json").read_text()) == CATALOG
    assert not C.CATALOG_SNAPSHOT.exists()      # `wide` holds recall only: W24's baseline moves on a replay
    rec = json.loads(C.WIDE_CACHE.read_text().splitlines()[0])
    assert rec["qs"] == C.question_shape(cal)


def _rerank_record(cat, qs=None):
    rec = {"k": f"k-{cat}", "variant": "ctx", "model": "jev-1.13.0", "uuid": "u1", "src": "wide", "cat": cat,
           "shelf": ["a", "b"], "ans": {}}
    return rec | ({"qs": qs} if qs else {})


def test_zero_matching_records_fail_loudly_and_name_the_cached_catalogues(cal):
    C.CACHE.write_text(json.dumps(_rerank_record("f65af73783c60a68")) + "\n")
    with pytest.raises(SystemExit) as e:
        C.scored(cal, _args())
    assert "f65af73783c60a68" in str(e.value) and "--catalog-hash" in str(e.value)


def test_catalog_hash_scores_the_named_catalogue(cal):
    C.CACHE.write_text(json.dumps(_rerank_record("f65af73783c60a68")) + "\n")
    P, U, n_pos, _ = C.scored(cal, _args(catalog_hash="f65af73783c60a68"))
    assert [r["uuid"] for r, _ in P] == ["u1"] and n_pos == 1


def test_answers_are_reused_only_for_the_same_question_shape(cal, monkeypatch):
    shape = C.question_shape(cal)
    assert C.usable({"qs": shape}, shape)
    assert C.usable({}, C.LEGACY_SHAPE) and not C.usable({}, "other")
    monkeypatch.setattr(cal, "JEV_WIDE_DESC", cal.JEV_WIDE_DESC + 40)
    assert C.question_shape(cal) != shape                     # a longer wide cut is a new shape
    monkeypatch.setattr(cal, "JEV_WIDE_DESC", cal.JEV_WIDE_DESC - 40)
    monkeypatch.setattr(cal, "JEV_CHOICE_INSTRUCTIONS", "Pick one.")
    assert C.question_shape(cal) != shape                     # new wording is a new shape
    C.CACHE.write_text(json.dumps(_rerank_record(C.catalog_hash(CATALOG), qs="stale-shape")) + "\n")
    with pytest.raises(SystemExit):                           # stale answers are never scored
        C.scored(cal, _args())
