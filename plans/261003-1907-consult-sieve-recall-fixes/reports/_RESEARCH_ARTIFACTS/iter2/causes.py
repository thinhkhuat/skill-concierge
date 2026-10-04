"""Cause tally for the 55 A0@20 misses, plus what the A0 U jev10 union still misses."""
import json, sys
from collections import Counter
from pathlib import Path
sys.path.insert(0, "/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/scripts")
import sieve_recall as SR
exec(open(Path(__file__).parent / "analyze_iter2.py").read().split("base = {k:")[0])
miss = [i for i in ids if D[i]["r_mixed"] > 20]
print("A0@20 misses:", len(miss))
blk = [i for i in miss if D[i]["label"] == "whereami"]
rest = [i for i in miss if i not in blk]
crowd = [i for i in rest if D[i]["r_inst"] <= 20]
buried = [i for i in rest if i not in crowd and min(D[i]["per_q_rank"]) <= 20]
nomatch = [i for i in rest if min(D[i]["per_q_rank"]) > 100]
other = [i for i in rest if i not in crowd and i not in buried and i not in nomatch]
print("C0 label blocklisted (unwinnable):", len(blk))
print("C1 crowded out by externals (installed-only rank <=20):", len(crowd), Counter(D[i]["label"] for i in crowd).most_common())
print("C2 MAX-pool burial (one query ranks it <=20, not C1):", len(buried), Counter(D[i]["label"] for i in buried).most_common())
print("C3 no query ranks it in the top 100:", len(nomatch), Counter(D[i]["label"] for i in nomatch).most_common())
print("C4 weak everywhere (best single-query rank 21-100, not C1/C2):", len(other), Counter(D[i]["label"] for i in other).most_common())
JW = {i: jev_wide_rr(J[i]) for i in ids}
for nm, grp in (("C1", crowd), ("C2", buried), ("C3", nomatch), ("C4", other)):
    print(nm, "recovered by A0 U jev10 @20:", sum(hit(i, union(JW[i][:10], R[i]["A0r@100"]["names"], 20), 20) for i in grp), "of", len(grp),
          "| by slots+rrf @20:", sum(hit(i, E[i]["slots+rrf@20"]["names"], 20) for i in grp))
still = [i for i in ids if not hit(i, union(JW[i][:10], R[i]["A0r@100"]["names"], 20), 20)]
print("still missed by A0 U jev10 @20:", len(still), Counter(D[i]["label"] for i in still).most_common())
lost = [i for i in ids if hit(i, E[i]["A0@20"]["names"], 20) and not hit(i, union(JW[i][:10], R[i]["A0r@100"]["names"], 20), 20)]
print("lost by A0 U jev10 @20 vs A0:", [(i[:8], D[i]["label"]) for i in lost])
