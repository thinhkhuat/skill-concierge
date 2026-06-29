#!/usr/bin/env python3
"""Skill-list parity: AGENTS.md must name the SAME bundled skills that exist on disk.
SSOT = the skills/*/SKILL.md directories. Mirror = the `skills/{...}/SKILL.md` brace list
in AGENTS.md. Stdlib-only. Exit 0 = parity, 1 = drift. drift-guard command_check.
ROOT override via SKILL_CONCIERGE_ROOT (used by the falsifiability test)."""
import os, re, sys, glob
from pathlib import Path

ROOT = Path(os.environ.get("SKILL_CONCIERGE_ROOT", Path(__file__).resolve().parent.parent))
BRACE = re.compile(r"skills/\{([^}]+)\}/SKILL\.md")

disk = {Path(p).parent.name for p in glob.glob(str(ROOT / "skills" / "*" / "SKILL.md"))}
agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
m = BRACE.search(agents)
if not m:
    print("skill-list-parity: could not find the `skills/{...}/SKILL.md` list in AGENTS.md")
    sys.exit(1)
claimed = {s.strip() for s in m.group(1).split(",") if s.strip()}
missing = disk - claimed   # on disk but not named in AGENTS.md
extra = claimed - disk     # named in AGENTS.md but absent on disk
if missing or extra:
    print(f"skill-list-parity DRIFT: disk={sorted(disk)} AGENTS={sorted(claimed)}")
    if missing: print(f"  AGENTS.md missing: {sorted(missing)}")
    if extra:   print(f"  AGENTS.md names absent on disk: {sorted(extra)}")
    sys.exit(1)
print(f"skill-list-parity OK: AGENTS.md names the {len(disk)} on-disk skills {sorted(disk)}")
sys.exit(0)
