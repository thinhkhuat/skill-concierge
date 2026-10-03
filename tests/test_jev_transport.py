"""Jev transport safety in the enforcer, pinned on loopback servers (no network, dummy token).

Covered:
  • `_post_json` never follows a redirect: a 301/302/303/307/308 raises, and the redirect target never
    receives the request (urllib's default re-sends Authorization to it on 301/302/303);
  • the direct Jev call refuses any ENFORCER_JEV_URL other than https://api.typesafe.ai or a loopback
    host, before the key leaves the process;
  • a response naming a model other than the pinned one is an error (the turn falls back), while a
    response that names the pinned model, or none, is used.
"""

import http.server
import importlib.util
import os
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ENFORCER = ROOT / "hooks" / "scripts" / "enforcer.py"


MACHINE_WIRING = ("ENFORCER_JEV_URL", "ENFORCER_JEV_KEY", "ENFORCER_JEV_MODEL", "ENFORCER_JEV_TIMEOUT",
                  "FLYWHEEL_LLM_ENDPOINT", "TYPESAFE_API_KEY")


@pytest.fixture(autouse=True)
def _no_machine_wiring(monkeypatch):
    """The shared env file wires this machine's router to a gateway; each test sets what it needs."""
    for k in MACHINE_WIRING:
        monkeypatch.delenv(k, raising=False)


def _load(tmp_path):
    old = dict(os.environ)
    os.environ["SKILL_CONCIERGE_LOG"] = str(tmp_path)
    try:
        spec = importlib.util.spec_from_file_location(f"enforcer_transport_{abs(hash(str(tmp_path)))}", ENFORCER)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        os.environ.clear()
        os.environ.update(old)


def _call(mod):
    """One call on a tier built from the module's current JEV_URL (tests monkeypatch it)."""
    url = mod.JEV_URL
    ep = "ts" if "typesafe" in url.lower() else "gw"
    return mod._jev_call({}, {}, {"ep": ep, "model": mod.JEV_MODEL, "url": url, "timeout": 1.0}, "k", 1.0)[:2]


def _serve(handler_cls):
    srv = http.server.HTTPServer(("127.0.0.1", 0), handler_cls)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.mark.parametrize("code", [301, 302, 303, 307, 308])
def test_redirect_is_refused_and_the_key_never_reaches_the_target(tmp_path, code):
    mod = _load(tmp_path)
    received = []

    class Target(http.server.BaseHTTPRequestHandler):
        def _any(self):
            received.append(self.headers.get("Authorization"))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"answers": {}}')
        do_GET = do_POST = _any

        def log_message(self, *a):
            pass

    target = _serve(Target)

    class Redirect(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(code)
            # a different host name, as a cross-host redirect would be
            self.send_header("Location", f"http://localhost:{target.server_port}/stolen")
            self.end_headers()

        def log_message(self, *a):
            pass

    source = _serve(Redirect)
    try:
        with pytest.raises(mod.urllib.error.HTTPError):
            mod._post_json(f"http://127.0.0.1:{source.server_port}/v1", {"q": 1}, 3,
                           {"Authorization": "Bearer DUMMY-TOKEN"})
        assert received == []
    finally:
        source.shutdown()
        target.shutdown()


@pytest.mark.parametrize("url, allowed", [
    ("https://api.typesafe.ai/v1/systemone", True),
    ("https://API.TypeSafe.AI/v1/systemone", True),
    ("http://127.0.0.1:9/v1/systemone", True),
    ("http://localhost:9/x", True),
    ("http://api.typesafe.ai/v1/systemone", False),       # plain http to the real host
    ("https://attacker.example/v1/systemone", False),
    ("https://api.typesafe.ai.attacker.example/v1", False),
])
def test_direct_call_pins_the_host_before_the_key_leaves(tmp_path, monkeypatch, url, allowed):
    mod = _load(tmp_path)
    sent = []
    monkeypatch.setattr(mod, "JEV_URL", url)
    monkeypatch.setattr(mod, "JEV_RELAY_URL", None)
    monkeypatch.setattr(mod, "_post_json", lambda u, b, t, h=None: sent.append(u) or {"answers": {"ok": 1}})
    if allowed:
        assert _call(mod) == ({"ok": 1}, "direct")
        assert sent == [url]
    else:
        with pytest.raises(ValueError):
            _call(mod)
        assert sent == []


def test_the_owners_gateway_host_is_trusted_from_the_flywheel_seam(tmp_path, monkeypatch):
    monkeypatch.setenv("FLYWHEEL_LLM_ENDPOINT", "https://gw.example.net/v1/chat/completions")
    mod = _load(tmp_path)
    sent = []
    monkeypatch.setattr(mod, "JEV_RELAY_URL", None)
    monkeypatch.setattr(mod, "_post_json", lambda u, b, t, h=None: sent.append(u) or {"answers": {"ok": 1}})
    for url, allowed in (("https://gw.example.net/v1/systemone", True),
                         ("http://gw.example.net/v1/systemone", False),       # never plain http off-box
                         ("https://other.example.net/v1/systemone", False)):
        monkeypatch.setattr(mod, "JEV_URL", url)
        sent.clear()
        if allowed:
            assert _call(mod) == ({"ok": 1}, "direct") and sent == [url]
        else:
            with pytest.raises(ValueError):
                _call(mod)
            assert sent == []


def test_each_key_reaches_only_its_own_endpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("FLYWHEEL_LLM_ENDPOINT", "https://gw.example.net/v1/chat/completions")
    mod = _load(tmp_path)
    monkeypatch.setattr(mod, "JEV_RELAY_URL", None)       # the relay forwards to TypeSafe only
    monkeypatch.setattr(mod, "_post_json", lambda u, b, t, h=None: pytest.fail("the key left the process"))
    for ep, url in (("ts", "https://gw.example.net/v1/systemone"),     # TypeSafe's key to the gateway
                    ("gw", "https://api.typesafe.ai/v1/systemone")):   # the gateway's key to TypeSafe
        with pytest.raises(ValueError):
            mod._jev_call({}, {}, {"ep": ep, "model": "m", "url": url, "timeout": 1.0}, "k", 1.0)


def test_the_relay_is_used_only_in_front_of_typesafe(tmp_path, monkeypatch):
    default = _load(tmp_path / "d")
    assert default.JEV_RELAY_URL and default.JEV_RELAY_URL.startswith("http://127.0.0.1:")
    monkeypatch.setenv("ENFORCER_JEV_URL", "https://gw.example.net/v1/systemone")
    assert _load(tmp_path / "g").JEV_RELAY_URL is None     # the relay forwards to TypeSafe only


@pytest.mark.parametrize("pinned, returned, ok", [
    ("jev-1.13.0", "jev-1.13.0", True), ("jev-1.13.0", None, True), ("jev-1.13.0", "jev-1.14.0", False),
    ("oc/jev-1.13-free", "jev-1.13-free", True),       # a gateway's provider prefix is not a model change
    ("oc/jev-1.13-free", "oc/jev-1.13-free", True),
    ("oc/jev-1.13-free", "jev-1.13.0", False),
    ("openrouter/typesafe/jev-1.13", "typesafe/jev-1.13-20260917", True),   # dated snapshot of the pin
    ("openrouter/typesafe/jev-1.13", "typesafe/jev-1.14-20261101", False),
    ("openrouter/typesafe/jev-1.13", "jev-1.13-free", False),
])
def test_returned_model_check_allows_only_a_provider_prefix(tmp_path, monkeypatch, pinned, returned, ok):
    mod = _load(tmp_path)
    monkeypatch.setattr(mod, "JEV_MODEL", pinned)
    resp = {"answers": {"ok": 1}} | ({"model": returned} if returned else {})
    if ok:
        assert mod._jev_answers(resp)[0] == {"ok": 1}
    else:
        with pytest.raises(mod.JevModelMismatch):
            mod._jev_answers(resp)


@pytest.mark.parametrize("returned, ok", [("jev-1.13.0", True), (None, True), ("jev-1.14.0", False)])
def test_a_different_returned_model_is_an_error(tmp_path, monkeypatch, returned, ok):
    mod = _load(tmp_path)
    monkeypatch.setattr(mod, "JEV_MODEL", "jev-1.13.0")
    resp = {"answers": {"ok": 1}} | ({"model": returned} if returned else {})
    monkeypatch.setattr(mod, "_post_json", lambda u, b, t, h=None: resp)
    if ok:
        assert _call(mod)[0] == {"ok": 1}
    else:
        with pytest.raises(mod.JevModelMismatch):
            _call(mod)
