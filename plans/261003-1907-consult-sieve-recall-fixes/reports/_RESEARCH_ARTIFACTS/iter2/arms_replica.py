"""Replica arms (exact engine primitives: embed_queries, query_groups, _fuse_ranked, _rrf_order,
_blocked) for orderings the engine has no flag for. Stores top-100 names per arm per case."""
from common import *
srv, cases, gen = load()
SF, IF = srv._scope_filter(), srv._installed_only_filter()
def rr(gl, n):
    """round-robin: rank-1 of each query in query order, then rank-2, ...; dedupe; drop blocked."""
    lists = [[(g["hits"][0].get("payload") or {}).get("name", g.get("id")) for g in gq if g.get("hits")] for gq in gl]
    out, seen = [], set()
    for i in range(max(map(len, lists))):
        for l in lists:
            if i < len(l) and l[i] not in seen:
                seen.add(l[i]); out.append(l[i])
    return [n for n in out if not srv._blocked(n)][:n]
def rrfk(gl, k, n):
    return [x for x in srv._rrf_order(gl, k) if not srv._blocked(x)][:n]
out = open(OUT / "arms_replica.jsonl", "w")
for c in cases:
    qs = SR.arm_queries("A0", gen, c)
    rec = {"id": c["id"], "label": c["label"]}
    t0 = time.perf_counter(); vec = srv.embed_queries(qs); t_emb = time.perf_counter() - t0
    for N in (20, 40, 100):
        t0 = time.perf_counter(); gl = groups(srv, vec, N, SF); tq = time.perf_counter() - t0
        rec[f"A0r@{N}"] = {"names": [r["name"] for r in fused(srv, gl, N)], "ms": 1000 * (t_emb + tq)}
        rec[f"rr@{N}"] = {"names": rr(gl, N), "ms": 1000 * (t_emb + tq)}
        for k in (1, 5, 20):
            rec[f"rrf{k}@{N}"] = {"names": rrfk(gl, k, N), "ms": 1000 * (t_emb + tq)}
        t0 = time.perf_counter(); gi = groups(srv, vec, N, IF); ti = time.perf_counter() - t0
        rec[f"inst@{N}"] = {"names": [r["name"] for r in fused(srv, gi, N)], "ms": 1000 * (t_emb + ti)}
        rec[f"instrr@{N}"] = {"names": rr(gi, N), "ms": 1000 * (t_emb + ti)}
    out.write(json.dumps(rec) + "\n")
print("done")
