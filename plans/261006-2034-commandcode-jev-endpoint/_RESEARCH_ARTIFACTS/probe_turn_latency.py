"""Time one full router turn shape (wide call, then rerank call on its shortlist) per endpoint. Keys from env, never printed."""
import json, os, sys, time, urllib.request
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../scripts"))
import jev_client
enf = jev_client.load_enforcer()
cat = enf._jev_catalog(); desc = dict(cat)
state = {"request": "help me fix the failing pytest in the router tests"}
eps = {"cc": ("https://api.commandcode.ai/provider/v1/systemone", "typesafe/jev", os.environ["CMD_API_KEY"]),
       "ts": ("https://api.typesafe.ai/v1/systemone", enf.JEV_MODEL, os.environ["TYPESAFE_API_KEY"])}
def call(url, model, key, qs):
    body = json.dumps({"model": model, "state": state, "questions": qs}).encode()
    req = urllib.request.Request(url, body, {"Authorization": "Bearer " + key, "Content-Type": "application/json", "User-Agent": "skill-concierge"})
    t = time.time(); r = json.load(urllib.request.urlopen(req, timeout=20)); return r, time.time() - t
for run in range(int(sys.argv[1]) if len(sys.argv) > 1 else 3):
    for ep, (url, model, key) in eps.items():
        try:
            w, tw = call(url, model, key, enf._jev_wide_questions(cat))
            sl = [(n, desc[n]) for n in enf._jev_shortlist(w["answers"]) if n in desc]
            r, tr = call(url, model, key, enf._jev_rerank_questions(sl))
            print(f"run{run} {ep}: wide {tw:.2f}s + rerank {tr:.2f}s = {tw+tr:.2f}s (rerank in_tok={r.get('usage',{}).get('input_tokens')})")
        except Exception as e:
            print(f"run{run} {ep}: ERROR {type(e).__name__}: {str(e)[:150]}")
