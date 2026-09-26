"""`scripts/calibrate_jev_gate.py live` — the epoch-watch W21-W24 report — pinned on a fixture
ledger and label corpus (no network: the live catalogue is replaced).

Covered:
  • only v0.51.0 router rows count: v0.50.0 yes/no rows (`jev.p`), their unmarked `{err, ms}` rows,
    other harnesses and rows before --since do not; an unmarked error takes its session's kind;
    one with no earlier row is reported as unattributed; a malformed line is skipped;
  • W23 latency percentiles, error share and relay/direct split;
  • W24 drift against the replay's catalogue snapshot;
  • W22 tail rows (after the lead) below p 0.01 on live offers;
  • W21 jev_skip turns where the agent then used a skill — printed by id, never by prompt text;
  • W22 offer quality per slice (interactive, sdk, dev sessions): error rows, interrupted or
    corrected turns, other label rules and used skills outside the catalogue are left out;
  • `--since` with an explicit offset means the same instant.
"""

import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import calibrate_jev_gate as C  # noqa: E402

SINCE = "2026-09-26T10:03"
T0 = 1790391780.0 + 60          # 2026-09-26 10:04 +07
PRIVATE = "commit the work now"


def _offer(dt, jev, band="offer", offered=None, sid="s", harness="claude"):
    return {"t": T0 + dt, "sid": sid, "ev": "offer", "band": band, "q": "x", "harness": harness,
            "offered": offered if offered is not None else [["ak-git", 0.8], ["b", 0.1], ["c", 0.005]], "jev": jev}


def _turn(**kw):
    base = {"sid": "abcdef123", "uuid": "u1", "ts_local": "2026-09-26T10:30:00+07:00", "prompt": PRIVATE,
            "ledger_jev": {"ms": 800, "fit": 0.9, "via": "relay", "n": 494}, "ledger_offer_band": "offer",
            "ledger_offered": [["plug:ak-git", 0.9], ["b", 0.05]], "label": "NEEDS_SKILL",
            "label_rule": "using+executed_this_turn", "final_names": ["ak-git"], "entry_class": "interactive",
            "meta_session": False, "interrupted": False, "next_prompt_correction": None}
    return base | kw


@pytest.fixture
def run(tmp_path, monkeypatch, capsys):
    # load_enforcer() setdefaults these for replay; keep them from leaking into later tests
    monkeypatch.setenv("ENFORCER_EMBED_TIMEOUT", "15")
    monkeypatch.setenv("ENFORCER_QDRANT_TIMEOUT", "15")
    snap = tmp_path / "invocable-catalog.json"
    snap.write_text(json.dumps([["x", "d"]] * 494))
    monkeypatch.setattr(C, "CATALOG_SNAPSHOT", snap)
    monkeypatch.setattr(C, "live_catalog", lambda: [["plug:ak-git", "d"], ["b", "d"], ["other", "d"]])

    def go(rows, turns, since=SINCE, harness="claude"):
        ledger = tmp_path / "ledger.log"
        ledger.write_text("".join(r if isinstance(r, str) else json.dumps(r) + "\n" for r in rows))
        corpus = tmp_path / "labels.jsonl"
        corpus.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in turns))
        monkeypatch.setattr(C, "LEDGER", ledger)
        assert C.cmd_live(types.SimpleNamespace(since=since, corpus=corpus, harness=harness)) == 0
        return capsys.readouterr().out
    return go


LEDGER_ROWS = [
    _offer(-3600, {"ms": 700, "fit": 0.9, "via": "relay", "n": 494}),                   # before --since
    _offer(-3000, {"p": 0.41, "ms": 400}, sid="old"),                                   # v0.50.0 session
    _offer(1, {"p": 0.41, "ms": 400}, sid="old"),                                       # v0.50.0 leg
    _offer(1.5, {"err": "URLError", "ms": 1500}, sid="old"),                            # v0.50.0 unmarked error
    "{not json\n",                                                                       # malformed line
    _offer(2, {"ms": 800, "fit": 0.9, "via": "relay", "n": 490}),
    _offer(3, {"ms": 900, "fit": 0.8, "via": "relay", "n": 500}),
    _offer(4, {"ms": 2000, "fit": 0.7, "via": "direct", "n": 494}),
    _offer(5, {"ms": 700, "fit": 0.2, "via": "relay", "n": 494}, band="jev_skip", offered=[]),
    _offer(6, {"err": "TimeoutError", "ms": 3000, "leg": "router"}, sid="new"),         # marked router error
    _offer(7, {"err": "ValueError", "ms": 900}),                                         # unmarked, router session
    _offer(8, {"err": "URLError", "ms": 900}, sid="fresh"),                              # unmarked, no history
    _offer(9, {"ms": 600, "fit": 0.9, "via": "relay", "n": 494}, harness="omp"),        # another harness
    {"t": T0 + 10, "sid": "s", "ev": "search"},
]

TURNS = [
    _turn(),                                                                    # hit
    _turn(final_names=["other"]),                                               # miss
    _turn(entry_class="sdk"),                                                   # sdk hit
    _turn(meta_session=True, final_names=["other"]),                            # dev-session miss
    _turn(ledger_offer_band="jev_skip", ledger_offered=[], uuid="u-skip"),      # W21 used a skill
    _turn(ledger_jev={"p": 0.4, "ms": 300}),                                    # v0.50.0 row
    _turn(ledger_jev={"err": "TimeoutError", "ms": 3000, "leg": "router"}),     # router failed
    _turn(ts_local="2026-09-26T09:00:00+07:00"),                                # before --since
    _turn(interrupted=True),                                                    # interrupted
    _turn(next_prompt_correction="dodge"),                                      # corrected next turn
    _turn(label_rule="loaded_earlier"),                                         # another label rule
    _turn(final_names=["external-only"]),                                       # used skill not in the catalogue
]


def test_live_report(run):
    out = run(LEDGER_ROWS, TURNS)
    assert "router rows since 2026-09-26T10:03+07:00 (claude): 6 (4 routed, 2 errors; 1 unattributed error rows left out)" in out
    assert "W23 latency ms p50 800 p90 2000" in out
    assert "errors 33.3% {'TimeoutError': 1, 'ValueError': 1}" in out and "via {'relay': 3, 'direct': 1}" in out
    assert "W24 catalogue size on rows: median 494 min 490 max 500; replay catalogue 494" in out
    assert "this cwd now 3; drift from the replay 0%" in out
    assert "W22 tail rows on live offers: 6; below p 0.01: 50%" in out
    assert "W21 jev_skip turns: 1; of them the agent then used a skill: 1" in out
    assert "session abcdef123 turn u-skip at 2026-09-26T10:30 used ['ak-git']" in out
    assert "W22 interactive (replay population): used skill in the offer 1/2 (50%)" in out
    assert "W22 sdk / claude -p: used skill in the offer 1/1 (100%)" in out
    assert "W22 skill-concierge dev sessions: used skill in the offer 0/1 (0%)" in out
    assert PRIVATE not in out


def test_since_with_offset_is_the_same_instant(run):
    out = run(LEDGER_ROWS, TURNS, since="2026-09-26T03:03:00+00:00")
    assert "(claude): 6 (4 routed, 2 errors;" in out and "W21 jev_skip turns: 1;" in out


def test_other_harness_reports_the_ledger_only(run):
    out = run(LEDGER_ROWS, TURNS, harness="omp")
    assert "(omp): 1 (1 routed, 0 errors;" in out
    assert "W21/W22 skipped: the label corpus holds Claude Code transcripts only" in out
