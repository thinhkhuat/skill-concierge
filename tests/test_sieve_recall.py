"""Consult sieve recall instrument (scripts/sieve_recall.py) — pinned offline.

No engine, no gateway, no live index: the label corpus rows, the index points, the chat client and
the server module are all fakes. The live build, generation and gate runs are separate steps.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import sieve_recall as S  # noqa: E402


def pts(*names, external=()):
    return [{"name": n, "tier": "external" if n in external else None} for n in names]


def row(uuid, sid, labels, prompt="please do the thing for me right now ok", offered=None, words=12):
    return {"uuid": uuid, "sid": sid, "final_names": labels, "prompt": prompt, "prompt_words": words,
            "ledger_offered": offered, "consult_call": False}


@pytest.fixture(autouse=True)
def private_paths_in_tmp(tmp_path, monkeypatch):
    """No test may create or chmod the real private calibration dir."""
    cal = tmp_path / "jev-calibration"
    monkeypatch.setattr(S, "HOME", tmp_path)
    monkeypatch.setattr(S, "CAL_DIR", cal)
    for name, fname in (("LABELS", "real-turn-labels.jsonl"), ("CONSULT_EVAL", "consult-eval.jsonl"),
                        ("CASES", "sieve-eval-cases.jsonl"), ("QUERIES", "sieve-eval-queries.jsonl"),
                        ("LOCK", "sieve-eval-queries.lock"), ("MANIFEST", "sieve-eval-manifest.json")):
        monkeypatch.setattr(S, name, cal / fname)


def test_label_resolves_to_the_exact_indexed_name():
    idx = S.build_name_index(pts("ak-plan", "a:review", "b:review"))
    assert S.resolve_label("ak:plan", idx) == ("ak-plan", "key")
    assert S.resolve_label("ak-plan", idx) == ("ak-plan", "exact")
    assert S.resolve_label("review", idx) == (None, "ambiguous")
    assert S.resolve_label("nothing", idx) == (None, "missing")
    cases, stats = S.build_cases([row("u1", "s1", ["review", "ak:plan"])], pts("ak-plan", "a:review", "b:review"),
                                 set(), set(), lambda r: True)
    assert [c["label"] for c in cases] == ["ak-plan"]
    assert stats["ambiguous"] == ["review"]


def test_hit_uses_the_full_skill_key_never_the_short_name():
    assert S.hit_at("ak-plan", [{"name": "other"}, {"name": "ak:plan"}], 20)
    assert not S.hit_at("x:review", [{"name": "review"}], 20)
    assert not S.hit_at("ak-plan", [{"name": "ak:plan"}], 0)


def test_label_named_in_prompt_as_a_whole_token_is_dropped():
    assert S.named_in_prompt("session-handoff", "run session-handoff now")
    assert S.named_in_prompt("ak-plan", "use /ak:plan please")
    assert not S.named_in_prompt("session-handoff", "my-session-handoffs are long")
    cases, stats = S.build_cases([row("u1", "s1", ["session-handoff"], prompt="run session-handoff now ok please do it")],
                                 pts("session-handoff"), set(), set(), lambda r: True)
    assert cases == [] and stats["named_dropped"] == ["session-handoff"]


def test_leak_check_drops_cases_on_label_words_of_four_letters_or_more():
    assert S.leaks("session-handoff", ["write the handoff document"])
    assert not S.leaks("ak-git", ["commit with git and push"])
    assert not S.leaks("session-handoff", ["write a hand off note"])
    cases = [{"id": "a", "key": "session-handoff"}, {"id": "b", "key": "ak-git"}]
    gen = {"a": {"d0": ["handoff doc"]}, "b": {"d0": ["use git"]}}
    assert S.leak_dropped(cases, gen) == ["a"]


def test_router_group_reads_name_score_pairs():
    assert S.router_group("ak-plan", [["ak:plan", 0.6]]) == "offered"
    assert S.router_group("ak-plan", [["other", 0.6]]) == "not_offered"
    assert S.router_group("ak-plan", None) == "unknown"


def test_composites_pair_distinct_sessions_and_labels_once():
    cases = [{"id": f"c{i}", "uuid": f"u{i}", "sid": f"s{i % 7}", "key": f"k{i % 5}"} for i in range(30)]
    pairs = S.make_pairs(cases)
    by = {c["id"]: c for c in cases}
    flat = [x for p in pairs for x in p]
    assert len(flat) == len(set(flat)) and len(pairs) > 5
    for a, b in pairs:
        assert by[a]["sid"] != by[b]["sid"] and by[a]["key"] != by[b]["key"]
    assert pairs == S.make_pairs(cases)


def test_cap_keeps_five_per_label_in_hash_order():
    cands = [{"uuid": f"u{i}", "key": "same"} for i in range(9)] + [{"uuid": "x", "key": "other"}]
    kept = S.pick_cases(cands)
    assert sum(1 for c in kept if c["key"] == "same") == 5 and len(kept) == 6


def test_forked_consults_count_once():
    a = {"task": "t", "queries": ["q1", "q2"], "primary": "p", "session": "129c"}
    b = {"task": "t", "queries": ["q1", "q2"], "primary": "p", "session": "79d0"}
    c = {"task": "t", "queries": ["q1"], "primary": "p", "session": "zzzz"}
    assert S.dedupe_runs([a, b, c]) == [a, c]


CASES3 = [{"id": f"c{i}", "gen_text": f"task text {i}", "label": "zzz-secret-label", "key": "zzz-secret-label"}
          for i in range(1)]


def fake_chat(calls, fail_at=None):
    def chat(system, user):
        calls.append((system, user))
        if fail_at is not None and len(calls) == fail_at:
            raise KeyboardInterrupt
        return {"queries": [f"q{len(calls)}"]} if "queries" in system else {"query": f"q{len(calls)}"}
    return chat


def test_generator_never_receives_labels(tmp_path):
    calls = []
    jobs = S.jobs_for(CASES3, [])
    assert len(jobs) == 3
    S.generate(jobs, fake_chat(calls), "m", path=tmp_path / "q.jsonl", log=lambda *_: None)
    assert len(calls) == 3
    for system, user in calls:
        assert "zzz-secret-label" not in system and "zzz-secret-label" not in user
    assert {j[1] for j in jobs} == {"d0", "how", "split"}


def test_generation_appends_resumes_locks_and_freezes(tmp_path, monkeypatch):
    qpath = tmp_path / "q.jsonl"
    cases = [{"id": f"c{i}", "gen_text": f"task {i}", "key": "k", "label": "k"} for i in range(1)]
    jobs = S.jobs_for(cases, [])          # 3 calls
    calls = []
    with pytest.raises(KeyboardInterrupt):
        S.generate(jobs, fake_chat(calls, fail_at=3), "m", path=qpath, log=lambda *_: None)
    assert len(S.read_jsonl(qpath)) == 2          # the first two were written as they completed
    calls2 = []
    made, failed = S.generate(jobs, fake_chat(calls2), "m", path=qpath, log=lambda *_: None)
    assert (made, failed) == (1, 0) and len(calls2) == 1
    assert len(S.read_jsonl(qpath)) == 3
    rec = S.read_jsonl(qpath)[0]
    assert rec["model"] == "m" and rec["temperature"] == 0.4 and rec["doctrine_sha"] and rec["reply"]
    # a failed key is skipped on a rerun, retried only with retry_failed
    qf = tmp_path / "f.jsonl"

    def boom(system, user):
        raise OSError("down")
    assert S.generate(jobs, boom, "m", path=qf, log=lambda *_: None) == (3, 3)
    assert S.generate(jobs, fake_chat([]), "m", path=qf, log=lambda *_: None) == (0, 0)
    assert S.generate(jobs, fake_chat([]), "m", path=qf, retry_failed=True, log=lambda *_: None) == (3, 0)
    assert all(not r.get("err") for r in S.latest_records(qf).values())

    # lock: a live holder blocks, a dead pid is replaced
    lock = tmp_path / "x.lock"
    S.acquire_lock(lock)
    with pytest.raises(S.LockError):
        S.acquire_lock(lock)
    S.release_lock(lock)
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    lock.write_text(str(dead.pid))
    S.acquire_lock(lock)
    assert lock.read_text() == str(os.getpid())
    S.release_lock(lock)

    # freeze: records the sha, then `queries` refuses
    monkeypatch.setattr(S, "CAL_DIR", tmp_path)
    monkeypatch.setattr(S, "QUERIES", qpath)
    monkeypatch.setattr(S, "CASES", tmp_path / "cases.jsonl")
    monkeypatch.setattr(S, "MANIFEST", tmp_path / "man.json")
    monkeypatch.setattr(S, "LOCK", tmp_path / "q.lock")
    (tmp_path / "cases.jsonl").write_text(json.dumps(cases[0]) + "\n")
    (tmp_path / "man.json").write_text(json.dumps({"frozen": False}))
    assert S.cmd_queries(argparse.Namespace(freeze=True, retry_failed=False)) == 0
    man = json.loads((tmp_path / "man.json").read_text())
    assert man["frozen"] and man["queries"]["sha256"] == S.sha256_file(qpath)
    assert man["queries"]["temperature"] == 0.4 and man["queries"]["by_part"]["d0"]["keys"] == 1
    assert S.cmd_queries(argparse.Namespace(freeze=False, retry_failed=False)) == 2
    # a live lock makes a second run exit non-zero (use an unfrozen manifest)
    (tmp_path / "man.json").write_text(json.dumps({"frozen": False}))
    S.acquire_lock(tmp_path / "q.lock")
    assert S.cmd_queries(argparse.Namespace(freeze=False, retry_failed=False)) == 3
    S.release_lock(tmp_path / "q.lock")


def mk(n, hits=None, ms=10.0, ext=5, rows=20, sids=None):
    hits = hits if hits is not None else [False] * n
    return [{"id": f"i{i}", "sid": (sids[i] if sids else f"s{i}"), "label": f"l{i}", "hit": hits[i],
             "ms": ms, "ext": ext, "rows": rows} for i in range(n)]


def test_gate_rules():
    # G1: 29 cases
    assert S.gate_rules(mk(29), mk(29))["verdict"] == "INSUFFICIENT"
    # G2: 4.9 points fails, 5.0 passes (n = 1000)
    base = mk(1000)
    assert not S.gate_rules(base, mk(1000, [i < 49 for i in range(1000)]))["G2"]
    assert S.gate_rules(base, mk(1000, [i < 50 for i in range(1000)]))["G2"]
    # G3: 5 losses for 20 gains fails, 4 passes
    def lg(lost):
        b = [i < lost for i in range(100)]                       # base hits: the first `lost` cases
        a = [False] * lost + [True] * 20 + [False] * (100 - lost - 20)
        return S.gate_rules(mk(100, b), mk(100, a))
    assert not lg(5)["G3"] and lg(4)["G3"]
    assert lg(5)["lost"] == 5 and lg(5)["gained"] == 20
    # G5: a median of 3 external rows fails; the share must also stay within +10 points
    assert not S.gate_rules(mk(40, ext=3), mk(40, ext=3))["G5"]
    assert S.gate_rules(mk(40, ext=5), mk(40, ext=5))["G5"]
    assert not S.gate_rules(mk(40, ext=4), mk(40, ext=14))["G5"]
    # G6: p90 + 101 ms fails, + 100 passes
    assert not S.gate_rules(mk(40, ms=10), mk(40, ms=111))["G6"]
    assert S.gate_rules(mk(40, ms=10), mk(40, ms=110))["G6"]


def test_holm_adjustment():
    assert S.holm([0.004, 0.02, 0.03, 0.2, 0.5]) == [True, False, False, False, False]
    assert S.holm([0.5, 0.004, 0.2, 0.03, 0.02]) == [False, True, False, False, False]
    assert S.holm([0.001, 0.002, 0.003, 0.004, 0.005]) == [True] * 5
    assert S.holm([1.0] * 5) == [False] * 5


def test_sign_test_counts_sessions_not_cases():
    sids = ["s1"] * 5 + ["s2"]
    base = [False] * 5 + [True]
    arm = [True] * 5 + [False]
    gained, lost, p = S.session_sign(sids, base, arm)
    assert (gained, lost) == (1, 1) and p == 0.75      # P(X <= 1 | n = 2): one session each way
    gained, lost, p = S.session_sign(["a", "b"], [True, False], [True, False])
    assert (gained, lost) == (0, 0) and p == 1.0        # sign_test_p would return 0.0 here
    gained, lost, p = S.session_sign([f"s{i}" for i in range(10)], [False] * 10, [True] * 10)
    assert (gained, lost) == (10, 0) and p < 0.01


def test_bootstrap_lower_bound_is_seeded_and_paired():
    units = [(-1, 1)] * 6 + [(0, 1)] * 94            # a constant -6 point difference
    lo = S.bootstrap_lower(units)
    assert lo == S.bootstrap_lower(units) and lo < -5
    assert S.bootstrap_lower([(0, 1)] * 50) == 0.0
    assert S.bootstrap_lower([(1, 1)] * 50) == 100.0
    assert S.bootstrap_lower([]) is None
    pairs = S.guard_units([("a", 1, 1), ("a", 0, 1), ("b", -1, 1)])
    assert sorted(pairs) == [(-1.0, 1), (1.0, 2)]


def test_index_lock_aborts_when_the_name_set_changes():
    a = {"points_count": 10, "base_count": 3, "names_sha256": "x", "names": []}
    S.check_index_lock(a, dict(a))
    with pytest.raises(RuntimeError, match="names_sha256"):
        S.check_index_lock(a, {**a, "names_sha256": "y"})
    with pytest.raises(RuntimeError, match="points_count"):
        S.check_index_lock(a, {**a, "points_count": 11})
    assert S.lock_line(a) == "INDEX-LOCK points=10 base=3 names_sha256=x"


def test_engine_outside_repo_is_refused():
    outside = SimpleNamespace(__file__="/tmp/elsewhere/skill_search/server.py")
    with pytest.raises(S.EngineError, match="/tmp/elsewhere|elsewhere"):
        S.assert_engine(outside, ())
    inside = SimpleNamespace(__file__=str(ROOT / "vendor" / "skill-search" / "skill_search" / "server.py"))
    S.assert_engine(inside, ["A0", "T"])               # no flag reader needed
    with pytest.raises(S.EngineError, match="_consult_slots_on"):
        S.assert_engine(inside, ["A1"])
    with pytest.raises(S.EngineError, match="_consult_rrf_on"):
        S.assert_engine(inside, ["A2"])
    with pytest.raises(S.EngineError):
        S.assert_engine(SimpleNamespace(__file__=inside.__file__, _consult_slots_on=lambda: 1), ["C"])
    S.assert_engine(SimpleNamespace(__file__=inside.__file__, _consult_slots_on=lambda: 1,
                                    _consult_rrf_on=lambda: 1), ["A1", "A2", "C"])


def test_arm_queries_follow_the_registered_shapes():
    case = {"id": "c", "task": "TASK"}
    gen = {"c": {"d0": ["a", "b", "c", "d", "e"], "how": ["HOW"], "split": ["s1", "s2"]}}
    assert S.arm_queries("A0", gen, case) == ["a", "b", "c", "d", "e"]
    assert S.arm_queries("T", gen, case) == ["TASK", "a", "b", "c", "d"]
    assert S.arm_queries("H", gen, case) == ["HOW", "a", "b", "c", "d"]
    assert S.arm_queries("S", gen, case) == ["s1", "s2"]
    assert S.arm_queries("C", gen, case, ["task", "how", "split"]) == ["TASK", "HOW", "s1", "s2"]
    assert S.arm_queries("C", gen, case, ["task"]) == ["TASK", "a", "b", "c", "d"]
    assert S.arm_queries("H", {"c": {"d0": ["a"]}}, case) is None


def test_fidelity_report_ranks_and_agreement():
    rep = S.fidelity_report([{"i": 0, "primary": "p", "real": 3, "gen": 41},
                             {"i": 1, "primary": "q", "real": 30, "gen": 35},
                             {"i": 2, "primary": "r", "skip": "missing"}])
    assert "median absolute rank difference 21.5" in rep and "in 1 of 2 runs" in rep


class FakeServer:
    """consult_candidates over fake rows: a label named in the first query is found at rank 1 only
    when `win` says this flag setting should win; 6 of every 20 rows are external."""
    __file__ = str(ROOT / "vendor" / "skill-search" / "skill_search" / "server.py")

    def __init__(self, win):
        self.win = win
        self.calls = []

    def _consult_slots_on(self):
        return True

    def _consult_rrf_on(self):
        return True

    def consult_candidates(self, queries, top_n=20):
        flags = (os.environ["SKILL_CONSULT_SLOTS"], os.environ["SKILL_CONSULT_RRF"])
        self.calls.append((tuple(queries), top_n, flags))
        rows = [{"name": f"filler{i}", "external": i < 6} for i in range(top_n)]
        if self.win(flags):
            for i, q in enumerate(queries):
                rows[i] = {"name": q.split("for:")[1].strip()}
        return json.dumps({"queries": queries, "results": rows})


def fake_cases(n=40):
    cases = [{"id": f"c{i}", "sid": f"s{i}", "label": f"skill-{i}", "key": f"skill-{i}", "uuid": f"u{i}",
              "group": "not_offered" if i % 2 else "offered", "task": f"task {i}"} for i in range(n)]
    gen = {c["id"]: {"d0": [f"for:{c['label']}"]} for c in cases}
    return cases, gen


def test_gate_end_to_end_with_a_fake_engine():
    cases, gen = fake_cases()
    pairs = [(cases[2 * i], cases[2 * i + 1]) for i in range(10)]
    srv = FakeServer(win=lambda flags: flags[0] == "1")
    res, comp = S.run_arms(srv, cases, pairs, gen, ["A0", "A1"])
    assert len(res["A0"]) == len(res["A1"]) == 40 and len(comp["A1"]) == 10
    assert {c[2] for c in srv.calls if c[2] == ("1", "0")} == {("1", "0")}      # flags set per call
    lines = S.evaluate(cases, pairs, res, comp, None, srv, gen)
    slots = [l for l in lines if l.startswith("VERDICT: slots")][0]
    assert slots.startswith("VERDICT: slots PASS") and "recall@20 0.0 -> 100.0" in slots
    assert any(l == "VERDICT: rrf NOT RUN" for l in lines) and lines[-1] == "SHIP: slots"
    # the same engine with no effect from the flag loses on G2
    srv2 = FakeServer(win=lambda flags: False)
    res2, comp2 = S.run_arms(srv2, cases, pairs, gen, ["A0", "A1"])
    assert [l for l in S.evaluate(cases, pairs, res2, comp2, None, srv2, gen) if "slots" in l][0].startswith("VERDICT: slots FAIL")
    # without --composites a flag decision cannot pass: the guard is unrun
    res3, comp3 = S.run_arms(srv, cases, [], gen, ["A0", "A1"])
    assert [l for l in S.evaluate(cases, [], res3, comp3, None, srv, gen) if "slots" in l][0].startswith("VERDICT: slots FAIL")


def test_combination_runs_arm_c_against_a0():
    cases, gen = fake_cases()
    pairs = [(cases[2 * i], cases[2 * i + 1]) for i in range(10)]
    srv = FakeServer(win=lambda flags: flags[0] == "1")
    res, comp = S.run_arms(srv, cases, pairs, gen, ["A0", "A1", "A2"])
    lines = S.evaluate(cases, pairs, res, comp, (["slots"], []), srv, gen)
    comb = [l for l in lines if l.startswith("COMBINED:")][0]
    assert comb.startswith("COMBINED: flags=slots parts=- PASS") and "composite-guard lower=" in comb
    lines = S.evaluate(cases, [], res, {"A0": {}}, (["slots"], []), srv, gen)
    assert "NOT RUN" in [l for l in lines if l.startswith("COMBINED:")][0]


def test_ship_choice_prefers_smallest_p_then_larger_gain():
    assert S.ship_choice({"a": {"p": 0.01, "gain_pts": 5}, "b": {"p": 0.001, "gain_pts": 1}}) == "b"
    assert S.ship_choice({"a": {"p": 0.01, "gain_pts": 5}, "b": {"p": 0.01, "gain_pts": 9}}) == "b"
    assert S.ship_choice({}) is None


def test_missing_queries_in_over_ten_percent_make_a_decision_insufficient():
    cases, gen = fake_cases(120)
    for c in cases[:16]:
        gen[c["id"]].pop("d0")                      # 8 of the 60 not-offered cases (13%) lack d0
    srv = FakeServer(win=lambda flags: False)
    res, comp = S.run_arms(srv, cases, [], gen, ["A0", "T"])
    lines = S.evaluate(cases, [], res, comp, None, srv, gen)
    task = [l for l in lines if l.startswith("VERDICT: task")][0]
    assert task.startswith("VERDICT: task INSUFFICIENT (proxy)") and "8 of 60 primary cases lack queries" in task


def test_strata_report_counts_and_never_gates():
    cases, gen = fake_cases(10)
    for c in cases[:3]:
        c.update(english=True, process=True)
    srv = FakeServer(win=lambda flags: flags[0] == "1")
    res, _ = S.run_arms(srv, cases, [], gen, ["A0", "A1"])
    out = {l.split(":")[0]: l for l in S.strata_report(cases, res)}
    assert "cases 10 sessions 10 recall@20 A0 0.0  A1 100.0" in out["STRATUM all"]
    assert "cases 3 sessions 3" in out["STRATUM process"] and "cases 0" in out["STRATUM unknown"]


def test_reply_shapes_the_model_actually_returns():
    q = lambda reply: S.queries_of({"reply": reply})
    assert q({"queries": ["a", " b "]}) == ["a", "b"] and q({"query": "x"}) == ["x"]
    assert q({"query": ["first", "second"]}) == ["first", "second"]
    assert q([{"query": "a"}, {"query": "b"}]) == ["a", "b"]
    assert q({"queries": [{"query": "a"}, {"query": "b"}]}) == ["a", "b"]
    assert q(None) == [] and q({"query": 3}) == [] and q({}) == []
    case = {"id": "c", "task": "T"}
    gen = {"c": {"d0": ["a"], "how": ["first", "second"]}}
    assert S.arm_queries("H", gen, case) == ["first", "a"]          # one how-query: the first


def test_refreeze_recounts_the_same_file_and_refuses_a_changed_one(tmp_path, monkeypatch):
    qpath = tmp_path / "q.jsonl"
    for name, val in (("CAL_DIR", tmp_path), ("QUERIES", qpath), ("CASES", tmp_path / "c.jsonl"),
                      ("MANIFEST", tmp_path / "m.json"), ("LOCK", tmp_path / "q.lock")):
        monkeypatch.setattr(S, name, val)
    (tmp_path / "c.jsonl").write_text(json.dumps({"id": "c0", "gen_text": "t", "key": "k", "label": "k"}) + "\n")
    (tmp_path / "m.json").write_text(json.dumps({"frozen": False}))
    S.generate(S.jobs_for([{"id": "c0", "gen_text": "t"}], []), fake_chat([]), "m", path=qpath, log=lambda *_: None)
    assert S.cmd_queries(argparse.Namespace(freeze=True, retry_failed=False)) == 0
    first = json.loads((tmp_path / "m.json").read_text())
    assert S.cmd_queries(argparse.Namespace(freeze=True, retry_failed=False)) == 0
    again = json.loads((tmp_path / "m.json").read_text())
    assert again["queries"]["sha256"] == first["queries"]["sha256"] and len(again["refrozen_utc"]) == 1
    qpath.write_text(qpath.read_text() + "\n")
    assert S.cmd_queries(argparse.Namespace(freeze=True, retry_failed=False)) == 2


def test_ship_tie_break_uses_holm_adjusted_p():
    # raw 0.010 (slots) and 0.012 (rrf) both adjust to 0.05: the larger gain must ship
    adj = S.holm_adjusted([0.010, 0.012, 1.0, 1.0, 1.0])
    assert adj[0] == pytest.approx(0.05) and adj[1] == pytest.approx(0.05)
    assert S.holm([0.010, 0.012, 1.0, 1.0, 1.0]) == [True, True, False, False, False]
    passed = {"slots": {"p": adj[0], "gain_pts": 6.0}, "rrf": {"p": adj[1], "gain_pts": 9.0}}
    assert S.ship_choice(passed) == "rrf"


def test_gate_refuses_rules_changed_after_the_freeze(monkeypatch):
    S._ensure_dir()
    for path in (S.LABELS, S.CASES, S.QUERIES):
        path.write_text("x\n")
    man = {"frozen": True, "inputs": {"real-turn-labels.jsonl": S.sha256_file(S.LABELS)},
           "cases_sha256": S.sha256_file(S.CASES), "queries": {"sha256": S.sha256_file(S.QUERIES)}}
    with pytest.raises(RuntimeError, match="rules"):
        S.check_freeze(man)                       # a manifest that never recorded the rules
    man["rules_sha256"] = S.rules_sha256()
    S.check_freeze(man)
    monkeypatch.setattr(S, "G2_GAIN_PTS", 3.0)
    with pytest.raises(RuntimeError, match="rules"):
        S.check_freeze(man)
    with pytest.raises(RuntimeError, match="rules"):
        S._freeze(man, [], "m")                   # a re-freeze cannot re-register them


def test_text_sent_to_the_gateway_is_cleaned():
    secret = "sk-" + "a1B2c3D4" * 5
    raw = f"<system-reminder>internal rule text</system-reminder> deploy with key {secret} please"
    out = S.gen_text(raw)
    assert secret not in out and "internal rule text" not in out and "deploy with key" in out
    # a prompt the corpus cut mid-token: the half secret at the cut is dropped, not sent
    half = "rotate the token ghp_" + "Zq9" * 4
    assert S.gen_text(half, truncated=True) == "rotate the token"
    assert S.jobs_for([], [{"task": raw}])[0][2] == out
