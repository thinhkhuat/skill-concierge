"""Is Command Code slower on a repeated identical prompt than on distinct prompts? Router path (enforcer code),
cc tier only, interleaved: same prompt x5 vs distinct prompts x5. Keys from env, never printed."""
import importlib.util, os, time
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
spec = importlib.util.spec_from_file_location("enf", os.path.join(ROOT, "hooks/scripts/enforcer.py"))
os.environ["ENFORCER_JEV_BENCH"] = "cc:typesafe/jev"; os.environ["ENFORCER_JEV_CC_TIMEOUT"] = "6.0"
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
SAME = "rename the variables in utils.py to snake case"
DISTINCT = ["add a dark mode toggle to the settings page", "summarize this youtube video for me",
            "set up pre-commit hooks for this repo", "draft a cold email to a potential investor",
            "find where the auth token is refreshed in this codebase"]
for i in range(5):
    for label, p in (("same", SAME), ("distinct", DISTINCT[i])):
        ev = m._jev_route(p, "")["event"] or {}
        print(f"run{i} {label:8} ms={ev.get('ms')} wide_ms={ev.get('wide_ms')} tier={ev.get('tier')} err={ev.get('err')} fell={ev.get('fell')}", flush=True)
