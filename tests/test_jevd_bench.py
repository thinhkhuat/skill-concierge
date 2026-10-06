"""jevd as the bench (ADR-0080): when JEVD_URL names a loopback jevd that answers GET /ladder, its ladder is the
bench and every router call goes to jevd pinned to one provider, with no key. Offline: a fake jevd on 127.0.0.1.

Covered:
  • the ladder becomes the tiers (order, model, per-call limit, span, key presence);
  • a turn's wide and rerank calls are pinned to the same provider, carry no Authorization and send their call
    limit as X-Jevd-Budget; the ledger event names the provider (`prov`) and `via` "jevd";
  • a failing provider moves the turn to the next one in jevd's ladder; a provider jevd has no key for is skipped;
  • jevd down, or JEVD_URL not loopback http, leaves ENFORCER_JEV_BENCH in charge, as before;
  • the offline client (scripts/jev_client.py) goes through the same jevd tiers;
  • review fixes: the ladder fetch spends the turn's budget; a jevd without keys leaves the env bench in
    charge; every router event names its bench; consult widening and the calibrator use jevd correctly;
    a JEVD_URL given with the API path still names the service.
"""
import importlib.util
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ENFORCER = ROOT / "hooks" / "scripts" / "enforcer.py"
CATALOG = [("ak-git", "Git operations."), ("tk-research", "Research a topic.")]
WIDE = {"wide::0": {"type": "choice", "probabilities": {"ak-git": 0.8, "tk-research": 0.2}}}
RERANK = {"which": {"type": "choice", "choice": "ak-git", "confidence": 0.8,
                    "probabilities": {"ak-git": 0.8, "tk-research": 0.2}},
          "fits::0": {"type": "noul", "noul": 0.9}, "fits::1": {"type": "noul", "noul": 0.2}}
LADDER = [{"name": "commandcode", "model": "typesafe/jev", "timeout_s": 5.5, "span_s": 5.5, "key": True},
          {"name": "typesafe", "model": "jev-1.13.0", "timeout_s": 1.5, "span_s": None, "key": True},
          {"name": "gateway", "model": "openrouter/typesafe/jev-1.13", "timeout_s": 2.0, "span_s": None,
           "key": False}]


class FakeJevd:
    """GET /ladder and POST /v1/systemone. `fail`: provider names that answer 502."""

    def __init__(self, ladder=LADDER, fail=(), ladder_delay=0.0):
        self.ladder, self.fail, self.calls, self.ladder_delay = ladder, set(fail), [], ladder_delay
        owner = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _send(self, code, obj):
                out = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

            def do_GET(self):
                time.sleep(owner.ladder_delay)
                self._send(200, {"version": "test", "providers": owner.ladder}) if self.path == "/ladder" \
                    else self._send(404, {})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                prov = self.headers.get("X-Jevd-Provider")
                owner.calls.append({"prov": prov, "auth": self.headers.get("Authorization"),
                                    "budget": float(self.headers.get("X-Jevd-Budget")),
                                    "wide": any(q.startswith("wide::") for q in body["questions"])})
                if prov in owner.fail:
                    return self._send(502, {"error": {"type": "jevd_upstream"}})
                model = next(p["model"] for p in owner.ladder if p["name"] == prov)
                self._send(200, {"model": model, "answers": WIDE if owner.calls[-1]["wide"] else RERANK})

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.srv.daemon_threads = True
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


@pytest.fixture
def jevd():
    made = []

    def make(**k):
        f = FakeJevd(**k)
        made.append(f)
        return f
    yield make
    for f in made:
        f.close()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("ENFORCER_JEV_BENCH", "ENFORCER_JEV_URL", "ENFORCER_JEV_ROUTER", "ENFORCER_JEV_GATE",
              "ENFORCER_JEV_BUDGET", "TYPESAFE_API_KEY", "CMD_API_KEY", "JEVD_URL", "ENFORCER_JEV_HISTORY"):
        monkeypatch.delenv(k, raising=False)


def _load(tmp_path, monkeypatch, **env):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("SKILL_CONCIERGE_LOG", str(tmp_path))
    spec = importlib.util.spec_from_file_location(f"enforcer_jevd_{abs(hash((str(tmp_path), str(env))))}", ENFORCER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "_jev_catalog", lambda: list(CATALOG))
    monkeypatch.setattr(mod, "_jev_context", lambda path: ("", []))
    return mod


def test_the_jevd_ladder_is_the_bench(tmp_path, monkeypatch, jevd):
    j = jevd()
    mod = _load(tmp_path, monkeypatch, JEVD_URL=j.url + "/")
    tiers = mod._jev_bench()
    assert [(t["ep"], t["name"], t["model"], t["timeout"]) for t in tiers] == [
        ("jevd", "commandcode", "typesafe/jev", 5.5), ("jevd", "typesafe", "jev-1.13.0", 1.5),
        ("jevd", "gateway", "openrouter/typesafe/jev-1.13", 2.0)]
    assert tiers[0]["span"] == 5.5 and "span" not in tiers[1]
    assert [mod._jev_key(t) for t in tiers] == ["jevd", "jevd", ""]


def test_a_turn_is_pinned_to_one_provider_with_no_key(tmp_path, monkeypatch, jevd):
    j = jevd()
    mod = _load(tmp_path, monkeypatch, JEVD_URL=j.url)
    out = mod._jev_route("commit my staged changes please", "")
    assert out["result"][0] == "offer" and out["result"][1][0][0] == "ak-git"
    ev = out["event"]
    assert (ev["via"], ev["prov"], ev["model"], ev["tier"]) == ("jevd", "commandcode", "typesafe/jev", 0)
    assert [(c["prov"], c["wide"]) for c in j.calls] == [("commandcode", True), ("commandcode", False)]
    assert all(c["auth"] is None for c in j.calls)
    assert all(0 < c["budget"] <= 5.5 for c in j.calls)


def test_a_failing_provider_moves_the_turn_down_jevds_ladder(tmp_path, monkeypatch, jevd):
    j = jevd(fail={"commandcode"})
    mod = _load(tmp_path, monkeypatch, JEVD_URL=j.url)
    ev = mod._jev_route("commit my staged changes please", "")["event"]
    assert (ev["prov"], ev["tier"]) == ("typesafe", 1)
    assert ev["fell"] == [["typesafe/jev", "HTTPError"]]
    assert [c["prov"] for c in j.calls] == ["commandcode", "typesafe", "typesafe"]


def test_a_provider_jevd_has_no_key_for_is_skipped(tmp_path, monkeypatch, jevd):
    j = jevd(fail={"commandcode", "typesafe"})
    mod = _load(tmp_path, monkeypatch, JEVD_URL=j.url)
    ev = mod._jev_route("commit my staged changes please", "")["event"]
    assert ev["fell"] == [["typesafe/jev", "HTTPError"], ["jev-1.13.0", "HTTPError"],
                          ["openrouter/typesafe/jev-1.13", "NoKey"]]
    assert "gateway" not in [c["prov"] for c in j.calls]


def test_jevd_down_leaves_the_env_bench_in_charge(tmp_path, monkeypatch):
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()                                   # nothing listens here: connection refused
    mod = _load(tmp_path, monkeypatch, JEVD_URL=f"http://127.0.0.1:{port}",
                ENFORCER_JEV_BENCH="ts:jev-1.13.0")
    assert [(t["ep"], t["model"]) for t in mod._jev_bench()] == [("ts", "jev-1.13.0")]


def test_a_jevd_url_that_is_not_loopback_http_is_ignored(tmp_path, monkeypatch):
    for url in ("https://127.0.0.1:4377", "http://jevd.example.net:4377", "file:///tmp/x"):
        mod = _load(tmp_path, monkeypatch, JEVD_URL=url)
        assert mod.JEVD_URL is None


def test_the_offline_client_uses_the_same_jevd_tiers(tmp_path, monkeypatch, jevd):
    j = jevd()
    monkeypatch.setenv("JEVD_URL", j.url)
    spec = importlib.util.spec_from_file_location("jev_client_jevd", ROOT / "scripts" / "jev_client.py")
    jc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(jc)
    answers, meta = jc.ask({"request": "x"}, {"wide::0": {"type": "choice", "options": {"ak-git": "a"}}},
                           timeout=4.0)
    assert answers == WIDE and meta["via"] == ["jevd"]
    assert [(c["prov"], c["auth"]) for c in j.calls] == [("commandcode", None)]
    assert j.calls[0]["budget"] == pytest.approx(5.5, abs=0.05)   # a span tier gets its whole span offline


def test_the_ladder_fetch_spends_this_turns_budget(tmp_path, monkeypatch, jevd):
    j = jevd(ladder_delay=0.25)
    mod = _load(tmp_path, monkeypatch, JEVD_URL=j.url)
    ev = mod._jev_route("commit my staged changes please", "")["event"]
    assert ev["ms"] >= 250 and ev["bench"] == "jevd"


def test_a_non_english_turn_never_fetches_the_ladder(tmp_path, monkeypatch, jevd):
    j = jevd(ladder_delay=0.25)
    mod = _load(tmp_path, monkeypatch, JEVD_URL=j.url)
    t0 = time.time()
    assert mod._jev_route("hãy commit các thay đổi đã stage giúp tôi", "") == {"result": None, "event": None}
    assert time.time() - t0 < 0.2


def test_a_jevd_without_keys_leaves_the_env_bench_in_charge(tmp_path, monkeypatch, jevd):
    j = jevd(ladder=[{**p, "key": False} for p in LADDER])
    mod = _load(tmp_path, monkeypatch, JEVD_URL=j.url, ENFORCER_JEV_BENCH="ts:jev-1.13.0", TYPESAFE_API_KEY="k")
    assert [t["ep"] for t in mod._jev_bench()] == ["ts"]


def test_every_router_event_names_its_bench(tmp_path, monkeypatch, jevd):
    j = jevd(fail={"commandcode", "typesafe"})
    mod = _load(tmp_path, monkeypatch, JEVD_URL=j.url)
    assert mod._jev_route("commit my staged changes please", "")["event"]["bench"] == "jevd"
    monkeypatch.delenv("JEVD_URL")
    mod = _load(tmp_path, monkeypatch, ENFORCER_JEV_BENCH="ts:jev-1.13.0", TYPESAFE_API_KEY="k")
    monkeypatch.setattr(mod, "_jev_call", lambda *a, **k: (_ for _ in ()).throw(TimeoutError("x")))
    assert mod._jev_route("commit my staged changes please", "")["event"]["bench"] == "env"


def test_a_jevd_url_with_the_api_path_still_names_the_service(tmp_path, monkeypatch):
    mod = _load(tmp_path, monkeypatch, JEVD_URL="http://127.0.0.1:4377/v1/systemone")
    assert mod.JEVD_URL == "http://127.0.0.1:4377"


def _script(name):
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(f"{name}_jevd", ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_consult_widening_uses_the_typesafe_rung_of_jevds_ladder(monkeypatch, jevd):
    j = jevd()
    monkeypatch.setenv("JEVD_URL", j.url)
    cf = _script("consult_fit")
    monkeypatch.setattr(cf.jc, "_ENF", None)   # jev_client caches one enforcer per process: load it with JEVD_URL set
    seen = {}

    def ask(state, qs, timeout, tiers=None, retries=0):
        seen["tiers"] = tiers
        return WIDE, {}
    cf.jev_top("commit my staged changes", catalog_fn=lambda: list(CATALOG), ask_fn=ask)
    assert [(t["ep"], t["name"], t["model"]) for t in seen["tiers"]] == [("jevd", "typesafe", "jev-1.13.0")]


def test_the_calibrator_sends_a_jevd_tier_through_the_hook_and_never_resends_a_timeout(monkeypatch, jevd):
    j = jevd()
    monkeypatch.setenv("JEVD_URL", j.url)
    cal = _script("calibrate_jev_gate")
    monkeypatch.setattr(cal, "ENF", None)      # same per-process cache in the calibrator
    enf = cal.load_enforcer() if hasattr(cal, "load_enforcer") else None
    assert enf is not None
    tier = next(t for t in enf._jev_bench() if t["name"] == "typesafe")
    answers, ms, _usage, err = cal.call(enf, tier, {"request": "x"}, {"wide::0": {"type": "choice"}}, 2.0)
    assert err is None and answers == WIDE
    assert j.calls[-1]["prov"] == "typesafe" and j.calls[-1]["auth"] is None
    sends = []
    monkeypatch.setattr(enf, "_jev_call", lambda *a, **k: sends.append(1) or (_ for _ in ()).throw(TimeoutError("slow")))
    assert cal.call(enf, tier, {"request": "x"}, {}, 2.0)[3] == "TimeoutError"
    assert len(sends) == 1
