"""ADR-0060 Jev needs-a-skill gate — the fifth AUTHORIZED-SKIP leg, pinned offline.

Covered here (no network: urlopen is replaced, main() runs in-process on a stdin fake):
  • a low p skips before embed with the locked "Jev needs-a-skill gate" signature, band
    `jev_skip`, and the p recorded in the ledger row;
  • a high p falls through to the normal pipeline (embed is reached);
  • fail-open: timeout / HTTP-shaped error / malformed body -> fall through, error recorded;
  • no TYPESAFE_API_KEY or ENFORCER_JEV_GATE=0 -> no network call at all;
  • a named deterministic route never asks Jev.

The live call itself is exercised by the deploy-time smoke test (real key, real API).
"""

import importlib.util
import io
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENFORCER = ROOT / "hooks" / "scripts" / "enforcer.py"
PROMPT = "please propagate this note to the other sessions right now"


class _Resp:
    def __init__(self, body: bytes):
        self._b = body

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _load(tmp_path, **env):
    old = dict(os.environ)
    os.environ.update({"SKILL_CONCIERGE_LOG": str(tmp_path), **env})
    try:
        spec = importlib.util.spec_from_file_location(f"enforcer_jev_{abs(hash(str(env)))}", ENFORCER)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        os.environ.clear()
        os.environ.update(old)


def _run(mod, monkeypatch, prompt=PROMPT, urlopen=None, key="test-key"):
    """Run main() on a fake stdin; returns (stdout, calls, embed_reached, ledger_rows)."""
    calls = []
    reached = {"embed": False}

    def fake_urlopen(req, timeout=None):
        calls.append(req.full_url)
        return urlopen(req, timeout)

    def fake_embed(_text):
        reached["embed"] = True
        raise OSError("stop after the gate")    # takes the embed_down fallback leg

    if key is None:
        monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    else:
        monkeypatch.setenv("TYPESAFE_API_KEY", key)
    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(mod, "_embed", fake_embed)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"prompt": prompt, "session_id": "t"})))
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    mod.main()
    rows = [json.loads(ln) for ln in mod.LEDGER.read_text(encoding="utf-8").splitlines()] \
        if mod.LEDGER.exists() else []
    return out.getvalue(), calls, reached["embed"], rows


def _answer(p):
    return lambda req, timeout: _Resp(json.dumps({"answers": {"needs_playbook": {"noul": p}}}).encode())


def test_low_p_skips_before_embed_with_locked_signature(tmp_path, monkeypatch):
    mod = _load(tmp_path)
    out, calls, embed, rows = _run(mod, monkeypatch, urlopen=_answer(0.05))
    assert calls == [mod.JEV_URL]
    assert not embed
    assert "SKILL-CHECK:" in out and "Jev needs-a-skill gate" in out and "p=0.05" in out
    assert rows[-1]["band"] == "jev_skip" and rows[-1]["jev"]["p"] == 0.05


def test_high_p_falls_through_to_retrieval(tmp_path, monkeypatch):
    mod = _load(tmp_path)
    out, calls, embed, rows = _run(mod, monkeypatch, urlopen=_answer(0.8))
    assert calls and embed
    assert "Jev needs-a-skill gate" not in out
    assert rows[-1]["band"] == "fallback" and rows[-1]["jev"]["p"] == 0.8


def test_fail_open_on_timeout_http_error_and_bad_body(tmp_path, monkeypatch):
    def timeout(req, t):
        raise TimeoutError("slow")

    def http_err(req, t):
        raise mod.urllib.error.HTTPError(req.full_url, 529, "overloaded", {}, None)

    def bad_body(req, t):
        return _Resp(b'{"answers": {}}')

    def out_of_range(req, t):
        return _Resp(json.dumps({"answers": {"needs_playbook": {"noul": 7}}}).encode())

    for fail, err in ((timeout, "TimeoutError"), (http_err, "HTTPError"),
                      (bad_body, "KeyError"), (out_of_range, "ValueError")):
        mod = _load(tmp_path / err)
        out, calls, embed, rows = _run(mod, monkeypatch, urlopen=fail)
        assert calls and embed, err
        assert "Jev needs-a-skill gate" not in out, err
        assert rows[-1]["jev"]["err"] == err, rows[-1]


def test_no_key_or_kill_switch_makes_no_call(tmp_path, monkeypatch):
    mod = _load(tmp_path / "nokey")
    _, calls, embed, rows = _run(mod, monkeypatch, urlopen=_answer(0.0), key=None)
    assert not calls and embed and "jev" not in rows[-1]
    mod = _load(tmp_path / "off", ENFORCER_JEV_GATE="0")
    _, calls, embed, _ = _run(mod, monkeypatch, urlopen=_answer(0.0))
    assert not calls and embed


def test_named_route_never_asks_jev(tmp_path, monkeypatch):
    mod = _load(tmp_path)
    monkeypatch.setattr(mod, "_route_hits", lambda prompt, keepoff: [("named-skill", "desc", 1.0)])
    _, calls, embed, _ = _run(mod, monkeypatch, urlopen=_answer(0.0))
    assert not calls and embed
