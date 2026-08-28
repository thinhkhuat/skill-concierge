#!/usr/bin/env python3
"""G7 probe — release integrity for the 0.38.0 tier-parity release."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
bad = []

# 1) Four manifests at 0.38.0
for f in [".claude-plugin/plugin.json", ".claude-plugin/marketplace.json",
          ".codex-plugin/plugin.json", "package.json"]:
    text = (ROOT / f).read_text()
    if '"0.38.0"' not in text:
        bad.append(f"{f} not at 0.38.0")

# 2) openwiki quickstart version matches the release
qs = (ROOT / "openwiki/quickstart.md").read_text()
if "- **Version:** `0.38.0`" not in qs:
    bad.append("openwiki/quickstart.md Version line is not 0.38.0")

# 3) driftcheck green (version parity across the surfaces the commit guard enforces)
proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "driftcheck.py"),
                       str(ROOT / "driftcheck.json")],
                      capture_output=True, text=True, cwd=str(ROOT), timeout=120)
if proc.returncode != 0:
    bad.append(f"driftcheck exited {proc.returncode}: {proc.stdout[-400:]}")

if bad:
    print("RELEASE FAIL:")
    for b in bad:
        print("  -", b)
    sys.exit(1)
print("RELEASE OK")
