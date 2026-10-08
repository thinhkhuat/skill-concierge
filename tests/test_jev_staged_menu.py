"""The staged Jev menu (ADR-0087): the wide pass's menu is a usable result of its own.

Offline — `_jev_call`, the catalogue and the transcript context are replaced.

Covered:
  • a rerank that fails on every tier keeps the wide menu instead of dropping the turn to the embedding
    menu, while a later tier's full route is still tried first (every harness);
  • ENFORCER_JEV_TIER pins the route to one tier, by jevd provider name or model;
  • wide rows are ordered by lift (probability x chunk size), so a small chunk cannot win by its size.
"""

import importlib.util
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ENFORCER = ROOT / "hooks" / "scripts" / "enforcer.py"
BENCH2 = "ts:jev-1.13.0 gw:openrouter/typesafe/jev-1.13"
GW = "https://gw.example.net/v1/chat/completions"
CATALOG = [("ak-git", "Git operations."), ("tk-research", "Research a topic.")]
WIDE = {"wide::0": {"type": "choice", "probabilities": {"ak-git": 0.3, "tk-research": 0.7}}}
RERANK = {"which": {"type": "choice", "choice": "ak-git", "confidence": 0.8,
                    "probabilities": {"ak-git": 0.8, "tk-research": 0.2}},
          "fits::0": {"type": "noul", "noul": 0.9}, "fits::1": {"type": "noul", "noul": 0.2}}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("ENFORCER_JEV_BENCH", "ENFORCER_JEV_URL", "ENFORCER_JEV_KEY", "ENFORCER_JEV_MODEL", "ENFORCER_JEV_TIMEOUT",
              "ENFORCER_JEV_ROUTER", "ENFORCER_JEV_GATE", "FLYWHEEL_LLM_ENDPOINT", "FLYWHEEL_LLM_API_KEY",
              "TYPESAFE_API_KEY", "CMD_API_KEY", "ENFORCER_JEV_BUDGET", "JEVD_URL", 
              "ENFORCER_JEV_TIER", "ENFORCER_LEDGER"):
        monkeypatch.delenv(k, raising=False)


def _load(tmp_path, monkeypatch, **env):
    env = {"ENFORCER_JEV_BENCH": BENCH2, "FLYWHEEL_LLM_ENDPOINT": GW, "TYPESAFE_API_KEY": "ts-key",
           "FLYWHEEL_LLM_API_KEY": "fw-key", **env}
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("SKILL_CONCIERGE_LOG", str(tmp_path))
    spec = importlib.util.spec_from_file_location(f"enforcer_staged_{abs(hash((str(tmp_path), str(env))))}", ENFORCER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "_jev_catalog", lambda: list(CATALOG))
    monkeypatch.setattr(mod, "_jev_context", lambda path: ("", []))
    return mod


def _calls(mod, monkeypatch, rerank_fails=(), wide=WIDE):
    seen = []

    def fake(state, questions, tier, key, timeout):
        kind = "wide" if any(q.startswith("wide::") for q in questions) else "rerank"
        seen.append((tier["model"], kind))
        if kind == "rerank" and tier["model"] in rerank_fails:
            raise urllib.error.URLError(ConnectionRefusedError())
        return (wide if kind == "wide" else RERANK), tier["ep"], tier["model"]
    monkeypatch.setattr(mod, "_jev_call", fake)
    return seen


def test_a_rerank_failing_on_every_tier_keeps_the_wide_menu(tmp_path, monkeypatch):
    mod = _load(tmp_path, monkeypatch)
    _calls(mod, monkeypatch, rerank_fails={"jev-1.13.0", "openrouter/typesafe/jev-1.13"})
    out = mod._jev_route("commit the work now please", "")
    verdict, rows = out["result"][0], out["result"][1]
    assert verdict == "offer"
    assert [n for n, _d, _p in rows] == ["tk-research", "ak-git"], "the wide pass's own order"
    assert out["event"]["stage"] == "wide"
    assert out["event"]["fell"] == [["jev-1.13.0", "URLError"], ["openrouter/typesafe/jev-1.13", "URLError"]]


def test_a_rerank_failure_still_tries_the_next_tiers_full_route_first(tmp_path, monkeypatch):
    mod = _load(tmp_path, monkeypatch)
    seen = _calls(mod, monkeypatch, rerank_fails={"jev-1.13.0"})
    out = mod._jev_route("commit the work now please", "")
    assert [n for n, _d, _p in out["result"][1]] == ["ak-git", "tk-research"], "the reranked order"
    assert out["event"]["stage"] == "full" and out["event"]["model"] == "openrouter/typesafe/jev-1.13"
    assert [k for _m, k in seen] == ["wide", "rerank", "wide", "rerank"]


def test_a_tier_pin_uses_only_that_tier(tmp_path, monkeypatch):
    mod = _load(tmp_path, monkeypatch, ENFORCER_JEV_TIER="openrouter/typesafe/jev-1.13")
    seen = _calls(mod, monkeypatch)
    mod._jev_route("commit the work now please", "")
    assert {m for m, _k in seen} == {"openrouter/typesafe/jev-1.13"}


def test_wide_rows_are_ordered_by_lift_not_by_raw_chunk_probability(tmp_path, monkeypatch):
    """A 2-option chunk's 0.6 is barely above an even split (lift 1.2); a 4-option chunk's 0.5 is twice it."""
    mod = _load(tmp_path, monkeypatch)
    catalog = [("a1", ""), ("a2", ""), ("a3", ""), ("a4", ""), ("b1", ""), ("b2", "")]
    monkeypatch.setattr(mod, "JEV_CHUNK", 4)
    wide = {"wide::0": {"type": "choice", "probabilities": {"a1": 0.5, "a2": 0.2, "a3": 0.2, "a4": 0.1}},
            "wide::1": {"type": "choice", "probabilities": {"b1": 0.6, "b2": 0.4}}}
    rows = mod._jev_wide_rows(wide, catalog)
    assert [n for n, _d, _p in rows][:2] == ["a1", "b1"]


def test_a_wide_answer_with_a_bad_probability_is_refused_and_the_next_tier_runs(tmp_path, monkeypatch):
    """A NaN must never reach the menu renderer or the ledger (it emptied the whole turn)."""
    mod = _load(tmp_path, monkeypatch)
    bad = {"wide::0": {"type": "choice", "probabilities": {"ak-git": float("nan"), "tk-research": 0.7}}}
    seen = []

    def fake(state, questions, tier, key, timeout):
        kind = "wide" if any(q.startswith("wide::") for q in questions) else "rerank"
        seen.append((tier["model"], kind))
        if kind == "wide":
            return (bad if tier["model"] == "jev-1.13.0" else WIDE), tier["ep"], tier["model"]
        return RERANK, tier["ep"], tier["model"]
    monkeypatch.setattr(mod, "_jev_call", fake)
    out = mod._jev_route("commit the work now please", "")
    assert out["event"]["fell"] == [["jev-1.13.0", "ValueError"]]
    assert out["event"]["stage"] == "full" and out["event"]["model"] == "openrouter/typesafe/jev-1.13"


def test_the_typesafe_pin_also_matches_the_env_bench_tier(tmp_path, monkeypatch):
    """Without jevd the bench comes from ENFORCER_JEV_BENCH, whose tiers carry no jevd name."""
    mod = _load(tmp_path, monkeypatch, ENFORCER_JEV_TIER="typesafe")
    seen = _calls(mod, monkeypatch)
    out = mod._jev_route("commit the work now please", "")
    assert {m for m, _k in seen} == {"jev-1.13.0"} and out["result"][0] == "offer"


def test_the_wide_menu_survives_a_route_that_runs_past_the_join(tmp_path, monkeypatch):
    """The join can give up before the route's own deadline; the wide menu it already has must stand."""
    import threading
    import time as _time
    mod = _load(tmp_path, monkeypatch)
    monkeypatch.setattr(mod, "JEV_BUDGET_S", 0.2)
    release = threading.Event()

    def slow_route(prompt, transcript, sink=None):
        sink["wide"] = {"result": ("offer", [("ak-git", "Git operations.", 1.0)], None, []),
                        "event": {"stage": "wide", "ms": 150}}
        release.wait(2)
        return {"result": None, "event": {"err": "TimeoutError"}}
    monkeypatch.setattr(mod, "_jev_route", slow_route)
    job = mod._jev_start("commit the work now please", "")
    t0 = _time.time()
    out = mod._jev_join(job)
    release.set()
    assert _time.time() - t0 < 1.0
    assert out[0] == "offer" and [n for n, _d, _p in out[1]] == ["ak-git"]
    assert mod._JEV_EVENT["stage"] == "wide" and mod._JEV_EVENT["err"] == "BudgetExceeded"
