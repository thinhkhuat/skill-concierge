#!/usr/bin/env python3
"""Cline first-call menu replay (2026-10-08): can Jev's wide pass alone carry Cline's first menu?

Cline gives a plugin hook 3 s, so the first model call waits at most 2 s. The full Jev route (a wide
pass over the whole catalogue, then a rerank of its shortlist) takes 2.0-2.5 s, so that call mostly
carries the embedding preview. A wide pass alone takes about 1 s. Three top-5 menus, same turns:

  preview  the enforcer's embedding pass (ENFORCER_JEV_ROUTER=0): what Cline's first call carries today
  wide     Jev's wide pass alone, its shortlist ordered by within-chunk probability (chunk
           distributions are not strictly comparable: that is what this measures)
  full     wide + rerank, the live whole-shelf ranking; a "skip" verdict counts as an empty menu

Population: calibrate_jev_gate's positives (the agent used a skill in that same turn, interactive,
outside skill-concierge's own sessions). Gold = the skills it used. hit@k = a gold skill is in the
menu's top k. "reachable" = a gold skill is still on today's shelf (the corpus is older than it).
Answers are cached outside the repo (the corpus is private) and reused on a rerun.

  first_menu_replay.py run [--provider commandcode] [--workers 6] [--limit N]
  first_menu_replay.py report
  first_menu_replay.py wideprobs [--provider commandcode] [--workers 6]   # wide answers with probabilities
  first_menu_replay.py ordering    # raw within-chunk order vs lift order (p x chunk size), same answers
"""
import argparse
import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import calibrate_jev_gate as cal  # noqa: E402

OUT = Path.home() / ".claude/skill-concierge/analysis-private" / HERE.name / "replay.jsonl"
PROBS = OUT.with_name("wide-probs.jsonl")
LOCK = threading.Lock()
K = 5


def bare(name):
    return name.split(":")[-1]


def tier(enf, provider):
    for t in enf._jev_bench():
        if t.get("ep") == "jevd" and t["name"] == provider:
            return t
    sys.exit(f"jevd provider {provider!r} not on the ladder (is jevd running and JEVD_URL set?)")


def preview_menu(prompt):
    """The enforcer's embedding pass as a subprocess, exactly as the Cline plugin runs it."""
    env = {**os.environ, "ENFORCER_JEV_ROUTER": "0", "ENFORCER_LEDGER": "defer"}
    t0 = time.time()
    r = subprocess.run([sys.executable, str(REPO / "hooks/scripts/enforcer.py")],
                       input=json.dumps({"prompt": prompt, "session_id": "replay"}),
                       capture_output=True, text=True, timeout=60, env=env)
    ms = int((time.time() - t0) * 1000)
    try:
        offer = json.loads(r.stdout.strip().splitlines()[-1])["skillConciergeOffer"]
    except (IndexError, ValueError, KeyError):
        return [], ms, "no_offer"
    return [o[0] if isinstance(o, list) else o for o in offer.get("offered") or []], ms, offer.get("band")


def score_one(enf, t, catalog, r):
    state = cal.build_state(r, "ctx")
    rec = {"uuid": r["uuid"], "gold": sorted(cal.gold(r))}
    rec["preview"], rec["preview_ms"], rec["preview_band"] = preview_menu(r["prompt"])
    wide, ms, _u, err = cal.call(enf, t, state, enf._jev_wide_questions(catalog), t["timeout"])
    rec["wide_ms"], rec["err"] = ms, err
    if wide:
        probs = {}
        for k, a in wide.items():
            if k.startswith("wide::"):
                for n, p in a["probabilities"].items():
                    probs[n] = max(probs.get(n, 0.0), p)
        short = enf._jev_shortlist(wide)
        rec["wide"] = sorted(short, key=lambda n: -probs.get(n, 0.0))
        desc = dict(catalog)
        shortlist = [(n, desc[n]) for n in short if n in desc]
        rr, ms2, _u, err2 = cal.call(enf, t, state, enf._jev_rerank_questions(shortlist), t["timeout"])
        rec["rerank_ms"], rec["err"] = ms2, err2
        if rr:
            verdict, rows, _conf, best = enf._jev_decide(rr, shortlist)
            rec["full"], rec["verdict"], rec["best_fit"] = [n for n, _d, _p in rows], verdict, round(best, 3)
    with LOCK, OUT.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    return rec.get("err")


def done():
    if not OUT.exists():
        return {}
    recs = [json.loads(line) for line in OUT.open()]
    return {r["uuid"]: r for r in recs if "full" in r}


def cmd_run(a):
    enf = cal.load_enforcer()
    t = tier(enf, a.provider)
    catalog = enf._jev_catalog()
    rows = cal.load_corpus(cal.CORPUS)
    pos, _ = cal.pick(enf, rows, 0, 0)
    have = done()
    todo = [r for r in pos if r["uuid"] not in have][: a.limit or None]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    print(f"{len(pos)} positives, {len(have)} cached, {len(todo)} to run via jevd/{t['name']} "
          f"({t['model']}); catalogue {len(catalog)}", flush=True)
    with ThreadPoolExecutor(a.workers) as ex:
        errs = [e for e in ex.map(lambda r: score_one(enf, t, catalog, r), todo) if e]
    print(f"done: {len(todo) - len(errs)} complete, {len(errs)} failed {sorted(set(errs))}")


def hit(menu, gold, k):
    return bool({bare(n) for n in (menu or [])[:k]} & set(gold))


def cmd_report(_a):
    enf = cal.load_enforcer()
    shelf = {bare(n) for n, _d in enf._jev_catalog()}
    recs = list(done().values())
    reach = [r for r in recs if set(r["gold"]) & shelf]
    print(f"turns with all three menus: {len(recs)}; gold still on today's shelf: {len(reach)}")
    for label, rs in (("reachable", reach), ("all", recs)):
        n = max(len(rs), 1)
        print(f"\n{label} (n={len(rs)})      hit@1    hit@3    hit@5")
        for m in ("preview", "wide", "full"):
            cells = "  ".join(f"{100 * sum(hit(r.get(m), r['gold'], k) for r in rs) / n:6.1f}%" for k in (1, 3, 5))
            print(f"  {m:8s}            {cells}")
    skips = sum(r.get("verdict") == "skip" for r in reach)
    print(f"\nfull route said 'skip' (no menu) on {skips}/{len(reach)} reachable turns where a skill was used")
    for m in ("preview_ms", "wide_ms", "rerank_ms"):
        v = sorted(r[m] for r in recs if r.get(m))
        if v:
            print(f"{m:11s} p50 {v[len(v) // 2]} ms  p90 {v[int(len(v) * 0.9)]} ms  (n={len(v)})")
    both = sorted(r["wide_ms"] + r["rerank_ms"] for r in recs if r.get("wide_ms") and r.get("rerank_ms"))
    if both:
        print(f"wide+rerank p50 {both[len(both) // 2]} ms  p90 {both[int(len(both) * 0.9)]} ms "
              f"(Jev calls only; the enforcer adds ~0.35 s)")
    wide_v = sorted(r["wide_ms"] for r in recs if r.get("wide_ms"))
    if wide_v:
        under = sum(v + 350 <= 2000 for v in wide_v) / len(wide_v)
        print(f"wide pass + 0.35 s inside Cline's 2 s wait: {100 * under:.0f}% of turns")


def wide_one(enf, t, catalog, r):
    wide, ms, _u, err = cal.call(enf, t, cal.build_state(r, "ctx"), enf._jev_wide_questions(catalog), t["timeout"])
    rec = {"uuid": r["uuid"], "gold": sorted(cal.gold(r)), "ms": ms, "err": err}
    if wide:
        rec["chunks"] = {k: {"n": len(a["probabilities"]), "p": a["probabilities"]}
                         for k, a in wide.items() if k.startswith("wide::")}
    with LOCK, PROBS.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    return err


def cmd_wideprobs(a):
    enf = cal.load_enforcer()
    t = tier(enf, a.provider)
    catalog = enf._jev_catalog()
    pos, _ = cal.pick(enf, cal.load_corpus(cal.CORPUS), 0, 0)
    have = {json.loads(l)["uuid"] for l in PROBS.open() if '"chunks"' in l} if PROBS.exists() else set()
    todo = [r for r in pos if r["uuid"] not in have]
    print(f"{len(todo)} wide calls via jevd/{t['name']}; catalogue {len(catalog)}", flush=True)
    with ThreadPoolExecutor(a.workers) as ex:
        errs = [e for e in ex.map(lambda r: wide_one(enf, t, catalog, r), todo) if e]
    print(f"done: {len(todo) - len(errs)} complete, {len(errs)} failed {sorted(set(errs))}")


def order(rec, how):
    flat = []
    for k, c in rec["chunks"].items():
        top = sorted(c["p"], key=lambda n: -c["p"][n])[:5]   # the live shortlist: top 5 per chunk
        flat += [(n, c["p"][n] * (c["n"] if how == "lift" else 1)) for n in top]
    return [n for n, _v in sorted(flat, key=lambda x: -x[1])]


def cmd_ordering(_a):
    enf = cal.load_enforcer()
    shelf = {bare(n) for n, _d in enf._jev_catalog()}
    recs = {}
    for l in PROBS.open():
        r = json.loads(l)
        if r.get("chunks"):
            recs[r["uuid"]] = r
    rs = [r for r in recs.values() if set(r["gold"]) & shelf]
    print(f"reachable turns with wide probabilities: {len(rs)}; chunk sizes "
          f"{sorted({c['n'] for r in rs for c in r['chunks'].values()})}")
    for how in ("raw", "lift"):
        cells = "  ".join(f"hit@{k} {100 * sum(hit(order(r, how), r['gold'], k) for r in rs) / len(rs):5.1f}%"
                          for k in (1, 3, 5))
        share = {}
        for r in rs:
            for n in order(r, how)[:5]:
                ck = next(k for k, c in r["chunks"].items() if n in c["p"])
                share[ck] = share.get(ck, 0) + 1
        tot = sum(share.values())
        print(f"  {how:5s} {cells}   top-5 rows by chunk: " +
              ", ".join(f"{k} {100 * v / tot:.0f}%" for k, v in sorted(share.items())))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--provider", default="commandcode")
    r.add_argument("--workers", type=int, default=6)
    r.add_argument("--limit", type=int, default=0)
    sub.add_parser("report")
    w = sub.add_parser("wideprobs")
    w.add_argument("--provider", default="commandcode")
    w.add_argument("--workers", type=int, default=6)
    sub.add_parser("ordering")
    a = ap.parse_args()
    {"run": cmd_run, "report": cmd_report, "wideprobs": cmd_wideprobs, "ordering": cmd_ordering}[a.cmd](a)


if __name__ == "__main__":
    main()
