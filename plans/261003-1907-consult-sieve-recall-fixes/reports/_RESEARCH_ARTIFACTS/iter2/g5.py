import json, sys, statistics as st
from pathlib import Path
sys.path.insert(0, "/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/scripts")
import sieve_recall as SR
exec(open(Path(__file__).parent / "analyze_iter2.py").read().split("base = {k:")[0])
extset = {}
for i in ids:
    for a in ("A0", "slots+rrf"):
        for N in (20, 40):
            for n, e in zip(E[i][f"{a}@{N}"]["names"], E[i][f"{a}@{N}"]["ext"]): extset[n] = e
JW = {i: jev_wide_rr(J[i]) for i in ids}
def ext_stats(lists):
    ex = [sum(1 for n in l if extset.get(n)) for l in lists]; return st.median(ex), round(100 * st.mean(e / max(len(l), 1) for e, l in zip(ex, lists)), 1)
for N in (20, 40):
    print(f"@{N} A0 median ext/share", ext_stats([E[i][f'A0@{N}']['names'] for i in ids]),
          "| slots+rrf", ext_stats([E[i][f'slots+rrf@{N}']['names'] for i in ids]),
          "| A0 U jev10", ext_stats([union(JW[i][:10], E[i]['A0@40']['names'], N) for i in ids]))
