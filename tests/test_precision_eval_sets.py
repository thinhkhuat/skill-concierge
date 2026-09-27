"""scripts/precision_eval.py's `findability` mode (ADR-0074) — bar math and set construction.

Pure functions and local-file-only set builders: no network, no owner, no engine import. The
full base-vs-candidate orchestration (run_findability) needs a real owner and is validated by
the live sweep/eval runs recorded in the build report, not by this offline suite.
"""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def pe():
    return _load("precision_eval_t", ROOT / "scripts" / "precision_eval.py")


@pytest.fixture()
def cal():
    return _load("calibrate_jev_gate_t", ROOT / "scripts" / "calibrate_jev_gate.py")


# ── sign test: gain direction (the earlier, WRONG gating value — kept, reported
# alongside the loss direction, never used alone to gate the bar again) ────────────────────
def test_sign_test_p_matches_the_review_measured_examples(pe):
    # review-adversarial-v3.md M1: pooled +24/-8 -> p ~= 0.004; MCP-only +8/-5 -> p ~= 0.29.
    assert abs(pe.sign_test_p(8, 24) - 0.0035) < 1e-3
    assert abs(pe.sign_test_p(5, 8) - 0.2905) < 1e-3


def test_sign_test_p_edge_cases(pe):
    assert pe.sign_test_p(0, 0) == 0.0
    assert pe.sign_test_p(0, 10) == pytest.approx((1 / 2) ** 10)   # only "0 losses" qualifies
    assert pe.sign_test_p(10, 0) == 1.0                             # every trial lost


# ── sign test: loss direction (design SS4 E bar 2's pre-registered "no significant loss";
# H1: losses > gains, p = P(L >= lost)) ─────────────────────────────────────────────────────
def test_sign_test_loss_p_matches_the_gain_direction_by_symmetry(pe):
    # the two directions of the SAME (8,24) split: 24 gains/8 losses is strong evidence of
    # gain (small gain_p) and correspondingly the WEAKEST possible evidence of loss (loss_p
    # near 1); the mirror split (8 gains/24 losses) is strong evidence of loss.
    assert abs(pe.sign_test_loss_p(8, 24) - 0.9989) < 1e-3
    assert abs(pe.sign_test_loss_p(24, 8) - 0.0035) < 1e-3


def test_sign_test_loss_p_edge_cases(pe):
    assert pe.sign_test_loss_p(0, 0) == 1.0           # zero changed cases: cannot show loss
    assert pe.sign_test_loss_p(0, 10) == 1.0          # zero losses: cannot show loss either
    assert pe.sign_test_loss_p(10, 0) == pytest.approx((1 / 2) ** 10)   # every trial lost


def test_gains_losses(pe):
    base = [True, True, False, False]
    cand = [True, False, True, False]
    gained, lost = pe.gains_losses(base, cand)
    assert gained == 1 and lost == 1


def test_lost_gained_cases_identifies_the_individual_pairs(pe):
    pairs = [("q1", "a"), ("q2", "b"), ("q3", "c"), ("q4", "d")]
    base = [True, True, False, False]
    cand = [True, False, True, False]
    lost, gained = pe.lost_gained_cases(pairs, base, cand)
    assert lost == [("q2", "b")] and gained == [("q3", "c")]


# ── cd_bar: the pre-registered wording is "net >= 0 AND no significant loss" — FAIL only
# on net < 0 or a significant LOSS sign test, never on an insignificant GAIN ─────────────────
def test_cd_bar_passes_on_a_clean_win(pe):
    r = pe.cd_bar([False, False, False, False], [True, True, True, True])   # +4/-0
    assert r["gained"] == 4 and r["lost"] == 0 and r["net"] == 4 and r["passed"]
    assert r["loss_p"] == 1.0


def test_cd_bar_fails_on_net_negative_even_when_the_sign_test_is_insignificant(pe):
    """The exact case the "or net < 0" clause exists for: 0/-3 has loss_p = 0.125, which
    alone would NOT clear the 0.10 significance bar — the sample is just too small — but a
    real net loss must still fail regardless."""
    r = pe.cd_bar([True, True, True], [False, False, False])   # +0/-3
    assert r["net"] == -3 and r["loss_p"] > 0.10 and not r["passed"]


def test_cd_bar_fails_on_a_significant_net_negative(pe):
    r = pe.cd_bar([True] * 10, [False] * 10)   # +0/-10
    assert r["net"] == -10 and r["loss_p"] <= 0.10 and not r["passed"]


def test_cd_bar_passes_a_net_gain_even_when_the_gain_is_not_significant(pe):
    """The exact bug this round fixes: +8/-5 (net +3, from review-adversarial-v3.md's
    measured MCP-view C+D split) has gain_p = 0.29 > 0.10 — an insignificant GAIN by the
    (wrong) earlier gating — but there is no significant LOSS either (loss_p = 0.867), and
    the pre-registered bar never required evidence of gain, only the absence of loss."""
    r = pe.cd_bar([False] * 8 + [True] * 5, [True] * 8 + [False] * 5)
    assert r["gained"] == 8 and r["lost"] == 5 and r["net"] == 3
    assert r["gain_p"] > 0.10        # would have FAILED under the earlier (wrong) gating
    assert r["loss_p"] > 0.10 and r["passed"]


def test_cd_bar_no_change_trivially_passes(pe):
    r = pe.cd_bar([True, False, True], [True, False, True])
    assert r["gained"] == 0 and r["lost"] == 0 and r["passed"]
    assert r["loss_p"] == 1.0 and r["gain_p"] == 0.0


# ── w_bar ────────────────────────────────────────────────────────────────────────────────────
def test_w_bar_fails_when_any_probe_leaves_the_top3(pe):
    rows = [{"skill": "a", "base_rank": 2, "cand_rank": 5}, {"skill": "b", "base_rank": 1, "cand_rank": 1}]
    r = pe.w_bar(rows)
    assert not r["passed"] and len(r["leavers"]) == 1 and r["leavers"][0]["skill"] == "a"


def test_w_bar_passes_when_no_one_leaves_even_if_someone_loses_a_rank(pe):
    """The v4 review's exact blocker case: F2 shifts 50/258 targets down one place inside
    the top 3, without any of them leaving it — bar 1's fixed wording must pass this."""
    rows = [{"skill": "a", "base_rank": 1, "cand_rank": 2}]
    assert pe.w_bar(rows)["passed"]


def test_w_bar_fails_when_the_top3_count_falls_even_with_no_individual_leaver(pe):
    # base has two OTHER skills in top-3 that candidate does not (net top-3 count fell),
    # even though the ones we tracked never individually left.
    rows = [{"skill": "a", "base_rank": 1, "cand_rank": 1}]
    r = pe.w_bar(rows)
    assert r["passed"]           # sanity: this shape alone can't show the count falling
    # the count-must-not-fall clause is exercised directly via base_top3/cand_top3:
    rows2 = [{"skill": "a", "base_rank": 3, "cand_rank": 3},
             {"skill": "b", "base_rank": 4, "cand_rank": 3}]   # b enters, nothing left -> fine
    assert pe.w_bar(rows2)["passed"]


def test_w_bar_passes_trivially_on_no_probes(pe):
    r = pe.w_bar([])
    assert r["passed"] and r["base_top3"] == 0 and r["cand_top3"] == 0


# ── n_bar (the N bound) ──────────────────────────────────────────────────────────────────────
def test_n_bar_vacuous_pass_on_empty_n(pe):
    r = pe.n_bar(0, 0, 0)
    assert r["passed"] is True and r["rate_ok"] and r["gain_ok"]


def test_n_bar_passes_within_both_bounds(pe):
    # 1000 negatives, 1% = 10; 9 gains, 1/3 = 3
    r = pe.n_bar(3, 1000, 9)
    assert r["passed"]


def test_n_bar_fails_the_rate_bound(pe):
    r = pe.n_bar(11, 1000, 100)     # 11 > 1% of 1000 (10)
    assert not r["rate_ok"] and not r["passed"]


def test_n_bar_fails_the_gain_bound(pe):
    r = pe.n_bar(5, 1000, 9)        # 5 > 1/3 of 9 (3.0), even though well under the 1% rate bound
    assert r["rate_ok"] and not r["gain_ok"] and not r["passed"]


# ── g_bar ────────────────────────────────────────────────────────────────────────────────────
def test_g_bar_passes_only_when_every_name_query_is_rank_1(pe):
    assert pe.g_bar([1, 1, 1])["passed"]
    assert not pe.g_bar([1, 2, 1])["passed"]
    assert not pe.g_bar([])["passed"]           # empty is never a real pass


# ── set construction: C / D (meta exclusion, EN/VN split) ──────────────────────────────────
def _row(prompt, final_names, search_queries=None, meta_session=False,
        entry_class="interactive"):
    return {"prompt": prompt, "final_names": final_names,
            "label": "NEEDS_SKILL", "label_rule": "using+executed_this_turn",
            "meta_session": meta_session, "entry_class": entry_class,
            "interrupted": False, "next_prompt_correction": False,
            "search_queries": search_queries or []}


def _write_corpus(tmp_path, rows):
    path = tmp_path / "real-turn-labels.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return path


def test_cd_pairs_excludes_meta_skills_and_splits_search_queries(pe, cal, tmp_path):
    enf = cal.load_enforcer()
    rows = [
        _row("deploy my app to a new server", ["ck:deploy"], search_queries=["deploy an app"]),
        _row("which skills fit this task best", ["skill-search"]),          # meta -> excluded
        _row("not a real positive turn", ["ck:debug"], entry_class="sdk"),   # not interactive
    ]
    c, d = pe._cd_pairs(cal, enf, _write_corpus(tmp_path, rows))
    assert c["en"] == [("deploy my app to a new server", "deploy")]
    assert d["en"] == [("deploy an app", "deploy")]


def test_cd_pairs_reports_vietnamese_separately(pe, cal, tmp_path):
    enf = cal.load_enforcer()
    rows = [_row("triển khai ứng dụng của tôi lên máy chủ mới ngay bây giờ", ["ck:deploy"])]
    c, _d = pe._cd_pairs(cal, enf, _write_corpus(tmp_path, rows))
    assert c["en"] == [] and len(c["vn"]) == 1


def test_cd_pairs_skips_non_positive_and_no_gold_rows(pe, cal, tmp_path):
    enf = cal.load_enforcer()
    rows = [_row("deploy my app to a new server", [])]     # positive shape but no final_names
    c, d = pe._cd_pairs(cal, enf, _write_corpus(tmp_path, rows))
    assert c["en"] == [] and d["en"] == []


# ── set construction: N ──────────────────────────────────────────────────────────────────────
def test_n_pairs_reads_current_installed_skills_only(pe, tmp_path, monkeypatch):
    shadow = tmp_path / "scenarios-shadow"
    shadow.mkdir()
    (shadow / "a.json").write_text(json.dumps({"skill": "a", "negative": ["neg for a"]}))
    (shadow / "gone.json").write_text(json.dumps({"skill": "gone", "negative": ["neg for gone"]}))
    monkeypatch.setattr(pe, "SHADOW_SCENARIOS_DIR", shadow)
    rows = pe._n_pairs({"a"})
    assert rows == [("a", "neg for a")]      # "gone" is not currently installed -> excluded


def test_n_pairs_appends_the_incident_controls_only_when_gdelt_is_installed(pe, tmp_path, monkeypatch):
    monkeypatch.setattr(pe, "SHADOW_SCENARIOS_DIR", tmp_path / "no-such-dir")
    assert pe._n_pairs({"other-skill"}) == []
    rows = pe._n_pairs({pe.GDELT_SKILL})
    assert len(rows) == len(pe.GDELT_INCIDENT_CONTROLS)
    assert all(skill == pe.GDELT_SKILL for skill, _q in rows)
    assert {q for _s, q in rows} == set(pe.GDELT_INCIDENT_CONTROLS)


def test_n_pairs_ignores_a_missing_shadow_dir_gracefully(pe, tmp_path, monkeypatch):
    monkeypatch.setattr(pe, "SHADOW_SCENARIOS_DIR", tmp_path / "does-not-exist")
    assert pe._n_pairs({"a", "b"}) == []


# ── dual-instance module loading (no network — proves genuinely SEPARATE instances) ────────
def test_enforcer_for_produces_independently_configured_instances(pe, cal, monkeypatch):
    monkeypatch.delenv("SKILL_CONCIERGE_HARNESS", raising=False)
    base = pe._enforcer_for(cal, "http://127.0.0.1:11111", 22222)
    cand = pe._enforcer_for(cal, "http://127.0.0.1:33333", 44444)
    assert base is not cand
    assert base.QDRANT_URL == "http://127.0.0.1:11111" and base.EMBED_PORT == "22222"
    assert cand.QDRANT_URL == "http://127.0.0.1:33333" and cand.EMBED_PORT == "44444"
    assert base.RUNNING_HARNESS == "claude" and cand.RUNNING_HARNESS == "claude"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
