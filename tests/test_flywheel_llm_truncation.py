"""Tests for flywheel_llm.chat()'s handling of a truncated completion.

Background (2026-07-10). The generators constrain output with an OpenAI
`response_format: json_schema`. LM Studio enforces that schema strictly — including
`pattern` and `minItems`. A regex the model is unlikely to satisfy (say, one requiring
a Vietnamese character while the prompt asks for English) masks the string-closing
quote until the obligation is met. The model emits non-quote characters until it hits
`max_tokens`, and the server returns a TRUNCATED, unterminated JSON string with
`finish_reason == "length"`.

`chat()` read only `choices[0].message.content` and never looked at `finish_reason`, so
a truncation was indistinguishable from any other bad reply: it surfaced as a
JSONDecodeError, which `llm_triggers.run()` catches with a bare `except`, prints WARN,
and drops the skill from the utterance layer. A silent per-skill coverage loss.

The nastiest variant is the third test below: a truncation that happens to leave
*parseable* JSON. Parsing alone cannot detect it — only `finish_reason` can. That is why
the guard keys on the field rather than on whether the body parses.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import flywheel_llm  # noqa: E402


class _FakeResponse:
    """Minimal stand-in for the object urlopen() yields as a context manager."""

    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _completion(content: str, finish_reason: str) -> dict:
    return {"choices": [{"message": {"content": content}, "finish_reason": finish_reason}]}


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    """chat() sleeps rate_s between calls; keep the suite fast."""
    monkeypatch.setattr(flywheel_llm.time, "sleep", lambda *_: None)


def _patch_response(monkeypatch, payload: dict):
    monkeypatch.setattr(flywheel_llm.urllib.request, "urlopen",
                        lambda *a, **k: _FakeResponse(payload))


def test_stop_with_valid_json_returns_parsed(monkeypatch):
    """The happy path must keep working: finish_reason=stop -> parsed dict."""
    _patch_response(monkeypatch, _completion('{"triggers": ["a", "b"]}', "stop"))
    assert flywheel_llm.chat("sys", "user", rate_s=0) == {"triggers": ["a", "b"]}


def test_truncated_completion_raises_not_jsondecodeerror(monkeypatch):
    """finish_reason=length with an unterminated string must fail LOUDLY and
    name the cause — not surface as an opaque JSONDecodeError."""
    truncated = '{"triggers": ["Commit your changes often and write clear messages'
    _patch_response(monkeypatch, _completion(truncated, "length"))
    with pytest.raises(flywheel_llm.TruncatedCompletion) as exc:
        flywheel_llm.chat("sys", "user", rate_s=0)
    assert "length" in str(exc.value)


def test_truncation_that_still_parses_is_rejected(monkeypatch):
    """The dangerous case. A `length` cut can leave syntactically valid JSON that is
    semantically short (here: 2 triggers, not the 10 requested). Parsing cannot catch
    it; only finish_reason can. Guard must key on the field, not on parseability."""
    _patch_response(monkeypatch, _completion('{"triggers": ["a", "b"]}', "length"))
    with pytest.raises(flywheel_llm.TruncatedCompletion):
        flywheel_llm.chat("sys", "user", rate_s=0)


def test_content_filter_and_other_terminal_reasons_raise(monkeypatch):
    """Any finish_reason other than stop means the completion is not whole."""
    _patch_response(monkeypatch, _completion('{"triggers": ["a"]}', "content_filter"))
    with pytest.raises(flywheel_llm.TruncatedCompletion):
        flywheel_llm.chat("sys", "user", rate_s=0)


def test_absent_finish_reason_is_tolerated(monkeypatch):
    """Fail-open on an ABSENT field: some OpenAI-compatible gateways omit it, and a
    missing field is not evidence of truncation. Fail-closed only on an explicit
    non-stop value."""
    payload = {"choices": [{"message": {"content": '{"triggers": ["a"]}'}}]}
    _patch_response(monkeypatch, payload)
    assert flywheel_llm.chat("sys", "user", rate_s=0) == {"triggers": ["a"]}


def test_truncation_is_not_retried_as_a_transient(monkeypatch):
    """A truncation is deterministic given the same prompt+schema. Retrying burns GPU
    for the same result, so the guard must raise on the FIRST response, calling the
    endpoint exactly once."""
    calls = []

    def _spy(*a, **k):
        calls.append(1)
        return _FakeResponse(_completion('{"t": ["x"', "length"))

    monkeypatch.setattr(flywheel_llm.urllib.request, "urlopen", _spy)
    with pytest.raises(flywheel_llm.TruncatedCompletion):
        flywheel_llm.chat("sys", "user", rate_s=0)
    assert len(calls) == 1, f"expected exactly 1 request, got {len(calls)}"
