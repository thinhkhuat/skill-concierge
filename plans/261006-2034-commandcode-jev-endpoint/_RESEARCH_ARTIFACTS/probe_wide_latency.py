"""Time real-size wide calls (whole invocable catalogue) on Command Code vs TypeSafe direct. Keys from env, never printed."""
import json, os, sys, time, urllib.request
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../scripts"))
import jev_client
enf = jev_client.load_enforcer()
cat = enf._jev_catalog()
qs = enf._jev_wide_questions(cat)
state = {"request": "help me fix the failing pytest in the router tests"}
eps = {"cc": ("https://api.commandcode.ai/provider/v1/systemone", "typesafe/jev", os.environ["CMD_API_KEY"]),
       "ts": ("https://api.typesafe.ai/v1/systemone", enf.JEV_MODEL, os.environ["TYPESAFE_API_KEY"])}
print(f"catalogue {len(cat)} skills, {len(qs)} wide chunks")
for run in range(int(sys.argv[1]) if len(sys.argv) > 1 else 3):
    for ep, (url, model, key) in eps.items():
        body = json.dumps({"model": model, "state": state, "questions": qs}).encode()
        req = urllib.request.Request(url, body, {"Authorization": "Bearer " + key, "Content-Type": "application/json", "User-Agent": "skill-concierge"})
        t = time.time()
        try:
            r = json.load(urllib.request.urlopen(req, timeout=15))
            top = [sorted(a["probabilities"], key=lambda n: -a["probabilities"][n])[:3] for a in r["answers"].values()]
            print(f"run{run} {ep}: {time.time()-t:.2f}s model={r.get('model')} in_tok={r.get('usage',{}).get('input_tokens')} top={top}")
        except Exception as e:
            print(f"run{run} {ep}: {time.time()-t:.2f}s ERROR {type(e).__name__}: {str(e)[:150]}")
