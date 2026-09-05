#!/usr/bin/env python3
"""Independent gate verifier for the harness instruction-prose audit.

Each subcommand runs its own assertions against the artifacts on disk and
prints a success-only marker only after every assertion passes. Any failure
exits non-zero with VERIFY-FAILED and a reason."""
import json
import re
import sys
from pathlib import Path

HOME = Path("/Users/thinhkhuat")
REPORTS = Path("/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/plans/reports")
SETTINGS = HOME / ".claude" / "settings.json"
SKILLS = HOME / ".claude" / "skills"


def die(msg):
    sys.exit(f"VERIFY-FAILED: {msg}")


def read(path):
    p = Path(path)
    if not p.is_file():
        die(f"missing file {p}")
    text = p.read_text(errors="replace")
    if not text.strip():
        die(f"empty file {p}")
    return text


def g1():
    report = read(REPORTS / "hooks-audit-260831-0339-instruction-audit.txt")
    hooks = json.loads(SETTINGS.read_text()).get("hooks", {})
    scripts = set()
    for entries in hooks.values():
        for entry in entries:
            for m in re.findall(r"[\w./-]+\.(?:py|mjs|js|sh|ts)", entry.get("command", "")):
                scripts.add(Path(m).name)
    missing = sorted(s for s in scripts if s not in report)
    if missing:
        die(f"hook scripts absent from report: {missing}")
    print(f"HOOKS-REPORT-VERIFIED events={len(hooks)} distinct-scripts={len(scripts)}")


def g2():
    analyzer = read(REPORTS / "skill-analyzer-260831-0339-instruction-audit.md")
    read(REPORTS / "skill-cleaner-260831-0339-instruction-audit.txt")
    count = len(list(SKILLS.glob("*/SKILL.md")))
    if count < 300:
        die(f"SKILL.md count implausibly low: {count}")
    if "skill" not in analyzer.lower():
        die("analyzer report lacks skill content")
    print(f"SKILLS-CENSUS-VERIFIED skillmd-count={count}")


def g3():
    text = read(REPORTS / "config-prose-260831-0339-instruction-audit.md")
    for token in ("CLAUDE.md", "RULES.md", "rules/", "directional", "finding"):
        if token not in text:
            die(f"config-prose report missing token: {token}")
    print("CONFIG-PROSE-VERIFIED")


def g4():
    text = read(REPORTS / "agents-styles-260831-0339-instruction-audit.md")
    agents = sorted(p.name for p in (HOME / ".claude" / "agents").glob("*.md"))
    styles = sorted(p.name for p in (HOME / ".claude" / "output-styles").glob("*.md"))
    miss_a = [a for a in agents if a not in text]
    miss_s = [s for s in styles if s not in text]
    if miss_a or miss_s:
        die(f"coverage gaps agents={miss_a} styles={miss_s}")
    print(f"AGENTS-STYLES-VERIFIED agents={len(agents)} styles={len(styles)}")


def g5():
    text = read(REPORTS / "contradiction-matrix-260831-0339-instruction-audit.md")
    if "pairs-checked:" not in text:
        die("matrix lacks pairs-checked line")
    n = int(text.split("pairs-checked:")[1].split()[0])
    if n < 40:
        die(f"pairs-checked too low: {n}")
    print(f"CONTRADICTION-MATRIX-VERIFIED pairs-checked={n}")


def g6():
    text = read(REPORTS / "validation-260831-0339-instruction-audit.md")
    if "VERDICT" not in text.upper():
        die("validation report lacks VERDICT")
    print("VALIDATION-VERIFIED")


def g7():
    text = read(REPORTS / "audit-260831-0339-harness-instruction-prose.md")
    for section in ("Hooks", "Skills", "Config prose", "Agents", "Contradiction", "Unresolved questions"):
        if section.lower() not in text.lower():
            die(f"final report missing section: {section}")
    print("FINAL-REPORT-VERIFIED")


if __name__ == "__main__":
    dispatch = {"g1": g1, "g2": g2, "g3": g3, "g4": g4, "g5": g5, "g6": g6, "g7": g7}
    dispatch[sys.argv[1]]()
