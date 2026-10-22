#!/usr/bin/env python3
"""Gate oracles for the 0.72.0 verification + issue sweep. Prints PASS:<token> on success."""
import json, subprocess, sys, os, urllib.request

ROOT = "/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge"
VENV = "/Users/thinhkhuat/.claude/skill-concierge/venv/bin/python3"

def fail(msg):
    print(f"FAIL: {msg}")
    raise SystemExit(1)

def doctor_rows():
    r = subprocess.run([VENV, "scripts/doctor.py"], cwd=ROOT, capture_output=True, text=True, timeout=900)
    return r.stdout

def cmd_doctor(label):
    for ln in doctor_rows().splitlines():
        if f"] {label}" in ln:
            print(ln.strip())
            if ln.strip().startswith("[✓]"):
                print(f"PASS:doctor:{label}")
                return
            fail(f"doctor row not green: {ln.strip()}")
    fail(f"row {label!r} not found")

def cmd_live():
    inst = json.load(open("/Users/thinhkhuat/.claude/plugins/installed_plugins.json"))
    row = (inst.get("plugins") or inst)["skill-concierge@skill-concierge"][0]
    if row["version"] != "0.72.0":
        fail(f"installed version {row['version']}")
    if not row["gitCommitSha"].startswith("1245851"):
        fail(f"commit {row['gitCommitSha']}")
    p = json.load(open(f"{row['installPath']}/.claude-plugin/plugin.json"))
    if p["version"] != "0.72.0":
        fail(f"cache plugin.json {p['version']}")
    with urllib.request.urlopen("http://127.0.0.1:6363/health", timeout=5) as r:
        h = json.loads(r.read())
    if h.get("model") != "embeddinggemma-2:270m":
        fail(f"owner model {h.get('model')}")
    if h.get("dim") != 768:
        fail(f"owner dim {h.get('dim')}")
    script = (
        "import sys,json; sys.path.insert(0, %r)\n"
        "from skill_search import server as S\n"
        "d=json.loads(S.search_skills('review this code for security vulnerabilities'))\n"
        "print(json.dumps([{'n':r['name'],'s':round(r['score'],3)} for r in d['results'][:3]]))\n"
        % f"{ROOT}/vendor/skill-search")
    e = subprocess.run([VENV, "scripts/engine_env.py", "--root", ROOT, "--exec", VENV, "-c", script],
                       cwd=ROOT, capture_output=True, text=True, timeout=300)
    line = [l for l in e.stdout.splitlines() if l.strip().startswith("[")]
    if not line:
        fail(f"no search results\n{e.stdout}\n{e.stderr}")
    hits = json.loads(line[-1])
    if len(hits) < 3:
        fail(f"only {len(hits)} hits")
    print(f"  plugin=0.72.0 commit=1245851 owner={h['model']} dim={h['dim']} top3={hits}")
    print("PASS:live")

def cmd_smoke_commandcode():
    """The smoke's own verdict is the oracle: it checks the run's ledger for BOTH an offer
    row and a search row. An earlier version of this gate scraped `evidence kept:`, which
    the smoke prints only on failure -- so a real PASS looked like zero rows. Fix the check,
    not the system."""
    e = subprocess.run([VENV, "scripts/smoke.py", "--advisory", "codex,dsh,commandcode,zcode", "commandcode"],
                       cwd=ROOT, capture_output=True, text=True, timeout=900)
    out = e.stdout + e.stderr
    row = [l.strip() for l in out.splitlines() if "commandcode" in l and ("PASS" in l or "FAIL" in l)]
    if not row:
        fail(f"no commandcode verdict row in smoke output\n{out[-800:]}")
    verdict = row[-1]
    print("  " + verdict)
    if "PASS" not in verdict:
        fail(f"commandcode smoke did not pass: {verdict}")
    if "offer + search" not in verdict:
        fail(f"commandcode verdict lacks 'offer + search': {verdict}")
    print("PASS:smoke-commandcode")

cmd = sys.argv[1]
if cmd == "doctor":
    cmd_doctor(sys.argv[2])
elif cmd == "live":
    cmd_live()
elif cmd == "smoke-commandcode":
    cmd_smoke_commandcode()
else:
    fail(f"unknown check {cmd!r}")
