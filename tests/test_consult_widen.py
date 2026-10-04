"""scripts/consult_fit.py `widen`: Jev's top 10 ahead of the sieve rows, cut to 20. Offline: Jev is replaced at
the enforcer's transport boundary (`_post_json`) and the catalogue at `_jev_catalog`, as test_consult_fit.py does.
"""

import io
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import consult_fit as cf  # noqa: E402
import consult_log  # noqa: E402
import sieve_recall  # noqa: E402

CAT = [(f"s{i}", f"desc {i}") for i in range(30)]


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for k in ("ENFORCER_JEV_BENCH", "ENFORCER_JEV_URL", "ENFORCER_JEV_KEY", "ENFORCER_JEV_MODEL",
              "FLYWHEEL_LLM_ENDPOINT", "FLYWHEEL_LLM_API_KEY", "SKILL_CONSULT_JEV_WIDEN", "SKILL_CONSULT_JEV"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ENFORCER_JEV_BENCH", "ts:jev-1.13.0")
    monkeypatch.setenv("TYPESAFE_API_KEY", "sk-test-SECRET-0000000000")
    monkeypatch.setenv("JEV_CLIENT_MAX_TPS", "1e9")
    monkeypatch.setenv("JEV_CLIENT_MAX_RPS", "1e9")
    cf.jc._RATE = cf.jc._Rate()


def fake_jev(monkeypatch, order=None, fail=False):
    """Fake the wide call: probabilities descend along `order` inside the single chunk."""
    enf = cf.jc.load_enforcer()
    calls = []
    monkeypatch.setattr(enf, "_jev_catalog", lambda: CAT)

    def post(url, body, timeout, headers=None):
        calls.append(body)
        if fail:
            raise TimeoutError()
        out = {}
        for k, q in body["questions"].items():
            names = [n for n in (order or []) if n in q["criteria"]]
            out[k] = {"type": "choice", "choice": None, "confidence": 0.5,
                      "probabilities": {n: 1.0 - i / 100 for i, n in enumerate(names)}}
        return {"answers": out, "model": body["model"]}
    monkeypatch.setattr(enf, "_post_json", post)
    return calls


def sieve(*names):
    return [{"name": n, "description": f"sieve {n}", "score": 0.5} for n in names]


def test_ordering_dedupe_and_cut_match_the_gate(monkeypatch):
    jev = [f"s{i}" for i in (7, 3, 11, 1, 20, 21, 22, 23, 24, 25, 26, 27)]
    fake_jev(monkeypatch, order=jev)
    rows = sieve("s3", "plug:s7", *[f"x{i}" for i in range(40)])
    out = cf.widen("set up a hook", {"results": rows})
    top10 = jev[:10]
    want = sieve_recall.union_rows(top10, [{"name": r["name"], "external": False} for r in rows], 20)
    assert [r["name"] for r in out["results"]] == [w["name"] for w in want]
    assert len(out["results"]) == 20 and out["jev"]["failed"] is False


def test_sources_and_both_rows_keep_sieve_fields(monkeypatch):
    fake_jev(monkeypatch, order=["s3", "s9"])
    out = cf.widen("t", sieve("s3", "x1"))
    r = {x["name"]: x for x in out["results"]}
    assert r["s3"]["source"] == "both" and r["s3"]["description"] == "sieve s3" and r["s3"]["score"] == 0.5
    assert r["s9"] == {"name": "s9", "description": "desc 9", "source": "jev"}
    assert r["x1"]["source"] == "sieve" and out["jev"]["added"] == 1
    assert [x["name"] for x in out["results"]] == ["s3", "s9", "x1"]


def test_candidates_may_be_the_bare_results_list(monkeypatch):
    fake_jev(monkeypatch, order=["s2"])
    assert cf.widen("t", sieve("a"))["results"][0]["name"] == "s2"


def test_secret_and_reminder_never_reach_jev(monkeypatch):
    calls = fake_jev(monkeypatch, order=["s1"])
    task = ("<system-reminder>PRIVATE-REMINDER-BODY</system-reminder> use Bearer abcdefghijklmnop123 "
            "to deploy")
    cf.widen(task, sieve("a"))
    sent = json.dumps(calls[0]["state"])
    assert "abcdefghijklmnop123" not in sent and "PRIVATE-REMINDER-BODY" not in sent
    assert "deploy" in sent


def test_half_token_is_dropped_when_the_task_is_truncated():
    task = "word " * 799 + "partialsecretfrag more"      # the 4000-char cut lands inside "partialsecretfrag"
    out = cf.widen_clean(task)
    assert out.endswith("word") and "partia" not in out


def test_a_task_under_the_cap_keeps_its_last_token():
    assert cf.widen_clean("fix the hook partialsecretfrag").endswith("partialsecretfrag")


def test_kill_switch_makes_no_jev_call_and_keeps_the_row_shape(monkeypatch, capsys):
    calls = fake_jev(monkeypatch, order=["s1"])
    monkeypatch.setenv("SKILL_CONSULT_JEV_WIDEN", "0")
    rows = sieve(*[f"x{i}" for i in range(30)])
    code = cf.main(["widen"], stdin=io.StringIO(json.dumps({"task": "t", "candidates": {"results": rows}})))
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and calls == []
    assert out["results"] == [{**r, "source": "sieve"} for r in rows[:20]]
    assert out["jev"] == {"ms": 0, "failed": False, "added": 0, "state": "off"}


def test_consult_jev_kill_switch_does_not_stop_widen(monkeypatch):
    calls = fake_jev(monkeypatch, order=["s1"])
    monkeypatch.setenv("SKILL_CONSULT_JEV", "0")
    assert cf.main(["widen"], stdin=io.StringIO(json.dumps({"task": "t", "candidates": sieve("a")}))) == 0
    assert len(calls) == 1


@pytest.mark.parametrize("mode", ["timeout", "no_key", "empty_catalogue"])
def test_jev_failure_falls_back_to_the_sieve_rows(monkeypatch, capsys, mode):
    enf = cf.jc.load_enforcer()
    calls = fake_jev(monkeypatch, order=["s1"], fail=(mode == "timeout"))
    if mode == "no_key":
        monkeypatch.delenv("TYPESAFE_API_KEY")
    if mode == "empty_catalogue":
        monkeypatch.setattr(enf, "_jev_catalog", lambda: [])
    rows = sieve(*[f"x{i}" for i in range(30)])
    code = cf.main(["widen"], stdin=io.StringIO(json.dumps({"task": "t", "candidates": rows})))
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["jev"]["failed"] is True and out["jev"]["added"] == 0
    assert [r["name"] for r in out["results"]] == [r["name"] for r in rows[:20]]
    assert (calls == []) == (mode != "timeout") and out["jev"]["state"] == "not-widened"


@pytest.mark.parametrize("raw", ["not json", json.dumps([]), json.dumps({"task": " ", "candidates": []}),
                                 json.dumps({"task": "t", "candidates": [{"description": "no name"}]})])
def test_bad_input_is_rejected(raw, capsys):
    assert cf.main(["widen"], stdin=io.StringIO(raw)) == 2
    assert json.loads(capsys.readouterr().out)["ok"] is False


def test_selftest_passes(capsys):
    assert cf.main(["widen", "--selftest"]) == 0
    assert "WIDEN-SELFTEST-OK" in capsys.readouterr().out


# --- privacy: strip and redact before the cut ----------------------------------------------------------

def test_a_reminder_straddling_the_cut_never_reaches_jev(monkeypatch):
    calls = fake_jev(monkeypatch, order=["s1"])
    task = "fix the hook " + "w " * 1800 + "<system-reminder>STRADDLE-SECRET-BODY " + "z " * 400 + "</system-reminder> end"
    assert task.index("<system-reminder>") < cf.WIDEN_TASK_CAP < task.index("</system-reminder>")
    cf.widen(task, sieve("a"))
    sent = json.dumps(calls[0]["state"])
    assert "STRADDLE-SECRET-BODY" not in sent and "system-reminder" not in sent


def test_a_long_leading_block_does_not_cut_off_the_request(monkeypatch):
    calls = fake_jev(monkeypatch, order=["s1"])
    cf.widen("<system-reminder>" + "r " * 3000 + "</system-reminder> MY-REAL-REQUEST please", sieve("a"))
    assert calls[0]["state"]["request"] == "MY-REAL-REQUEST please"


def test_an_empty_cleaned_request_skips_jev(monkeypatch):
    calls = fake_jev(monkeypatch, order=["s1"])
    out = cf.widen("<system-reminder>only injected text</system-reminder>", sieve("a", "b"))
    assert calls == [] and out["jev"]["failed"] is True and out["jev"]["added"] == 0
    assert [r["name"] for r in out["results"]] == ["a", "b"]


# --- the call shape the gate proved ---------------------------------------------------------------------

def test_jev_call_shape_is_one_attempt_3s_ts_tier_empty_context(monkeypatch):
    monkeypatch.setenv("ENFORCER_JEV_BENCH", "gw:g-model ts:first ts:second")
    seen = {}

    def ask(state, qs, timeout, tiers=None, retries=1, **kw):
        seen.update(state=state, timeout=timeout, tiers=tiers, retries=retries, kw=kw)
        return {"wide::0": {"probabilities": {"s1": 1.0}}}, {}
    cf.jev_top("the request", catalog_fn=lambda: CAT, ask_fn=ask)
    assert seen["retries"] == 0 and seen["timeout"] == 3.0
    assert [t["ep"] for t in seen["tiers"]] == ["ts"] and seen["tiers"][0]["model"] == "first"
    assert seen["state"] == {"request": "the request", "recent_context": "",
                             "skills_already_loaded_this_session": []}


def test_jev_top_takes_ten_names():
    answers = {"wide::0": {"probabilities": {f"s{i}": 1 - i / 100 for i in range(15)}}}
    names = cf.jev_top("t", catalog_fn=lambda: CAT, ask_fn=lambda *a, **k: (answers, {}))
    assert [n for n, _ in names] == [f"s{i}" for i in range(10)]


def test_round_robin_across_two_chunks_not_concatenated():
    answers = {"wide::1": {"probabilities": {"b1": .9, "b2": .8}},
               "wide::0": {"probabilities": {"a1": .5, "a2": .4, "a3": .3}},
               "wide::10": {"probabilities": {"c1": .1}}}
    assert cf.jev_round_robin(answers) == ["a1", "b1", "c1", "a2", "b2", "a3"]


# --- merge edge cases -----------------------------------------------------------------------------------

def test_an_installed_jev_pick_beats_an_external_sieve_row_of_the_same_key(monkeypatch):
    fake_jev(monkeypatch, order=["s3"])
    ext = {"name": "s3", "description": "ext copy", "external": "catalog-x", "score": .4}
    out = cf.widen("t", [ext])
    assert out["results"][0]["source"] == "both" and "external" not in out["results"][0]
    assert out["results"][0]["description"] == "ext copy"


def test_selftest_restores_the_environment(monkeypatch):
    monkeypatch.setenv("SKILL_CONSULT_JEV_WIDEN", "1")
    monkeypatch.delenv("ENFORCER_JEV_BENCH", raising=False)
    monkeypatch.setenv("TYPESAFE_API_KEY", "keep-me")
    before = dict(os.environ)
    assert cf.widen_selftest() == 0
    assert dict(os.environ) == before


# --- the sieve runs inside widen ------------------------------------------------------------------------

def test_queries_input_runs_the_engine_with_the_queries(monkeypatch, capsys):
    fake_jev(monkeypatch, order=["s2"])
    got = []
    monkeypatch.setattr(cf, "sieve_rows_from_engine", lambda q: got.append(q) or sieve("a", "b"))
    code = cf.main(["widen"], stdin=io.StringIO(json.dumps({"task": "t", "queries": ["q1", "q2"]})))
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and got == [["q1", "q2"]]
    assert [r["name"] for r in out["results"]] == ["s2", "a", "b"] and out["jev"]["state"] == "widened"


def test_engine_failure_exits_4_and_makes_no_row_claim(monkeypatch, capsys):
    fake_jev(monkeypatch, order=["s2"])

    def down(q):
        raise cf.SieveUnavailable("ModuleNotFoundError")
    monkeypatch.setattr(cf, "sieve_rows_from_engine", down)
    code = cf.main(["widen"], stdin=io.StringIO(json.dumps({"task": "t", "queries": ["q"]})))
    out = json.loads(capsys.readouterr().out)
    assert code == 4 and out["ok"] is False and "results" not in out


@pytest.mark.parametrize("body", [{"task": "t"}, {"task": "t", "queries": []}, {"task": "t", "queries": [1]}])
def test_neither_queries_nor_candidates_is_bad_input(body, capsys):
    assert cf.main(["widen"], stdin=io.StringIO(json.dumps(body))) == 2


def fake_engine(tmp_path, monkeypatch):
    pkg = tmp_path / "pkg" / "skill_search"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "server.py").write_text(
        "import json, os\n"
        "def consult_candidates(queries, top_n):\n"
        "    leak = [k for k in ('OPENAI_API_KEY', 'TYPESAFE_API_KEY', 'ANTHROPIC_API_KEY') if k in os.environ]\n"
        "    return json.dumps({'results': [{'name': q, 'description': os.environ['SKILL_CONSULT_SLOTS'] + "
        "os.environ['SKILL_CONSULT_RRF'] + str(top_n), 'cwd': os.getcwd(), 'leak': leak, "
        "'keep': [os.environ.get('SKILL_COLLECTION'), 'PATH' in os.environ, 'HOME' in os.environ]} "
        "for q in queries]})\n")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path / "pkg"))


def test_engine_child_runs_the_installed_package_with_flags_off(monkeypatch, tmp_path):
    fake_engine(tmp_path, monkeypatch)
    monkeypatch.setenv("SKILL_CONSULT_SLOTS", "1")
    rows = cf.sieve_rows_from_engine(["qa", "qb"], python=sys.executable)
    assert [(r["name"], r["description"]) for r in rows] == [("qa", "0040"), ("qb", "0040")]


def test_engine_child_runs_in_the_callers_working_directory(monkeypatch, tmp_path):
    fake_engine(tmp_path, monkeypatch)
    proj = tmp_path / "proj"
    proj.mkdir()
    monkeypatch.chdir(proj)
    rows = cf.sieve_rows_from_engine(["q"], python=sys.executable)
    assert Path(rows[0]["cwd"]).resolve() == proj.resolve()


def test_a_project_skill_visible_only_from_the_callers_cwd_reaches_the_rows(monkeypatch, tmp_path):
    """A stand-in engine that, like the real one, lists <cwd>/.claude/skills: run from the project folder."""
    pkg = tmp_path / "pkg" / "skill_search"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "server.py").write_text(
        "import json, os\n"
        "def consult_candidates(queries, top_n):\n"
        "    d = os.path.join(os.getcwd(), '.claude', 'skills')\n"
        "    names = sorted(os.listdir(d)) if os.path.isdir(d) else []\n"
        "    return json.dumps({'results': [{'name': n, 'description': 'project'} for n in names]})\n")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path / "pkg"))
    proj = tmp_path / "proj"
    (proj / ".claude" / "skills" / "only-in-this-project").mkdir(parents=True)
    monkeypatch.chdir(proj)
    monkeypatch.setattr(cf, "sieve_rows_from_engine",
                        lambda q, _real=cf.sieve_rows_from_engine: _real(q, python=sys.executable))
    fake_jev(monkeypatch, order=[])
    out = cf.widen("t", queries=["q"])
    assert "only-in-this-project" in [r["name"] for r in out["results"]]


def test_engine_child_gets_no_api_keys_but_keeps_what_it_reads(monkeypatch, tmp_path):
    fake_engine(tmp_path, monkeypatch)
    for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "TYPESAFE_API_KEY"):
        monkeypatch.setenv(k, "sk-not-for-the-engine")
    monkeypatch.setenv("SKILL_COLLECTION", "my-collection")
    row_ = cf.sieve_rows_from_engine(["q"], python=sys.executable)[0]
    assert row_["leak"] == [] and row_["keep"] == ["my-collection", True, True]


def test_engine_timeout_is_under_the_agents_bash_limit():
    assert cf.WIDEN_ENGINE_TIMEOUT < 120


@pytest.mark.parametrize("py", ["/nonexistent/python3", sys.executable])
def test_engine_child_failure_raises_sieve_unavailable(monkeypatch, tmp_path, py):
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))      # no skill_search there: the import fails
    with pytest.raises(cf.SieveUnavailable):
        cf.sieve_rows_from_engine(["q"], python=py)


# --- consult_log: epoch-watch fields --------------------------------------------------------------------

def test_verdict_row_carries_sieve_and_jev_added(monkeypatch, tmp_path):
    monkeypatch.setattr(consult_log, "LOG_DIR", tmp_path)
    monkeypatch.setattr(consult_log, "LEDGER", tmp_path / "l.log")
    assert consult_log.append_verdict("SINGLE", "a", "a", 0, sieve="widened", jev_added=7)
    assert consult_log.append_verdict("SINGLE", "a", "a", 0, sieve="bogus", jev_added=-1)
    assert consult_log.append_verdict("SINGLE", "a", "a", 0)
    rows = [json.loads(x) for x in (tmp_path / "l.log").read_text().splitlines()]
    assert rows[0]["sieve"] == "widened" and rows[0]["jev_added"] == 7
    assert "sieve" not in rows[1] and "jev_added" not in rows[1] and "sieve" not in rows[2]


def test_log_cli_accepts_sieve_and_jev_added(tmp_path):
    import subprocess
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "consult_log.py"), "--shape", "NONE",
                        "--sieve", "off", "--jev-added", "0"],
                       env={"SKILL_CONCIERGE_LOG": str(tmp_path), "PATH": "/usr/bin"})
    row_ = json.loads((tmp_path / "skill-invocation-ledger.log").read_text())
    assert r.returncode == 0 and row_["sieve"] == "off" and row_["jev_added"] == 0


@pytest.mark.parametrize("extra", [["--sieve", "bogus"], ["--jev-added", "abc"], ["--sieve", "x", "--jev-added", "-"]])
def test_log_cli_never_loses_the_row_over_a_bad_value(tmp_path, extra):
    import subprocess
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "consult_log.py"), "--shape", "NONE", *extra],
                       env={"SKILL_CONCIERGE_LOG": str(tmp_path), "PATH": "/usr/bin"})
    row_ = json.loads((tmp_path / "skill-invocation-ledger.log").read_text())
    assert r.returncode == 0 and row_["shape"] == "NONE" and "sieve" not in row_ and "jev_added" not in row_


def test_skill_step_2_uses_a_unique_heredoc_delimiter():
    text = (ROOT / "skills" / "consult" / "SKILL.md").read_text()
    assert "widen <<'CONSULT_WIDEN_INPUT'" in text and "\nEOF\n" not in text
