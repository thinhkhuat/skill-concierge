"""The smoke pass rule: a harness passes only when its run wrote an offer row (the per-turn enforcer
ran) and a search row (search_skills reached the model). A turn row alone is written by ledger.py, so
it never proves the enforcer ran: that gap hid Codex skipping the enforcer after a hook change."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import smoke  # noqa: E402


def test_offer_and_search_pass():
    assert smoke.verdict([{"ev": "turn"}, {"ev": "offer", "band": "offer"}, {"ev": "search"}]) == ("PASS", "offer + search")


def test_a_turn_row_without_an_offer_row_fails():
    status, detail = smoke.verdict([{"ev": "turn"}, {"ev": "search"}])
    assert status == "FAIL" and "enforcer did not run" in detail


def test_hook_rows_without_a_search_row_fail():
    status, detail = smoke.verdict([{"ev": "turn"}, {"ev": "offer", "band": "offer"}])
    assert status == "FAIL" and "search_skills did not reach the model" in detail


def test_an_early_exit_band_fails_because_retrieval_never_ran():
    for band in ("negation", "harness_skip", "fallback", "getaway"):
        status, detail = smoke.verdict([{"ev": "offer", "band": band}, {"ev": "search"}])
        assert status == "FAIL" and "before retrieval" in detail, band
    assert smoke.verdict([{"ev": "offer", "band": "jev_skip"}, {"ev": "search"}])[0] == "PASS"


def test_an_empty_ledger_fails_on_both_signals():
    status, detail = smoke.verdict([])
    assert status == "FAIL" and "offer" in detail and "search" in detail


def test_a_missing_command_line_fails_instead_of_skipping():
    assert smoke.verdict([{"ev": "offer", "band": "offer"}, {"ev": "search"}], cli_found=False)[0] == "FAIL"


def test_zcode_is_unproven_and_fails_the_run_unless_accepted(capsys):
    assert smoke.smoke("zcode")[0] == "UNPROVEN"
    assert smoke.main(["zcode"]) == 1
    assert smoke.main(["zcode", "--accept-unproven", "zcode"]) == 0
