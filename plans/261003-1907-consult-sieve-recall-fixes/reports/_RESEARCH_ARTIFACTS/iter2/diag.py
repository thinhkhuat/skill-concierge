"""Per-case baseline (A0, d0 queries) diagnosis to rank 100. Writes diag.jsonl (ids, names, numbers)."""
from common import *
srv, cases, gen = load()
SF = srv._scope_filter()
def nflt(name):
    f = srv._scope_filter(); f["must"] = [{"key": "name", "match": {"value": name}}]; return f
inst_f = srv._installed_only_filter()
def kindf(kind, base):
    f = json.loads(json.dumps(base)); f.setdefault("must", []).append({"key": "kind", "match": {"value": kind}}); return f
def rank(name, rows, miss=101):
    k = SR.skill_key(name)
    for i, r in enumerate(rows):
        if SR.skill_key(r["name"]) == k: return i + 1
    return miss
out = open(OUT / "diag.jsonl", "w")
eq_bad = 0
for c in cases:
    qs = SR.arm_queries("A0", gen, c)
    vec = srv.embed_queries(qs)
    gl = groups(srv, vec, 100, SF)
    full = fused(srv, gl, 100)                       # blocked dropped
    for N in (20, 40):                               # engine equivalence
        eqv = [r["name"] for r in fused(srv, gl, N)]
        if eqv != [r["name"] for r in engine(srv, qs, N)[0]]: eq_bad += 1
    r_mixed = rank(c["label"], full)
    inst = fused(srv, groups(srv, vec, 100, inst_f), 100)
    r_inst = rank(c["label"], inst)
    # label's own best hit per query
    lab = [srv._qdrant.query_groups(srv.COLLECTION, v, group_by="name", limit=1, filter=nflt(c["label"])) for v in vec]
    lab_best = [(g[0]["hits"][0]["score"], (g[0]["hits"][0].get("payload") or {}).get("kind")) if g else (None, None) for g in lab]
    per_q_rank = [rank(c["label"], [{"name": (g["hits"][0].get("payload") or {}).get("name", g.get("id"))} for g in gq if g.get("hits")]) for gq in gl]
    s20 = full[19]["score"] if len(full) >= 20 else None
    s40 = full[39]["score"] if len(full) >= 40 else None
    above = full[:min(r_mixed - 1, 20)]
    # base-only and trigger-only fusion (description vs trigger points)
    rb = rank(c["label"], fused(srv, groups(srv, vec, 100, kindf("base", SF)), 100))
    rt = rank(c["label"], fused(srv, groups(srv, vec, 100, kindf("trigger", SF)), 100))
    # whole task text as one query (gen_text, the redacted prompt) and the 300-char task
    gv = srv.embed_queries([c["gen_text"], c["task"]])
    rg = rank(c["label"], fused(srv, groups(srv, gv[:1], 100, SF), 100))
    rgt = rank(c["label"], fused(srv, groups(srv, gv[1:], 100, SF), 100))
    rec = {"id": c["id"], "label": c["label"], "group": c["group"], "process": c["process"], "english": c["english"],
           "nq": len(qs), "r_mixed": r_mixed, "r_inst": r_inst, "r_base_only": rb, "r_trig_only": rt,
           "r_gentext": rg, "r_task": rgt, "per_q_rank": per_q_rank,
           "lab_best": [s for s, _ in lab_best], "lab_best_kind": [k for _, k in lab_best],
           "s20": s20, "s40": s40, "ext_above_top20": sum(1 for r in above if r.get("external")),
           "n_above_top20": len(above), "top20": [(r["name"], bool(r.get("external")), r["score"]) for r in full[:20]]}
    out.write(json.dumps(rec) + "\n")
print("engine-equivalence mismatches (of", 2 * len(cases), "):", eq_bad)
