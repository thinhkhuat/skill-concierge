#!/usr/bin/env python3
"""Doc parity: CLAUDE.md (adapter) must name the SAME tool-state/scratch dirs as AGENTS.md (SSOT).
Stdlib-only. Exit 0 = parity, 1 = drift. Used as a drift-guard command_check."""
import re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOKEN = re.compile(r"`([^`]+/)`")          # backticked path-like tokens (end in /)

def scratch_line(text, *needles):
    for ln in text.splitlines():
        low = ln.lower()
        if all(n in low for n in needles):
            return set(TOKEN.findall(ln))
    return set()

agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
claude = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
ssot = scratch_line(agents, "tool state", "scratch")          # AGENTS canonical line
copy = scratch_line(claude, "tool state")                      # CLAUDE adapter line
if not ssot:
    print("doc-parity: could not locate the scratch line in AGENTS.md (SSOT)"); sys.exit(1)
missing = ssot - copy
extra = copy - ssot
if missing or extra:
    print(f"doc-parity DRIFT: AGENTS.md scratch set={sorted(ssot)} but CLAUDE.md={sorted(copy)}")
    if missing: print(f"  CLAUDE.md missing: {sorted(missing)}")
    if extra:   print(f"  CLAUDE.md extra:   {sorted(extra)}")
    sys.exit(1)
print(f"doc-parity OK: CLAUDE.md names the same scratch dirs as AGENTS.md {sorted(ssot)}")
sys.exit(0)
