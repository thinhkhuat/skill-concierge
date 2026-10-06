"""The Jev bench (ADR-0075, ADR-0079): an ordered list of SystemOne tiers tried in turn within one hook turn.
Offline — `_jev_call`, the catalogue and the transcript context are replaced.

Covered:
  • ENFORCER_JEV_BENCH parsing: `ts:<model>` = TypeSafe (ENFORCER_JEV_URL, TYPESAFE_API_KEY, the warm
    relay), `gw:<model>` = the owner's gateway named by FLYWHEEL_LLM_ENDPOINT (/v1/systemone, its own key
    and timeout), `cc:<model>` = Command Code (CMD_API_KEY, always direct, a timeout that is also its
    turn span); unset = TypeSafe alone, exactly as before; malformed entries are dropped;
  • any failure (HTTP error, model mismatch, refused host, malformed answer, timeout) moves the turn to the
    next tier, and the event names the tier that answered and the ones that fell;
  • a tier with a span spends at most that much of the turn, so TypeSafe behind it still fits the budget;
  • a tier without a key is skipped; a tier that cannot fit the remaining budget is not started, and a
    later tier that still fits is.
"""

import importlib.util
import os
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ENFORCER = ROOT / "hooks" / "scripts" / "enforcer.py"
GW = "https://gw.example.net/v1/chat/completions"
BENCH4 = "ts:jev-1.13.0 gw:openrouter/typesafe/jev-1.13 gw:oc/jev-1.13-free gw:ocz/jev-1.13-free"
CATALOG = [("ak-git", "Git operations."), ("tk-research", "Research a topic.")]
WIDE = {"wide::0": {"type": "choice", "probabilities": {"ak-git": 0.8, "tk-research": 0.2}}}
RERANK = {"which": {"type": "choice", "choice": "ak-git", "confidence": 0.8,
                    "probabilities": {"ak-git": 0.8, "tk-research": 0.2}},
          "fits::0": {"type": "noul", "noul": 0.9}, "fits::1": {"type": "noul", "noul": 0.2}}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("ENFORCER_JEV_BENCH", "ENFORCER_JEV_URL", "ENFORCER_JEV_KEY", "ENFORCER_JEV_MODEL",
              "ENFORCER_JEV_TIMEOUT", "ENFORCER_JEV_GATEWAY_TIMEOUT", "ENFORCER_JEV_ROUTER", "ENFORCER_JEV_GATE",
              "FLYWHEEL_LLM_ENDPOINT", "FLYWHEEL_LLM_API_KEY", "TYPESAFE_API_KEY", "CMD_API_KEY",
              "ENFORCER_JEV_CC_URL", "ENFORCER_JEV_CC_TIMEOUT", "ENFORCER_JEV_BUDGET", "JEVD_URL"):
        monkeypatch.delenv(k, raising=False)


def _load(tmp_path, monkeypatch, **env):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("SKILL_CONCIERGE_LOG", str(tmp_path))
    spec = importlib.util.spec_from_file_location(f"enforcer_bench_{abs(hash((str(tmp_path), str(env))))}", ENFORCER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "_jev_catalog", lambda: list(CATALOG))
    monkeypatch.setattr(mod, "_jev_context", lambda path: ("", []))
    return mod


def _calls(mod, monkeypatch, behaviour):
    """behaviour: {model: exception or None}. Records (model, via-relay?) per call."""
    seen = []

    def fake(state, questions, tier, key, timeout):
        seen.append((tier["model"], key, timeout))
        err = behaviour.get(tier["model"])
        if err:
            raise err
        return (WIDE if any(q.startswith("wide::") for q in questions) else RERANK), tier["ep"], "returned-" + tier["model"]
    monkeypatch.setattr(mod, "_jev_call", fake)
    return seen


def test_unset_bench_is_typesafe_alone(tmp_path, monkeypatch):
    mod = _load(tmp_path, monkeypatch)
    assert [(t["ep"], t["model"], t["timeout"]) for t in mod._jev_bench()] == [("ts", "jev-1.13.0", 1.5)]


def test_bench_parses_tiers_in_order(tmp_path, monkeypatch):
    mod = _load(tmp_path, monkeypatch, ENFORCER_JEV_BENCH=BENCH4 + " bogus gw: zz:m", FLYWHEEL_LLM_ENDPOINT=GW)
    tiers = mod._jev_bench()
    assert [t["model"] for t in tiers] == ["jev-1.13.0", "openrouter/typesafe/jev-1.13",
                                           "oc/jev-1.13-free", "ocz/jev-1.13-free"]
    assert tiers[0]["url"] == mod.JEV_URL and tiers[0]["timeout"] == 1.5
    assert {t["url"] for t in tiers[1:]} == {"https://gw.example.net/v1/systemone"}
    assert {t["timeout"] for t in tiers[1:]} == {2.0}


def test_a_gateway_tier_without_a_gateway_is_dropped(tmp_path, monkeypatch):
    mod = _load(tmp_path, monkeypatch, ENFORCER_JEV_BENCH=BENCH4)       # no FLYWHEEL_LLM_ENDPOINT
    assert [t["ep"] for t in mod._jev_bench()] == ["ts"]


def test_keys_are_per_endpoint(tmp_path, monkeypatch):
    mod = _load(tmp_path, monkeypatch, ENFORCER_JEV_BENCH=BENCH4, FLYWHEEL_LLM_ENDPOINT=GW,
                TYPESAFE_API_KEY="ts-key", FLYWHEEL_LLM_API_KEY="fw-key")
    ts, gw = mod._jev_bench()[:2]
    assert mod._jev_key(ts) == "ts-key" and mod._jev_key(gw) == "fw-key"
    monkeypatch.setenv("ENFORCER_JEV_KEY", "gw-key")
    assert mod._jev_key(gw) == "gw-key" and mod._jev_key(ts) == "ts-key"


def _bench(tmp_path, monkeypatch):
    return _load(tmp_path, monkeypatch, ENFORCER_JEV_BENCH=BENCH4, FLYWHEEL_LLM_ENDPOINT=GW,
                 TYPESAFE_API_KEY="ts-key", FLYWHEEL_LLM_API_KEY="fw-key")


@pytest.mark.parametrize("fast", [
    urllib.error.HTTPError("u", 503, "busy", {}, None),
    urllib.error.URLError(ConnectionRefusedError()),
    ValueError("ENFORCER_JEV_URL must be https"),
])
def test_a_fast_failure_moves_the_turn_to_the_next_tier(tmp_path, monkeypatch, fast):
    mod = _bench(tmp_path, monkeypatch)
    seen = _calls(mod, monkeypatch, {"jev-1.13.0": fast})
    out = mod._jev_route("commit the work now please", "")
    assert out["result"][0] == "offer"
    ev = out["event"]
    assert ev["model"] == "openrouter/typesafe/jev-1.13" and ev["tier"] == 1
    assert ev["rmodel"] == "returned-openrouter/typesafe/jev-1.13"
    assert ev["fell"] == [["jev-1.13.0", type(fast).__name__]] and ev["to"] == 2.0
    assert [m for m, _, _ in seen] == ["jev-1.13.0", "openrouter/typesafe/jev-1.13", "openrouter/typesafe/jev-1.13"]
    assert seen[0][1] == "ts-key" and seen[1][1] == "fw-key"


def test_a_model_mismatch_falls_through_too(tmp_path, monkeypatch):
    mod = _bench(tmp_path, monkeypatch)
    _calls(mod, monkeypatch, {"jev-1.13.0": mod.JevModelMismatch("x"),
                              "openrouter/typesafe/jev-1.13": urllib.error.HTTPError("u", 429, "rate", {}, None)})
    ev = mod._jev_route("commit the work now please", "")["event"]
    assert ev["model"] == "oc/jev-1.13-free" and ev["tier"] == 2
    assert ev["fell"] == [["jev-1.13.0", "JevModelMismatch"], ["openrouter/typesafe/jev-1.13", "HTTPError"]]


@pytest.mark.parametrize("slow", [TimeoutError("timed out"), urllib.error.URLError(TimeoutError("timed out"))])
def test_a_timeout_falls_through_to_the_next_tier(tmp_path, monkeypatch, slow):
    mod = _bench(tmp_path, monkeypatch)
    seen = _calls(mod, monkeypatch, {"jev-1.13.0": slow})
    out = mod._jev_route("commit the work now please", "")
    assert out["result"][0] == "offer" and out["event"]["tier"] == 1
    assert out["event"]["fell"] == [["jev-1.13.0", type(slow).__name__]]
    assert [m for m, _, _ in seen][:2] == ["jev-1.13.0", "openrouter/typesafe/jev-1.13"]


def test_every_tier_failing_is_one_router_error(tmp_path, monkeypatch):
    mod = _bench(tmp_path, monkeypatch)
    bad = urllib.error.HTTPError("u", 500, "x", {}, None)
    _calls(mod, monkeypatch, {m: bad for m in ("jev-1.13.0", "openrouter/typesafe/jev-1.13",
                                               "oc/jev-1.13-free", "ocz/jev-1.13-free")})
    out = mod._jev_route("commit the work now please", "")
    assert out["result"] is None and out["event"]["err"] == "HTTPError" and len(out["event"]["fell"]) == 4


def test_a_tier_without_a_key_is_skipped(tmp_path, monkeypatch):
    mod = _load(tmp_path, monkeypatch, ENFORCER_JEV_BENCH=BENCH4, FLYWHEEL_LLM_ENDPOINT=GW,
                FLYWHEEL_LLM_API_KEY="fw-key")                         # no TYPESAFE_API_KEY
    _calls(mod, monkeypatch, {})
    ev = mod._jev_route("commit the work now please", "")["event"]
    assert ev["tier"] == 1 and ev["fell"] == [["jev-1.13.0", "NoKey"]]


def test_a_tier_that_cannot_fit_the_budget_is_not_started(tmp_path, monkeypatch):
    mod = _bench(tmp_path, monkeypatch)
    monkeypatch.setattr(mod, "JEV_BUDGET_S", 2.5)                      # after a 1 s failure, 1.5 s is left
    clock = {"t": 1000.0}
    monkeypatch.setattr(mod.time, "time", lambda: clock["t"])

    def fake(state, questions, tier, key, timeout):
        clock["t"] += 1.0
        raise urllib.error.HTTPError("u", 503, "busy", {}, None)
    monkeypatch.setattr(mod, "_jev_call", fake)
    out = mod._jev_route("commit the work now please", "")
    assert out["result"] is None
    assert out["event"]["fell"] == [["jev-1.13.0", "HTTPError"], ["openrouter/typesafe/jev-1.13", "NoTime"],
                                    ["oc/jev-1.13-free", "NoTime"], ["ocz/jev-1.13-free", "NoTime"]]


def test_a_tier_that_does_not_fit_does_not_stop_a_later_one_that_does(tmp_path, monkeypatch):
    mod = _load(tmp_path, monkeypatch, ENFORCER_JEV_BENCH="cc:typesafe/jev ts:jev-1.13.0",
                ENFORCER_JEV_BUDGET="1.6", CMD_API_KEY="cc-key", TYPESAFE_API_KEY="ts-key")
    seen = _calls(mod, monkeypatch, {})
    ev = mod._jev_route("commit the work now please", "")["event"]
    assert ev["model"] == "jev-1.13.0" and ev["fell"] == [["typesafe/jev", "NoTime"]]
    assert {m for m, _, _ in seen} == {"jev-1.13.0"}


def test_only_the_typesafe_tier_uses_the_relay(tmp_path, monkeypatch):
    mod = _bench(tmp_path, monkeypatch)
    urls = []
    monkeypatch.setattr(mod, "_post_json", lambda u, b, t, h=None: urls.append((u, b["model"])) or
                        {"answers": {"ok": 1}})
    ts, gw = mod._jev_bench()[:2]
    assert mod._jev_call({}, {}, ts, "k", 1.0)[:2] == ({"ok": 1}, "relay")
    assert mod._jev_call({}, {}, gw, "k", 1.0)[:2] == ({"ok": 1}, "direct")
    assert urls == [(mod.JEV_RELAY_URL, "jev-1.13.0"),
                    ("https://gw.example.net/v1/systemone", "openrouter/typesafe/jev-1.13")]


CC_BENCH = "cc:typesafe/jev ts:jev-1.13.0 gw:openrouter/typesafe/jev-1.13"


def _cc(tmp_path, monkeypatch, **env):
    return _load(tmp_path, monkeypatch, ENFORCER_JEV_BENCH=CC_BENCH, FLYWHEEL_LLM_ENDPOINT=GW,
                 CMD_API_KEY="cc-key", TYPESAFE_API_KEY="ts-key", FLYWHEEL_LLM_API_KEY="fw-key", **env)


def test_command_code_tier_parses_with_its_own_url_key_and_span(tmp_path, monkeypatch):
    mod = _cc(tmp_path, monkeypatch)
    cc, ts, gw = mod._jev_bench()
    assert (cc["ep"], cc["model"], cc["url"]) == ("cc", "typesafe/jev",
                                                 "https://api.commandcode.ai/provider/v1/systemone")
    assert cc["timeout"] == cc["span"] == 5.5 and "span" not in ts and "span" not in gw
    assert [mod._jev_key(t) for t in (cc, ts, gw)] == ["cc-key", "ts-key", "fw-key"]
    assert _cc(tmp_path, monkeypatch, ENFORCER_JEV_CC_TIMEOUT="2.5")._jev_bench()[0]["span"] == 2.5


def test_command_code_is_called_direct_with_a_user_agent(tmp_path, monkeypatch):
    mod = _cc(tmp_path, monkeypatch)
    monkeypatch.setattr(mod, "JEV_CC_RELAY_URL", None)   # the direct path; the owner's /jev/cc relay (ADR-0081) has
                                                         # its own tests in test_owner_jev_relay.py
    sent = []
    monkeypatch.setattr(mod, "_post_json", lambda u, b, t, h=None: sent.append((u, b["model"], h)) or
                        {"answers": {"ok": 1}, "model": "typesafe/jev"})
    assert mod._jev_call({}, {}, mod._jev_bench()[0], "cc-key", 1.0) == ({"ok": 1}, "direct", "typesafe/jev")
    url, model, headers = sent[0]
    assert (url, model) == ("https://api.commandcode.ai/provider/v1/systemone", "typesafe/jev")
    # Command Code's Cloudflare front refuses Python's default User-Agent (error 1010)
    assert headers["User-Agent"] and not headers["User-Agent"].startswith("Python-urllib")
    assert headers["Authorization"] == "Bearer cc-key"


def test_the_command_code_key_never_reaches_another_host(tmp_path, monkeypatch):
    mod = _cc(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        mod._jev_direct_url("https://api.typesafe.ai/v1/systemone", "cc")
    with pytest.raises(ValueError):
        mod._jev_direct_url("https://api.commandcode.ai/provider/v1/systemone", "ts")
    with pytest.raises(ValueError):
        mod._jev_direct_url("http://api.commandcode.ai/provider/v1/systemone", "cc")


def test_command_code_gets_its_whole_span_before_typesafe_is_called(tmp_path, monkeypatch):
    mod = _cc(tmp_path, monkeypatch)
    clock = {"t": 1000.0}
    monkeypatch.setattr(mod.time, "time", lambda: clock["t"])
    seen = []

    def fake(state, questions, tier, key, timeout):
        seen.append((tier["model"], round(timeout, 3)))
        if tier["ep"] == "cc":                  # Command Code answers the wide call, then stalls on the rerank
            clock["t"] += 2.0 if any(q.startswith("wide::") for q in questions) else timeout
            if any(q.startswith("wide::") for q in questions):
                return WIDE, "direct", "typesafe/jev"
            raise TimeoutError("timed out")
        clock["t"] += 0.5
        return (WIDE if any(q.startswith("wide::") for q in questions) else RERANK), "relay", "jev-1.13.0"
    monkeypatch.setattr(mod, "_jev_call", fake)
    out = mod._jev_route("commit the work now please", "")
    assert out["result"][0] == "offer"
    ev = out["event"]
    assert ev["model"] == "jev-1.13.0" and ev["tier"] == 1 and ev["fell"] == [["typesafe/jev", "TimeoutError"]]
    # the rerank on Command Code got only what was left of its 5.5 s span, never TypeSafe's share
    assert seen[:2] == [("typesafe/jev", 5.5), ("typesafe/jev", 3.5)]
    assert clock["t"] - 1000.0 <= mod.JEV_BUDGET_S


def test_command_code_answering_inside_its_span_never_calls_typesafe(tmp_path, monkeypatch):
    mod = _cc(tmp_path, monkeypatch)
    clock = {"t": 1000.0}
    monkeypatch.setattr(mod.time, "time", lambda: clock["t"])
    seen = []

    def fake(state, questions, tier, key, timeout):
        seen.append(tier["model"])
        clock["t"] += 2.4                       # slow, but each call inside the 5.5 s span
        return (WIDE if any(q.startswith("wide::") for q in questions) else RERANK), "direct", "typesafe/jev"
    monkeypatch.setattr(mod, "_jev_call", fake)
    ev = mod._jev_route("commit the work now please", "")["event"]
    assert ev["tier"] == 0 and ev["model"] == "typesafe/jev" and "fell" not in ev
    assert seen == ["typesafe/jev", "typesafe/jev"]   # one bill: TypeSafe is never asked


def test_typesafe_still_starts_after_command_code_overruns_its_span(tmp_path, monkeypatch):
    """urllib bounds each socket operation, not the call: a live Command Code turn ran 0.13-0.23 s past its span."""
    mod = _cc(tmp_path, monkeypatch)
    clock = {"t": 1000.0}
    monkeypatch.setattr(mod.time, "time", lambda: clock["t"])
    seen = []

    def fake(state, questions, tier, key, timeout):
        seen.append(tier["model"])
        if tier["ep"] == "cc":
            clock["t"] += timeout + 0.4         # overruns its own timeout
            raise TimeoutError("timed out")
        clock["t"] += 0.5
        return (WIDE if any(q.startswith("wide::") for q in questions) else RERANK), "relay", "jev-1.13.0"
    monkeypatch.setattr(mod, "_jev_call", fake)
    out = mod._jev_route("commit the work now please", "")
    assert out["result"][0] == "offer" and out["event"]["model"] == "jev-1.13.0"
    assert seen == ["typesafe/jev", "jev-1.13.0", "jev-1.13.0"]
    assert clock["t"] - 1000.0 <= mod.JEV_BUDGET_S


def test_a_rerank_that_cannot_finish_in_the_span_is_not_sent(tmp_path, monkeypatch):
    mod = _cc(tmp_path, monkeypatch)
    clock = {"t": 1000.0}
    monkeypatch.setattr(mod.time, "time", lambda: clock["t"])
    seen = []

    def fake(state, questions, tier, key, timeout):
        wide = any(q.startswith("wide::") for q in questions)
        seen.append((tier["model"], "wide" if wide else "rerank"))
        clock["t"] += 5.2 if tier["ep"] == "cc" else 0.5     # Command Code's wide call leaves 0.3 s of its span
        return (WIDE if wide else RERANK), "direct", tier["model"]
    monkeypatch.setattr(mod, "_jev_call", fake)
    ev = mod._jev_route("commit the work now please", "")["event"]
    assert ("typesafe/jev", "rerank") not in seen               # never billed for a call that could not finish
    assert ev["model"] == "jev-1.13.0" and ev["fell"] == [["typesafe/jev", "TimeoutError"]]


def test_command_code_is_cut_off_by_the_clock_not_by_its_socket(tmp_path, monkeypatch):
    """Real time, no fake clock: a Command Code call that ignores its timeout (urllib's timeout bounds each socket
    operation, not the call) must not hold the turn past its span; TypeSafe answers right after."""
    import time as real_time
    mod = _cc(tmp_path, monkeypatch, ENFORCER_JEV_CC_TIMEOUT="0.3")

    def fake(state, questions, tier, key, timeout):
        if tier["ep"] == "cc":
            real_time.sleep(1.5)                # overruns its 0.3 s span by far
            return WIDE, "direct", "typesafe/jev"
        return (WIDE if any(q.startswith("wide::") for q in questions) else RERANK), "relay", "jev-1.13.0"
    monkeypatch.setattr(mod, "_jev_call", fake)
    t0 = real_time.time()
    out = mod._jev_route("commit the work now please", "")
    assert real_time.time() - t0 < 1.0
    assert out["result"][0] == "offer" and out["event"]["model"] == "jev-1.13.0"
    assert out["event"]["fell"] == [["typesafe/jev", "TimeoutError"]]
