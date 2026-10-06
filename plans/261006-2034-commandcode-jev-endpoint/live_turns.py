"""Live router turns on the Command Code-first bench (owner's 5 s design), each paired with a TypeSafe-only
turn on the same prompt for comparison. Keys from env, never printed. One line per turn, summary at the end."""
import importlib.util, json, os, statistics, sys, time
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
PROMPTS = [
    "please fix the failing pytest in the router tests",
    "commit my staged changes with a good conventional commit message",
    "write a Vietnamese government report about flood response in the central provinces",
    "research the latest Claude Code hooks features and summarize them",
    "review this pull request for security problems",
    "make a pitch deck in pptx for our new product launch",
    "why is my docker container running out of memory",
    "plan the migration of our postgres schema to add soft deletes",
    "generate a progress map html page for this project",
    "check whether the skill-concierge index is healthy",
    "turn this csv of sales into a dashboard with charts",
    "explain how the enforcer hook decides which skills to offer",
]
# `_jev_bench` reads ENFORCER_JEV_BENCH at CALL time, so each turn sets the bench it means to test right before
# the call. (The first version set the TypeSafe-only bench once at load, which silently turned every "live" turn
# into a TypeSafe turn.)
LIVE_BENCH = os.environ["ENFORCER_JEV_BENCH"]
TS_BENCH = "ts:jev-1.13.0"
spec = importlib.util.spec_from_file_location("enf_live", os.path.join(ROOT, "hooks/scripts/enforcer.py"))
live = importlib.util.module_from_spec(spec); spec.loader.exec_module(live)
assert live._jev_bench()[0]["ep"] == "cc" and live.JEV_CC_TIMEOUT_S == 5.5 and live.JEV_BUDGET_S == 7.8
ts_only = live

def route(bench, p):
    os.environ["ENFORCER_JEV_BENCH"] = bench
    out = live._jev_route(p, "")
    ev = out["event"] or {}
    assert bench != LIVE_BENCH or ev.get("model") is None or ev.get("tier", 0) > 0 or ev["model"] == "typesafe/jev", ev
    return out
rows = []
for p in PROMPTS:
    a = route(LIVE_BENCH, p)
    b = route(TS_BENCH, p)
    ea, eb = a["event"] or {}, b["event"] or {}
    r = {"prompt": p[:48], "served": ea.get("model") if a["result"] else None, "rmodel": ea.get("rmodel"), "tier": ea.get("tier"),
         "ms": ea.get("ms"), "wide_ms": ea.get("wide_ms"), "fell": ea.get("fell"), "err": ea.get("err"),
         "verdict": a["result"][0] if a["result"] else None, "lead": ea.get("lead"),
         "ts_lead": eb.get("lead"), "ts_ms": eb.get("ms"), "ts_verdict": b["result"][0] if b["result"] else None}
    rows.append(r); print(json.dumps(r), flush=True)
cc = [r for r in rows if r["tier"] == 0]
fellthrough = [r for r in rows if r["fell"] and r["fell"][0][0] == "typesafe/jev"]
lost = [r for r in rows if r["served"] is None]
both = [r for r in rows if r["lead"] and r["ts_lead"]]
print(f"\nSUMMARY n={len(rows)}: served by Command Code {len(cc)}, fell through to TypeSafe {len(fellthrough)} "
      f"({[f[1] for r in fellthrough for f in r['fell'][:1]]}), no Jev verdict {len(lost)}")
if cc: print(f"Command Code-served turn ms: min {min(r['ms'] for r in cc)} median {statistics.median(r['ms'] for r in cc)} max {max(r['ms'] for r in cc)}")
if fellthrough: print(f"fell-through turn ms: min {min(r['ms'] for r in fellthrough)} max {max(r['ms'] for r in fellthrough)}")
print(f"TypeSafe-only turn ms: min {min(r['ts_ms'] for r in rows)} median {statistics.median(r['ts_ms'] for r in rows)} max {max(r['ts_ms'] for r in rows)}")
print(f"same lead skill as TypeSafe-only: {sum(r['lead'] == r['ts_lead'] for r in both)}/{len(both)}; "
      f"same verdict (offer/skip): {sum(r['verdict'] == r['ts_verdict'] for r in rows)}/{len(rows)}")
