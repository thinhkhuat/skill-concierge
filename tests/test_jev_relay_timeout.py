"""The owner's relay reports an upstream timeout as HTTP 502 {"error": "TimeoutError"} (index_owner.py).
The router must read that as a timeout and end the tier chain, as it does for a direct timeout, instead of
re-sending the turn to the next tier (which double-bills). Offline: `_post_json` is replaced.
"""

import importlib.util
import io
import json
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ENFORCER = ROOT / "hooks" / "scripts" / "enforcer.py"
GW = "https://gw.example.net/v1/chat/completions"
RELAY = "http://127.0.0.1:1/jev"
CATALOG = [("ak-git", "Git operations."), ("tk-research", "Research a topic.")]
WIDE = {"wide::0": {"type": "choice", "probabilities": {"ak-git": 0.8, "tk-research": 0.2}}}
RERANK = {"which": {"type": "choice", "choice": "ak-git", "confidence": 0.8,
                    "probabilities": {"ak-git": 0.8, "tk-research": 0.2}},
          "fits::0": {"type": "noul", "noul": 0.9}, "fits::1": {"type": "noul", "noul": 0.2}}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("ENFORCER_JEV_BENCH", "ENFORCER_JEV_URL", "ENFORCER_JEV_KEY", "ENFORCER_JEV_MODEL",
              "ENFORCER_JEV_TIMEOUT", "ENFORCER_JEV_GATEWAY_TIMEOUT", "ENFORCER_JEV_ROUTER", "ENFORCER_JEV_GATE",
              "FLYWHEEL_LLM_ENDPOINT", "FLYWHEEL_LLM_API_KEY", "TYPESAFE_API_KEY", "ENFORCER_JEV_HISTORY"):
        monkeypatch.delenv(k, raising=False)


def _route(tmp_path, monkeypatch, relay_body: bytes):
    """Run one routing decision on a ts+gw bench whose relay answers 502 with `relay_body`."""
    for k, v in {"ENFORCER_JEV_BENCH": "ts:jev-1.13.0 gw:openrouter/typesafe/jev-1.13",
                 "FLYWHEEL_LLM_ENDPOINT": GW, "TYPESAFE_API_KEY": "ts-key",
                 "FLYWHEEL_LLM_API_KEY": "gw-key", "SKILL_CONCIERGE_LOG": str(tmp_path)}.items():
        monkeypatch.setenv(k, v)
    spec = importlib.util.spec_from_file_location(f"enforcer_relay_to_{abs(hash(relay_body))}", ENFORCER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "_jev_catalog", lambda: list(CATALOG))
    monkeypatch.setattr(mod, "_jev_context", lambda path: ("", []))
    monkeypatch.setattr(mod, "JEV_RELAY_URL", RELAY)
    sent = []

    def fake(url, body, timeout, headers=None):
        sent.append(url)
        if url == RELAY:
            raise urllib.error.HTTPError(url, 502, "Bad Gateway", {}, io.BytesIO(relay_body))
        wide = any(q.startswith("wide::") for q in body["questions"])
        return {"answers": WIDE if wide else RERANK, "model": body["model"]}
    monkeypatch.setattr(mod, "_post_json", fake)
    return mod._jev_route("please commit my staged changes to git", ""), sent


def test_relay_reported_timeout_ends_the_tier_chain(tmp_path, monkeypatch):
    out, sent = _route(tmp_path, monkeypatch, json.dumps({"error": "TimeoutError"}).encode())
    assert out["result"] is None
    assert out["event"]["err"] == "TimeoutError"
    assert sent == [RELAY]                       # the gateway tier is never called


def test_other_relay_502_still_moves_to_the_next_tier(tmp_path, monkeypatch):
    out, sent = _route(tmp_path, monkeypatch, json.dumps({"error": "ConnectionResetError"}).encode())
    assert out["result"] is not None and out["event"]["tier"] == 1
    assert sent[0] == RELAY and "gw.example.net" in sent[1]


def test_unparsable_502_body_is_a_fast_failure(tmp_path, monkeypatch):
    out, sent = _route(tmp_path, monkeypatch, b"<html>bad gateway</html>")
    assert out["result"] is not None and out["event"]["tier"] == 1
    assert sent[0] == RELAY
