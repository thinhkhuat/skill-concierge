from common import *
srv, cases, gen = load()
print("kept cases", len(cases))
# replica == engine check on all cases at 40
bad = 0
for c in cases:
    qs = SR.arm_queries("A0", gen, c)
    vec = srv.embed_queries(qs)
    rep = [r["name"] for r in fused(srv, groups(srv, vec, 100, srv._scope_filter()), 100)][:40]
    eng = [r["name"] for r in engine(srv, qs, 40)[0]]
    if rep != eng: bad += 1
print("replica mismatches at 40:", bad)
import jev_client
enf = jev_client.load_enforcer()
cat = enf._jev_catalog()
print("jev catalog", len(cat), "chunks", len(enf._jev_wide_questions(cat)))
print("wide tokens est", enf._jev_tokens(json.dumps({"state": {"request": "x"*2000}, "questions": enf._jev_wide_questions(cat)})))
print("bench", [(t["ep"], t["model"], t["timeout"]) for t in enf._jev_bench()])
labels = {c["label"] for c in cases}
cn = {n for n, _ in cat}
print("labels in jev catalog", sum(1 for l in labels if l in cn), "/", len(labels))
print("labels missing from jev catalog:", sorted(l for l in labels if l not in cn))
