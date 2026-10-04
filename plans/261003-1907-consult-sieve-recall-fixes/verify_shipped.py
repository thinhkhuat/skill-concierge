"""G5 oracle: the proven J20 widening is live, not merely committed. Prints the marker only when
every check holds; exits 1 naming the first failed check."""
import json, os, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def fail(why):
    print(f"NOT SHIPPED: {why}")
    sys.exit(1)


def run(*cmd, **kw):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=900, **kw)


fit = (ROOT / "scripts/consult_fit.py").read_text()
if "SKILL_CONSULT_JEV_WIDEN" not in fit:
    fail("scripts/consult_fit.py has no SKILL_CONSULT_JEV_WIDEN switch")
r = run(sys.executable, "scripts/consult_fit.py", "widen", "--selftest")
if r.returncode or "WIDEN-SELFTEST-OK" not in r.stdout:
    fail(f"widen selftest: {r.stdout[-300:]}{r.stderr[-300:]}")
if "consult_fit.py widen" not in (ROOT / "skills/consult/SKILL.md").read_text():
    fail("skills/consult/SKILL.md does not call `consult_fit.py widen`")
ver = json.loads((ROOT / ".claude-plugin/plugin.json").read_text())["version"]
if ver in ("0.57.1", "0.57.0"):
    fail(f"no new release (plugin.json still {ver})")
top = re.search(r"^## \[([0-9.]+)\]", (ROOT / "CHANGELOG.md").read_text(), re.M)
if not top or top.group(1) != ver:
    fail("CHANGELOG top release does not match plugin.json")
if run("python3", "scripts/driftcheck.py", "driftcheck.json").returncode:
    fail("driftcheck not in sync")
t = run(sys.executable, "-m", "pytest", "tests/", "-q", "-p", "no:randomly")
if t.returncode:
    fail("test suite: " + t.stdout.strip().splitlines()[-1])
if run("git", "status", "--porcelain", "--untracked-files=no").stdout.strip():
    fail("uncommitted tracked changes")
run("git", "fetch", "-q", "origin")
if run("git", "rev-parse", "HEAD").stdout != run("git", "rev-parse", "origin/main").stdout:
    fail("HEAD is not pushed to origin/main")
reg = json.loads((Path.home() / ".claude/plugins/installed_plugins.json").read_text())
installed = [e.get("version") for k, v in reg.get("plugins", {}).items() if k.startswith("skill-concierge@")
             for e in (v if isinstance(v, list) else [v])]
if ver not in installed:
    fail(f"Claude Code has {installed}, not {ver}")
print("J20-SHIPPED-AND-LIVE")
