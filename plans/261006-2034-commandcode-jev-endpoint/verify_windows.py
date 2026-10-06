"""G4: each harness that kills the enforcer early runs it under a Jev budget that ends first, with room left
for the post-join annex queries. Prints KILL-WINDOWS-OK only when all hold."""
import json, os, re
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
src = open(os.path.join(ROOT, "hooks/scripts/enforcer.py")).read()
cap = float(re.search(r'JEV_BUDGET_S = min\(float\(os\.environ\.get\("ENFORCER_JEV_BUDGET", "([\d.]+)"\)\), ([\d.]+)\)', src).group(2))
hooks = json.load(open(os.path.join(ROOT, "hooks/hooks.json")))
enf = [h for g in hooks["hooks"]["UserPromptSubmit"] for h in g["hooks"] if "enforcer.py" in h["command"]]
assert len(enf) == 1 and enf[0]["timeout"] >= cap + 2, (enf, cap)
print(f"claude-code: kill {enf[0]['timeout']} s, budget {cap} s")
for f in ("adapters/commandcode/skill-concierge.mod.ts", "adapters/dsh/skill-concierge.dsh.ts"):
    t = open(os.path.join(ROOT, f)).read()
    m = re.search(r'spawnSync\("python3", \[ENFORCER_SCRIPT\].*?ENFORCER_JEV_BUDGET: "([\d.]+)".*?timeout: (\d+)', t, re.S)
    assert m, f
    budget, kill = float(m.group(1)), int(m.group(2)) / 1000
    assert budget + 0.8 <= kill and budget >= 1.5, (f, budget, kill)    # TypeSafe's 1.5 s per-call timeout must fit
    print(f"{f}: kill {kill} s, budget {budget} s")
for f, kill_re in (("adapters/omp/skill-concierge.ext.ts", r"timeout: (\d[\d_]*), // 10s hard timeout on the user input path"),
                   ("adapters/cline/skill-concierge.cline-hook.cjs", r"runScript\(ENFORCER, \{ prompt, session_id: sid \}, (\d+)\)")):
    kill = int(re.search(kill_re, open(os.path.join(ROOT, f)).read()).group(1).replace("_", "")) / 1000
    assert kill >= cap + 2, (f, kill)
    print(f"{f}: kill {kill} s, budget {cap} s")
print("KILL-WINDOWS-OK")
