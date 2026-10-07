"""ADR-0083 owner reputation badges — pinned offline.

Covered:
  • tier resolution: an exact entry beats every family pattern, ❤️ beats ⭐ between two matches of
    one kind, no match -> no tier; a missing, malformed or wrong-typed file -> no badge;
    SKILL_REPUTATION=0 -> no badge anywhere;
  • 🔥 comes from the proven digest and stacks with an owner tier;
  • the menu renders badges after the name and keeps the given row order; the legend appears only
    when a shown row carries a badge;
  • pull-in appends owner-badged rows Jev ranked 6-10 whose own `fits` clears the bar, at most the
    cap, never an unbadged row, never a row past the depth, never displacing a shown row;
  • the offer event records the badges shown and the pulled rows.
"""

import importlib.util
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENFORCER = ROOT / "hooks" / "scripts" / "enforcer.py"


def _load(tmp_path, rep=None, proven=None, **env):
    tmp_path.mkdir(parents=True, exist_ok=True)
    rp, pp = tmp_path / "reputation.json", tmp_path / "proven.json"
    if rep is not None:
        rp.write_text(rep if isinstance(rep, str) else json.dumps(rep), encoding="utf-8")
    if proven is not None:
        pp.write_text(json.dumps({"proven": proven}), encoding="utf-8")
    old = dict(os.environ)
    for k in ("SKILL_REPUTATION", "SKILL_REPUTATION_PULL_FIT", "SKILL_REPUTATION_PULL_MAX",
              "SKILL_REPUTATION_PULL_DEPTH", "ENFORCER_MULTI_INTENT"):
        os.environ.pop(k, None)
    os.environ.update({"SKILL_CONCIERGE_LOG": str(tmp_path), "SKILL_CONCIERGE_REPUTATION": str(rp),
                       "SKILL_CONCIERGE_PROVEN": str(pp), "ENFORCER_MULTI_INTENT": "0", **env})
    try:
        spec = importlib.util.spec_from_file_location(
            f"enforcer_rep_{abs(hash((str(tmp_path), str(env), str(rep))))}", ENFORCER)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        os.environ.clear()
        os.environ.update(old)


REP = {"heart": ["ak-code-review", "pstack:*"], "star": ["ak-*", "pstack:recall", "code-review"]}


def test_exact_entry_beats_family_and_heart_beats_star(tmp_path):
    mod = _load(tmp_path, REP)
    assert mod._owner_tier("ak-code-review") == "heart"     # exact ❤️ inside a ⭐ family
    assert mod._owner_tier("ak-git") == "star"              # only the ⭐ family matches
    assert mod._owner_tier("pstack:recall") == "star"       # exact ⭐ beats the ❤️ family
    assert mod._owner_tier("pstack:architect") == "heart"   # ❤️ family
    assert mod._owner_tier("code-review") == "star"         # exact, not a pattern
    assert mod._owner_tier("agent-skills:code-review") is None   # exact entries match exactly
    assert mod._owner_tier("tui-fundamentals") is None


def test_same_name_in_both_tiers_is_heart(tmp_path):
    mod = _load(tmp_path, {"heart": ["x"], "star": ["x"]})
    assert mod._owner_tier("x") == "heart"


def test_bad_or_absent_files_show_no_badge(tmp_path):
    for rep in ("{not json", json.dumps(["heart"]), json.dumps({"heart": "ak-git"}), None):
        mod = _load(tmp_path / str(abs(hash(str(rep)))), rep) if rep is not None else _load(tmp_path / "none")
        assert mod._badge("ak-git") == ""


def test_kill_switch_turns_every_badge_off(tmp_path):
    mod = _load(tmp_path, REP, proven=["ak-git"], SKILL_REPUTATION="0")
    assert mod._badge("ak-code-review") == "" and mod._badge("ak-git") == ""


def test_proven_stacks_with_owner_tier(tmp_path):
    mod = _load(tmp_path, REP, proven=["ak-git", "unlazy"])
    assert mod._badge("ak-git") == " ⭐🔥"
    assert mod._badge("unlazy") == " 🔥"
    assert mod._badge("ak-code-review") == " ❤️"
    assert mod._badge("nobody") == ""


def test_menu_shows_badges_in_given_order_with_legend(tmp_path):
    mod = _load(tmp_path, REP, proven=["code-review"])
    rows = [("code-review", "Review changes.", 0.45), ("agent-skills:code-review-and-quality", "Review.", 0.20),
            ("ak-code-review", "Review code quality.", 0.11)]
    out = mod._ranked_mandate(rows, whole_shelf=True)
    lines = [ln for ln in out.splitlines() if ln.startswith("  • ")]
    assert lines[0].startswith("  • code-review ⭐🔥 (")
    assert lines[1].startswith("  • agent-skills:code-review-and-quality (")
    assert lines[2].startswith("  • ak-code-review ❤️ (")
    assert "Badges are the owner's ranking" in out


def test_no_legend_without_a_badge(tmp_path):
    mod = _load(tmp_path, REP)
    out = mod._ranked_mandate([("tui-fundamentals", "Terminal UIs.", 0.5), ("refactor", "Refactor.", 0.3)])
    assert "Badges are" not in out and "❤️" not in out and "⭐" not in out


def _answers(names, fits):
    """Choice probabilities fall with list position; fits::i follows the shortlist order."""
    probs = {n: round(1.0 - i * 0.05, 3) for i, n in enumerate(names)}
    ans = {"which": {"type": "choice", "confidence": 0.5, "probabilities": probs}}
    ans.update({f"fits::{i}": {"type": "noul", "noul": f} for i, f in enumerate(fits)})
    return ans


SHORT = [(f"s{i}", f"skill {i}") for i in range(12)]


def _rows(mod, ans):
    verdict, rows, _c, _b = mod._jev_decide(ans, SHORT)
    assert verdict == "offer"
    return rows


def test_pull_in_takes_badged_rows_below_the_cut_that_fit(tmp_path):
    mod = _load(tmp_path, {"heart": ["s6"], "star": ["s8", "s9", "s2"]})
    fits = [0.9] * 6 + [0.7, 0.9, 0.6, 0.55, 0.9, 0.9]
    ans = _answers([n for n, _ in SHORT], fits)
    rows = _rows(mod, ans)
    assert [r[0] for r in rows] == ["s0", "s1", "s2", "s3", "s4"]
    pulled = mod._jev_pull_ins(ans, SHORT, rows)
    assert [p[0] for p in pulled] == ["s6", "s8"]          # badged, fit >= 0.5, Choice order, cap 2
    assert [r[0] for r in rows] == ["s0", "s1", "s2", "s3", "s4"]   # shown rows never move


def test_pull_in_respects_bar_depth_cap_and_badges(tmp_path):
    names = [n for n, _ in SHORT]
    mod = _load(tmp_path, {"star": ["s5", "s10", "s11"]})
    ans = _answers(names, [0.9] * 5 + [0.49, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9])
    rows = _rows(mod, ans)
    assert mod._jev_pull_ins(ans, SHORT, rows) == []        # s5 under the bar; s10/s11 past depth 10
    mod2 = _load(tmp_path / "off", {"star": ["s6"]}, SKILL_REPUTATION_PULL_MAX="0")
    ans2 = _answers(names, [0.9] * 12)
    assert mod2._jev_pull_ins(ans2, SHORT, _rows(mod2, ans2)) == []
    mod3 = _load(tmp_path / "none", {})                     # nothing badged -> nothing pulled
    assert mod3._jev_pull_ins(ans2, SHORT, _rows(mod3, ans2)) == []


def test_pulled_rows_render_under_the_ranking(tmp_path):
    mod = _load(tmp_path, {"heart": ["ak-code-review"]})
    rows = [("code-review", "Review changes.", 0.45), ("refactor", "Refactor.", 0.30)]
    out = mod._ranked_mandate(rows, whole_shelf=True, pulled=[("ak-code-review", "Review code quality.", 0.02)])
    i_rank = out.index("  • refactor")
    i_block = out.index("On the owner's list, ranked lower by Jev")
    assert i_rank < i_block < out.index("  • ak-code-review ❤️ — ")


def test_offer_event_records_badges_and_pulled(tmp_path):
    mod = _load(tmp_path, {"heart": ["ak-code-review"], "star": ["code-review"]}, proven=["refactor"])
    mod._append_offer("sid", "offer", [["code-review", 0.45], ["refactor", 0.3]], None, "q",
                      pulled=[["ak-code-review", 0.02]])
    ev = json.loads((tmp_path / "skill-invocation-ledger.log").read_text().splitlines()[-1])
    assert ev["pulled"] == [["ak-code-review", 0.02]]
    assert ev["badges"] == {"code-review": "⭐", "refactor": "🔥", "ak-code-review": "❤️"}


def test_script_and_hook_resolve_every_name_the_same_way(tmp_path):
    """scripts/reputation.py `why` restates the hook's rule; they must never disagree."""
    spec = importlib.util.spec_from_file_location("reputation_script", ROOT / "scripts" / "reputation.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    mod = _load(tmp_path, REP)
    for name in ("ak-code-review", "ak-git", "pstack:recall", "pstack:architect", "code-review",
                 "agent-skills:code-review", "tui-fundamentals", "ak:plan", "pstack:"):
        assert script._resolve(name, REP)[0] == mod._owner_tier(name), name


def test_pull_in_reads_fits_by_shortlist_index_not_choice_rank(tmp_path):
    """Choice order differs from shortlist order: the fit must come from the candidate's own index."""
    mod = _load(tmp_path, {"star": ["s6"]})
    names = [n for n, _ in SHORT]
    probs = {n: round(1.0 - i * 0.05, 3) for i, n in enumerate(reversed(names))}   # s11 ranks first
    fits = [0.9] * 12
    fits[names.index("s6")] = 0.2           # s6's own fit is low; Choice rank 6 holds s5 (fit 0.9)
    ans = {"which": {"type": "choice", "confidence": 0.5, "probabilities": probs}}
    ans.update({f"fits::{i}": {"type": "noul", "noul": f} for i, f in enumerate(fits)})
    rows = _rows(mod, ans)
    assert [r[0] for r in rows] == ["s11", "s10", "s9", "s8", "s7"]
    assert mod._jev_pull_ins(ans, SHORT, rows) == []          # s6 is at rank 6, but its own fit is 0.2
    fits[names.index("s6")] = 0.6
    ans.update({f"fits::{i}": {"type": "noul", "noul": f} for i, f in enumerate(fits)})
    assert [p[0] for p in mod._jev_pull_ins(ans, SHORT, rows)] == ["s6"]


def test_external_and_other_harness_rows_carry_no_owner_badge(tmp_path):
    mod = _load(tmp_path, {"star": ["*:*"]})
    out = mod._ranked_mandate([("pstack:architect", "Design.", 0.5), ("refactor", "Refactor.", 0.3)],
                              annex=[("antigravity:x", "Ext.", 0.4, "antigravity")],
                              foreign=[("vercel:mw", "Other.", 0.4, "codex")])
    assert "pstack:architect ⭐" in out
    assert "antigravity:x [external" in out and "antigravity:x ⭐" not in out
    assert "vercel:mw [codex]" in out and "vercel:mw ⭐" not in out


def test_proven_only_menu_gets_the_short_legend(tmp_path):
    mod = _load(tmp_path, {}, proven=["refactor"])
    out = mod._ranked_mandate([("refactor", "Refactor.", 0.5), ("ak-git", "Git.", 0.3)])
    assert "🔥 = used often here" in out and "Badges are the owner's ranking" not in out
    mod2 = _load(tmp_path / "both", {"star": ["ak-git"]}, proven=["refactor"])
    out2 = mod2._ranked_mandate([("refactor", "Refactor.", 0.5), ("ak-git", "Git.", 0.3)])
    assert "Badges are the owner's ranking" in out2 and "🔥 = used often here" not in out2


def test_env_typos_and_bad_patterns_never_break_the_hook(tmp_path):
    mod = _load(tmp_path, {"star": ["[z-a]*", "ak-*"]}, SKILL_REPUTATION_PULL_FIT="0,5",
                SKILL_REPUTATION_PULL_MAX="two", SKILL_REPUTATION_PULL_DEPTH="-3")
    assert mod.REPUTATION_PULL_FIT == 0.5 and mod.REPUTATION_PULL_MAX == 2 and mod.REPUTATION_PULL_DEPTH == 0
    assert mod._badge("ak-git") == " ⭐" and mod._badge("zz") == ""


def test_skip_rows_record_no_badges(tmp_path):
    mod = _load(tmp_path, {"star": ["ak-git"]})
    mod._append_offer("sid", "jev_skip", [["ak-git", 0.1]], "jev_no_fit", "q")
    ev = json.loads((tmp_path / "skill-invocation-ledger.log").read_text().splitlines()[-1])
    assert "badges" not in ev


def test_reputation_script_selftest_covers_every_suggestion_rule():
    import subprocess, sys
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "reputation.py"), "selftest"],
                       capture_output=True, text=True, check=False)
    assert r.returncode == 0 and "reputation selftest ok" in r.stdout, r.stdout + r.stderr
