"""scripts/jev_client.py and the three enforcer helpers it shares with later phases. Offline: Jev is
replaced at the transport boundary (`_post_json`), the way tests/test_jev_transport.py does.

Covered: the ported token estimator; the secret redactor; the typed-user-text allow-list; batching under
Jev's two token limits; parallel batches merged; tier walk (fast failure -> next tier, timeout -> chain
ends, model mismatch -> next tier); 429 Retry-After; the total deadline; the relay bypass; the scoped
log env and the single locked load; no key in error messages.
"""

import importlib.util
import io
import os
import threading
import time
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "scripts" / "jev_client.py"
GW = "https://gw.example.net/v1/chat/completions"
WIRING = ("ENFORCER_JEV_BENCH", "ENFORCER_JEV_URL", "ENFORCER_JEV_KEY", "ENFORCER_JEV_MODEL",
          "ENFORCER_JEV_TIMEOUT", "ENFORCER_JEV_GATEWAY_TIMEOUT", "FLYWHEEL_LLM_ENDPOINT",
          "FLYWHEEL_LLM_API_KEY", "TYPESAFE_API_KEY", "JEV_CLIENT_MAX_TPS", "JEV_CLIENT_MAX_RPS")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in WIRING:
        monkeypatch.delenv(k, raising=False)


@pytest.fixture
def jc(monkeypatch):
    """A fresh jev_client with a fresh enforcer, on a ts+gw bench with dummy keys."""
    monkeypatch.setenv("ENFORCER_JEV_BENCH", "ts:jev-1.13.0 gw:openrouter/typesafe/jev-1.13")
    monkeypatch.setenv("FLYWHEEL_LLM_ENDPOINT", GW)
    monkeypatch.setenv("TYPESAFE_API_KEY", "sk-test-SECRET-0000000000")
    monkeypatch.setenv("FLYWHEEL_LLM_API_KEY", "gw-key")
    spec = importlib.util.spec_from_file_location(f"jev_client_{time.time_ns()}", CLIENT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fake(enf, monkeypatch, behaviour):
    """behaviour(url, body) -> answers dict or raises. Records every URL."""
    seen = []

    def post(url, body, timeout, headers=None):
        seen.append(url)
        out = behaviour(url, body)
        return {"answers": out, "model": body["model"]}
    monkeypatch.setattr(enf, "_post_json", post)
    return seen


def _yes(url, body):
    return {k: {"type": "noul", "noul": 0.9} for k in body["questions"]}


def _err(code, headers=None):
    return urllib.error.HTTPError("u", code, "x", headers or {}, io.BytesIO(b"{}"))


# --- enforcer helpers ------------------------------------------------------------------------------

def test_token_estimate_matches_the_ported_rules(jc):
    enf = jc.load_enforcer()
    assert enf._jev_tokens('{"a": 12}') == 7
    assert enf._jev_tokens("abcdefgh") == 2
    assert enf._jev_tokens("") == 0


def test_redactor_removes_every_secret_shape(jc):
    enf = jc.load_enforcer()
    secrets = ["sk-abcdefghijklmnopqrstuv", "Authorization: Bearer abcdefghijklmnop123",
               "OPENAI_API_KEY=xyz123secret", "AKIAABCDEFGHIJKLMNOP",
               "-----BEGIN RSA PRIVATE KEY-----\nMIIabc\n-----END RSA PRIVATE KEY-----",
               "ghp_" + "a" * 36, "xoxb-1234567890-abc"]
    out = enf._jev_redact("\n".join(secrets))
    for s in ("sk-abcdefghijklmnopqrstuv", "abcdefghijklmnop123", "xyz123secret", "AKIAABCDEFGHIJKLMNOP",
              "MIIabc", "ghp_", "xoxb-1234567890"):
        assert s not in out
    plain = "Please fix the login form and run the tests."
    assert enf._jev_redact(plain) == plain


@pytest.mark.parametrize("record", [
    {"type": "user", "message": {"content": "<bash-stdout>secret output</bash-stdout>"}},
    {"type": "user", "message": {"content": "<local-command-stdout>x</local-command-stdout>"}},
    {"type": "user", "message": {"content": "<task-notification><result>x</result>"}},
    {"type": "user", "message": {"content": "<system-reminder>x</system-reminder>"}},
    {"type": "user", "isMeta": True, "message": {"content": "typed?"}},
    {"type": "user", "isSidechain": True, "message": {"content": "typed?"}},
    {"type": "user", "message": {"content": [{"type": "tool_result", "content": "out"}]}},
    {"type": "assistant", "message": {"content": "hello"}},
    {"type": "user", "message": "not a dict"},
])
def test_typed_text_rejects_harness_and_command_output(jc, record):
    assert jc.load_enforcer()._jev_typed_user_text(record) is None


def test_typed_text_accepts_a_typed_sentence(jc):
    enf = jc.load_enforcer()
    assert enf._jev_typed_user_text({"type": "user", "message": {"content": "fix the bug"}}) == "fix the bug"
    rec = {"type": "user", "message": {"content": [{"type": "text", "text": "fix the bug"}]}}
    assert enf._jev_typed_user_text(rec) == "fix the bug"


def test_typed_text_strips_embedded_reminders_and_redacts(jc):
    enf = jc.load_enforcer()
    rec = {"type": "user", "message": {"content":
           "call it with Bearer abcdefghijklmnop99 now<system-reminder>hidden</system-reminder>"}}
    out = enf._jev_typed_user_text(rec)
    assert "hidden" not in out and "abcdefghijklmnop99" not in out and out.startswith("call it with")


# --- batching ------------------------------------------------------------------------------------

def test_batches_respect_the_total_request_limit(jc):
    enf = jc.load_enforcer()
    import json
    state = {"s": "word " * 1500}
    qs = {f"q{i}": {"type": "noul", "instructions": "word " * 1500} for i in range(300)}
    parts = jc.batches(state, qs)
    assert len(parts) > 1
    for p in parts:
        assert enf._jev_tokens(json.dumps({"state": state, "questions": p})) <= jc.MAX_REQUEST_TOKENS
    assert [k for p in parts for k in p] == list(qs)


def test_batches_respect_state_plus_longest_question(jc, monkeypatch):
    enf = jc.load_enforcer()
    sent = _fake(enf, monkeypatch, _yes)
    with pytest.raises(jc.JevTooLarge):
        jc.ask({"s": "a " * 29500}, {"q": {"type": "noul", "instructions": "a " * 2000}}, timeout=1.0)
    assert sent == []


# --- ask -----------------------------------------------------------------------------------------

def test_ask_merges_answers_across_parallel_batches(jc, monkeypatch):
    enf = jc.load_enforcer()
    monkeypatch.setenv("JEV_CLIENT_MAX_TPS", "1e9")
    monkeypatch.setenv("JEV_CLIENT_MAX_RPS", "1e9")
    jc._RATE = jc._Rate()
    _fake(enf, monkeypatch, _yes)
    qs = {f"q{i}": {"type": "noul", "instructions": "word " * 1500} for i in range(120)}
    ans, meta = jc.ask({}, qs, timeout=1.0)
    assert set(ans) == set(qs)
    assert meta["requests"] == len(jc.batches({}, qs)) > 1
    assert set(meta["per_key_model"]) == set(qs)


def test_fast_failure_moves_to_the_next_tier(jc, monkeypatch):
    enf = jc.load_enforcer()
    seen = _fake(enf, monkeypatch, lambda u, b: (_ for _ in ()).throw(_err(500)) if "typesafe" in u else _yes(u, b))
    ans, meta = jc.ask({}, {"q": {"type": "noul", "instructions": "x"}}, timeout=1.0)
    assert ans["q"]["noul"] == 0.9 and "gw.example.net" in seen[-1]
    assert meta["model"] == ["openrouter/typesafe/jev-1.13"]


def test_timeout_moves_to_the_next_tier(jc, monkeypatch):
    enf = jc.load_enforcer()
    seen = _fake(enf, monkeypatch, lambda u, b: (_ for _ in ()).throw(TimeoutError()) if "typesafe" in u else _yes(u, b))
    ans, meta = jc.ask({}, {"q": {"type": "noul", "instructions": "x"}}, timeout=1.0)
    assert ans["q"]["noul"] == 0.9 and "gw.example.net" in seen[-1]
    assert sum("typesafe" in u for u in seen) == 1                 # a timed-out tier is not retried


def test_deadline_is_never_overrun(jc, monkeypatch):
    enf = jc.load_enforcer()
    _fake(enf, monkeypatch, lambda u, b: (_ for _ in ()).throw(_err(429, {"Retry-After": "5"})))
    t0 = time.time()
    with pytest.raises(jc.JevError):
        jc.ask({}, {"q": {"type": "noul", "instructions": "x"}}, timeout=1.0, deadline=time.time() + 0.5)
    assert time.time() - t0 < 0.6


def test_rate_limit_waits_then_retries_once(jc, monkeypatch):
    enf = jc.load_enforcer()
    calls = []

    def behaviour(u, b):
        calls.append(u)
        if len(calls) == 1:
            raise _err(429, {"Retry-After": "0"})
        return _yes(u, b)
    _fake(enf, monkeypatch, behaviour)
    ans, _ = jc.ask({}, {"q": {"type": "noul", "instructions": "x"}}, timeout=1.0)
    assert ans["q"]["noul"] == 0.9 and calls[0] == calls[1]       # the same tier answered the retry


def test_model_mismatch_moves_to_the_next_tier(jc, monkeypatch):
    enf = jc.load_enforcer()
    seen = []

    def post(url, body, timeout, headers=None):
        seen.append(url)
        model = "other-model" if "typesafe" in url else body["model"]
        return {"answers": _yes(url, body), "model": model}
    monkeypatch.setattr(enf, "_post_json", post)
    jc.ask({}, {"q": {"type": "noul", "instructions": "x"}}, timeout=1.0)
    assert "gw.example.net" in seen[-1]


def test_offline_calls_bypass_the_relay(jc, monkeypatch):
    enf = jc.load_enforcer()
    assert enf.JEV_RELAY_URL is None
    seen = _fake(enf, monkeypatch, _yes)
    jc.ask({}, {"q": {"type": "noul", "instructions": "x"}}, timeout=1.0)
    assert seen == ["https://api.typesafe.ai/v1/systemone"]


def test_loading_does_not_leak_the_log_env(jc, monkeypatch):
    monkeypatch.delenv("SKILL_CONCIERGE_LOG", raising=False)
    jc.load_enforcer()
    assert "SKILL_CONCIERGE_LOG" not in os.environ


def test_concurrent_loads_import_once(jc, monkeypatch):
    runs = []
    real = importlib.util.module_from_spec

    def counting(spec):
        runs.append(spec.name)
        time.sleep(0.05)
        return real(spec)
    monkeypatch.setattr(importlib.util, "module_from_spec", counting)
    threads = [threading.Thread(target=jc.load_enforcer) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert runs.count("enforcer_jev_client") == 1


def test_no_key_is_ever_in_an_error_message(jc, monkeypatch):
    enf = jc.load_enforcer()
    _fake(enf, monkeypatch, lambda u, b: (_ for _ in ()).throw(ValueError("bad sk-test-SECRET-0000000000")))
    with pytest.raises(jc.JevError) as ei:
        jc.ask({}, {"q": {"type": "noul", "instructions": "x"}}, timeout=1.0)
    assert "SECRET" not in str(ei.value)


GAP_SECRETS = {
    "json quoted name": ('{"OPENAI_API_KEY": "abcd1234efgh5678ijkl"}', "abcd1234efgh5678ijkl"),
    "lowercase name": ('api_key = "zq81xv92mk03lp45"', "zq81xv92mk03lp45"),
    "github_pat": ("github_pat_" + "A1b2C3d4E5" * 3, "A1b2C3d4E5A1b2C3d4E5"),
    "gho": ("gho_" + "a1B2c3D4e5" * 3, "a1B2c3D4e5a1B2c3D4e5"),
    "ghu": ("ghu_" + "a1B2c3D4e5" * 3, "a1B2c3D4e5a1B2c3D4e5"),
    "ghs": ("ghs_" + "a1B2c3D4e5" * 3, "a1B2c3D4e5a1B2c3D4e5"),
    "gitlab": ("glpat-" + "x9Y8z7W6v5" * 2, "x9Y8z7W6v5x9Y8z7W6v5"),
    "google": ("AIzaSy" + "A" * 33, "AIzaSyAAAA"),
    "url password": ("postgres://admin:S3cretPass@db.internal/app", "S3cretPass"),
    "bare jwt": ("Authorization: token eyJhbGciOi.eyJzdWIiOiIx.SflKxwRJSMeKKF2QT4", "eyJhbGciOi"),
    "x-api-key header": ("x-api-key: 9f8e7d6c5b4a3210", "9f8e7d6c5b4a3210"),
    "password header": ("password: hunter2hunter2", "hunter2hunter2"),
    "unterminated key": ("see -----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAA\nQQQQ", "b3BlbnNzaC1rZXk"),
}


@pytest.mark.parametrize("name", sorted(GAP_SECRETS))
def test_redactor_covers_the_review_gaps(jc, name):
    text, secret = GAP_SECRETS[name]
    out = jc.load_enforcer()._jev_redact(f"before {text}\nafter line")
    assert secret not in out and "[redacted]" in out and out.startswith("before ")


def test_redactor_leaves_ordinary_prose_alone(jc):
    enf = jc.load_enforcer()
    for plain in ("Please fix the login form and run the tests.",
                  "The tokens are counted per request; max_tokens stays 4096 and the secretary agrees.",
                  "See https://example.com/docs/path and http://localhost:4200/x for details, ok?",
                  "Use the key points from the report; password reset flow is out of scope."):
        assert enf._jev_redact(plain) == plain


def test_typed_text_strips_injected_hook_blocks(jc):
    enf = jc.load_enforcer()

    def typed(text):
        return enf._jev_typed_user_text({"type": "user", "message": {"content": text}})
    skills = "[Relevant skills for this request]\nThese skills may help:\n- a: b\n\n[User Request]\nfix the login bug"
    assert typed(skills) == "fix the login bug"
    rules = "[Assistant Rules]\n# Repo Explorer\nYou are an expert.\n[/Assistant Rules]\n\nhttps://github.com/x/y.git"
    assert typed(rules) == "https://github.com/x/y.git"
    assert typed("[Assistant Rules]\n# Persona only, never closed") is None
    assert typed("[Relevant skills for this request]\n- a: b") is None


def test_a_span_tier_is_never_cut_before_its_span(monkeypatch):
    """Command Code gets its whole span offline too (ADR-0079): a caller's shorter timeout would bill it and the
    next tier for one answer."""
    monkeypatch.setenv("ENFORCER_JEV_BENCH", "cc:typesafe/jev ts:jev-1.13.0")
    monkeypatch.setenv("CMD_API_KEY", "cc-key")
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-key")
    spec = importlib.util.spec_from_file_location(f"jev_client_{time.time_ns()}", CLIENT)
    jc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(jc)
    enf = jc.load_enforcer()
    got = []
    monkeypatch.setattr(enf, "_jev_call", lambda st, qs, tier, key, to: got.append((tier["ep"], round(to, 1)))
                        or ({k: {"type": "noul", "noul": 0.5} for k in qs}, "direct", tier["model"]))
    jc.ask({}, {"q": {"type": "noul", "instructions": "x"}}, timeout=2.0, deadline=time.time() + 60)
    assert got == [("cc", 5.5)]
    got.clear()
    jc.ask({}, {"q": {"type": "noul", "instructions": "x"}}, timeout=2.0, deadline=time.time() + 3.0)
    assert got[0][0] == "cc" and got[0][1] <= 3.0               # still bounded by the caller's deadline
