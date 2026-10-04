"""Strata and session-level stats for the key arms. Joins the label corpus by uuid for ledger_jev and ts
(no prompt text read out)."""
import json, sys, math
from collections import Counter
from pathlib import Path
sys.path.insert(0, "/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/scripts")
import sieve_recall as SR
exec(open(Path(__file__).parent / "analyze_iter2.py").read().split("base = {k:")[0])  # helpers + loaders
IR = L("inst_rrf.jsonl")
lab = {}
for l in open(SR.LABELS):
    r = json.loads(l); lab[r["uuid"]] = {"jev": r.get("ledger_jev"), "ts": r.get("ts_utc"), "band": r.get("ledger_offer_band")}
cases = {c["id"]: c for c in SR.read_jsonl(SR.CASES)}
meta = {i: lab.get(cases[i]["uuid"], {}) for i in ids}
def jev_state(m):
    j = m.get("jev")
    if not j: return "no-router"
    return "router-err" if j.get("err") else "router-ok"
print("ts range", min(m["ts"] for m in meta.values()), max(m["ts"] for m in meta.values()))
print("router state", Counter(jev_state(m) for m in meta.values()))
print("band", Counter(m.get("band") for m in meta.values()))
JW = {i: jev_wide_rr(J[i]) for i in ids}
ARMS = {
 "A0": lambda i, k: E[i][f"A0@{k}"]["names"],
 "slots+rrf": lambda i, k: E[i][f"slots+rrf@{k}"]["names"],
 "inst": lambda i, k: R[i][f"inst@{k}"]["names"],
 "inst-rrf60": lambda i, k: IR[i][f"instrrf@{k}"],
 "jev wide-rr only": lambda i, k: JW[i],
 "A0 U jev10": lambda i, k: union(JW[i][:10], R[i]["A0r@100"]["names"], k),
 "slots U jev10": lambda i, k: union(JW[i][:10], E[i]["slots@40"]["names"], k),
 "slots+rrf U jev10": lambda i, k: union(JW[i][:10], E[i]["slots+rrf@40"]["names"], k),
 "inst U jev10": lambda i, k: union(JW[i][:10], R[i]["inst@100"]["names"], k),
}
strata = {"all": lambda i: True, "not_offered": lambda i: cases[i]["group"] == "not_offered",
          "offered": lambda i: cases[i]["group"] == "offered",
          "no-router": lambda i: jev_state(meta[i]) == "no-router",
          "router-ok": lambda i: jev_state(meta[i]) == "router-ok",
          "router-ok & not_offered": lambda i: jev_state(meta[i]) == "router-ok" and cases[i]["group"] == "not_offered",
          "english": lambda i: cases[i]["english"], "non-english": lambda i: not cases[i]["english"],
          "excl. blocklisted label": lambda i: D[i]["label"] != "whereami"}
for sname, f in strata.items():
    sel = [i for i in ids if f(i)]
    if not sel: continue
    ss = len({cases[i]["sid"] for i in sel})
    parts = []
    for a, g in ARMS.items():
        h20 = sum(hit(i, g(i, 20), 20) for i in sel); h40 = sum(hit(i, g(i, 40), 40) for i in sel)
        parts.append(f"{a} {100*h20/len(sel):.1f}/{100*h40/len(sel):.1f}")
    print(f"STRATUM {sname}: n={len(sel)} sessions={ss} | " + " | ".join(parts))
# session-level sign test + bootstrap lower bound (session unit) at @20 and @40 vs A0
print()
for a, g in ARMS.items():
    if a == "A0": continue
    for k in (20, 40):
        b = [hit(i, ARMS["A0"](i, k), k) for i in ids]; x = [hit(i, g(i, k), k) for i in ids]
        gs, ls, p = SR.session_sign([cases[i]["sid"] for i in ids], b, x)
        low = SR.bootstrap_lower(SR.guard_units([(cases[i]["sid"], int(xx) - int(bb), 1) for i, bb, xx in zip(ids, b, x)]))
        print(f"SESSION {a} @{k}: gain {100*(sum(x)-sum(b))/len(ids):.1f} pts, sessions +{gs}/-{ls} p={p:.5f}, bootstrap 95% lower {low:.1f}")
# which miss-causes does jev recover
print()
cause = lambda d: "21-40" if 20 < d["r_mixed"] <= 40 else "41-100" if 40 < d["r_mixed"] <= 100 else ">100" if d["r_mixed"] > 100 else "hit"
for cz in ("hit", "21-40", "41-100", ">100"):
    sel = [i for i in ids if cause(D[i]) == cz]
    print(f"CAUSE {cz}: n={len(sel)} jev-wide top10 hits {sum(hit(i, JW[i], 10) for i in sel)} top20 {sum(hit(i, JW[i], 20) for i in sel)}"
          f"; union A0+jev10 @20 {sum(hit(i, union(JW[i][:10], R[i]['A0r@100']['names'], 20), 20) for i in sel)}")
