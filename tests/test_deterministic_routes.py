"""Deterministic routes (ADR-0054) match whole words only.

Covered:
  • every seeded route in config/deterministic-routes.json fires on a prompt that names it;
  • a route never fires inside a longer word — `/cook` inside a `/cookbooks` URL pinned ak-cook
    three times on the live ledger (2026-09-26);
  • both sides count: a letter, digit, `_` or `-` directly before or after a route blocks it;
  • punctuation, slashes, backticks, case and non-ASCII text around a route still count as a
    boundary (CJK prompts have no spaces).
Harness filters (keep-off, blocklist, foreign scopes) are neutralised here: they have their own
selftest cases; this file pins only the matching.
"""

import importlib.util
import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ENFORCER = ROOT / "hooks" / "scripts" / "enforcer.py"
ROUTES = json.loads((ROOT / "config" / "deterministic-routes.json").read_text(encoding="utf-8"))["routes"]


@pytest.fixture(scope="module")
def enf(tmp_path_factory):
    old = dict(os.environ)
    os.environ["SKILL_CONCIERGE_LOG"] = str(tmp_path_factory.mktemp("log"))
    os.environ.pop("ENFORCER_DETERMINISTIC", None)
    os.environ.pop("SKILL_CONCIERGE_ROUTES", None)
    try:
        spec = importlib.util.spec_from_file_location("enforcer_routes", ENFORCER)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        os.environ.clear()
        os.environ.update(old)
    mod._blocked = lambda _name: False
    mod.FOREIGN_SCOPES = frozenset()
    return mod


def names(enf, prompt):
    return [n for n, _d, _s in enf._route_hits(prompt)]


def test_config_loaded(enf):
    assert len(enf._ROUTES) == len(ROUTES) > 0


@pytest.mark.parametrize("route", ROUTES, ids=[r["contains"] for r in ROUTES])
def test_every_seeded_route_fires_on_its_own_prompt(enf, route):
    assert route["skill"] in names(enf, f"please {route['contains']} this now")


@pytest.mark.parametrize("prompt", [
    "study this index of cookbooks: https://docs.typesafe.ai/cookbooks",
    "what about https://docs.typesafe.ai/cookbooks/hierarchical_classification then?",
    "is the unlazyness gone?",
    "read the session-handoffs folder",
    "open xak-cook-legacy",
    "I already did commit and pushed it",
    "xunlazy now",                               # letter before, clean after: the leading side
    "run re-unlazy on it",                       # hyphen before
    "open the pre-session handoff file",         # hyphen before a multi-word route
    "see my-progress-map notes",                 # hyphen before, hyphen-free after
    "the progress-map-v2 board",                 # hyphen after
])
def test_no_route_inside_a_longer_word(enf, prompt):
    assert names(enf, prompt) == []


@pytest.mark.parametrize("prompt, skill", [
    ("(unlazy) this", "unlazy"),
    ("run `ak-cook` on it", "ak-cook"),
    ("/cook --auto the plan", "ak-cook"),
    ("write the session-handoff, then stop", "session-handoff"),
    ("UNLAZY please", "unlazy"),
    ("ok, commit & push.", "ak-git"),
    ("please work on /ak-cook --auto the issues", "ak-cook"),
    ("请用unlazy处理这个", "unlazy"),              # CJK has no spaces: only ASCII name characters continue a word
    ("dùng unlazy nhé", "unlazy"),
])
def test_boundary_punctuation_and_case(enf, prompt, skill):
    assert names(enf, prompt) == [skill]
