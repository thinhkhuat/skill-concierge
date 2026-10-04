import sys, json
sys.path.insert(0, "/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/scripts")
import sieve_recall as S
S.set_iter(1)
srv = S.load_engine()
wide, tier, ask = S.jev_setup()
print("tier", {k: v for k, v in tier.items() if k != "key"}, "chunks", list(wide), [len(q["criteria"]) for q in wide.values()])
case = S.read_jsonl(S.CASES)[0]
state = {"request": case["gen_text"][:4000], "recent_context": "", "skills_already_loaded_this_session": []}
import jev_client
print("batches", len(jev_client.batches(state, wide)))
ans, meta = ask(state, wide, 3.0, tiers=[tier], retries=0)
print({k: v for k, v in meta.items() if k != "per_key_model"})
