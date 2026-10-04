from common import *
srv, cases, gen = load()
for c in cases[:6]:
    qs = SR.arm_queries("A0", gen, c)
    vec = srv.embed_queries(qs)
    for lim in (40, 100):
        rep = [r["name"] for r in srv._fuse_ranked(groups(srv, vec, lim, srv._scope_filter()), 40)]
        eng = [r["name"] for r in engine(srv, qs, 40)[0]]
        eng2 = [r["name"] for r in engine(srv, qs, 40)[0]]
        print(lim, "rep==eng", rep == eng, "eng stable", eng == eng2, "setdiff", len(set(rep) ^ set(eng)),
              "first diff idx", next((i for i,(a,b) in enumerate(zip(rep,eng)) if a!=b), None), "lens", len(rep), len(eng))
    # vectors stable?
    v2 = srv.embed_queries(qs)
    import math
    print("vec maxdiff", max(abs(a-b) for x,y in zip(vec,v2) for a,b in zip(x,y)))
