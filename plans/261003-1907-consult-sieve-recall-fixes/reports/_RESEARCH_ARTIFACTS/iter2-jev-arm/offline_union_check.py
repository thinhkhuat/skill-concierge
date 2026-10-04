"""Offline: my union_rows + jev_round_robin on the diagnosis's saved Jev answers and engine rows."""
import json, sys
sys.path.insert(0, "/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/scripts")
import sieve_recall as S
D = "/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/plans/261003-1907-consult-sieve-recall-fixes/reports/_RESEARCH_ARTIFACTS/iter2/"
L = lambda f: {r["id"]: r for r in map(json.loads, open(D + f))}
E, R = L("arms_engine.jsonl"), L("arms_replica.jsonl")
for jf in ("jev_wide.jsonl", "jev_wide_rep2.jsonl"):
    J = L(jf)
    for src in ("engine40", "replica100"):
        h = {20: 0, 40: 0}
        for i, e in E.items():
            rows = [{"name": n, "external": x} for n, x in zip(e["A0@40"]["names"], e["A0@40"]["ext"])] if src == "engine40" \
                else [{"name": n} for n in R[i]["A0r@100"]["names"]]
            names = S.jev_round_robin({k: {"probabilities": v} for k, v in J[i].get("wide", {}).items()})[:10]
            for k in (20, 40):
                h[k] += S.hit_at(e["label"], S.union_rows(names, rows, k), k)
        print(jf, src, {k: round(100 * v / len(E), 1) for k, v in h.items()})
