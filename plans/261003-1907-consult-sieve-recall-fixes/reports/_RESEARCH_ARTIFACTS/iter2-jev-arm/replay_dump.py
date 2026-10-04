"""Scratch: the replay-arms path (iteration 1 only) with per-case Jev top-10 names dumped, two repeats."""
import sys, json
sys.path.insert(0, "/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/scripts")
import sieve_recall as S
S.set_iter(1)
srv = S.load_engine()
wide, tier, ask = S.jev_setup()
gen = S.load_generated()
cases, nl, ng = S._gate_cases(S.read_jsonl(S.CASES), gen, {p["name"] for p in S.scroll_base_points()})
S.call_engine(srv, ["warm up the skill index"], 20, "0", "0")
for rep in (1, 2):
    res = S.run_arms2(srv, cases, gen, lambda t: S.jev_top(t, wide, tier, ask))
    with open(f"replay_dump_rep{rep}.jsonl", "w") as f:
        for c in cases:
            r = res["J20"][c["id"]]
            f.write(json.dumps({"id": c["id"], "label": c["label"], "jev": r["jev_names"], "ms": r["jev_ms"], "err": r["jev_err"],
                                "j20": r["hit"], "j40": res["J40"][c["id"]]["hit"]}) + "\n")
    print("rep", rep, *S.recall_lines2(res), *S.jev_report(res), sep="\n", flush=True)
