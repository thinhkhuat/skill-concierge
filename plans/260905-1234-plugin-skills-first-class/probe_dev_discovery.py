#!/usr/bin/env python3
"""G6: dev-engine discovery probe over the LIVE machine.

Runs the DEV vendored engine's discovery (union enablement + root-relative scan)
against this machine's real manifests and asserts the fix set:

  - agent-skills:* rows ARE discovered (project-re-enable union, the v0.45.0 fix)
  - zero examples:* phantom rows (root-relative scan)
  - zero temp_git_* rows (root-relative scan)
  - ponytail:* still discovered (machine-global index semantics — the SESSION gate,
    not the index, subtracts it)

Run: /Users/thinhkhuat/.claude/skill-concierge/venv/bin/python probe_dev_discovery.py
Exit 0 + GATE6-OK on success; prints GATE6-FAIL:<reason> otherwise.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "vendor" / "skill-search"))
from skill_search import skills_discovery as sd  # noqa: E402

names = set()
paths = sd.discover_skill_paths()
claude_cache_hits = [p for p in paths if "/.claude/plugins/cache/" in str(p)]
for p in claude_cache_hits:
    sk = sd.parse_skill(p)
    if sk and sk["name"]:
        names.add(sk["name"])

problems = []
if not any(n.startswith("agent-skills:") for n in names):
    problems.append("no agent-skills:* rows discovered (union enablement not effective)")
if any(n.startswith("examples:") for n in names):
    problems.append("examples:* phantom rows still discovered")
if any("temp_git_" in str(p) for p in claude_cache_hits):
    problems.append("temp_git_* clone paths still discovered")
if not any(n.startswith("ponytail:") for n in names):
    problems.append("ponytail:* missing (union semantics require it indexed)")

if problems:
    for pr in problems:
        print("GATE6-FAIL:" + pr)
    print(f"context: {len(claude_cache_hits)} claude-cache paths discovered")
    sys.exit(1)

print(f"agent-skills rows: {sorted(n for n in names if n.startswith('agent-skills:'))}")
print(f"ponytail rows: {sorted(n for n in names if n.startswith('ponytail:'))}")
print(f"total claude-cache plugin names discovered: {len(names)}")
print("GATE6-OK")
