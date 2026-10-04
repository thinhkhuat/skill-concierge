"""Decompose slots+rrf: installed-only RRF(k=60) ordering at 20/40, replica."""
from common import *
srv, cases, gen = load()
IF = srv._installed_only_filter()
out = open(OUT / "inst_rrf.jsonl", "w")
for c in cases:
    vec = srv.embed_queries(SR.arm_queries("A0", gen, c))
    rec = {"id": c["id"]}
    for N in (20, 40):
        gl = groups(srv, vec, N, IF)
        rec[f"instrrf@{N}"] = [x for x in srv._rrf_order(gl, 60) if not srv._blocked(x)][:N]
    out.write(json.dumps(rec) + "\n")
print("done")
