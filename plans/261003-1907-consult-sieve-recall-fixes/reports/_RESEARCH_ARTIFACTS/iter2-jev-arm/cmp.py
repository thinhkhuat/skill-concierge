import json, sys
sys.path.insert(0, "/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/scripts")
import sieve_recall as S
D = "../iter2/"
L = lambda f: {r["id"]: r for r in map(json.loads, open(f))}
a, b = L(D + "jev_wide.jsonl"), L(D + "jev_wide_rep2.jsonl")
m1, m2 = L("replay_dump_rep1.jsonl"), L("replay_dump_rep2.jsonl")
top = lambda r: S.jev_round_robin({k: {"probabilities": v} for k, v in r["wide"].items()})[:10]
runs = {"diag1": {i: top(r) for i, r in a.items()}, "diag2": {i: top(r) for i, r in b.items()},
        "mine1": {i: r["jev"] for i, r in m1.items()}, "mine2": {i: r["jev"] for i, r in m2.items()}}
hit = lambda i, names: any(S.skill_key(n) == S.skill_key(a[i]["label"]) for n in names)
print("jev-top10 label hit:", {k: sum(hit(i, v[i]) for i in a) for k, v in runs.items()})
names = list(runs)
for x in range(4):
    for y in range(x + 1, 4):
        ov = [len(set(runs[names[x]][i]) & set(runs[names[y]][i])) / 10 for i in a]
        print(names[x], names[y], f"overlap {100*sum(ov)/len(ov):.1f}%")
