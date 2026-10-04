"""Engine arms via srv.consult_candidates: flags x top_n. Stores row names per case for union work."""
from common import *
srv, cases, gen = load()
engine(srv, ["warm up the skill index"], 20)
ARMS = {"A0": ("0", "0"), "slots": ("1", "0"), "rrf": ("0", "1"), "slots+rrf": ("1", "1")}
out = open(OUT / "arms_engine.jsonl", "w")
for n, c in enumerate(cases):
    qs = SR.arm_queries("A0", gen, c)
    rec = {"id": c["id"], "label": c["label"]}
    order = list(ARMS)[n % 4:] + list(ARMS)[:n % 4]
    for a in order:
        for N in (20, 40):
            rows, ms = engine(srv, qs, N, *ARMS[a])
            rec[f"{a}@{N}"] = {"names": [r["name"] for r in rows], "ext": [bool(r.get("external")) for r in rows], "ms": ms}
    out.write(json.dumps(rec) + "\n")
print("done")
