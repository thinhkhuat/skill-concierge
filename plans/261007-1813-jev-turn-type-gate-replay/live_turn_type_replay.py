#!/usr/bin/env python3
"""Live replay of two new prompt-level "turn type" Jev questions over the calibration corpus.

  work   "is the user asking for work now?"              (prob = needs work)
  convo  "is this only conversation, no new work?"        (inverted: prob = 1 - p)

Populations (same rules as calibrate_jev_gate): pos = real skill turns, neg = labelled no-skill turns
(searched_then_skipped / skip_nosearch_conversational), unl = the hash-ordered traffic sample. State is
the live `ctx` variant (request + tail of the previous assistant message + skills loaded). Calls go
through jevd pinned to one provider (default commandcode). Answers are appended to answers.jsonl and
reused, so a rerun only scores what is missing.

  live_turn_type_replay.py score [--provider commandcode] [--workers 6]
  live_turn_type_replay.py curve
  live_turn_type_replay.py probes      # this session's conversational turns + the HOIVU one-liner
"""
import argparse
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "scripts"))
sys.path.insert(0, str(HERE))
import calibrate_jev_gate as cal  # noqa: E402
from offline_gate_curves import is_negative, THRESHOLDS  # noqa: E402

# Answers carry turn ids from the private calibration corpus: keep them outside the public repo.
OUT = Path.home() / ".claude/skill-concierge/analysis-private" / HERE.name / "answers.jsonl"
QUESTIONS = {
    "work": ("Is the user asking the assistant to carry out a task now (produce, change, run, fix, check, "
             "or look up something), rather than only to discuss, explain, give an opinion, or confirm "
             "something in conversation?"),
    "convo": ("Is this message only conversation with the assistant (asking for its view, an explanation, "
              "giving feedback, or confirming something) with no new work for the assistant to carry out?"),
}
INVERTED = {"convo"}
PROBES = [   # verbatim user prompts; the first four are this session's, the last is the HOIVU turn
    ("conv", "jev should, first and foremost - decice this: is the user's request worth a skill or is it trivial "
             "enough to just let the agent proceed on its own, without the need of the concierge to get involved at "
             "all? your take on this?"),
    ("conv", "yes, your refined words made it much clearer and closer to my intent. What I asked, was to have a "
             "mechanism so that before any search for skill calls or anything, we have Jev to decide, or at least "
             "give the main agent a recalibrated measurement  to base its skill/no-skill call on. yes?"),
    ("conv", "both, had you forced to use the SEARCH protocol while in my point of view, as a human, my requests "
             "were \"trivial\" enough in a sense that they never meant for you, the agent, to even need to call for "
             "a skill. the task could be done simply using your own context and standard tools. your take?"),
    ("work", "great. i've got a little more time for you to work on the analysis there, so GO pls"),
    ("work", "have the default UI to be set in VI please"),
]
LOCK = threading.Lock()


def prob(ans, q):
    p = ans[q]["noul"]
    return 1 - p if q in INVERTED else p


def populations(enf):
    rows = cal.load_corpus(cal.CORPUS)
    pos, unl = cal.pick(enf, rows, 300, 0)
    neg = [r for r in rows if is_negative(r) and enf._is_english(r["prompt"]) and cal.reaches_gate(enf, r["prompt"])]
    return {"pos": pos, "neg": neg, "unl": unl}


def done():
    if not OUT.exists():
        return {}
    recs = [json.loads(line) for line in OUT.open()]
    return {r["uuid"]: r for r in recs if r.get("ans")}


def tier(enf, provider):
    for t in enf._jev_bench():
        if t.get("ep") == "jevd" and t["name"] == provider:
            return t
    sys.exit(f"jevd provider {provider!r} not on the ladder (is jevd running and JEVD_URL set?)")


def score_one(enf, t, uuid, state, pop):
    ans, ms, _u, err = cal.call(enf, t, state, {q: {"type": "noul", "instructions": txt}
                                                for q, txt in QUESTIONS.items()}, t["timeout"])
    rec = {"uuid": uuid, "pop": pop, "provider": t["name"], "model": t["model"], "ms": ms, "err": err,
           "ans": ans and {q: {"noul": ans[q]["noul"]} for q in QUESTIONS}}
    with LOCK, OUT.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    return err


def cmd_score(a):
    enf = cal.load_enforcer()
    t = tier(enf, a.provider)
    have = done()
    todo = [(r["uuid"], cal.build_state(r, "ctx"), pop) for pop, rs in populations(enf).items()
            for r in rs if r["uuid"] not in have]
    seen = set()
    todo = [x for x in todo if not (x[0] in seen or seen.add(x[0]))]
    print(f"{len(have)} cached, {len(todo)} to score via jevd/{t['name']} ({t['model']})", flush=True)
    with ThreadPoolExecutor(a.workers) as ex:
        errs = [e for e in ex.map(lambda x: score_one(enf, t, *x), todo) if e]
    print(f"done: {len(todo) - len(errs)} scored, {len(errs)} failed {sorted(set(errs))}")


def cmd_curve(_a):
    enf = cal.load_enforcer()
    have = done()
    pops = populations(enf)
    sets = {p: [have[r["uuid"]] for r in rs if r["uuid"] in have] for p, rs in pops.items()}
    print("scored: " + ", ".join(f"{p} {len(sets[p])}/{len(pops[p])}" for p in pops))
    ms = sorted(r["ms"] for s in sets.values() for r in s if r["ms"])
    if ms:
        print(f"latency p50 {ms[len(ms) // 2]} ms, p90 {ms[int(len(ms) * 0.9)]} ms")
    for q in list(QUESTIONS) + ["both"]:
        f = (lambda r: max(prob(r["ans"], "work"), prob(r["ans"], "convo"))) if q == "both" else \
            (lambda r, q=q: prob(r["ans"], q))
        print(f"\n{q}{' (skip only when both say conversation)' if q == 'both' else ''}"
              f"\n   thr  pos false-NO (UCB95)  neg skipped  unl skipped")
        n = len(sets["pos"])
        for t in THRESHOLDS:
            fn = sum(f(r) < t for r in sets["pos"])
            ns = sum(f(r) < t for r in sets["neg"]) / max(len(sets["neg"]), 1)
            us = sum(f(r) < t for r in sets["unl"]) / max(len(sets["unl"]), 1)
            print(f"  {t:.2f}  {100*fn/n:5.1f}% ({100*cal.wilson_upper(fn, n):5.1f}%)"
                  f"      {100*ns:5.1f}%      {100*us:5.1f}%")
    if a_misses := [r for r in sets["pos"] if prob(r["ans"], "work") < 0.30]:
        by = {r["uuid"]: r for r in pops["pos"]}
        print(f"\npositives with work < 0.30 ({len(a_misses)}), prompt heads:")
        for r in a_misses:
            print(f"  work={prob(r['ans'], 'work'):.2f} convo={prob(r['ans'], 'convo'):.2f} "
                  f"used={sorted(cal.gold(by[r['uuid']]))} | {by[r['uuid']]['prompt'][:90]!r}")


def cmd_probes(a):
    enf = cal.load_enforcer()
    t = tier(enf, a.provider)
    qs = {q: {"type": "noul", "instructions": txt} for q, txt in QUESTIONS.items()}
    for kind, p in PROBES:
        ans, ms, _u, err = cal.call(enf, t, {"request": p, "recent_context": ""}, qs, t["timeout"])
        if err:
            print(f"{kind}: error {err} | {p[:60]!r}")
            continue
        print(f"{kind}: work={prob(ans, 'work'):.2f} convo(inv)={prob(ans, 'convo'):.2f} {ms} ms | {p[:60]!r}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("score", "probes"):
        s = sub.add_parser(name)
        s.add_argument("--provider", default="commandcode")
        s.add_argument("--workers", type=int, default=6)
    sub.add_parser("curve")
    a = ap.parse_args()
    {"score": cmd_score, "curve": cmd_curve, "probes": cmd_probes}[a.cmd](a)
