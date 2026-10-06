"""Real-size router turns on Command Code ONLY (owner's order 2026-10-06 21:41: no TypeSafe calls without his yes).
Bench = cc:typesafe/jev alone, TYPESAFE_API_KEY removed from this process, live span with the wall-clock cap.
A miss is recorded as a miss; nothing falls through. Keys from env, never printed."""
import importlib.util, json, os, statistics, time
os.environ.pop("TYPESAFE_API_KEY", None)
os.environ["ENFORCER_JEV_BENCH"] = "cc:typesafe/jev"
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
spec = importlib.util.spec_from_file_location("enf_cc", os.path.join(ROOT, "hooks/scripts/enforcer.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
bench = m._jev_bench()
assert [t["ep"] for t in bench] == ["cc"] and m.JEV_CC_TIMEOUT_S == 5.5, bench
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
rows = []
for p in PROMPTS:
    out = m._jev_route(p, "")
    ev = out["event"] or {}
    r = {"prompt": p[:40], "ok": out["result"] is not None, "rmodel": ev.get("rmodel"), "ms": ev.get("ms"),
         "wide_ms": ev.get("wide_ms"), "err": ev.get("err"), "fell": ev.get("fell"), "lead": ev.get("lead")}
    assert r["rmodel"] in (None, "typesafe/jev"), r      # never anything but Command Code
    rows.append(r); print(json.dumps(r), flush=True)
ok = [r for r in rows if r["ok"]]
print(f"\nSUMMARY n={len(rows)}: answered {len(ok)}, missed the 5 s span or errored {len(rows) - len(ok)} "
      f"({[r['fell'] for r in rows if not r['ok']]})")
if ok:
    ms = sorted(r["ms"] for r in ok); w = sorted(r["wide_ms"] for r in ok)
    print(f"answered turn ms: min {ms[0]} median {statistics.median(ms)} max {ms[-1]}; wide call ms: min {w[0]} median {statistics.median(w)} max {w[-1]}")
