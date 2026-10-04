"""Jev run-to-run stability: recall of the two runs and top-10 overlap."""
import json, sys, statistics as st
from pathlib import Path
sys.path.insert(0, "/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/scripts")
import sieve_recall as SR
exec(open(Path(__file__).parent / "analyze_iter2.py").read().split("base = {k:")[0])
J2 = L("jev_wide_rep2.jsonl")
errs = sum(1 for i in ids if "wide_err" in J2[i]) , sum(1 for i in ids if "wide_err" in J[i])
print("wide errors run1/run2:", errs[1], errs[0], "| rerank errors run1/run2:",
      sum(1 for i in ids if "rerank_err" in J[i]), sum(1 for i in ids if "rerank_err" in J2[i]))
for run, JJ in (("run1", J), ("run2", J2)):
    W = {i: jev_wide_rr(JJ[i]) for i in ids}
    ms = [JJ[i]["wide_ms"] for i in ids]
    print(run, "jev-only @10", round(100*sum(hit(i, W[i], 10) for i in ids)/len(ids),1), "@20", round(100*sum(hit(i, W[i], 20) for i in ids)/len(ids),1),
          "| A0 U jev10 @20", round(100*sum(hit(i, union(W[i][:10], R[i]["A0r@100"]["names"], 20), 20) for i in ids)/len(ids),1),
          "@40", round(100*sum(hit(i, union(W[i][:10], R[i]["A0r@100"]["names"], 40), 40) for i in ids)/len(ids),1),
          "| wide ms p50/p90", pct(ms,.5), pct(ms,.9), "max", max(ms))
ov = [len(set(jev_wide_rr(J[i])[:10]) & set(jev_wide_rr(J2[i])[:10])) / 10 for i in ids]
print("top-10 overlap run1 vs run2: mean", round(st.mean(ov),3), "min", min(ov))
flip = sum(hit(i, jev_wide_rr(J[i]), 10) != hit(i, jev_wide_rr(J2[i]), 10) for i in ids)
print("cases whose jev top-10 hit flips between runs:", flip)
print("models:", set(J[i].get("model") for i in ids), set(J2[i].get("model") for i in ids))
