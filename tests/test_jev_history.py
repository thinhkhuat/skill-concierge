"""Fitted conversation history for the router's rerank call (ENFORCER_JEV_HISTORY, default OFF) —
pinned offline: no network; the catalogue and Jev are replaced, transcripts are synthetic JSONL.

Covered:
  • the history holds only typed user text and assistant text, secrets redacted, tools by name;
  • it fits a token budget with the recent turns kept longest, and never raises on malformed records;
  • only the rerank call sees it, it is computed alongside the wide call, a slow or failed history falls
    back to today's state, and history alone can never cause the authorized skip;
  • flag off: requests are today's;
  • the calibrator's `hist` replay reads only up to the turn, gate mode caches failures as misses at
    the timeout, and `hist-compare` applies the pre-registered verdict rules.
"""

import json
import sys
import time
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import calibrate_jev_gate as C  # noqa: E402
import jev_client  # noqa: E402
import test_jev_router as R  # noqa: E402

PROMPT = R.PROMPT


def user(text, **kw):
    return {"type": "user", "message": {"role": "user", "content": text}, **kw}


def asst(text=None, tools=(), inputs=None):
    blocks = ([{"type": "text", "text": text}] if text else []) + [
        {"type": "tool_use", "name": n, "input": (inputs or {}).get(n, {})} for n in tools]
    return {"type": "assistant", "message": {"role": "assistant", "content": blocks}}


def tool_result(text):
    return {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "x", "content": text}]}}


def write(path, recs):
    path.write_text("\n".join(r if isinstance(r, str) else json.dumps(r) for r in recs) + "\n", encoding="utf-8")
    return str(path)


def lines(recs):
    return [json.dumps(r) for r in recs]


@pytest.fixture
def mod(tmp_path):
    return R._load(tmp_path / "on", ENFORCER_JEV_HISTORY="1")


@pytest.fixture
def mod_off(tmp_path):
    return R._load(tmp_path / "off")


def route(mod, monkeypatch, transcript, rerank=None, fake=None, prompt=PROMPT):
    """_jev_route with Jev replaced -> (result dict, [(state, question names)])."""
    calls = []
    good = rerank or R._rerank(0.9, [0.9, 0.2, 0.1, 0.1], {"update-config": 0.9, "ak-git": 0.04,
                                                           "session-handoff": 0.03, "tk-research": 0.03})

    def fake_call(state, questions, tier, key, timeout):
        calls.append((state, sorted(questions)))
        if fake:
            out = fake(state, questions)
            if out is not None:
                return out, "relay", "jev-1.13.0"
        if any(q.startswith("wide::") for q in questions):
            return R._wide([n for n, _ in R.CATALOG]), "relay", "jev-1.13.0"
        return good, "relay", "jev-1.13.0"

    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.setattr(mod, "_jev_catalog", lambda: list(R.CATALOG))
    monkeypatch.setattr(mod, "_jev_call", fake_call)
    return mod._jev_route(prompt, transcript), calls


def rerank_state(calls):
    return [st for st, qs in calls if not any(q.startswith("wide::") for q in qs)][0]


def wide_state(calls):
    return [st for st, qs in calls if any(q.startswith("wide::") for q in qs)][0]


def test_history_holds_only_typed_and_assistant_text(mod, monkeypatch, tmp_path):
    t = write(tmp_path / "t.jsonl", [
        user("typed words one"),
        user("<bash-stdout>BASHOUT</bash-stdout>"),
        user("<local-command-stdout>LOCALOUT</local-command-stdout>"),
        user("<task-notification>TASKNOTE</task-notification>"),
        user("<system-reminder>REMINDER</system-reminder>"),
        asst("assistant reply one", tools=["Bash"], inputs={"Bash": {"command": "ls COMMANDTEXT"}}),
        tool_result("RESULTTEXT"),
        user("typed words two", isMeta=True),
        {**user("sidechain typed"), "isSidechain": True},
    ])
    res, calls = route(mod, monkeypatch, t)
    assert res["result"] is not None
    blob = json.dumps(rerank_state(calls))
    for leaked in ("BASHOUT", "LOCALOUT", "TASKNOTE", "REMINDER", "COMMANDTEXT", "RESULTTEXT",
                   "typed words two", "sidechain typed"):
        assert leaked not in blob
    assert "typed words one" in blob and "assistant reply one" in blob


def test_secrets_never_reach_the_state(mod, monkeypatch, tmp_path):
    t = write(tmp_path / "t.jsonl", [
        user("call it with Authorization: Bearer abcdef123456789 please"),
        asst("I used sk-abcdefghijklmnopqrstuv for that"),
    ])
    res, calls = route(mod, monkeypatch, t)
    blob = json.dumps([st for st, _ in calls])
    assert "abcdef123456789" not in blob and "sk-abcdefghijklmnopqrstuv" not in blob
    assert "[redacted]" in blob


def test_tools_appear_by_name_only(mod, monkeypatch, tmp_path):
    t = write(tmp_path / "t.jsonl", [
        user("run the thing"),
        asst("running", tools=["Bash"], inputs={"Bash": {"command": "curl -H 'x-api-key: SUPERSECRETVALUE' https://x"}}),
    ])
    res, calls = route(mod, monkeypatch, t)
    blob = json.dumps(rerank_state(calls))
    assert '"Bash"' in blob
    assert "curl" not in blob and "SUPERSECRETVALUE" not in blob


def test_current_prompt_is_not_repeated_in_history(mod):
    base = [user("earlier question"), asst("earlier answer")]
    res = mod._jev_history_lines(lines(base + [user(PROMPT)]), 10000, PROMPT)
    assert [e["text"] for e in res["conversation"]] == ["earlier question", "earlier answer"]
    res = mod._jev_history_lines(lines(base + [user(PROMPT), asst("reply to it")]), 10000, PROMPT)
    assert PROMPT in [e["text"] for e in res["conversation"]]       # only a trailing copy is dropped


def long_conversation(turns):
    recs = []
    for i in range(turns):
        recs += [user(f"question {i} " + "alpha beta gamma " * 20), asst(f"answer {i} " + "delta epsilon " * 60,
                                                                           tools=["Read", "Bash"])]
    return lines(recs)


def test_history_fits_the_token_budget(mod):
    res = mod._jev_history_lines(long_conversation(100), 10000, PROMPT, ["ak-git"])
    assert res is not None and res["tokens"] <= 10000
    state = mod._jev_history_state(PROMPT, ["ak-git"], res)
    assert mod._jev_tokens(json.dumps(state, ensure_ascii=False)) <= 10000
    assert res["stage"] != "full"


def test_recent_turns_survive_longer_than_old_ones(mod):
    recs = []
    for i in range(30):
        recs += [user(f"u{i} " + "w" * 200)] if i % 2 == 0 else [asst(f"a{i} " + "w" * 200, tools=["Read"])]
    res = mod._jev_history_lines(lines(recs), 700, PROMPT)
    assert res is not None
    conv = res["conversation"]
    originals = [r["message"]["content"] if isinstance(r["message"]["content"], str)
                 else r["message"]["content"][0]["text"] for r in recs]
    assert [e["text"] for e in conv[-6:]] == originals[-6:]
    assert res["stage"] in ("old messages collapsed", "old tools counted", "old messages left out")
    assert len(conv) <= 30 and all(not e["text"].startswith("u0 ") for e in conv)


def test_unfittable_entry_returns_none(mod):
    assert mod._jev_history_lines(lines([user("x " * 5000)]), 40, PROMPT) is None
    assert mod._jev_history_lines([], 10000, PROMPT) is None
    assert mod._jev_history_lines(lines([user(PROMPT)]), 10000, PROMPT) is None


def test_malformed_records_fall_back_silently(mod, monkeypatch, tmp_path):
    junk = ["not json at all", "[1, 2]", "null",
            json.dumps({"type": "assistant", "message": "just a string"}),
            json.dumps({"type": "assistant", "message": {"content": "string content"}}),
            json.dumps({"type": "assistant", "message": {"content": [
                {"text": "no type"}, {"type": "tool_use"}, {"type": "tool_use", "name": "Edit"}, 5, None,
                {"type": "text", "text": None}]}}),
            json.dumps({"type": "user", "message": None}),
            json.dumps({"type": "user", "message": {"content": [{"type": "text", "text": None}, "x"]}}),
            json.dumps(user("a real typed line"))]
    t = write(tmp_path / "t.jsonl", junk)
    out = mod._jev_history(t, PROMPT)
    assert out is None or isinstance(out, dict)
    assert out is not None and "a real typed line" in json.dumps(out)
    assert mod._jev_history(str(tmp_path / "missing.jsonl"), PROMPT) is None
    monkeypatch.setattr(mod, "_jev_history_lines", lambda *a, **k: 1 / 0)
    info = {}
    assert mod._jev_history(t, PROMPT, info=info) is None and info["err"] == "ZeroDivisionError"
    res, _ = route(mod, monkeypatch, t)
    assert res["result"] is not None and res["event"]["hist"] == {"err": "ZeroDivisionError"}


def three_key(state):
    return set(state) == {"request", "recent_context", "skills_already_loaded_this_session"}


def test_flag_off_sends_todays_state_to_both_calls(mod_off, monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(mod_off, "_jev_history", lambda *a, **k: seen.append(a))
    t = write(tmp_path / "t.jsonl", [user("earlier"), asst("reply")])
    res, calls = route(mod_off, monkeypatch, t)
    assert not seen and "hist" not in res["event"]
    assert len(calls) == 2 and all(three_key(st) for st, _ in calls)
    assert json.dumps(calls[0][0], sort_keys=True) == json.dumps(calls[1][0], sort_keys=True)
    assert calls[0][0]["recent_context"] == "reply"


def test_flag_on_changes_only_the_rerank_state(mod, monkeypatch, tmp_path):
    t = write(tmp_path / "t.jsonl", [user("earlier"), asst("reply")])
    res, calls = route(mod, monkeypatch, t)
    assert three_key(wide_state(calls)) and wide_state(calls)["recent_context"] == "reply"
    rs = rerank_state(calls)
    assert "conversation" in rs and "recent_context" not in rs
    assert {"request", "conversation_note", "skills_already_loaded_this_session"} <= set(rs)
    assert res["result"][0] == "offer"


def test_history_is_computed_alongside_the_wide_call(mod, monkeypatch, tmp_path):
    t = write(tmp_path / "t.jsonl", [user("earlier"), asst("reply")])
    real = mod._jev_history

    def slow_history(*a, **k):
        time.sleep(0.3)
        return real(*a, **k)
    monkeypatch.setattr(mod, "_jev_history", slow_history)

    def slow_wide(state, questions):
        if any(q.startswith("wide::") for q in questions):
            time.sleep(0.3)
        return None
    t0 = time.time()
    res, calls = route(mod, monkeypatch, t, fake=slow_wide)
    assert time.time() - t0 < 0.55          # 0.3 + 0.3 run one after the other would be 0.6
    assert "conversation" in rerank_state(calls) and res["event"]["hist"]["used"] is True


def test_slow_history_falls_back_to_todays_state(mod, monkeypatch, tmp_path):
    t = write(tmp_path / "t.jsonl", [user("earlier"), asst("reply")])
    monkeypatch.setattr(mod, "_jev_history", lambda *a, **k: (time.sleep(1.0), {"conversation": [], "stage": "full", "tokens": 1})[1])
    res, calls = route(mod, monkeypatch, t)
    assert three_key(rerank_state(calls)) and res["event"]["hist"] == {"err": "Slow"}


SKIPPY = R._rerank(0.5, [0.1, 0.1, 0.1, 0.1], {"update-config": 0.4, "ak-git": 0.2, "session-handoff": 0.2,
                                               "tk-research": 0.2})


def skip_on_history(state, questions):
    """History in the state -> every fit under the floor; today's state -> a fit of 0.8."""
    if any(q.startswith("wide::") for q in questions):
        return None
    return SKIPPY if "conversation" in state else R._rerank(0.9, [0.8, 0.2, 0.1, 0.1], {
        "update-config": 0.9, "ak-git": 0.04, "session-handoff": 0.03, "tk-research": 0.03})


def test_history_alone_never_skips(mod, monkeypatch, tmp_path):
    t = write(tmp_path / "t.jsonl", [user("earlier"), asst("No skill is needed for this; answer directly.")])
    res, calls = route(mod, monkeypatch, t, fake=skip_on_history)
    verdict, rows, best = res["result"][:3]
    assert verdict == "offer" and best == pytest.approx(0.8) and rows[0][0] == "update-config"
    assert res["event"]["hist"]["reask"] is True and len(calls) == 3
    assert "conversation" in calls[1][0] and three_key(calls[2][0])
    # no budget left for the second rerank: the embedding path decides, never a skip
    monkeypatch.setattr(mod, "JEV_REASK_MIN_S", 99.0)
    res, calls = route(mod, monkeypatch, t, fake=skip_on_history)
    assert res["result"] is None and res["event"]["err"] == "HistorySkip" and len(calls) == 2


def test_todays_own_skip_still_skips_with_history_on(mod, monkeypatch, tmp_path):
    t = write(tmp_path / "t.jsonl", [user("earlier"), asst("reply")])
    res, calls = route(mod, monkeypatch, t, rerank=SKIPPY)
    assert res["result"][0] == "skip" and res["event"]["hist"]["reask"] is True


def test_missing_transcript_falls_back_to_todays_state(mod, monkeypatch, tmp_path):
    res, calls = route(mod, monkeypatch, str(tmp_path / "nope.jsonl"))
    assert three_key(rerank_state(calls)) and res["event"]["hist"] == {"err": "FileNotFoundError"}
    assert res["result"] is not None


def test_event_records_history_size_stage_and_time(mod, monkeypatch, tmp_path):
    t = write(tmp_path / "t.jsonl", [user("earlier"), asst("reply")])
    res, _ = route(mod, monkeypatch, t)
    h = res["event"]["hist"]
    assert set(h) == {"tok", "stage", "ms", "used", "reask"}
    assert h["tok"] > 0 and h["stage"] == "full" and h["used"] is True and h["reask"] is False


# ── calibrator ───────────────────────────────────────────────────────────────

def test_replay_reads_only_up_to_the_turn(mod, monkeypatch, tmp_path):
    proj = tmp_path / "projects" / "-p"
    proj.mkdir(parents=True)
    recs = [{**user("before one"), "uuid": "u1"}, {**asst("before two"), "uuid": "u2"},
            {**user("the turn itself"), "uuid": "u3"}, {**asst("after one"), "uuid": "u4"},
            {**user("after two"), "uuid": "u5"}]
    write(proj / "s1.jsonl", recs)
    monkeypatch.setattr(C, "PROJECTS", tmp_path / "projects")
    monkeypatch.setattr(C, "load_enforcer", lambda: mod)
    row = {"project": "-p", "sid": "s1", "uuid": "u3", "prompt": "the turn itself", "prev_assistant": "before two",
           "session_skills": []}
    state, meta = C.build_hist(mod, row)
    blob = json.dumps(state)
    assert "before one" in blob and "before two" in blob
    assert "after one" not in blob and "after two" not in blob and "the turn itself" not in state["conversation"][-1]["text"]
    assert meta["fallback"] is False and C.build_state(row, "hist") == state
    gone = dict(row, sid="missing")
    state, meta = C.build_hist(mod, gone)
    assert meta["fallback"] is True and state == C.build_state(gone, "ctx")
    adv, _ = C.build_hist(mod, row, inject=True)
    assert adv["conversation"][-1]["text"].endswith(C.INJECTION)


CATALOG = [["update-config", "Configure settings."], ["ak-git", "Git."], ["session-handoff", "Handoff."],
           ["tk-research", "Research."]]


@pytest.fixture
def cal(tmp_path, monkeypatch):
    enf = R._load(tmp_path / "log", ENFORCER_JEV_HISTORY="1")
    row = {"uuid": "u1", "sid": "s", "project": "-p", "prompt": "do the other repo too", "prompt_words": 5,
           "prev_assistant": "done with the first", "session_skills": [], "final_names": ["update-config"],
           "ts_local": "2026-09-30T10:00:00+07:00"}
    monkeypatch.setattr(C, "load_enforcer", lambda: enf)
    monkeypatch.setattr(C, "CAL_DIR", tmp_path)
    monkeypatch.setattr(C, "GATE_CACHE", tmp_path / "gate-scores.jsonl")
    monkeypatch.setattr(C, "PROJECTS", tmp_path / "projects")
    monkeypatch.setattr(C, "load_corpus", lambda p: [])
    monkeypatch.setattr(C, "pick", lambda e, rows, n, seed: ([row], []))
    monkeypatch.setattr(C, "live_catalog", lambda: [list(x) for x in CATALOG])
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    return enf, row


def gate_args(**kw):
    base = dict(shelf="wide", variants=["ctx", "hist"], corpus=Path("x"), unlabelled=0, seed=1,
                model="jev-1.13.0", endpoint="ts", dry_run=False, gate=True)
    base.update(kw)
    return types.SimpleNamespace(**base)


def test_gate_mode_caches_failures_as_misses(cal, monkeypatch, tmp_path):
    enf, row = cal
    asked = []

    def failing(state, questions, timeout, **kw):
        asked.append(kw)
        raise jev_client.JevError("TimeoutError")
    monkeypatch.setattr(C.jev_client, "ask", failing)
    assert C.cmd_replay_gate(gate_args()) == 0
    recs = [json.loads(ln) for ln in (tmp_path / "gate-scores.jsonl").read_text().splitlines()]
    assert len(recs) == 1 and recs[0]["kind"] == "wide" and recs[0]["ans"] is None
    assert recs[0]["err"] == "TimeoutError"
    assert recs[0]["ms"] == int(enf.JEV_TIMEOUT_S * 1000)         # a miss costs the whole timeout
    assert asked == [{"tiers": [enf._jev_bench()[0]], "retries": 0, "workers": 1}]
    C.cmd_replay_gate(gate_args())                                  # cached: one attempt per call, ever
    assert len(asked) == 1


def test_gate_dry_run_sends_nothing(cal, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(C.jev_client, "ask", lambda *a, **k: pytest.fail("sent"))
    assert C.cmd_replay_gate(gate_args(dry_run=True)) == 0
    assert "nothing sent" in capsys.readouterr().out and not (tmp_path / "gate-scores.jsonl").exists()


def test_gate_scores_ctx_and_hist_and_hist_compare_reads_them(cal, monkeypatch, tmp_path, capsys):
    enf, row = cal
    proj = tmp_path / "projects" / "-p"
    proj.mkdir(parents=True)
    write(proj / "s.jsonl", [{**user("earlier ask"), "uuid": "a"}, {**asst("did the first repo"), "uuid": "b"},
                             {**user(row["prompt"]), "uuid": "u1"}])
    wide = R._wide([n for n, _ in CATALOG])

    def ask(state, questions, timeout, **kw):
        if any(q.startswith("wide::") for q in questions):
            return wide, {"ms": 400}
        top = "update-config" if "conversation" in state else "ak-git"
        probs = {n: 0.01 for n, _ in CATALOG}
        probs[top] = 0.9
        return R._rerank(0.9, [0.8] * 4, probs), {"ms": 700 if "conversation" in state else 600}
    monkeypatch.setattr(C.jev_client, "ask", ask)
    assert C.cmd_replay_gate(gate_args()) == 0
    kinds = sorted(json.loads(ln)["kind"] for ln in (tmp_path / "gate-scores.jsonl").read_text().splitlines())
    assert kinds == ["adv-ctx", "adv-hist", "ctx", "hist", "wide"]
    capsys.readouterr()
    assert C.cmd_hist_compare(types.SimpleNamespace(corpus=Path("x"), model="jev-1.13.0", unlabelled=0, seed=1,
                                                    catalog_hash=None)) == 0
    out = capsys.readouterr().out
    verdict_lines = [ln for ln in out.splitlines() if ln.startswith("VERDICT:")]
    assert len(verdict_lines) == 1 and verdict_lines[0].startswith("VERDICT: INSUFFICIENT")
    assert "wins" not in out or "hist gets and ctx misses: 1" in out        # hist offers the used skill, ctx does not
    assert "adversarial row: 1 planted-text turns" in out


def good_metrics(**kw):
    m = {"n_offered_follow": 80, "ceiling_follow": 90.0, "ctx_follow_recall": 60.0, "hist_follow_recall": 70.0,
         "wins": 12, "losses": 3, "ctx_recall": 74.0, "hist_recall": 75.0, "ctx_false_no": 5, "hist_false_no": 5,
         "hist_rerank_p90": 1200, "route_p90": 2400, "fit_p90": 40, "adv_n": 20, "adv_skips": 0}
    m.update(kw)
    return m


def test_hist_compare_verdict_rules():
    assert C.hist_verdict(good_metrics())[0] == "PASS"
    assert C.hist_verdict(good_metrics(n_offered_follow=49))[0] == "INSUFFICIENT"
    assert C.hist_verdict(good_metrics(n_offered_follow=50))[0] == "PASS"
    assert C.hist_verdict(good_metrics(ceiling_follow=62.9))[0] == "INSUFFICIENT"      # ceiling - ctx < 3.0
    assert C.hist_verdict(good_metrics(adv_n=19))[0] == "INSUFFICIENT"
    failing = {"follow-up recall gain": dict(hist_follow_recall=62.9),
               "follow-up wins > losses": dict(wins=3, losses=3),
               "overall recall no loss": dict(hist_recall=73.9),
               "false NO no worse": dict(hist_false_no=6),
               "hist rerank p90 <= 1500 ms": dict(hist_rerank_p90=1501),
               "route p90 <= 3000 ms": dict(route_p90=3001),
               "fit p90 <= 100 ms": dict(fit_p90=101),
               "adversarial row: 0 history-caused skips": dict(adv_skips=1)}
    for name, change in failing.items():
        verdict, why = C.hist_verdict(good_metrics(**change))
        assert verdict == "FAIL" and why == [name], name
    assert C.hist_verdict(good_metrics(route_p90=None))[0] == "FAIL"


def test_hist_compare_handles_every_cached_record_shape(cal, monkeypatch, tmp_path, capsys):
    """Shapes seen in a real replay cache: a wide record alone (the wide call timed out), a record shared by
    two turns with the same state (it carries only the first turn's uuid), a failed hist rerank, a hist
    copied from ctx (no transcript), and the adversarial pair with one failed side."""
    enf, row = cal
    proj = tmp_path / "projects" / "-p"
    proj.mkdir(parents=True)
    write(proj / "s.jsonl", [{**user("earlier ask"), "uuid": "a"}, {**asst("did the first repo"), "uuid": "b"},
                             {**user(row["prompt"]), "uuid": "u1"}, {**user(row["prompt"]), "uuid": "u2"},
                             {**user("a different ask"), "uuid": "u3"}])
    same = dict(row, uuid="u2")                                   # same state as u1: shares wide and ctx records
    nohist = dict(row, uuid="u9", sid="gone", prompt="another ask entirely")
    late = dict(row, uuid="u3", prompt="a different ask")
    monkeypatch.setattr(C, "pick", lambda e, rows, n, seed: ([row, same, nohist, late], []))
    timed_out = {"late": True}

    def ask(state, questions, timeout, **kw):
        if state["request"] == "a different ask" and any(q.startswith("wide::") for q in questions):
            raise jev_client.JevError("TimeoutError")
        if "conversation" in state and state["request"] == row["prompt"] and \
                state["conversation"][-1]["text"].endswith(C.INJECTION) and timed_out.pop("late", None):
            raise jev_client.JevError("TimeoutError")
        if any(q.startswith("wide::") for q in questions):
            return R._wide([n for n, _ in CATALOG]), {"ms": 400}
        probs = {n: 0.01 for n, _ in CATALOG}
        probs["update-config"] = 0.9
        return R._rerank(0.9, [0.8] * 4, probs), {"ms": 700}
    monkeypatch.setattr(C.jev_client, "ask", ask)
    assert C.cmd_replay_gate(gate_args()) == 0
    capsys.readouterr()
    args = types.SimpleNamespace(corpus=Path("x"), model="jev-1.13.0", unlabelled=0, seed=1, catalog_hash=None)
    assert C.cmd_hist_compare(args) == 0
    out = capsys.readouterr().out
    assert "turns with no cached record at all: 0" in out           # u2 is found through the shared key
    assert "turns whose wide call failed (no rerank, a miss at the timeout): 1" in out
    assert "hist fell back to today's state on 1 turns" in out
    assert out.count("VERDICT:") == 1
    assert "'wide': 1" in out and "'adv-hist': 1" in out or "'adv-ctx': 1" in out


def test_private_files_are_created_0600(cal, monkeypatch, tmp_path):
    monkeypatch.setattr(C.jev_client, "ask", lambda *a, **k: (_ for _ in ()).throw(jev_client.JevError("TimeoutError")))
    old = __import__("os").umask(0o022)
    try:
        assert C.cmd_replay_gate(gate_args()) == 0
    finally:
        __import__("os").umask(old)
    for path in [tmp_path / "gate-scores.jsonl", *tmp_path.glob("catalog-*.json")]:
        assert path.stat().st_mode & 0o777 == 0o600, path


def test_malformed_history_env_values_never_crash_the_import(tmp_path):
    for n, var in enumerate(("ENFORCER_JEV_HISTORY_TOKENS", "ENFORCER_JEV_HISTORY_BYTES")):
        m = R._load(tmp_path / f"bad{n}", **{var: "abc"})
        assert m.JEV_HISTORY_TOKENS == 10000 and m.JEV_HISTORY_BYTES == 2097152
    m = R._load(tmp_path / "ok", ENFORCER_JEV_HISTORY_TOKENS="6000", ENFORCER_JEV_HISTORY_BYTES="1000")
    assert m.JEV_HISTORY_TOKENS == 6000 and m.JEV_HISTORY_BYTES == 1000


def short_turns(n):
    out = []
    for i in range(n):
        out.append(json.dumps(user(f"short turn number {i} ok") if i % 2 == 0 else asst(f"reply {i} done")))
    return out


def test_fit_time_stays_flat_on_a_long_transcript_of_short_turns(mod, monkeypatch):
    big = short_turns(25000)                                    # about 2 MB of JSONL
    assert sum(len(x) + 1 for x in big) > 1_900_000
    t = time.time()
    res = mod._jev_history_lines(big, 10000, PROMPT)
    ms = (time.time() - t) * 1000
    assert res is not None and res["tokens"] <= 10000
    assert ms < 150, f"{ms:.0f} ms"
    # work scales with the budget, not with the transcript: ten times the lines, the same token-estimator calls
    calls = []
    real = mod._jev_tokens
    monkeypatch.setattr(mod, "_jev_tokens", lambda text: (calls.append(1), real(text))[1])
    mod._jev_history_lines(short_turns(2500), 10000, PROMPT)
    small = len(calls)
    calls.clear()
    mod._jev_history_lines(short_turns(25000), 10000, PROMPT)
    assert len(calls) <= small * 1.2


def test_fitter_calls_scale_linearly_with_entries(mod, monkeypatch):
    calls = []
    real = mod._jev_tokens
    monkeypatch.setattr(mod, "_jev_tokens", lambda text: (calls.append(1), real(text))[1])
    counts = []
    for n in (200, 400, 800):
        calls.clear()
        mod._jev_history_lines(lines([user("alpha beta gamma " * 4) if i % 2 == 0 else asst("delta " * 12)
                                      for i in range(n)]), 1000, PROMPT)
        counts.append(len(calls))
    assert counts[2] <= counts[0] * 5 and counts[1] <= counts[0] * 2.6      # quadratic would be 16x and 4x


def test_newest_turns_are_kept_when_reading_stops_early(mod):
    res = mod._jev_history_lines(short_turns(20000), 10000, PROMPT)
    assert res["conversation"][-1]["text"] == "reply 19999 done"
    assert res["conversation"][-2]["text"] == "short turn number 19998 ok"
