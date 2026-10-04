from common import *
srv, cases, gen = load()
SF = srv._scope_filter()
for c in cases:
    qs = SR.arm_queries("A0", gen, c); vec = srv.embed_queries(qs)
    for N in (20, 40):
        a = [r["name"] for r in fused(srv, groups(srv, vec, 100, SF), N)]
        b = [r["name"] for r in fused(srv, groups(srv, vec, N, SF), N)]
        e = [r["name"] for r in engine(srv, qs, N)[0]]
        if a != e:
            print(c["id"][:8], N, "lim100==engine", a == e, "limN==engine", b == e, "set diff", sorted(set(a) ^ set(e))[:4], "label in a", c["label"] in a, "in e", c["label"] in e)
