#!/usr/bin/env python3
"""Gate verifier for the audit-arc closeout chunk."""
import sys
from pathlib import Path

WORKBENCH = Path("/Users/thinhkhuat/in-PROD/MY-WORKBENCH")
REPORTS = WORKBENCH / "skill-concierge/plans/reports"


def die(msg):
    sys.exit(f"VERIFY-FAILED: {msg}")


def read(path):
    p = Path(path)
    if not p.is_file():
        die(f"missing file {p}")
    t = p.read_text(errors="replace")
    if not t.strip():
        die(f"empty file {p}")
    return t


def g1():
    handoffs = sorted((WORKBENCH / ".handoff").glob("handoff-2026-09-01-*harness*.md"))
    if not handoffs:
        die("no matching handoff file found")
    t = read(handoffs[-1])
    for section in ("What was accomplished", "Decisions locked", "Key files", "Running state", "Pick up here"):
        if section.lower() not in t.lower():
            die(f"handoff missing section: {section}")
    for milestone in ("consult", "contradiction", "model", "hygiene", "validator"):
        if milestone.lower() not in t.lower():
            die(f"handoff missing arc milestone mention: {milestone}")
    print(f"HANDOFF-VERIFIED file={handoffs[-1].name}")


def g2():
    t = read(REPORTS / "lane-consolidation-map-260901-0331.md")
    names = ["explore", "goal-scout", "goal-judge", "librarian-cataloger", "researcher",
             "agent-validator", "tk-validator", "vn-validator", "brainstormer", "planner",
             "code-reviewer", "code-simplifier", "coding-level-0", "coding-level-5"]
    missing = [n for n in names if n not in t]
    if missing:
        die(f"decision map missing candidates: {missing}")
    for verdict in ("KEEP", "MERGE", "RETIRE"):
        if verdict not in t:
            die(f"decision map missing verdict vocabulary: {verdict}")
    if "caller" not in t.lower():
        die("decision map lacks caller evidence section")
    print("DECISION-MAP-VERIFIED")


def g3():
    s = read(REPORTS / "audit-260831-0339-harness-instruction-prose.md")
    if "lane-consolidation-map-260901-0331" not in s:
        die("synthesis report not updated with map pointer")
    print("CLOSEOUT-RECORDED")


if __name__ == "__main__":
    {"g1": g1, "g2": g2, "g3": g3}[sys.argv[1]]()
