"""Recall@20/@40, n, latency p50/p90, gained/lost vs A0 for every arm. Reads only scratch outputs
plus the frozen case ids (sid for session counts). Prints label names and ids, never prompt text."""
import json, math, sys
from pathlib import Path
sys.path.insert(0, "/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/scripts")
import sieve_recall as SR
H = Path(__file__).resolve().parent
L = lambda f: {r["id"]: r for r in map(json.loads, open(H / f))}
E, R, J, D = L("arms_engine.jsonl"), L("arms_replica.jsonl"), L("jev_wide.jsonl"), L("diag.jsonl")
ids = list(D)
sid = {c["id"]: c["sid"] for c in SR.read_jsonl(SR.CASES)}
key = {i: SR.skill_key(D[i]["label"]) for i in ids}
blocked_ids = {i for i in ids if D[i]["label"] == "whereami"}
def hit(i, names, k): return any(SR.skill_key(n) == key[i] for n in names[:k])
def pct(xs, q):
    s = sorted(xs); return s[min(len(s) - 1, max(0, math.ceil(q * len(s)) - 1))]
def binom_p(a, b):  # two-sided exact sign test
    n = a + b
    if n == 0: return 1.0
    k = min(a, b); p = sum(math.comb(n, j) for j in range(k + 1)) / 2 ** n
    return min(1.0, 2 * p)
def jev_wide_rr(r):
    if "wide" not in r: return []
    chunks = [sorted(p, key=lambda n: -p[n]) for _, p in sorted(r["wide"].items(), key=lambda kv: int(kv[0].split("::")[1]))]
    out = []
    for i in range(max(map(len, chunks))):
        for c in chunks:
            if i < len(c): out.append(c[i])
    return out
def jev_wide_glob(r):
    if "wide" not in r: return []
    allp = {n: p for ch in r["wide"].values() for n, p in ch.items()}
    return sorted(allp, key=lambda n: -allp[n])
def jev_rerank(r):
    w = r.get("which") or {}
    return sorted(w, key=lambda n: -w[n])
def union(first, rest, Ltot):
    out, seen = [], set()
    for n in list(first) + list(rest):
        k = SR.skill_key(n)
        if k not in seen:
            seen.add(k); out.append(n)
        if len(out) >= Ltot: break
    return out
base = {k: {i: hit(i, E[i][f"A0@{k}"]["names"], k) for i in ids} for k in (20, 40)}
rows = []
def arm(name, lists20, lists40, ms):
    h20 = {i: hit(i, lists20[i], 20) for i in ids}
    h40 = {i: hit(i, lists40[i], 40) for i in ids}
    g = sum(h20[i] and not base[20][i] for i in ids); l = sum(base[20][i] and not h20[i] for i in ids)
    g4 = sum(h40[i] and not base[40][i] for i in ids); l4 = sum(base[40][i] and not h40[i] for i in ids)
    n = len(ids)
    rows.append((name, n, 100 * sum(h20.values()) / n, 100 * sum(h40.values()) / n, g, l, binom_p(g, l), g4, l4, binom_p(g4, l4),
                 pct(ms, .5), pct(ms, .9)))
    return h20, h40
eng = lambda a: ({i: E[i][f"{a}@20"]["names"] for i in ids}, {i: E[i][f"{a}@40"]["names"] for i in ids},
                 [E[i][f"{a}@40"]["ms"] for i in ids])
rep = lambda a: ({i: R[i][f"{a}@20"]["names"] for i in ids}, {i: R[i][f"{a}@40"]["names"] for i in ids},
                 [R[i][f"{a}@40"]["ms"] for i in ids])
for a in ("A0", "slots", "rrf", "slots+rrf"):
    arm(f"engine {a}", *eng(a))
for a in ("A0r", "rr", "rrf1", "rrf5", "rrf20", "inst", "instrr"):
    arm(f"replica {a}", *rep(a))
jms = [J[i]["wide_ms"] for i in ids]
jrms = [J[i]["wide_ms"] + J[i].get("rerank_ms", 0) for i in ids]
a0ms = {i: E[i]["A0@40"]["ms"] for i in ids}
JW = {i: jev_wide_rr(J[i]) for i in ids}; JG = {i: jev_wide_glob(J[i]) for i in ids}; JR = {i: jev_rerank(J[i]) for i in ids}
arm("jev-only wide rr", JW, JW, jms)
arm("jev-only wide global", JG, JG, jms)
arm("jev-only router rerank (<=15)", JR, JR, jrms)
srcs = {"A0": {i: R[i]["A0r@100"]["names"] for i in ids}, "slots": {i: E[i]["slots@40"]["names"] for i in ids},
        "inst": {i: R[i]["inst@100"]["names"] for i in ids}, "rr": {i: R[i]["rr@100"]["names"] for i in ids}}
sms = {"A0": a0ms, "slots": {i: E[i]["slots@40"]["ms"] for i in ids}, "inst": {i: R[i]["inst@40"]["ms"] for i in ids},
       "rr": {i: R[i]["rr@40"]["ms"] for i in ids}}
for s in ("A0", "slots", "inst", "rr"):
    for jn, JL, jt in (("wide-rr", JW, "wide_ms"), ("wide-glob", JG, "wide_ms"), ("rerank", JR, None)):
        for k in (5, 10, 20):
            if jn == "rerank" and k > 15: continue
            l20 = {i: union(JL[i][:k], srcs[s][i], 20) for i in ids}
            l40 = {i: union(JL[i][:k], srcs[s][i], 40) for i in ids}
            ms = [max(sms[s][i], J[i]["wide_ms"] + (J[i].get("rerank_ms", 0) if jt is None else 0)) for i in ids]
            arm(f"union {s} + jev {jn} top{k}", l20, l40, ms)
print(f"{'arm':44s} {'n':>3} {'@20':>5} {'@40':>5}  g20/l20 p20    g40/l40 p40     p50ms  p90ms")
for r in rows:
    print(f"{r[0]:44s} {r[1]:3d} {r[2]:5.1f} {r[3]:5.1f}  +{r[4]}/-{r[5]} {r[6]:.4f}  +{r[7]}/-{r[8]} {r[9]:.4f}  {r[10]:6.0f} {r[11]:6.0f}")
print("excluding the 2 blocklisted-label cases changes n to", len(ids) - len(blocked_ids))
