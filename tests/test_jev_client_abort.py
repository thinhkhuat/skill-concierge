"""jev_client.ask stops starting requests once one batch of the same ask has failed (no spend on a doomed
answer). Offline: Jev is replaced at `_post_json`."""

import importlib.util
import time
import urllib.error
import io
from pathlib import Path

import pytest

CLIENT = Path(__file__).resolve().parents[1] / "scripts" / "jev_client.py"


@pytest.fixture
def jc(monkeypatch):
    for k in ("ENFORCER_JEV_BENCH", "FLYWHEEL_LLM_ENDPOINT", "FLYWHEEL_LLM_API_KEY", "ENFORCER_JEV_URL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("TYPESAFE_API_KEY", "dummy-key")
    spec = importlib.util.spec_from_file_location(f"jev_client_abort_{time.time_ns()}", CLIENT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_a_failed_batch_stops_the_remaining_batches(jc, monkeypatch):
    enf = jc.load_enforcer()
    sent = []

    def post(url, body, timeout, headers=None):
        sent.append(sorted(body["questions"]))
        raise urllib.error.HTTPError(url, 500, "x", {}, io.BytesIO(b"{}"))
    monkeypatch.setattr(enf, "_post_json", post)
    qs = {f"q{i}": {"type": "noul", "instructions": "word " * 1500} for i in range(120)}
    n = len(jc.batches({}, qs))
    assert n > 2
    with pytest.raises(jc.JevError):
        jc.ask({}, qs, timeout=1.0, workers=1)
    assert len(sent) == 1        # the first batch failed; no other batch was sent
