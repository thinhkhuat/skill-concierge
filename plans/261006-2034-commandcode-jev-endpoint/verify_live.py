"""G2: real calls on the live bench (keys from env, never printed). Prints CC-LIVE-VERIFIED only when all pass:
1. the `cc` tier alone answers through jev_client (the offline path);
2. one full router turn on the live bench answers (whichever tier serves it);
3. with Command Code's span forced to 0.3 s, the same turn times out there and finishes on TypeSafe."""
import importlib.util, os, sys, time
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import jev_client

def fresh(**env):
    os.environ.update(env)
    spec = importlib.util.spec_from_file_location(f"enf_{time.time_ns()}", os.path.join(ROOT, "hooks/scripts/enforcer.py"))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

assert os.environ.get("CMD_API_KEY") and os.environ["ENFORCER_JEV_BENCH"].split()[0] == "cc:typesafe/jev", "env not loaded"
enf = fresh()
cc = enf._jev_bench()[0]
assert cc["ep"] == "cc", cc
ans, meta = jev_client.ask({"ticket": "Payments failed for three days."},
                           {"urgent": {"type": "noul", "instructions": "Does this need urgent attention?"}},
                           timeout=15.0, tiers=[cc], retries=0)
assert 0.0 <= ans["urgent"]["noul"] <= 1.0 and meta["model"] == ["typesafe/jev"], (ans, meta)
print(f"1 cc-alone: noul={ans['urgent']['noul']} ms={meta['ms']} model={meta['model']}")

prompt = "please fix the failing pytest in the router tests"
out = enf._jev_route(prompt, "")
ev = out["event"]
assert out["result"] is not None, ev
print(f"2 live-bench turn: served by tier {ev['tier']} ({ev['model']}) in {ev['ms']} ms, fell={ev.get('fell')}, lead={ev['lead']}")

enf2 = fresh(ENFORCER_JEV_CC_TIMEOUT="0.3")
out2 = enf2._jev_route(prompt, "")
ev2 = out2["event"]
assert out2["result"] is not None and ev2["model"] == "jev-1.13.0" and ev2["tier"] == 1, ev2
assert ev2["fell"][0][0] == "typesafe/jev" and ev2["fell"][0][1] in ("TimeoutError", "URLError"), ev2
assert ev2["ms"] <= enf2.JEV_BUDGET_S * 1000, ev2
print(f"3 forced cc timeout: fell={ev2['fell']}, served by TypeSafe in {ev2['ms']} ms (budget {enf2.JEV_BUDGET_S} s)")
print("CC-LIVE-VERIFIED")
