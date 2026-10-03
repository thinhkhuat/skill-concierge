"""scripts/trigger_filter.py and the writers of triggers.json it protects (ADR-0076, phase 3).

Jev is replaced at the transport boundary only: jev_client.load_enforcer(), then `enf._post_json`
(the way tests/test_jev_client.py does). The data sources (installed skills, retrieval, embeddings) are
monkeypatched; they are not Jev. Every path (triggers, cache, thresholds, ledger, backups, the flywheel
lock) points at tmp_path; nothing here touches ~/.claude/skill-concierge or the network.
"""
import importlib.util
import io
import json
import re
import sys
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_triggers  # noqa: E402
import flywheel_llm  # noqa: E402
import flywheel_lock  # noqa: E402
import jev_client  # noqa: E402
import llm_triggers  # noqa: E402
import trigger_filter as tf  # noqa: E402

GW = "https://gw.example.net/v1/chat/completions"
WIRING = ("ENFORCER_JEV_BENCH", "ENFORCER_JEV_URL", "ENFORCER_JEV_KEY", "ENFORCER_JEV_MODEL",
          "ENFORCER_JEV_TIMEOUT", "ENFORCER_JEV_GATEWAY_TIMEOUT", "FLYWHEEL_LLM_ENDPOINT",
          "FLYWHEEL_LLM_API_KEY", "TYPESAFE_API_KEY", "JEV_CLIENT_MAX_TPS", "JEV_CLIENT_MAX_RPS",
          "SKILL_TRIGGER_JEV_FILTER")
TS_MODEL = "jev-1.13.0"
GW_MODEL = "typesafe/jev-1.13-20260917"
SIBS = ["beta", "gamma", "delta"]
INSTALLED = {n: f"{n} description" for n in ["alpha", "alpha2", *SIBS, "omega"]}
GOOD = ["sort incoming reports", "triage the backlog", "prioritise open tickets", "rank pending issues",
        "tự động phân loại lỗi", "xếp thứ tự công việc"]


def thresholds(model=TS_MODEL, en=0.0, vn=0.0, vn_gate=True):
    return {"models": {model: {"en": {"threshold": en, "gate": True},
                                "vn": {"threshold": vn, "gate": vn_gate}}}}


@pytest.fixture
def env(tmp_path, monkeypatch):
    for k in WIRING:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ENFORCER_JEV_BENCH", f"ts:{TS_MODEL} gw:openrouter/typesafe/jev-1.13")
    monkeypatch.setenv("FLYWHEEL_LLM_ENDPOINT", GW)
    monkeypatch.setenv("TYPESAFE_API_KEY", "sk-test-SECRET-0000000000")
    monkeypatch.setenv("FLYWHEEL_LLM_API_KEY", "gw-key")
    monkeypatch.setattr(jev_client, "_ENF", None)
    enf = jev_client.load_enforcer()
    monkeypatch.setattr(enf, "_embed", lambda text: [0.0])
    monkeypatch.setattr(enf, "_retrieve", lambda vec: pytest.fail("siblings must not use the per-session _retrieve"))
    for name, val in (("CACHE_FILE", tmp_path / "cache.jsonl"), ("THRESHOLDS_FILE", tmp_path / "thr.json"),
                      ("CAPSULES_FILE", tmp_path / "capsules.json"), ("BACKUP_DIR", tmp_path / "backups"),
                      ("LEDGER", tmp_path / "ledger.log")):
        monkeypatch.setattr(tf, name, val)
    monkeypatch.setattr(llm_triggers, "TRIGGERS_FILE", tmp_path / "triggers.json")
    monkeypatch.setattr(llm_triggers, "CACHE_FILE", tmp_path / "flywheel-cache.json")
    monkeypatch.setattr(flywheel_lock, "LOCK_PATH", tmp_path / "fw.lock")
    monkeypatch.setattr(tf, "all_descriptions", lambda: (dict(INSTALLED), dict(INSTALLED)))
    monkeypatch.setattr(tf, "_engine_cap", lambda: "16")
    monkeypatch.setattr(flywheel_llm, "live_skills", lambda: dict(INSTALLED))
    (tmp_path / "thr.json").write_text(json.dumps(thresholds()), encoding="utf-8")
    ns = SimpleNamespace(tmp=tmp_path, enf=enf, calls=[], mp=monkeypatch, groups=list(INSTALLED),
                         handler=lambda *a: pytest.fail("Jev was called"))

    def dispatch(url, body, timeout, headers=None):
        if url == enf.QUERY_GROUPS_URL:                 # the grouped nearest-skills query
            return {"result": {"groups": [{"id": n, "hits": [{"payload": {"name": n}, "score": 0.9}]}
                                          for n in ns.groups]}}
        return ns.handler(url, body, timeout, headers)
    monkeypatch.setattr(enf, "_post_json", dispatch)
    ns.ctx = lambda **kw: tf.Ctx(dict(INSTALLED), cache=tf.Cache(tmp_path / "cache.jsonl"),
                                  thresholds=kw.get("thr", thresholds()["models"]), capsules={})
    return ns


def fake_jev(env, score, ts_fails=lambda body: False, all_fail=False, on_call=None):
    """Install a transport-level Jev. score(phrase, skill_name) -> p. ts_fails(body) -> the TypeSafe tier
    answers HTTP 500 (a fast failure: the client moves to the next tier)."""
    def post(url, body, timeout, headers=None):
        env.calls.append(body)
        is_ts = "typesafe.ai" in url
        if all_fail or (is_ts and ts_fails(body)):
            raise urllib.error.HTTPError(url, 500, "boom", {}, io.BytesIO(b"{}"))
        if on_call:
            on_call(body)
        names = list(body["state"]["skills"])
        out = {}
        for key, q in body["questions"].items():
            _, _i, j = key.split("::")
            u = re.search(r'types "(.*)" to a coding', q["instructions"]).group(1)
            out[key] = {"type": "noul", "noul": score(u, names[int(j)])}
        return {"answers": out, "model": TS_MODEL if is_ts else GW_MODEL}
    env.handler = post


def good_score(u, skill):
    """Phrases containing SIBLING point at beta; everything else points at its own skill."""
    if "SIBLING" in u:
        return 0.9 if skill == "beta" else 0.4
    return 0.9 if skill.startswith("alpha") else 0.3


# --- decision --------------------------------------------------------------------------------------

def test_phrase_pointing_at_a_sibling_is_dropped(env):
    fake_jev(env, good_score)
    phrases = GOOD + ["SIBLING pointer here"]
    res = tf.filter_phrases("alpha", INSTALLED["alpha"], phrases, env.ctx())
    assert res["kept"] == GOOD
    [d] = res["audit"]["dropped"]
    assert d["t"] == "SIBLING pointer here" and d["why"] == "jev" and d["model"] == TS_MODEL
    assert d["p"] == pytest.approx(0.4) and d["margin"] == pytest.approx(-0.5) and d["i"] == 6
    assert "err" not in res["audit"] and res["audit"]["pending"] == 0


def test_never_drops_below_min_triggers():
    phrases = [f"phrase number {w}" for w in "abcdef"]
    margins = [-0.5, -0.4, -0.3, -0.2, -0.1, 0.5]
    scores = [{"model": "m", "p_own": 0.5, "margin": m} for m in margins]
    kept, dropped, pending = tf.decide(phrases, scores, thresholds("m")["models"])
    assert kept == phrases[2:] and len(kept) == llm_triggers.MIN_TRIGGERS
    assert [d["i"] for d in dropped] == [0, 1] and pending == 0


def test_uncalibrated_model_score_is_pending_and_kept():
    phrases = [f"phrase number {w}" for w in "abcde"]
    scores = [{"model": "unknown-model", "p_own": 0.1, "margin": -0.9}] * 5
    kept, dropped, pending = tf.decide(phrases, scores, thresholds("m")["models"])
    assert kept == phrases and dropped == [] and pending == 5


def test_exempt_language_is_scored_but_kept():
    phrases = ["english phrase one", "english phrase two", "english phrase three", "english phrase four",
               "english bad pointer", "tự động hóa quy trình"]
    scores = [{"model": "m", "p_own": 0.9, "margin": 0.5}] * 4 + [{"model": "m", "p_own": 0.1, "margin": -0.9}] * 2
    kept, dropped, pending = tf.decide(phrases, scores, thresholds("m", vn_gate=False)["models"])
    assert "tự động hóa quy trình" in kept and "english bad pointer" not in kept
    assert [d["t"] for d in dropped] == ["english bad pointer"] and pending == 0


def test_answering_model_is_recorded_per_score(env):
    fake_jev(env, good_score, ts_fails=lambda body: next(iter(body["state"]["skills"])) == "alpha2")
    ctx = env.ctx()
    r1 = tf.filter_phrases("alpha", INSTALLED["alpha"], GOOD, ctx)
    r2 = tf.filter_phrases("alpha2", INSTALLED["alpha2"], GOOD, ctx)
    ctx.cache.add_many(r1["new_rows"] + r2["new_rows"])
    assert {r["model"] for r in r1["new_rows"]} == {TS_MODEL}
    assert {r["model"] for r in r2["new_rows"]} == {GW_MODEL}
    assert r1["audit"]["models"] == [TS_MODEL] and r1["audit"]["pending"] == 0
    assert r2["audit"]["models"] == [GW_MODEL] and r2["audit"]["pending"] == len(GOOD)   # no threshold: pending
    rows = [json.loads(line) for line in (env.tmp / "cache.jsonl").read_text().splitlines()]
    assert {r["model"] for r in rows} == {TS_MODEL, GW_MODEL}


def test_siblings_are_installed_only(env):
    env.groups = ["ext:foo", "alpha", "beta", "gamma", "delta", "omega"]
    assert [n for n, _ in tf.siblings(env.enf, "alpha", "d", INSTALLED)] == SIBS
    # end to end through calibrate: neither the external row nor a sibling is ever the random column
    env.mp.setattr(llm_triggers, "load_triggers",
                   lambda: {"alpha": {"llm_triggers": {"triggers": GOOD}}})
    env.mp.setattr(flywheel_llm, "live_skills", lambda: dict(INSTALLED))
    fake_jev(env, good_score)
    assert tf.calibrate(env.tmp / "stage", n_skills=1, workers=1) == 0
    assert env.calls
    for body in env.calls:
        names = list(body["state"]["skills"])
        assert names[:4] == ["alpha", *SIBS] and len(names) == 5
        assert "ext:foo" not in names and names[4] not in names[:4]
    out = json.loads((env.tmp / "stage" / "trigger-jev-thresholds.json").read_text())
    assert set(out["models"]) == {TS_MODEL, GW_MODEL} and out["n_skills"] == 1


def test_auc_matches_hand_computed_values():
    assert tf.auc([0.9, 0.8], [0.1, 0.2]) == 1.0
    assert tf.auc([0.5, 0.5], [0.5, 0.5]) == 0.5
    assert tf.auc([1, 2], [2, 3]) == pytest.approx(0.125)     # 1v2 lose, 1v3 lose, 2v2 tie, 2v3 lose
    assert tf.auc([], [1]) is None


def _rows(spec):
    """spec: [(count, margin)] -> calibration rows whose margin is own - best sibling."""
    out = []
    for count, margin in spec:
        sib = 0.4
        out += [{"p_own": sib + margin, "p_sib": [sib, 0.1, 0.1], "margin": margin}] * count
    return out


def test_threshold_is_the_largest_t_within_the_drop_cap():
    # share below -0.2: 5 %, below -0.1: 12 %, below 0.0: 20 %, below 0.1: 20 %
    g = tf.calibrate_group(_rows([(50, -0.3), (70, -0.15), (80, -0.05), (800, 0.5)]))
    assert g["threshold"] == -0.1 and g["n"] == 1000 and g["gate"] is True
    assert g["drop"]["-0.1"] == pytest.approx(0.12) and g["drop"]["0.0"] == pytest.approx(0.2)
    small = tf.calibrate_group(_rows([(5, -0.3), (95, 0.5)]))
    assert small["gate"] is False                                # n below the floor
    weak = tf.calibrate_group(_rows([(300, -0.3), (700, 0.0)]))
    assert weak["threshold"] is None and weak["gate"] is False  # even -0.2 drops more than 15 %


# --- merge, audit, cap ------------------------------------------------------------------------------

def test_kept_plus_dropped_restores_the_original_through_a_merge():
    orig = [f"phrase number {i:02d}" for i in range(15)]
    triggers = {}
    llm_triggers.merge_utterance_layer(triggers, "s", orig, cap=12, audit={"dropped": []}, orig=orig)
    layer = triggers["s"]["llm_triggers"]
    assert [d["why"] for d in layer["jev"]["dropped"]] == ["cap"] * 3
    assert tf.original_phrases(triggers["s"]) == orig
    # two jev drops, then the cap cuts one more
    scores = [{"model": "m", "p_own": 0.5, "margin": -0.5 if i in (3, 8) else 0.5} for i in range(15)]
    kept, dropped, pending = tf.decide(orig, scores, thresholds("m")["models"])
    audit = tf.make_audit(orig, scores, thresholds("m")["models"], dropped, pending, 0)
    llm_triggers.merge_utterance_layer(triggers, "s2", kept, cap=12, audit=audit, orig=orig)
    layer = triggers["s2"]["llm_triggers"]
    assert [d["why"] for d in layer["jev"]["dropped"]] == ["jev", "jev", "cap"]
    assert len(layer["triggers"]) == 12 and tf.original_phrases(triggers["s2"]) == orig


def test_engine_reads_only_kept_phrases(env):
    fake_jev(env, good_score)
    res = tf.filter_phrases("alpha", INSTALLED["alpha"], GOOD + ["SIBLING pointer here"], env.ctx())
    triggers = {}
    llm_triggers.merge_utterance_layer(triggers, "alpha", res["kept"], audit=res["audit"],
                                       orig=GOOD + ["SIBLING pointer here"])
    layer = triggers["alpha"]["llm_triggers"]
    # the engine's read (server.py `_llm_utterance_phrases`): (v.get("llm_triggers") or {}).get("triggers")
    assert layer["triggers"] == GOOD and "jev" in layer
    assert "SIBLING pointer here" not in triggers["alpha"]["triggers"]


def _run(env, phrases=GOOD, name="alpha"):
    env.mp.setattr(flywheel_llm, "chat", lambda *a, **k: {"triggers": list(phrases)})
    return llm_triggers.run(only=name, rate=0)


def test_jev_failure_keeps_every_phrase(env):
    fake_jev(env, good_score, all_fail=True)
    [r] = _run(env)
    assert r["status"] == "generated"
    entry = json.loads((env.tmp / "triggers.json").read_text())["alpha"]
    assert entry["llm_triggers"]["triggers"] == GOOD
    assert entry["llm_triggers"]["jev"]["err"] == "JevError"


def test_flag_off_restores_the_unfiltered_merge(env):
    env.mp.setenv("SKILL_TRIGGER_JEV_FILTER", "0")
    fake_jev(env, lambda u, s: pytest.fail("Jev was called with the flag off"))
    _run(env, GOOD + ["SIBLING pointer here"])
    expected = {}
    llm_triggers.merge_utterance_layer(expected, "alpha", GOOD + ["SIBLING pointer here"])
    assert (env.tmp / "triggers.json").read_text(encoding="utf-8") == json.dumps(
        expected, indent=2, ensure_ascii=False)


def test_no_thresholds_file_means_no_filtering(env):
    (env.tmp / "thr.json").unlink()
    fake_jev(env, lambda u, s: pytest.fail("Jev was called without thresholds"))
    _run(env, GOOD + ["SIBLING pointer here"])
    expected = {}
    llm_triggers.merge_utterance_layer(expected, "alpha", GOOD + ["SIBLING pointer here"])
    assert (env.tmp / "triggers.json").read_text(encoding="utf-8") == json.dumps(
        expected, indent=2, ensure_ascii=False)


def test_run_with_the_filter_stores_kept_and_audit(env):
    fake_jev(env, good_score)
    _run(env, GOOD + ["SIBLING pointer here"])
    layer = json.loads((env.tmp / "triggers.json").read_text())["alpha"]["llm_triggers"]
    assert layer["triggers"] == GOOD and layer["jev"]["dropped"][0]["t"] == "SIBLING pointer here"
    assert (env.tmp / "cache.jsonl").exists()


def test_save_is_atomic(tmp_path):
    path = tmp_path / "t.json"
    path.write_text('{"keep": 1}', encoding="utf-8")
    with pytest.raises(TypeError):
        llm_triggers.save_triggers({"bad": {1, 2}}, path)           # not JSON-serialisable
    assert path.read_text(encoding="utf-8") == '{"keep": 1}'
    assert [p.name for p in tmp_path.iterdir()] == ["t.json"]
    llm_triggers.save_triggers({"ok": 2}, path)
    assert json.loads(path.read_text()) == {"ok": 2} and [p.name for p in tmp_path.iterdir()] == ["t.json"]


# --- backfill --------------------------------------------------------------------------------------

def entry(phrases, jev=None):
    layer = {"source": "llm-utterance", "triggers": list(phrases), "n": len(phrases)}
    if jev is not None:
        layer["jev"] = jev
    return {"source": "llm-utterance", "triggers": list(phrases), "n": len(phrases),
            "prose_triggers": [], "llm_triggers": layer}


COMPLETE = {"models": [TS_MODEL], "thresholds": {}, "scored": 6, "pending": 0, "dropped": [], "at": "x"}


def seed(env, **named):
    (env.tmp / "triggers.json").write_text(json.dumps(named, indent=2, ensure_ascii=False), encoding="utf-8")


def args(env, **kw):
    base = dict(workers=1, limit=None, out=None, dry_run=False, rescore=False, thresholds=None)
    return SimpleNamespace(**{**base, **kw})


def read(env):
    return json.loads((env.tmp / "triggers.json").read_text(encoding="utf-8"))


def test_backfill_retries_err_and_pending_entries(env):
    seed(env, alpha=entry(GOOD), alpha2=entry(GOOD, {"err": "JevError", "dropped": []}),
         beta=entry(GOOD, {**COMPLETE, "pending": 2}), gamma=entry(GOOD, COMPLETE), delta={"triggers": ["x y z"]})
    assert [n for n, e in read(env).items() if tf.needs_backfill(e)] == ["alpha", "alpha2", "beta"]
    fake_jev(env, good_score)
    assert tf.backfill(args(env)) == 0
    data = read(env)
    for n in ("alpha", "alpha2", "beta"):
        jev = data[n]["llm_triggers"]["jev"]
        assert "err" not in jev and jev["pending"] == 0 and jev["scored"] == len(GOOD)
    assert data["gamma"]["llm_triggers"]["jev"] == COMPLETE            # complete entries are not rescored
    assert "llm_triggers" not in data["delta"]


def test_backfill_resumes_from_the_cache(env):
    seed(env, alpha=entry(GOOD))
    fake_jev(env, good_score)
    tf.backfill(args(env))
    first = len(env.calls)
    assert first >= 1
    tf.backfill(args(env, rescore=True))                                # same phrases, same state: all cached
    assert len(env.calls) == first


def test_backfill_refuses_while_the_flywheel_lock_is_held(env):
    seed(env, alpha=entry(GOOD))
    before = (env.tmp / "triggers.json").read_bytes()
    fake_jev(env, good_score)
    assert flywheel_lock.acquire(block=False)
    try:
        assert tf.backfill(args(env)) == 4
    finally:
        flywheel_lock.release()
    assert (env.tmp / "triggers.json").read_bytes() == before and env.calls == []


def test_backfill_save_keeps_a_concurrent_writers_entry(env):
    seed(env, alpha=entry(GOOD), alpha2=entry(GOOD), omega=entry(GOOD, COMPLETE))
    env.mp.setattr(tf, "SAVE_EVERY", 1)
    state = {"n": 0}

    def other_writer(body):
        state["n"] += 1
        if state["n"] == 2:                                             # between the first and the last save
            data = read(env)
            data["omega"]["note"] = "written by an older install"
            (env.tmp / "triggers.json").write_text(json.dumps(data), encoding="utf-8")

    fake_jev(env, good_score, on_call=other_writer)
    assert tf.backfill(args(env)) == 0
    data = read(env)
    assert data["omega"]["note"] == "written by an older install"
    assert "jev" in data["alpha"]["llm_triggers"] and "jev" in data["alpha2"]["llm_triggers"]


def test_backup_is_written_before_the_first_live_write(env):
    seed(env, alpha=entry(GOOD))
    original = (env.tmp / "triggers.json").read_bytes()
    fake_jev(env, good_score)
    tf.backfill(args(env))
    [backup] = list((env.tmp / "backups").iterdir())
    assert backup.name.startswith("triggers-") and backup.read_bytes() == original
    assert (env.tmp / "triggers.json").read_bytes() != original


def test_backfill_out_copy_leaves_the_live_file_and_skips_the_backup(env):
    seed(env, alpha=entry(GOOD))
    original = (env.tmp / "triggers.json").read_bytes()
    fake_jev(env, good_score)
    tf.backfill(args(env, out=str(env.tmp / "stage" / "triggers.json")))
    assert (env.tmp / "triggers.json").read_bytes() == original
    assert "jev" in json.loads((env.tmp / "stage" / "triggers.json").read_text())["alpha"]["llm_triggers"]
    assert not (env.tmp / "backups").exists() and not (env.tmp / "ledger.log").exists()


def test_corpus_epoch_event_is_appended(env):
    seed(env, alpha=entry(GOOD + ["SIBLING pointer here"]))
    fake_jev(env, good_score)
    tf.backfill(args(env))
    rows = [json.loads(line) for line in (env.tmp / "ledger.log").read_text().splitlines()]
    [row] = rows
    assert row["ev"] == "corpus_epoch" and row["what"] == "trigger_filter_backfill"
    assert row["kept"] == len(GOOD) and row["dropped"] == 1 and row["pending"] == 0 and row["backup"]
    env.mp.setattr(tf.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=0, stdout='{"indexed": 3, "embedded": 4, "deleted": 7}\n', stderr=""))
    assert tf.reindex() == 0
    rows = [json.loads(line) for line in (env.tmp / "ledger.log").read_text().splitlines()]
    assert [(r["ev"], r["what"]) for r in rows] == [("corpus_epoch", "trigger_filter_backfill"),
                                                    ("corpus_epoch", "reindex")]
    assert rows[1]["embedded"] == 4 and rows[1]["deleted"] == 7


def test_report_accounts_for_every_phrase(env, capsys):
    fake_jev(env, good_score)
    seed(env, alpha=entry(GOOD + ["SIBLING pointer here"]), beta=entry(GOOD))
    tf.backfill(args(env, limit=1))
    capsys.readouterr()
    tf.report()
    out = capsys.readouterr().out
    assert "scored ok 1" in out and "not yet scored 1" in out and "dropped by jev 1" in out
    assert "inconsistent audit 0" in out


# --- other writers of triggers.json ----------------------------------------------------------------

def _build_env(env, monkeypatch, points, catalog_points=()):
    import catalogs
    out = env.tmp / "triggers.json"
    monkeypatch.setattr(build_triggers, "OUT", out)
    monkeypatch.setattr(catalogs, "_load", lambda: {"cat": {"path": "/nowhere"}} if catalog_points else {})
    monkeypatch.setattr(build_triggers, "scroll_all_points",
                        lambda catalog=None, paths=False: iter(catalog_points if catalog else points))
    return out


DESC = "Sort incoming bug reports into prioritised work. Use when the backlog grows faster than it shrinks."


def test_build_triggers_refuses_while_locked(env, monkeypatch):
    out = _build_env(env, monkeypatch, [("alpha", DESC)])
    out.write_text('{"keep": true}', encoding="utf-8")
    assert flywheel_lock.acquire(block=False)
    try:
        assert build_triggers.run(False) == 4
    finally:
        flywheel_lock.release()
    assert out.read_text(encoding="utf-8") == '{"keep": true}'


def test_build_triggers_keeps_utterance_layer(env, monkeypatch):
    out = _build_env(env, monkeypatch, [("alpha", DESC)], catalog_points=[("cat:thing", "d")])
    audit = {**COMPLETE, "dropped": [{"t": "SIBLING pointer here", "i": 6, "why": "jev", "model": TS_MODEL,
                                      "p": 0.4, "margin": -0.5}]}
    audit_only = {"source": "prose-phrase", "triggers": ["only prose here"], "n": 1,
                  "llm_triggers": {"jev": COMPLETE}}          # what a purge leaves behind
    old = {"alpha": entry(GOOD, audit), "cat:thing": entry(GOOD, COMPLETE), "stale-llm": entry(GOOD, COMPLETE),
           "stale-prose": {"source": "prose-phrase", "triggers": ["only prose here"], "n": 1},
           "cat:audit-only": audit_only}
    out.write_text(json.dumps(old), encoding="utf-8")
    assert build_triggers.run(False) == 0
    new = json.loads(out.read_text(encoding="utf-8"))
    assert json.dumps(new["alpha"]["llm_triggers"]) == json.dumps(old["alpha"]["llm_triggers"])  # byte-equal
    expected = {"alpha": {"source": "prose-phrase", "triggers": build_triggers.split_phrases(DESC),
                          "n": len(build_triggers.split_phrases(DESC))}}
    llm_triggers.merge_utterance_layer(expected, "alpha", GOOD)
    assert new["alpha"]["triggers"] == expected["alpha"]["triggers"]
    assert new["alpha"]["prose_triggers"] == build_triggers.split_phrases(DESC)
    assert new["cat:thing"] == old["cat:thing"]                    # a catalog skill still indexed: carried verbatim
    assert "stale-llm" not in new and "stale-prose" not in new     # no longer indexed: dropped as before
    assert "cat:audit-only" not in new                             # not indexed either
    # an audit-only layer on a live skill survives a rebuild
    old2 = {"alpha": {**audit_only}}
    out.write_text(json.dumps(old2), encoding="utf-8")
    assert build_triggers.run(False) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["alpha"]["llm_triggers"] == {"jev": COMPLETE}


def _doctor(env, monkeypatch):
    spec = importlib.util.spec_from_file_location("doctor_trigger_filter_t", ROOT / "scripts" / "doctor.py")
    dr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dr)
    monkeypatch.setattr(dr, "TRIGGERS", env.tmp / "triggers.json")
    monkeypatch.setattr(dr, "SS_BIN", env.tmp / "no-such-skill-search")
    monkeypatch.setattr(dr, "_junk_triggers", lambda: {"alpha": ["x"]})
    return dr


def test_purge_junk_keeps_the_audit_and_respects_the_lock(env, monkeypatch):
    prose = ["sort incoming reports by urgency"]
    junk = {**entry(["xxxx"], COMPLETE), "prose_triggers": prose}
    seed(env, alpha=junk)
    before = (env.tmp / "triggers.json").read_bytes()
    dr = _doctor(env, monkeypatch)
    assert flywheel_lock.acquire(block=False)
    try:
        ok, msg = dr.fix_purge_junk()
    finally:
        flywheel_lock.release()
    assert (ok, msg) == (False, "flywheel running; retry later")
    assert (env.tmp / "triggers.json").read_bytes() == before
    ok, msg = dr.fix_purge_junk()
    assert ok, msg
    purged = read(env)["alpha"]
    assert purged["triggers"] == prose and purged["llm_triggers"] == {"jev": COMPLETE}
    assert not any(p.name.endswith(".tmp") for p in env.tmp.iterdir())


def _auto_reindex(env, monkeypatch):
    spec = importlib.util.spec_from_file_location("auto_reindex_trigger_filter_t",
                                                  ROOT / "hooks" / "scripts" / "auto_reindex.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fake_bin = env.tmp / "skill-search"
    fake_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    fake_bin.chmod(0o755)
    spawned = []
    monkeypatch.setattr(mod, "SS_BIN", fake_bin)
    monkeypatch.setattr(mod, "LOGDIR", env.tmp / "logs")
    monkeypatch.setattr(mod, "STAMP", env.tmp / "logs" / "stamp")
    monkeypatch.setattr(mod, "LOGFILE", env.tmp / "logs" / "auto.log")
    monkeypatch.setattr(mod, "_mcp_env", lambda: ({}, "http://example.invalid"))
    monkeypatch.setattr(mod, "_qdrant_up", lambda url: True)
    monkeypatch.setattr(mod.subprocess, "Popen", lambda *a, **k: spawned.append(a))
    return mod, spawned


def test_auto_reindex_skips_while_locked(env, monkeypatch):
    mod, spawned = _auto_reindex(env, monkeypatch)
    assert flywheel_lock.acquire(block=False)
    try:
        assert mod.main() == 0
    finally:
        flywheel_lock.release()
    assert spawned == [] and not (env.tmp / "logs" / "stamp").exists()   # no stamp: the next session retries
    assert mod.main() == 0 and len(spawned) == 1                        # control: unlocked, it spawns


def test_llm_triggers_cli_refuses_while_locked(env, monkeypatch):
    seed(env, alpha=entry(GOOD))
    before = (env.tmp / "triggers.json").read_bytes()
    monkeypatch.setattr(sys, "argv", ["llm_triggers.py", "--only", "alpha"])
    monkeypatch.setattr(flywheel_llm, "chat", lambda *a, **k: pytest.fail("generated while locked"))
    import runpy
    assert flywheel_lock.acquire(block=False)
    try:
        with pytest.raises(SystemExit) as e:
            runpy.run_path(str(ROOT / "scripts" / "llm_triggers.py"), run_name="__main__")
    finally:
        flywheel_lock.release()
    assert e.value.code == 4 and (env.tmp / "triggers.json").read_bytes() == before


# --- review fixes -----------------------------------------------------------------------------------

def test_save_aborts_instead_of_writing_a_partial_corpus(env):
    seed(env, alpha=entry(GOOD), alpha2=entry(GOOD), omega=entry(GOOD, COMPLETE))
    original = (env.tmp / "triggers.json").read_bytes()
    env.mp.setattr(tf, "SAVE_EVERY", 1)
    for damage in ("delete", "corrupt", "array"):
        (env.tmp / "triggers.json").write_bytes(original)
        (env.tmp / "cache.jsonl").unlink(missing_ok=True)
        env.calls.clear()

        def hurt(body, damage=damage):
            if len(env.calls) == 2:
                f = env.tmp / "triggers.json"
                f.unlink() if damage == "delete" else f.write_text("{not json" if damage == "corrupt" else "[]")

        fake_jev(env, good_score, on_call=hurt)
        assert tf.backfill(args(env)) == 3
        f = env.tmp / "triggers.json"
        assert not f.exists() if damage == "delete" else f.read_text() in ("{not json", "[]")   # never a partial corpus
        # repair the file: a re-run completes and does not re-ask what the cache already holds
        f.write_bytes(original)
        before = len(env.calls)
        assert tf.backfill(args(env)) == 0
        data = read(env)
        assert "jev" in data["alpha"]["llm_triggers"] and "jev" in data["alpha2"]["llm_triggers"]
        assert data["omega"]["llm_triggers"]["jev"] == COMPLETE
        asked = [c for c in env.calls[before:] if next(iter(c["state"]["skills"])) == "alpha"]
        assert asked == []                                           # alpha's scores came from the cache


def test_calibration_control_is_never_a_sibling(env):
    env.groups = ["alpha", "beta"]                                   # a skill with ONE sibling
    env.mp.setattr(llm_triggers, "load_triggers", lambda: {"alpha": {"llm_triggers": {"triggers": GOOD}}})
    fake_jev(env, lambda u, s: 0.9 if s == "alpha" else 0.1 if s == "beta" else 0.95)
    assert tf.calibrate(env.tmp / "stage", n_skills=1, workers=1) == 0
    rows = [json.loads(line) for line in (env.tmp / "stage" / "calibration-rows.jsonl").read_text().splitlines()]
    assert rows and all(len(r["p_sib"]) == 1 and r["p_rand"] == 0.95 for r in rows)
    assert all(r["margin"] == pytest.approx(0.8) for r in rows)      # own minus the real sibling, not the control
    ctx = env.ctx()
    with pytest.raises(tf.NoSiblings):                                # no real sibling: nothing to measure
        tf.score_skill([("alpha", "d"), ("omega", "d")], GOOD, ctx, control=True)
    with pytest.raises(tf.NoSiblings):
        tf.score_skill([("alpha", "d")], GOOD, ctx)


def test_inconsistent_audit_is_skipped_and_counted(env, capsys):
    bad = {**COMPLETE, "pending": 1, "dropped": [{"t": "x", "i": 0, "why": "jev"}, {"t": "y", "i": 0, "why": "jev"}]}
    worse = {**COMPLETE, "pending": 1, "dropped": [{"t": "x", "i": 99, "why": "jev"}]}
    seed(env, alpha=entry(GOOD), alpha2=entry(GOOD, bad), beta=entry(GOOD, worse))
    fake_jev(env, good_score)
    assert tf.backfill(args(env)) == 0
    assert "inconsistent audit 2" in capsys.readouterr().out
    data = read(env)
    assert "jev" in data["alpha"]["llm_triggers"] and data["alpha"]["llm_triggers"]["jev"]["pending"] == 0
    assert data["alpha2"]["llm_triggers"]["jev"] == bad and data["beta"]["llm_triggers"]["jev"] == worse
    with pytest.raises(ValueError):
        tf.original_phrases(entry(GOOD, bad))


def test_purge_drops_cache_keys_even_if_the_triggers_save_fails(env, monkeypatch):
    seed(env, alpha={**entry(["xxxx"], COMPLETE), "prose_triggers": ["sort incoming reports by urgency"]})
    before = (env.tmp / "triggers.json").read_bytes()
    llm_triggers.save_cache({llm_triggers.CACHE_PREFIX + "alpha": "h", "keep": "k"})
    dr = _doctor(env, monkeypatch)
    monkeypatch.setattr(llm_triggers, "save_triggers", lambda *a, **k: (_ for _ in ()).throw(OSError("disk")))
    ok, msg = dr.fix_purge_junk()
    assert not ok and "purge failed" in msg
    assert llm_triggers.load_cache() == {"keep": "k"}                 # regenerates next run; never "already current"
    assert (env.tmp / "triggers.json").read_bytes() == before


def test_siblings_do_not_depend_on_the_sessions_invocability_filter(env):
    env.mp.setattr(env.enf, "_row_invocable", lambda name, scope: False)   # a different cwd/harness
    assert [n for n, _ in tf.siblings(env.enf, "alpha", "d", INSTALLED)] == ["alpha2", *SIBS[:2]]


def test_enforcer_setup_leaves_the_process_environment_alone(env, monkeypatch):
    import os
    from concurrent.futures import ThreadPoolExecutor
    monkeypatch.delenv("ENFORCER_EMBED_TIMEOUT", raising=False)
    monkeypatch.delenv("ENFORCER_QDRANT_TIMEOUT", raising=False)
    monkeypatch.setattr(jev_client, "_ENF", None)
    before = dict(os.environ)
    with ThreadPoolExecutor(max_workers=4) as pool:
        mods = list(pool.map(lambda _: tf._enforcer(), range(8)))
    assert dict(os.environ) == before and len({id(m) for m in mods}) == 1
    assert mods[0].EMBED_TIMEOUT_S == 15.0 and mods[0].QDRANT_TIMEOUT_S == 15.0   # offline lengths, on the module
    # an explicit caller setting wins
    monkeypatch.setenv("ENFORCER_EMBED_TIMEOUT", "2")
    monkeypatch.setattr(jev_client, "_ENF", None)
    assert tf._enforcer().EMBED_TIMEOUT_S == 2.0
