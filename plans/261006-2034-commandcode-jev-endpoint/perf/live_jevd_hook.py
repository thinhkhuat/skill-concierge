"""Live hook turns through jevd (ADR-0080), Command Code ONLY. TypeSafe is removed from the provider list in this
process (never by timing: a 5.6 s budget once let a turn reach TypeSafe), so it cannot be called.
Arg "down": jevd expected stopped; the hook must fall back to ENFORCER_JEV_BENCH, set here to Command Code alone."""
import importlib.util, os, sys, time
os.environ.pop("TYPESAFE_API_KEY", None)
if sys.argv[1:] == ["down"]:
    os.environ["ENFORCER_JEV_BENCH"] = "cc:typesafe/jev"
ROOT = os.path.expanduser("~/in-PROD/MY-WORKBENCH/skill-concierge")
spec = importlib.util.spec_from_file_location("enf_live", ROOT + "/hooks/scripts/enforcer.py")
enf = importlib.util.module_from_spec(spec); spec.loader.exec_module(enf)
_ladder = enf._jevd_ladder
enf._jevd_ladder = lambda: (lambda t: [x for x in t if x["name"] == "commandcode"] if t else t)(_ladder())
assert all(t.get("name", "cc") == "commandcode" or t["ep"] == "cc" for t in enf._jev_bench()), "TypeSafe in bench"
PROMPTS = ["fix the failing pytest in tests/test_api.py", "commit my staged changes with a good message",
           "research how Claude Code hooks work", "make a pitch deck pptx for the launch",
           "why does docker run out of memory on my mac", "explain how the enforcer hook works"]
for p in PROMPTS[: (2 if sys.argv[1:] == ["down"] else 6)]:
    t0 = time.time()
    out = enf._jev_route(p, "")
    ev = out["event"] or {}
    print(f"{time.time() - t0:5.2f}s via={ev.get('via')} prov={ev.get('prov')} model={ev.get('model')} "
          f"lead={ev.get('lead')} fell={ev.get('fell')} err={ev.get('err')}", flush=True)
