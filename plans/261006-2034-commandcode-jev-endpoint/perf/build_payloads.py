"""Write real-size Command Code request bodies with the router's own builders: one wide request (all chunks),
the same chunks as separate requests, and a rerank request built from one Command Code wide answer. No TypeSafe."""
import json, os, sys, urllib.request
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
os.environ.pop("TYPESAFE_API_KEY", None)
import jev_client
enf = jev_client.load_enforcer()
cat = enf._jev_catalog(); desc = dict(cat)
state = {"request": "plan the migration of our postgres schema to add soft deletes", "recent_context": "",
         "skills_already_loaded_this_session": []}
wide = enf._jev_wide_questions(cat)
body = lambda qs: {"model": "typesafe/jev", "state": state, "questions": qs}
json.dump(body(wide), open("wide.json", "w"))
for k, q in wide.items():
    json.dump(body({k: q}), open(f"wide-{k.split('::')[1]}.json", "w"))
req = urllib.request.Request("https://api.commandcode.ai/provider/v1/systemone", json.dumps(body(wide)).encode(),
                             {"Authorization": "Bearer " + os.environ["CMD_API_KEY"], "Content-Type": "application/json",
                              "User-Agent": "skill-concierge"})
ans = json.load(urllib.request.urlopen(req, timeout=30))
assert ans["model"] == "typesafe/jev"
sl = [(n, desc[n]) for n in enf._jev_shortlist(ans["answers"]) if n in desc]
json.dump(body(enf._jev_rerank_questions(sl)), open("rerank.json", "w"))
for f in sorted(os.listdir(".")):
    if f.endswith(".json"): print(f, os.path.getsize(f), "bytes")
