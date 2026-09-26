"""ADR-0061 Jev skill router — pinned offline (no network: catalogue, Jev, embed and retrieval
are replaced; main() runs in-process on a stdin fake, exactly as the hook does).

Covered:
  • the offer is the rerank Choice's top 5, in its order (never collapsed to one row, even when
    the Choice is confident — measured: that lowered recall);
  • no candidate's `fits` reaches the floor -> authorized skip, locked "Jev needs-a-skill gate"
    signature, band `jev_skip`;
  • a non-English prompt, no TYPESAFE_API_KEY, ENFORCER_JEV_ROUTER=0 (or the ADR-0060
    ENFORCER_JEV_GATE=0 alias) and a named route never call Jev;
  • any Jev failure or a blown budget -> the embedding path decides, error recorded;
  • embed down -> a Jev verdict still serves the turn;
  • the conversation context comes from the transcript tail;
  • the warm relay falls back to a direct call only when the shim lacks the route or is not
    listening — never after a timeout.
The live calls are exercised by the deploy-time end-to-end check (real key, real API).
"""

import importlib.util
import io
import json
import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ENFORCER = ROOT / "hooks" / "scripts" / "enforcer.py"
PROMPT = "please back up settings.json and wire up the new local model"
CATALOG = [("update-config", "Configure the Claude Code harness via settings.json."),
           ("ak-git", "Git operations with conventional commits."),
           ("session-handoff", "Structured end-of-session summary."),
           ("tk-research", "Research a topic into a briefing.")]


def _load(tmp_path, **env):
    old = dict(os.environ)
    os.environ.update({"SKILL_CONCIERGE_LOG": str(tmp_path), **env})
    try:
        spec = importlib.util.spec_from_file_location(f"enforcer_router_{abs(hash((str(tmp_path), str(env))))}", ENFORCER)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        os.environ.clear()
        os.environ.update(old)


def _rerank(conf, fits, probs):
    ans = {"which": {"type": "choice", "choice": max(probs, key=probs.get), "confidence": conf,
                     "probabilities": probs}}
    ans.update({f"fits::{i}": {"type": "noul", "noul": f} for i, f in enumerate(fits)})
    return ans


def _wide(names):
    return {"wide::0": {"type": "choice", "confidence": 0.5,
                        "probabilities": {n: round(1 / (i + 2), 3) for i, n in enumerate(names)}}}


def _run(mod, monkeypatch, prompt=PROMPT, rerank=None, jev_error=None, key="test-key",
         embed_error=None, transcript=""):
    """main() on a fake stdin -> (stdout, jev calls, embed reached, ledger rows)."""
    calls, reached = [], {"embed": False}

    def fake_call(state, questions, k):
        calls.append((state, sorted(questions)))
        if jev_error:
            raise jev_error
        if any(q.startswith("wide::") for q in questions):
            return _wide([n for n, _ in CATALOG]), "relay"
        return rerank, "relay"

    def fake_embed(_text):
        reached["embed"] = True
        if embed_error:
            raise embed_error
        return [0.0] * 768

    if key is None:
        monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    else:
        monkeypatch.setenv("TYPESAFE_API_KEY", key)
    monkeypatch.setattr(mod, "_jev_catalog", lambda: list(CATALOG))
    monkeypatch.setattr(mod, "_jev_call", fake_call)
    monkeypatch.setattr(mod, "_embed", fake_embed)
    monkeypatch.setattr(mod, "_retrieve", lambda v: [("tk-research", "Research a topic into a briefing.", 0.62),
                                                     ("ak-git", "Git operations.", 0.55)])
    monkeypatch.setattr(mod, "_retrieve_external", lambda v, top=0.0: [])
    monkeypatch.setattr(mod, "_retrieve_foreign", lambda v, top, names: [])
    monkeypatch.setattr(mod, "_intent_conversational", lambda v: False)
    monkeypatch.setattr(mod, "_route_hits", lambda p, keepoff=frozenset(): [])
    payload = {"prompt": prompt, "session_id": "t", "transcript_path": transcript}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    mod.main()
    rows = [json.loads(ln) for ln in mod.LEDGER.read_text(encoding="utf-8").splitlines()] \
        if mod.LEDGER.exists() else []
    return out.getvalue(), calls, reached["embed"], rows


CONFIDENT = _rerank(0.93, [0.9, 0.2, 0.1, 0.1], {"update-config": 0.93, "ak-git": 0.04,
                                                  "session-handoff": 0.02, "tk-research": 0.01})
SPREAD = _rerank(0.40, [0.6, 0.5, 0.4, 0.1], {"update-config": 0.30, "ak-git": 0.45,
                                               "session-handoff": 0.20, "tk-research": 0.05})
NO_FIT = _rerank(0.30, [0.10, 0.12, 0.05, 0.02], {"update-config": 0.4, "ak-git": 0.3,
                                                  "session-handoff": 0.2, "tk-research": 0.1})


def test_confident_choice_still_offers_the_ranked_rows(tmp_path, monkeypatch):
    mod = _load(tmp_path)
    out, calls, _, rows = _run(mod, monkeypatch, rerank=CONFIDENT)
    assert len(calls) == 2                                  # wide, then rerank
    assert [r[0] for r in rows[-1]["offered"]] == ["update-config", "ak-git", "session-handoff", "tk-research"]
    assert rows[-1]["band"] == "offer" and out.index("update-config") < out.index("ak-git")
    assert rows[-1]["jev"]["lead"] == "update-config" and rows[-1]["jev"]["via"] == "relay"


def test_offer_is_capped_and_in_choice_order(tmp_path, monkeypatch):
    mod = _load(tmp_path)
    monkeypatch.setattr(mod, "JEV_OFFER_ROWS", 3)
    out, _, _, rows = _run(mod, monkeypatch, rerank=SPREAD)
    assert [r[0] for r in rows[-1]["offered"]] == ["ak-git", "update-config", "session-handoff"]
    assert out.index("ak-git") < out.index("update-config") < out.index("session-handoff")
    assert "tk-research" not in out


def test_no_fitting_candidate_takes_the_authorized_skip(tmp_path, monkeypatch):
    mod = _load(tmp_path)
    out, _, _, rows = _run(mod, monkeypatch, rerank=NO_FIT)
    assert "SKILL-CHECK:" in out and "Jev needs-a-skill gate" in out and "0.12 < 0.30" in out
    assert rows[-1]["band"] == "jev_skip" and rows[-1]["jev"]["fit"] == 0.12
    assert rows[-1]["offered"]                              # what retrieval would have shown


@pytest.mark.parametrize("prompt", ["làm ơn sao lưu settings.json rồi cấu hình model mới",
                                    "请帮我备份设置文件然后配置新的模型"])
def test_non_english_prompt_never_calls_jev(tmp_path, monkeypatch, prompt):
    mod = _load(tmp_path)
    _, calls, embed, rows = _run(mod, monkeypatch, prompt=prompt, rerank=CONFIDENT)
    assert not calls and embed and "jev" not in rows[-1]


def test_no_key_kill_switch_and_alias_make_no_call(tmp_path, monkeypatch):
    for sub, env, key in (("nokey", {}, None), ("off", {"ENFORCER_JEV_ROUTER": "0"}, "k"),
                          ("alias", {"ENFORCER_JEV_GATE": "0"}, "k")):
        mod = _load(tmp_path / sub, **env)
        _, calls, embed, rows = _run(mod, monkeypatch, rerank=CONFIDENT, key=key)
        assert not calls and embed and "jev" not in rows[-1], sub


def test_named_route_never_asks_jev(tmp_path, monkeypatch):
    mod = _load(tmp_path)
    started = []
    monkeypatch.setattr(mod, "_jev_start", lambda *a: started.append(a))
    orig = mod.main

    def main_with_route():
        mod._route_hits = lambda p, keepoff=frozenset(): [("tk-research", "desc", 1.0)]
        return orig()
    monkeypatch.setattr(mod, "main", main_with_route)
    _run(mod, monkeypatch, rerank=CONFIDENT)
    assert not started


def test_jev_failure_leaves_the_embedding_path_to_decide(tmp_path, monkeypatch):
    for err in (TimeoutError("slow"), OSError("refused"), KeyError("answers")):
        mod = _load(tmp_path / type(err).__name__)
        out, calls, embed, rows = _run(mod, monkeypatch, jev_error=err)
        assert calls and embed
        assert "Jev needs-a-skill gate" not in out and "tk-research" in out    # retrieval's menu
        assert rows[-1]["band"] == "offer" and rows[-1]["jev"]["err"] == type(err).__name__
        assert rows[-1]["jev"]["leg"] == "router"   # tells it from the v0.50.0 leg's unmarked {err, ms}


def test_malformed_rerank_answer_falls_back(tmp_path, monkeypatch):
    for bad in (_rerank(1.7, [0.9, 0.1, 0.1, 0.1], {"update-config": 1.0}),          # out of range
                _rerank(0.9, [0.9, 0.1, 0.1, 0.1], {"not-in-shortlist": 1.0})):      # names nothing offered
        mod = _load(tmp_path / str(abs(hash(json.dumps(bad)))))
        _, _, embed, rows = _run(mod, monkeypatch, rerank=bad)
        assert embed and rows[-1]["jev"]["err"] == "ValueError"


def test_blown_budget_is_abandoned(tmp_path, monkeypatch):
    mod = _load(tmp_path, ENFORCER_JEV_BUDGET="0.05")
    monkeypatch.setattr(mod, "_jev_route", lambda p, t: (time.sleep(0.5), {"result": ("offer", [], 0.9)})[1])
    out, _, embed, rows = _run(mod, monkeypatch, rerank=CONFIDENT)
    assert embed and rows[-1]["jev"]["err"] == "BudgetExceeded" and "tk-research" in out
    assert rows[-1]["jev"]["leg"] == "router"


def test_embed_down_still_served_by_jev(tmp_path, monkeypatch):
    mod = _load(tmp_path)
    out, _, _, rows = _run(mod, monkeypatch, rerank=CONFIDENT, embed_error=OSError("shim down"))
    assert "update-config" in out and rows[-1]["band"] == "offer"
    assert rows[-1]["offered"][0][0] == "update-config"


def test_context_comes_from_the_transcript_tail(tmp_path, monkeypatch):
    tr = tmp_path / "t.jsonl"
    recs = [{"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Skill", "input": {"skill": "ak:git"}},
                {"type": "text", "text": "Staged three files. Commit them now?"}]}},
            {"type": "assistant", "isSidechain": True, "message": {"content": [
                {"type": "text", "text": "subagent chatter must not leak in"}]}},
            {"type": "user", "message": {"content": "Base directory for this skill: /x/skills/session-handoff\n"}}]
    tr.write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    mod = _load(tmp_path / "m")
    _, calls, _, _ = _run(mod, monkeypatch, rerank=CONFIDENT, transcript=str(tr))
    state = calls[0][0]
    assert state["recent_context"] == "Staged three files. Commit them now?"
    assert state["skills_already_loaded_this_session"] == ["ak-git", "session-handoff"]
    assert mod._jev_context(str(tmp_path / "missing.jsonl")) == ("", [])


def test_relay_falls_back_to_direct_only_when_the_route_is_missing(tmp_path, monkeypatch):
    mod = _load(tmp_path)
    seen = []

    def post(url, body, timeout, headers=None):
        seen.append(url)
        if url == mod.JEV_RELAY_URL:
            raise failure
        return {"answers": {"ok": True}}
    monkeypatch.setattr(mod, "_post_json", post)
    for failure, direct in ((mod.urllib.error.HTTPError(mod.JEV_RELAY_URL, 404, "nf", {}, None), True),
                            (mod.urllib.error.URLError(ConnectionRefusedError()), True),
                            (TimeoutError("slow"), False),
                            (mod.urllib.error.HTTPError(mod.JEV_RELAY_URL, 401, "auth", {}, None), False)):
        seen.clear()
        if direct:
            assert mod._jev_call({}, {}, "k") == ({"ok": True}, "direct")
            assert seen == [mod.JEV_RELAY_URL, mod.JEV_URL]
        else:
            with pytest.raises(type(failure)):
                mod._jev_call({}, {}, "k")
            assert seen == [mod.JEV_RELAY_URL]


def test_non_finite_probability_falls_back(tmp_path, monkeypatch):
    for bad in (_rerank(0.9, [float("nan"), 0.5, 0.1, 0.1], {"update-config": 0.9}),
                _rerank(0.9, [0.9, 0.5, 0.1, 0.1], {"update-config": float("inf"), "ak-git": 0.1})):
        mod = _load(tmp_path / str(abs(hash(repr(bad)))))
        out, _, embed, rows = _run(mod, monkeypatch, rerank=bad)
        assert embed and rows[-1]["jev"]["err"] == "ValueError" and "tk-research" in out


def test_unexpected_error_in_the_worker_is_contained(tmp_path, monkeypatch):
    mod = _load(tmp_path)

    def broken(_path):
        raise AttributeError("'NoneType' object has no attribute 'get'")
    monkeypatch.setattr(mod, "_jev_context", broken)
    out, _, embed, rows = _run(mod, monkeypatch, rerank=CONFIDENT)
    assert embed and "tk-research" in out and rows[-1]["jev"]["err"] == "AttributeError"
    assert rows[-1]["jev"]["leg"] == "router"   # the thread-boundary error path


def test_outage_served_by_jev_stays_visible_in_the_ledger(tmp_path, monkeypatch):
    mod = _load(tmp_path)
    _, _, _, rows = _run(mod, monkeypatch, rerank=CONFIDENT, embed_error=OSError("shim down"))
    assert rows[-1]["fallback"] == "embed_down" and rows[-1]["jev"]["outage"] == "embed_down"


def test_relay_is_loopback_only(tmp_path):
    assert _load(tmp_path / "lo").JEV_RELAY_URL.startswith("http://127.0.0.1:")
    remote = _load(tmp_path / "remote", EMBED_SHIM_HOST="10.0.0.5")
    assert remote.JEV_RELAY_URL is None


def test_budget_cannot_exceed_the_ceiling(tmp_path):
    assert _load(tmp_path, ENFORCER_JEV_BUDGET="9").JEV_BUDGET_S == 3.0


def test_is_english_matches_the_calibration_rule(tmp_path):
    mod = _load(tmp_path)
    assert mod._is_english("commit now pls, and café is fine")          # one accented letter
    assert not mod._is_english("viết báo cáo")
    assert not mod._is_english("请帮我")
