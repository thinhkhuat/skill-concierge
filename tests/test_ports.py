"""Unit tests for vendor/skill-search/skill_search/ports.py's pure grammar functions,
against the shared case table (tests/port_cases.py). Every OTHER caller's agreement with
this exact grammar is proven separately by tests/test_port_agreement.py, which runs each
caller's REAL code — this file only proves the grammar itself is correct in isolation.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor" / "skill-search"))
from skill_search import ports  # noqa: E402

from port_cases import SCALAR_CASES, URL_CASES  # noqa: E402


@pytest.mark.parametrize("raw,valid", SCALAR_CASES)
def test_parse_port_matches_the_shared_case_table(raw, valid):
    default = object()   # a sentinel the grammar must never accidentally coerce/compare
    result = ports.parse_port(raw, default)
    assert result == (valid if valid is not None else default)


@pytest.mark.parametrize("url,default_port,expected", URL_CASES)
def test_safe_url_matches_the_shared_case_table(url, default_port, expected):
    assert ports.safe_url(url, default_port) == expected


@pytest.mark.parametrize("url,default_port,expected", URL_CASES)
def test_url_port_agrees_with_safe_url_on_the_same_table(url, default_port, expected):
    """url_port derives the SAME port safe_url substituted or kept, https included: one
    fallback rule, so a caller that derives a port and one that rebuilds a URL never disagree."""
    from urllib.parse import urlsplit
    got = ports.url_port(url, default_port)
    want = urlsplit(expected).port
    assert got == want


def test_safe_url_never_raises_on_pathological_input():
    for bad in (None, "not a url at all", "http://" + "x" * 5000, "http://[unterminated",
                "http://host:" + "9" * 40):
        ports.safe_url(bad, 6333)   # must not raise


def test_embed_port_prefers_owner_override_over_shim_port():
    assert ports.embed_port({"SKILL_OWNER_EMBED_PORT": "7333", "EMBED_SHIM_PORT": "7444"}) == 7333
    assert ports.embed_port({"EMBED_SHIM_PORT": "7444"}) == 7444
    assert ports.embed_port({}) == 6363


def test_query_port_prefers_owner_override_over_qdrant_url():
    assert ports.query_port({"SKILL_OWNER_QUERY_PORT": "7333",
                              "SKILL_QDRANT_URL": "http://127.0.0.1:7444"}) == 7333
    assert ports.query_port({"SKILL_QDRANT_URL": "http://127.0.0.1:7444"}) == 7444
    assert ports.query_port({}) == 6333


def test_resolved_qdrant_url_notice_only_on_an_actual_fallback():
    url, notice = ports.resolved_qdrant_url({"SKILL_QDRANT_URL": "http://127.0.0.1:7333"})
    assert url == "http://127.0.0.1:7333" and notice is None
    url, notice = ports.resolved_qdrant_url({"SKILL_QDRANT_URL": "http://127.0.0.1:notaport"})
    assert url == "http://127.0.0.1:6333" and "notaport" in notice
    url, notice = ports.resolved_qdrant_url({})
    assert url == "http://localhost:6333" and notice is None


def test_resolved_query_port_and_embed_port_notices():
    port, notice = ports.resolved_query_port({"SKILL_OWNER_QUERY_PORT": "70000"})
    assert port == 6333 and "70000" in notice
    port, notice = ports.resolved_embed_port({"EMBED_SHIM_PORT": "-5"})
    assert port == 6363 and "-5" in notice
    port, notice = ports.resolved_embed_port({})
    assert port == 6363 and notice is None
