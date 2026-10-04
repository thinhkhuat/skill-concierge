"""One Jev wide call (+ the router's rerank on the top-5-per-chunk shortlist) per kept case.
ts tier only, one attempt each, timeout 3 s. Writes names/probabilities only (no prompt text)."""
from common import *
import jev_client
srv, cases, gen = load()
enf = jev_client.load_enforcer()
cat = enf._jev_catalog()
desc = dict(cat)
tier = [t for t in enf._jev_bench() if t["ep"] == "ts"][0]
key = enf._jev_key(tier)
wq = enf._jev_wide_questions(cat)
out = open(OUT / "jev_wide_rep2.jsonl", "w")
for c in cases:
    state = {"request": c["gen_text"][:4000], "recent_context": "", "skills_already_loaded_this_session": []}
    rec = {"id": c["id"], "label": c["label"], "catalog_n": len(cat)}
    t0 = time.time()
    try:
        ans, via, model = enf._jev_call(state, wq, tier, key, 3.0)
        rec.update(wide_ms=int((time.time() - t0) * 1000), model=model,
                   wide={k: ans[k]["probabilities"] for k in ans if k.startswith("wide::")})
    except Exception as e:  # counted as a miss
        rec.update(wide_err=type(e).__name__, wide_ms=int((time.time() - t0) * 1000))
    if "wide" in rec:
        sl = [(n, desc[n]) for n in enf._jev_shortlist({k: {"probabilities": v} for k, v in rec["wide"].items()}) if n in desc]
        t1 = time.time()
        try:
            rr, _, _ = enf._jev_call(state, enf._jev_rerank_questions(sl), tier, key, 3.0)
            rec.update(rerank_ms=int((time.time() - t1) * 1000), which=rr["which"]["probabilities"],
                       fits={sl[i][0]: rr[f"fits::{i}"]["noul"] for i in range(len(sl))})
        except Exception as e:
            rec.update(rerank_err=type(e).__name__, rerank_ms=int((time.time() - t1) * 1000))
    out.write(json.dumps(rec) + "\n"); out.flush()
    print(c["id"][:8], rec.get("wide_err", "ok"), rec["wide_ms"], rec.get("rerank_err", "ok"), rec.get("rerank_ms"), flush=True)
print("done")
