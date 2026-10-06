"""Real-size router turn (wide over the whole catalogue, then rerank on its shortlist) via `cmd -p` (stdin JSON,
--output-format json) vs direct HTTPS to the same Command Code endpoint, interleaved. Keys from env, never printed."""
import json, os, subprocess, sys, time, urllib.request
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import jev_client
enf = jev_client.load_enforcer()
cat = enf._jev_catalog(); desc = dict(cat)
URL = "https://api.commandcode.ai/provider/v1/systemone"
def via_cmd(state, qs):
    t = time.time()
    p = subprocess.run(["cmd", "-p", "-m", "typesafe/jev", "--output-format", "json"], input=json.dumps({"state": state, "questions": qs}),
                       capture_output=True, text=True, timeout=60, cwd=os.path.dirname(__file__))
    wall = time.time() - t
    last = [l for l in p.stdout.splitlines() if l.strip()][-1]
    r = json.loads(last)
    assert p.returncode == 0 and r.get("subtype") == "success", (p.returncode, last[:300], p.stderr[:300])
    return r["answers"], wall, r.get("durationMs"), r.get("usage", {}).get("input_tokens")
def via_http(state, qs):
    body = json.dumps({"model": "typesafe/jev", "state": state, "questions": qs}).encode()
    req = urllib.request.Request(URL, body, {"Authorization": "Bearer " + os.environ["CMD_API_KEY"], "Content-Type": "application/json", "User-Agent": "skill-concierge"})
    t = time.time(); r = json.load(urllib.request.urlopen(req, timeout=60)); return r["answers"], time.time() - t, None, r.get("usage", {}).get("input_tokens")
prompts = ["help me fix the failing pytest in the router tests", "make a pitch deck in pptx for our launch", "commit my staged changes"]
for i, pr in enumerate(prompts):
    state = {"request": pr, "recent_context": "", "skills_already_loaded_this_session": []}
    for name, fn in (("cmd", via_cmd), ("http", via_http)):
        try:
            w, tw, dw, tok = fn(state, enf._jev_wide_questions(cat))
            sl = [(n, desc[n]) for n in enf._jev_shortlist(w) if n in desc]
            r, tr, dr, _ = fn(state, enf._jev_rerank_questions(sl))
            lead = r["which"].get("choice")
            extra = f" (cmd-reported durationMs wide {dw}, rerank {dr})" if name == "cmd" else ""
            print(f"turn{i} {name:4}: wide {tw:.2f}s + rerank {tr:.2f}s = {tw+tr:.2f}s, in_tok={tok}, lead={lead}{extra}", flush=True)
        except Exception as e:
            print(f"turn{i} {name:4}: ERROR {type(e).__name__}: {str(e)[:200]}", flush=True)
