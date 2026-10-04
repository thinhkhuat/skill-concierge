"""Consult sieve recall instrument (scripts/sieve_recall.py) — pinned offline.

No engine, no gateway, no live index: the label corpus rows, the index points, the chat client and
the server module are all fakes. The live build, generation and gate runs are separate steps.
"""
import argparse
import json
import os
import stat
import subprocess
import sys
import threading
import time
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
    # iteration paths: ITER restored on teardown, the pre-registration and gate output redirected
    monkeypatch.setattr(S, "ITER", 1)
    monkeypatch.setattr(S, "PLAN_DIR", tmp_path / "plan")
    (tmp_path / "plan" / "reports").mkdir(parents=True)


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


# ── iterations ─────────────────────────────────────────────────────────────────────────────
def test_iteration_one_paths_are_the_original_names(tmp_path):
    cal = tmp_path / "jev-calibration"
    S.set_iter(1)
    assert S.ITER == 1
    assert [p.name for p in (S.LABELS, S.CASES, S.QUERIES, S.LOCK, S.MANIFEST)] == [
        "real-turn-labels.jsonl", "sieve-eval-cases.jsonl", "sieve-eval-queries.jsonl",
        "sieve-eval-queries.lock", "sieve-eval-manifest.json"]
    assert all(p.parent == cal for p in (S.LABELS, S.CASES, S.QUERIES, S.LOCK, S.MANIFEST))


def test_iteration_two_suffixes_every_private_path_and_keeps_modes(tmp_path):
    cal = tmp_path / "jev-calibration"
    S.set_iter(2)
    assert S.ITER == 2
    assert [p.name for p in (S.LABELS, S.CASES, S.QUERIES, S.LOCK, S.MANIFEST)] == [
        "real-turn-labels-iter2.jsonl", "sieve-eval-cases-iter2.jsonl", "sieve-eval-queries-iter2.jsonl",
        "sieve-eval-queries-iter2.lock", "sieve-eval-manifest-iter2.json"]
    S.set_iter(13)
    assert S.CASES.name == "sieve-eval-cases-iter13.jsonl"
    S.set_iter(2)
    S.write_private(S.CASES, "x\n")
    S._append(S.QUERIES, {"k": 1})
    S.acquire_lock()
    assert stat.S_IMODE(os.stat(cal).st_mode) == 0o700
    for p in (S.CASES, S.QUERIES, S.LOCK):
        assert stat.S_IMODE(os.stat(p).st_mode) == 0o600
    assert sorted(f.name for f in cal.iterdir()) == [
        "sieve-eval-cases-iter2.jsonl", "sieve-eval-queries-iter2.jsonl", "sieve-eval-queries-iter2.lock"]
    for bad in (0, -1, "2"):
        with pytest.raises(ValueError):
            S.set_iter(bad)


def test_main_takes_a_global_iter_and_labels_needs_two(capsys):
    with pytest.raises(SystemExit):
        S.main(["labels"])                       # iteration 1's corpus is never rewritten
    with pytest.raises(SystemExit):
        S.main(["--iter", "0", "build"])
    assert S.cmd_labels(argparse.Namespace()) == 2          # direct call at iteration 1: refused too
    assert S.main(["--iter", "2", "check-prereg"]) == 1 and S.ITER == 2
    assert S.MANIFEST.name == "sieve-eval-manifest-iter2.json"


def lrow(uuid, sid, ts, positive=True, words=12):
    return {"uuid": uuid, "sid": sid, "ts_utc": ts, "prompt_words": words,
            "label": "NEEDS_SKILL" if positive else "NO_SKILL", "label_rule": "using+executed_this_turn",
            "meta_session": False, "entry_class": "interactive", "interrupted": False,
            "next_prompt_correction": None}


def test_fresh_rows_keep_only_strictly_later_turns_in_new_sessions():
    cut = "2026-09-26T09:05:44.285Z"
    rows = [lrow("a", "s-new", "2026-09-26T09:05:44.286Z"),
            lrow("b", "s-new2", "2026-09-26T09:05:44.285Z"),     # equal to the cutoff: not after
            lrow("c", "s-new3", "2026-09-25T00:00:00Z"),
            lrow("d", "s-old", "2026-09-27T00:00:00Z"),          # later turn of an iteration-1 session
            lrow("e", "s-new4", "2026-09-27T00:00:00Z"),         # reused uuid
            lrow("f", "s-new5", None),
            lrow("g", "s-new6", "2026-10-01T10:00:00+00:00")]
    kept, c = S.fresh_rows(rows, cut, {"s-old"}, {"e"})
    assert [r["uuid"] for r in kept] == ["a", "g"]
    assert c == {"raw": 7, "not_after_cutoff": 3, "excluded_session": 1, "excluded_uuid": 1, "kept": 2}


def write_jsonl(path, rows):
    S.write_private(path, "".join(json.dumps(r) + "\n" for r in rows))


def test_iteration_one_exclusions_cover_case_and_feeding_sessions_and_the_cutoff():
    rows = [lrow("u1", "s1", "2026-09-01T00:00:00Z"),                       # feeds a case
            lrow("u2", "s2", "2026-09-26T09:05:44.285Z"),                   # positive, fed but capped out
            lrow("u3", "s3", "2026-09-20T00:00:00Z", positive=False),       # not positive: session free
            lrow("u4", "s4", "2026-09-20T00:00:00Z", words=3),              # too short: session free
            lrow("u5", "s5", "garbage")]
    write_jsonl(S.iter_path("real-turn-labels.jsonl", 1), rows)
    write_jsonl(S.iter_path("sieve-eval-cases.jsonl", 1), [{"id": "u1|k", "uuid": "u1", "sid": "s1"},
                                                          {"id": "x|k", "uuid": "x", "sid": "s9"}])
    sids, uuids, cutoff = S.iter1_exclusions()
    assert sids == {"s1", "s2", "s5", "s9"} and uuids == {"u1", "u2", "u3", "u4", "u5", "x"}
    assert cutoff == "2026-09-26T09:05:44.285Z"
    S.iter_path("sieve-eval-cases.jsonl", 1).unlink()
    with pytest.raises(RuntimeError, match="missing"):
        S.iter1_exclusions()


CUT = "2026-09-26T09:05:44.285Z"


def fresh_setup(n_cases=31, leaking=0, prereg=True):
    """A frozen iteration-2 evaluation on disk plus the iteration-1 files it must not overlap."""
    write_jsonl(S.iter_path("real-turn-labels.jsonl", 1), [lrow("o1", "old1", "2026-09-01T00:00:00Z"),
                                                          lrow("o2", "old2", CUT)])
    write_jsonl(S.iter_path("sieve-eval-cases.jsonl", 1), [{"id": "o1|k", "uuid": "o1", "sid": "old1"}])
    S.set_iter(2)
    cases = [{"id": f"n{i}|zeta{i}", "uuid": f"n{i}", "sid": f"new{i}", "key": f"zeta{i}", "label": f"zeta{i}"}
             for i in range(n_cases)]
    write_jsonl(S.LABELS, [lrow(c["uuid"], c["sid"], "2026-10-01T00:00:00Z") for c in cases])
    write_jsonl(S.CASES, cases)
    for i, c in enumerate(cases):
        q = f"zeta{i} thing" if i < leaking else "do the thing"
        S._append(S.QUERIES, {"k": f"{c['id']}|d0|x", "case": c["id"], "part": "d0", "reply": {"queries": [q]},
                              "err": None})
    if prereg:
        S.prereg_path().write_text("pre-registered rules\n")
    man = {"frozen": True, "iteration": 2, "rules_sha256": S.rules_sha256(),
           "inputs": {S.LABELS.name: S.sha256_file(S.LABELS)}, "cases_sha256": S.sha256_file(S.CASES),
           "queries": {"sha256": S.sha256_file(S.QUERIES)}, "fresh": {"cutoff_ts": CUT}}
    if prereg:
        man["prereg_sha256"] = S.sha256_file(S.prereg_path())
    S.write_private(S.MANIFEST, json.dumps(man))
    return cases, man


def put_manifest(man):
    S.write_private(S.MANIFEST, json.dumps(man))


def fail_of(capsys):
    assert S.cmd_check_fresh(None) == 1
    return capsys.readouterr().err


def test_check_fresh_passes_a_frozen_fresh_evaluation(capsys):
    fresh_setup()
    assert S.cmd_check_fresh(None) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[-1] == "FRESH-HELDOUT-OK" and "surviving the leak check 31" in out


def test_check_fresh_refuses_iteration_one(capsys):
    assert S.cmd_check_fresh(None) == 1 and "iteration" in capsys.readouterr().err


def test_check_fresh_names_each_failed_check(capsys):
    cases, man = fresh_setup()
    put_manifest({**man, "frozen": False})
    assert "frozen" in fail_of(capsys)
    put_manifest(man)
    S.CASES.write_text(S.CASES.read_text() + " ")             # a file changed after the freeze
    assert "cases file changed" in fail_of(capsys)
    # a case in an iteration-1 session
    cases, man = fresh_setup()
    cases[0]["sid"] = "old1"
    write_jsonl(S.CASES, cases)
    put_manifest({**man, "cases_sha256": S.sha256_file(S.CASES)})
    err = fail_of(capsys)
    assert "sessions" in err and "old1" in err
    # a case whose label turn is not after the iteration-1 cutoff
    cases, man = fresh_setup()
    write_jsonl(S.LABELS, [lrow(c["uuid"], c["sid"], CUT if i == 3 else "2026-10-01T00:00:00Z")
                           for i, c in enumerate(cases)])
    put_manifest({**man, "inputs": {S.LABELS.name: S.sha256_file(S.LABELS)}})
    assert "time" in fail_of(capsys)
    # the manifest's recorded cutoff differs from the iteration-1 corpus
    cases, man = fresh_setup()
    put_manifest({**man, "fresh": {"cutoff_ts": "2026-09-01T00:00:00Z"}})
    assert "cutoff" in fail_of(capsys)
    # the leak check leaves 26 cases
    fresh_setup(leaking=5)
    err = fail_of(capsys)
    assert "leak-check" in err and "26" in err


def test_check_fresh_fails_when_the_prereg_changed_after_the_freeze(capsys):
    fresh_setup()
    S.prereg_path().write_text("edited after the freeze\n")
    assert "frozen" in fail_of(capsys)


def raw_with(h, line="provenance: script sha256 aa rules sha256 bb prereg sha256 "):
    S.gate_raw_path().write_text(f"noise\n{line}{h}\nVERDICT: x\n")


def test_check_prereg_passes_and_names_each_mismatch(capsys):
    cases, man = fresh_setup()
    h = man["prereg_sha256"]
    assert S.cmd_check_prereg(None) == 1 and "gate-raw" in capsys.readouterr().err      # no raw file yet
    raw_with(h)
    assert S.cmd_check_prereg(None) == 0 and capsys.readouterr().out.strip() == "PREREG-MATCHES-RUN"
    raw_with("0" * 64)                                                                  # run used another prereg
    assert S.cmd_check_prereg(None) == 1 and "gate-raw" in capsys.readouterr().err
    S.gate_raw_path().write_text(f"VERDICT: x\nsomething prereg sha256 {h}\n")        # not a provenance line
    assert S.cmd_check_prereg(None) == 1 and "no provenance" in capsys.readouterr().err
    raw_with(h)
    S.prereg_path().write_text("edited\n")                                              # file changed since freeze
    assert S.cmd_check_prereg(None) == 1 and "prereg-file" in capsys.readouterr().err
    S.prereg_path().unlink()
    assert S.cmd_check_prereg(None) == 1 and "missing" in capsys.readouterr().err
    put_manifest({k: v for k, v in man.items() if k != "prereg_sha256"})
    assert S.cmd_check_prereg(None) == 1 and "manifest" in capsys.readouterr().err
    S.set_iter(1)
    assert S.cmd_check_prereg(None) == 1


def test_freeze_needs_the_prereg_and_records_its_hash():
    S.set_iter(2)
    S._ensure_dir()
    S.write_private(S.CASES, json.dumps({"id": "c0", "gen_text": "t", "key": "k", "label": "k"}) + "\n")
    S.write_private(S.MANIFEST, json.dumps({"frozen": False}))
    S.generate(S.jobs_for([{"id": "c0", "gen_text": "t"}], []), fake_chat([]), "m", path=S.QUERIES,
               log=lambda *_: None)
    args = argparse.Namespace(freeze=True, retry_failed=False)
    assert S.cmd_queries(args) == 2                                  # no iter2-prereg.md
    assert not json.loads(S.MANIFEST.read_text())["frozen"]
    S.prereg_path().write_text("rules\n")
    assert S.cmd_queries(args) == 0
    man = json.loads(S.MANIFEST.read_text())
    assert man["frozen"] and man["prereg_sha256"] == S.sha256_file(S.prereg_path())
    S.prereg_path().write_text("changed\n")                         # a re-freeze cannot re-register it
    with pytest.raises(RuntimeError, match="prereg"):
        S._freeze(man, [], "m")
    # iteration 1 needs no prereg and records none
    S.set_iter(1)
    S.write_private(S.CASES, json.dumps({"id": "c0", "gen_text": "t", "key": "k", "label": "k"}) + "\n")
    S.write_private(S.MANIFEST, json.dumps({"frozen": False}))
    S.generate(S.jobs_for([{"id": "c0", "gen_text": "t"}], []), fake_chat([]), "m", path=S.QUERIES,
               log=lambda *_: None)
    assert S.cmd_queries(args) == 0 and "prereg_sha256" not in json.loads(S.MANIFEST.read_text())


def test_gate_provenance_carries_the_prereg_hash_from_iteration_two():
    assert "prereg" not in S.provenance_line()
    S.set_iter(2)
    S.prereg_path().write_text("rules\n")
    line = S.provenance_line()
    assert line.startswith("provenance: script sha256 ") and f"rules sha256 {S.rules_sha256()}" in line
    assert line.endswith(f"prereg sha256 {S.sha256_file(S.prereg_path())}")


# ── parallel generation ────────────────────────────────────────────────────────────────────
def threaded_chat(calls, lock, fail_at=None, soft=False):
    def chat(system, user):
        with lock:
            calls.append(user)
            n = len(calls)
        time.sleep(0.01)
        if fail_at is not None and n == fail_at:
            raise OSError("down") if soft else KeyboardInterrupt
        return {"queries": [user + "x" * 5000]} if "queries" in system else {"query": user + "x" * 5000}
    return chat


def keys_once(path, jobs):
    lines = path.read_text().splitlines()
    recs = [json.loads(l) for l in lines]                 # an interleaved line would not parse
    assert sorted(r["k"] for r in recs) == sorted({S.query_key(c, p, S.SYSTEM[p]) for c, p, _ in jobs})
    return recs


def test_parallel_generation_writes_every_key_once_and_resumes(tmp_path):
    cases = [{"id": f"c{i}", "gen_text": f"task {i}"} for i in range(8)]
    jobs = S.jobs_for(cases, [])                                       # 24 calls
    path, lock = tmp_path / "q.jsonl", threading.Lock()
    calls = []
    assert S.generate(jobs, threaded_chat(calls, lock), "m", path=path, log=lambda *_: None, workers=3) == (24, 0)
    assert len(calls) == 24
    recs = keys_once(path, jobs)
    assert all(r["model"] == "m" and r["temperature"] == 0.4 and r["reply"] for r in recs)
    assert S.generate(jobs, threaded_chat([], lock), "m", path=path, log=lambda *_: None, workers=3) == (0, 0)
    # a worker dies mid-run: what was written stays, the rerun completes the rest and nothing repeats
    p2, calls2 = tmp_path / "q2.jsonl", []
    with pytest.raises(KeyboardInterrupt):
        S.generate(jobs, threaded_chat(calls2, lock, fail_at=7), "m", path=p2, log=lambda *_: None, workers=3)
    done = len(S.read_jsonl(p2))
    assert 0 < done < 24
    calls3 = []
    made, failed = S.generate(jobs, threaded_chat(calls3, lock), "m", path=p2, log=lambda *_: None, workers=3)
    assert (made, failed) == (24 - done, 0)
    keys_once(p2, jobs)
    # failed calls are recorded, skipped on a rerun, retried with retry_failed
    p3 = tmp_path / "q3.jsonl"
    assert S.generate(jobs, threaded_chat([], lock, fail_at=5, soft=True), "m", path=p3,
                      log=lambda *_: None, workers=3) == (24, 1)
    assert S.generate(jobs, threaded_chat([], lock), "m", path=p3, log=lambda *_: None, workers=3) == (0, 0)
    assert S.generate(jobs, threaded_chat([], lock), "m", path=p3, retry_failed=True,
                      log=lambda *_: None, workers=3) == (1, 0)
    assert all(not r["err"] for r in S.latest_records(p3).values())


def test_workers_one_stays_serial(tmp_path):
    seen = []

    def chat(system, user):
        seen.append(threading.current_thread())
        return {"queries": ["q"]} if "queries" in system else {"query": "q"}
    S.generate(S.jobs_for([{"id": "c", "gen_text": "t"}], []), chat, "m", path=tmp_path / "q.jsonl",
               log=lambda *_: None)
    assert set(seen) == {threading.current_thread()}


# ── iteration 2: Jev union arms ────────────────────────────────────────────────────────────
def wide(*chunks):
    """Fake Jev wide answers: each chunk is {name: probability}."""
    return {f"wide::{i}": {"probabilities": c} for i, c in enumerate(chunks)}


def srows(*names, external=()):
    return [{"name": n, "external": n in external} for n in names]


def test_jev_round_robin_takes_rank_one_of_every_chunk_first():
    ans = wide({"a": .9, "b": .5, "c": .1}, {"d": .3, "e": .2}, {"f": .8})
    assert S.jev_round_robin(ans) == ["a", "d", "f", "b", "e", "c"]
    # chunk keys sort numerically, not as text: chunk 10 comes after chunk 2
    many = {f"wide::{i}": {"probabilities": {f"n{i}": .5}} for i in (10, 2, 1)}
    assert S.jev_round_robin(many) == ["n1", "n2", "n10"]
    assert S.jev_round_robin({}) == [] and S.jev_round_robin({"other": {}}) == []


def test_union_puts_jev_first_then_sieve_deduped_and_truncated():
    assert S.skill_key("ak:plan") == S.skill_key("ak-plan")
    sieve = srows("s1", "ak-plan", "s3", "s4", "s5", external=("s1", "s3"))
    out = S.union_rows(["j1", "ak:plan"], sieve, 4)
    # jev rows first; the sieve row sharing a skill key with a jev row is dropped; cut at 4
    assert [r["name"] for r in out] == ["j1", "ak:plan", "s1", "s3"]
    assert [r["external"] for r in out] == [False, False, True, True]
    assert [r["name"] for r in S.union_rows(["j1"], sieve, 40)] == ["j1", "s1", "ak-plan", "s3", "s4", "s5"]
    assert [r["name"] for r in S.union_rows([], sieve, 2)] == ["s1", "ak-plan"]
    # a jev name that is also an external sieve row counts once, as the jev (installed) row
    both = S.union_rows(["s1"], sieve, 20)
    assert [r["name"] for r in both].count("s1") == 1 and both[0]["external"] is False


def test_jev_top_makes_one_attempt_on_the_ts_tier_with_an_empty_context():
    seen = {}

    def ask(state, questions, timeout, tiers=None, retries=1):
        seen.update(state=state, timeout=timeout, tiers=tiers, retries=retries, q=questions)
        return wide({"a": .9, "b": .8}, {"c": .7}), {}
    names, ms, err = S.jev_top("x" * 5000, {"wide::0": {}}, {"ep": "ts"}, ask, k=2)
    assert names == ["a", "c"] and err is None and ms >= 0
    assert seen["timeout"] == 3.0 and seen["retries"] == 0 and seen["tiers"] == [{"ep": "ts"}]
    assert seen["state"] == {"request": "x" * 4000, "recent_context": "",
                             "skills_already_loaded_this_session": []}


def test_a_failed_jev_call_gives_no_rows_and_the_case_still_runs_on_sieve_rows(monkeypatch):
    def broken(state, questions, timeout, tiers=None, retries=1):
        raise TimeoutError("slow")
    names, ms, err = S.jev_top("t", {}, {"ep": "ts"}, broken)
    assert names == [] and err == "TimeoutError"
    sieve = [{"name": f"s{i}", "skill_key": i, "external": i % 2 == 0} for i in range(40)]
    monkeypatch.setenv("SKILL_CONSULT_SLOTS", "0")
    monkeypatch.setenv("SKILL_CONSULT_RRF", "0")
    srv = SimpleNamespace(consult_candidates=lambda qs, n: json.dumps({"results": sieve[:n]}))
    case = {"id": "c1", "sid": "s", "label": "s30", "gen_text": "task"}
    out = S.run_case2(srv, case, ["q"], lambda t: S.jev_top(t, {}, {"ep": "ts"}, broken))
    assert [r["name"] for r in S.union_rows([], sieve, 20)] == [f"s{i}" for i in range(20)]
    assert out["J20"]["rows"] == 20 and out["J40"]["rows"] == 40
    assert out["J20"]["hit"] is False and out["J40"]["hit"] is True      # s30 sits at sieve rank 31
    assert out["J20"]["jev_failed"] is True and out["J20"]["jev_err"] == "TimeoutError"
    assert out["J20"]["jev_ms"] >= 0 and out["J20"]["ext"] == 10


def test_run_case2_joins_jev_rows_to_the_sieve_and_times_a_jev_arm_as_the_slower_call(monkeypatch):
    monkeypatch.setenv("SKILL_CONSULT_SLOTS", "0")
    monkeypatch.setenv("SKILL_CONSULT_RRF", "0")
    flags = []

    def consult(qs, n):
        flags.append((os.environ["SKILL_CONSULT_SLOTS"], os.environ["SKILL_CONSULT_RRF"], n))
        slow = os.environ["SKILL_CONSULT_SLOTS"] == "1"
        rows = [{"name": f"s{i}"} for i in range(n)]
        return json.dumps({"results": rows[::-1] if slow else rows})
    srv = SimpleNamespace(consult_candidates=consult)
    case = {"id": "c1", "sid": "s", "label": "jevhit", "gen_text": "task"}
    out = S.run_case2(srv, case, ["q"], lambda t: (["jevhit"], 2500.0, None))
    assert sorted(flags) == [("0", "0", 20), ("0", "0", 40), ("1", "1", 40)]
    assert set(out) == set(S.ARMS2)
    assert out["J20"]["hit"] and out["J40"]["hit"] and not out["A0@20"]["hit"]
    assert out["J20"]["ms"] == out["J40"]["ms"] == 2500.0 and out["J20"]["jev_failed"] is False
    assert out["SR40"]["rows"] == 40 and out["A0@20"]["rows"] == 20


def test_offer_source_is_jev_only_when_a_working_router_offered_the_label():
    ok = {"ms": 900, "fit": 0.6}
    assert S.offer_source("offered", ok) == "jev"
    assert S.offer_source("offered", {**ok, "err": "Timeout", "leg": "router"}) == "embed_or_none"
    assert S.offer_source("offered", None) == "embed_or_none"
    assert S.offer_source("offered", {}) == "embed_or_none"
    assert S.offer_source("not_offered", ok) == "embed_or_none"      # the router served, the label was not in it
    assert S.offer_source("unknown", ok) == "embed_or_none"


def test_build_cases_stamps_the_stratum_from_each_turns_ledger_row_and_drops_blocked_labels(monkeypatch):
    ok = {"ms": 900}
    rows = [row("u1", "s1", ["alpha"], offered=[["alpha", .5]]) | {"ledger_jev": ok},
            row("u2", "s2", ["beta"], offered=[["beta", .5]]) | {"ledger_jev": {"err": "X", "ms": 1}},
            row("u3", "s3", ["gamma"], offered=[["zzz", .5]]) | {"ledger_jev": ok},
            row("u4", "s4", ["delta"], offered=None),
            row("u5", "s5", ["whereami"], offered=[]),
            row("u6", "s6", ["whereami"], offered=[])]
    points = pts("alpha", "beta", "gamma", "delta", "whereami")
    plain, st0 = S.build_cases(rows, points, set(), set(), lambda r: True)
    assert len(plain) == 6 and all("offer_source" not in c for c in plain)    # iteration 1 build unchanged
    enf = S._enf()
    monkeypatch.setattr(enf, "BLOCKLIST", frozenset({"whereami"}))
    cases, st = S.build_cases(rows, points, set(), set(), lambda r: True, blocked=enf._blocked)
    src = {c["label"]: c["offer_source"] for c in cases}
    assert src == {"alpha": "jev", "beta": "embed_or_none", "gamma": "embed_or_none", "delta": "embed_or_none"}
    assert st["blocklisted_dropped"] == ["whereami", "whereami"]
    assert all(c["pair"] is None or c["pair"] in {x["id"] for x in cases} for c in cases)


def test_blocklist_helper_blocks_a_qualified_twin_of_a_bare_entry_only():
    enf = S._enf()
    blocked = lambda n: n == "whereami" or n.endswith(":whereami")      # the enforcer's rule, spelled out
    kept, dropped = S.drop_blocklisted([{"label": "whereami"}, {"label": "p:whereami"}, {"label": "p:other"}], blocked)
    assert dropped == ["whereami", "p:whereami"] and kept == [{"label": "p:other"}]
    saved = enf.BLOCKLIST
    try:
        enf.BLOCKLIST = frozenset({"whereami", "q:exact"})
        assert enf._blocked("p:whereami") and enf._blocked("q:exact") and not enf._blocked("r:exact")
    finally:
        enf.BLOCKLIST = saved


def test_cmd_build_iteration_two_records_stratum_counts_blocklist_drops_and_keeps_generation(monkeypatch, capsys):
    def old(uuid, sid, labels, jev=None):
        return lrow(uuid, sid, "2026-09-01T00:00:00Z") | row(uuid, sid, labels, offered=[]) | {"ledger_jev": jev}
    write_jsonl(S.iter_path("real-turn-labels.jsonl", 1), [
        old("o1", "old1", ["alpha"]),                                    # an iteration-1 case: never taken again
        old("o2", "old1", ["alpha"], jev={"ms": 5}),                      # unseen, shares the spent session
        old("o3", "old2", ["beta"]),                                      # unseen, own session
        old("o4", "old3", ["whereami"])])                                 # unseen but blocklisted
    write_jsonl(S.iter_path("sieve-eval-cases.jsonl", 1), [{"id": "o1|alpha", "uuid": "o1", "sid": "old1"}])
    i1 = {"frozen": True, "inputs": {"real-turn-labels.jsonl": S.sha256_file(S.iter_path("real-turn-labels.jsonl", 1))},
          "cases_sha256": "c"}
    S.write_private(S.iter_path("sieve-eval-manifest.json", 1), json.dumps(i1))
    S.set_iter(2)
    ok = {"ms": 900}
    new = [row("u1", "s1", ["alpha"], offered=[["alpha", .5]]) | {"ledger_jev": ok, "ts_utc": "2026-10-01T00:00:00Z"},
           row("u2", "s2", ["beta"], offered=[]) | {"ts_utc": "2026-10-01T00:00:00Z"},
           row("u3", "s3", ["whereami"], offered=[]) | {"ts_utc": "2026-10-01T00:00:00Z"}]
    write_jsonl(S.LABELS, new)
    S.write_private(S.CONSULT_EVAL, "")
    S.write_private(S.MANIFEST, json.dumps({"generation": [{"workers": 4}], "stale": 1}))
    enf = S._enf()
    monkeypatch.setattr(enf, "BLOCKLIST", frozenset({"whereami"}))
    points = pts("alpha", "beta", "whereami")
    monkeypatch.setattr(S, "_pe", lambda: SimpleNamespace(META_SKILLS=set()))
    monkeypatch.setattr(S, "_cal", lambda: SimpleNamespace(load_corpus=lambda p: S.read_jsonl(p), is_positive=lambda r: True))
    monkeypatch.setattr(S, "scroll_base_points", lambda: points)
    monkeypatch.setattr(S, "index_state", lambda: {"points_count": 3, "base_count": 3, "names_sha256": "x",
                                                  "names": ["alpha", "beta", "whereami"]})
    monkeypatch.setattr(S, "iter1_exclusions", lambda: (set(), set(), "2026-09-26T00:00:00Z"))
    assert S.cmd_build(argparse.Namespace(force=False)) == 0
    man = S.read_manifest()
    c = man["counts"]
    assert c["cases"] == 4 and c["blocklisted_dropped"] == 2          # one fresh, one pool
    assert c["offer_source"] == {"jev": 1, "embed_or_none": 1, "pre_router": 2}
    assert c["source"] == {"fresh": 2, "pre_router_unseen": 2}
    assert c["primary_cases"] == 3 and c["primary_sessions"] == 3
    assert c["pool_extension"]["cases"] == 2 and c["pool_extension"]["sessions"] == 2
    assert c["pool_extension"]["sessions_shared_with_spent_cases"] == 1
    assert c["pool_extension"]["cases_in_spent_sessions"] == 1 and c["pool_extension"]["with_ledger_jev"] == 1
    assert c["pool_extension"]["blocklisted_dropped"] == 1
    assert man["dropped"]["blocklisted"] == ["whereami"]
    assert man["generation"] == [{"workers": 4}] and "stale" not in man
    assert "primary set (not jev) 3 cases / 3 sessions" in capsys.readouterr().out
    got = S.read_jsonl(S.CASES)
    assert {c["offer_source"] for c in got} == {"jev", "embed_or_none", "pre_router"}
    assert {c["id"] for c in got if c["source"] == "pre_router_unseen"} == {"o2|alpha", "o3|beta"}


def test_iteration_one_rules_fingerprint_is_unchanged_and_iteration_two_has_its_own(monkeypatch):
    assert S.ITER == 1
    assert S.rules_sha256() == "97051cc4df983b33af26c3bdf30e4e7a29b2c7d0b0b32284c1754b38539cc251"
    monkeypatch.setattr(S, "JEV_TOP_K", 5)                       # an iteration-2 constant: iteration 1 ignores it
    assert S.rules_sha256() == "97051cc4df983b33af26c3bdf30e4e7a29b2c7d0b0b32284c1754b38539cc251"
    monkeypatch.undo()
    S.set_iter(2)
    h2 = S.rules_sha256()
    assert h2 != "97051cc4df983b33af26c3bdf30e4e7a29b2c7d0b0b32284c1754b38539cc251"
    for name, val in (("JEV_TOP_K", 5), ("G6_JEV_P90_MS", 1400.0), ("JEV_TIMEOUT_S", 2.0),
                      ("DECISIONS2", ("D_J20", "D_SR40")), ("OFFER_SOURCES", ("jev",))):
        with monkeypatch.context() as m:
            m.setattr(S, name, val)
            assert S.rules_sha256() != h2, name
    with monkeypatch.context() as m:
        m.setitem(S.ARM2, "SR40", ("1", "1", 20, 0, 20))
        assert S.rules_sha256() != h2


def test_check_freeze_for_iteration_two_refuses_a_changed_iteration_two_rule():
    cases, man = fresh_setup()
    S.check_freeze(man)
    S.G6_JEV_P90_MS, old = 1400.0, S.G6_JEV_P90_MS
    try:
        with pytest.raises(RuntimeError, match="gate rules differ"):
            S.check_freeze(man)
    finally:
        S.G6_JEV_P90_MS = old


def mk2(cases, hits, ms, ext=5, rows=20):
    return {c["id"]: {"id": c["id"], "sid": c["sid"], "label": c["label"], "hit": hits(i), "ms": ms,
                      "ext": ext, "rows": rows} for i, c in enumerate(cases)}


def cases2(n_primary, n_jev):
    out = [{"id": f"p{i}", "sid": f"sp{i}", "label": f"l{i}", "group": "not_offered",
            "offer_source": "embed_or_none"} for i in range(n_primary)]
    return out + [{"id": f"j{i}", "sid": f"sj{i}", "label": f"m{i}", "group": "offered",
                   "offer_source": "jev"} for i in range(n_jev)]


def res2(cases, j20_gain=0, j20_ms=800.0, sr_gain=0, sr_ms=10.0):
    """A0 hits nothing; J20 gains the first j20_gain cases, SR40 the first sr_gain; J40 = A0."""
    zero = lambda i: False
    return {"A0@20": mk2(cases, zero, 10.0), "A0@40": mk2(cases, zero, 10.0, rows=40),
            "J20": mk2(cases, lambda i: i < j20_gain, j20_ms), "J40": mk2(cases, zero, 800.0, rows=40),
            "SR40": mk2(cases, lambda i: i < sr_gain, sr_ms, rows=40)}


def test_iteration_two_decisions_use_their_primary_sets_and_holm_with_m_three():
    cs = cases2(32, 8)
    lines = S.evaluate2(cs, res2(cs, j20_gain=6))
    by = {l.split()[1]: l for l in lines if l.startswith("VERDICT")}
    assert set(by) == set(S.DECISIONS2) and S.DECISION2["D_SR40"][2] == "all"
    # D_J20 is judged on the 32 primary cases, D_SR40 on all 40, D_J40 on the 32
    assert " n=32 (J20 vs A0@20, not_jev)" in by["D_J20"] and " n=40 (SR40 vs A0@40, all)" in by["D_SR40"]
    assert " n=32 (J40 vs A0@40, not_jev)" in by["D_J40"]
    # six session-level gains, no losses: p = 0.5**6 = 0.0156; Holm with m = 3 gives 0.0469 <= 0.05
    # (m = 5 would give 0.0781 and fail), and the other two decisions are not significant
    assert "VERDICT: D_J20 PASS" in by["D_J20"] and "holm_p=0.0469" in by["D_J20"]
    assert "VERDICT: D_SR40 FAIL" in by["D_SR40"] and "VERDICT: D_J40 FAIL" in by["D_J40"]
    assert lines[-1] == "SHIP: D_J20"
    assert S.holm_adjusted([0.5 ** 6, 1.0, 1.0])[0] == pytest.approx(3 * 0.5 ** 6)


def test_iteration_two_jev_arms_have_an_absolute_p90_bound_and_sr40_a_relative_one():
    cs = cases2(32, 8)
    ok = S.evaluate2(cs, res2(cs, j20_gain=7, j20_ms=1500.0))
    assert any(l.startswith("VERDICT: D_J20 PASS") for l in ok)
    slow = S.evaluate2(cs, res2(cs, j20_gain=7, j20_ms=1501.0))
    assert any(l.startswith("VERDICT: D_J20 FAIL") and "G6=False" in l for l in slow)
    # SR40: 8 of 40 gained; p90 may sit 100 ms above its baseline (10 ms), not 101
    on = S.evaluate2(cs, res2(cs, sr_gain=8, sr_ms=110.0))
    assert any(l.startswith("VERDICT: D_SR40 PASS") for l in on)
    off = S.evaluate2(cs, res2(cs, sr_gain=8, sr_ms=111.0))
    assert any(l.startswith("VERDICT: D_SR40 FAIL") and "G6=False" in l for l in off)


def test_iteration_two_primary_stratum_below_the_jev_floor_is_insufficient():
    cs = cases2(24, 25)
    lines = S.evaluate2(cs, res2(cs, j20_gain=20, sr_gain=20))
    by = {l.split()[1]: l for l in lines if l.startswith("VERDICT")}
    assert by["D_J20"].startswith("VERDICT: D_J20 INSUFFICIENT n=24")
    assert by["D_J40"].startswith("VERDICT: D_J40 INSUFFICIENT n=24")
    assert "n=49" in by["D_SR40"] and "INSUFFICIENT" not in by["D_SR40"]
    assert not any(l.startswith("SHIP") for l in lines) or lines[-1] == "SHIP: D_SR40"


def test_gate_under_iteration_two_refuses_iteration_one_options_and_replay_is_iteration_one_only(capsys):
    S.set_iter(2)
    with pytest.raises(RuntimeError, match="iteration-1 options"):
        S.cmd_gate2({}, argparse.Namespace(arms="A0", combine=None, composites=False))
    assert S.cmd_replay_arms(None) == 2
    assert "iteration-1 set only" in capsys.readouterr().err


def test_gate_dispatches_to_the_iteration_two_arms_only_after_the_freeze_checks(monkeypatch):
    seen = []
    monkeypatch.setattr(S, "cmd_gate2", lambda man, args: seen.append(man["iteration"]) or 0)
    args = argparse.Namespace(arms=None, combine=None, composites=False)
    cases, man = fresh_setup()
    assert S.cmd_gate(args) == 0 and seen == [2]
    S.PLAN_DIR.joinpath("iter2-prereg.md").write_text("edited after the freeze\n")
    with pytest.raises(RuntimeError, match="prereg"):
        S.cmd_gate(args)
    assert seen == [2]


def test_pool_extension_skips_iteration_one_cases_caps_among_the_rest_and_stamps_pre_router():
    rows = [row(f"u{i}", f"s{i}", ["alpha"], offered=[]) for i in range(8)] + [row("w", "sw", ["whereami"], offered=[])]
    points = pts("alpha", "whereami")
    taken = {"u0|alpha", "u1|alpha"}
    enf = S._enf()
    saved = enf.BLOCKLIST
    enf.BLOCKLIST = frozenset({"whereami"})
    try:
        pool, st = S.build_cases(rows, points, set(), set(), lambda r: True, blocked=enf._blocked,
                                 exclude_ids=taken, pre_router=True)
        fresh, _ = S.build_cases(rows, points, set(), set(), lambda r: True, blocked=enf._blocked)
    finally:
        enf.BLOCKLIST = saved
    assert len(pool) == S.MAX_PER_LABEL                              # 6 unseen alpha rows, capped at 5 among themselves
    assert not taken & {c["id"] for c in pool}
    assert {c["offer_source"] for c in pool} == {"pre_router"} and {c["source"] for c in pool} == {"pre_router_unseen"}
    assert st["blocklisted_dropped"] == ["whereami"]
    assert {c["source"] for c in fresh} == {"fresh"} and {c["offer_source"] for c in fresh} == {"embed_or_none"}


def test_the_not_jev_primary_set_holds_embed_or_none_and_pre_router_cases():
    cs = cases2(10, 8) + [{"id": f"r{i}", "sid": f"sr{i}", "label": f"r{i}", "group": "not_offered",
                           "offer_source": "pre_router", "source": "pre_router_unseen"} for i in range(22)]
    lines = S.evaluate2(cs, res2(cs, j20_gain=0))
    by = {l.split()[1]: l for l in lines if l.startswith("VERDICT")}
    assert " n=32 (J20 vs A0@20, not_jev)" in by["D_J20"] and " n=40 (SR40 vs A0@40, all)" in by["D_SR40"]
    assert S.stratum_counts2(cs) == {"jev": 8, "embed_or_none": 10, "pre_router": 22}


def test_check_fresh_checks_session_and_time_on_fresh_cases_only_and_counts_unseen_cases_for_the_floor():
    cases, man = fresh_setup(n_cases=31)
    # an unseen iteration-1 row: it shares a spent session and is not after the cutoff, by design
    extra = {"id": "o9|zeta99", "uuid": "o9", "sid": "old1", "key": "zeta99", "label": "zeta99",
             "source": "pre_router_unseen", "offer_source": "pre_router"}
    write_jsonl(S.CASES, cases + [extra])
    S._append(S.QUERIES, {"k": "o9|zeta99|d0|x", "case": "o9|zeta99", "part": "d0", "reply": {"queries": ["do it"]}, "err": None})
    man["cases_sha256"] = S.sha256_file(S.CASES)
    man["queries"]["sha256"] = S.sha256_file(S.QUERIES)
    put_manifest(man)
    assert "cases 32" in S.check_fresh()
    # the same row marked fresh would fail on the shared session
    write_jsonl(S.CASES, cases + [{**extra, "source": "fresh"}])
    man["cases_sha256"] = S.sha256_file(S.CASES)
    put_manifest(man)
    with pytest.raises(S.FreshFail, match="sessions"):
        S.check_fresh()


def test_jev_decisions_use_their_own_case_floor_and_sr40_keeps_thirty():
    # 26 primary cases: enough for the Jev floor (25), not for the 30-case floor
    cs = cases2(26, 0)
    by = {l.split()[1]: l for l in S.evaluate2(cs, res2(cs, j20_gain=7)) if l.startswith("VERDICT")}
    assert "INSUFFICIENT" not in by["D_J20"] and "INSUFFICIENT" not in by["D_J40"]
    assert by["D_SR40"].startswith("VERDICT: D_SR40 INSUFFICIENT")
    cs = cases2(24, 0)
    by = {l.split()[1]: l for l in S.evaluate2(cs, res2(cs, j20_gain=7)) if l.startswith("VERDICT")}
    assert by["D_J20"].startswith("VERDICT: D_J20 INSUFFICIENT")
