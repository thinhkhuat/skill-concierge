"""G4 oracle: release 0.63.0 with ADR-0086, and no Cline file still claims ADR-0085 or 0.62.0."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
bad = []
for f in (".claude-plugin/plugin.json", ".codex-plugin/plugin.json", "package.json"):
    if json.loads((ROOT / f).read_text())["version"] != "0.63.0":
        bad.append(f"{f} version is not 0.63.0")
if not (ROOT / "docs/adr/0086-cline-native-plugin-and-agent-plugin.md").is_file():
    bad.append("ADR-0086 missing")
if not re.search(r"^## \[0\.63\.0\]", (ROOT / "CHANGELOG.md").read_text(), re.M):
    bad.append("CHANGELOG has no [0.63.0] section")
if len(list((ROOT / "docs/adr").glob("0085-*.md"))) != 1:
    bad.append("more than one ADR-0085 file")
for f in sorted((ROOT / "adapters/cline").rglob("*")):
    if f.is_file() and f.suffix in (".ts", ".cjs", ".sh", ".py", ".json"):
        text = f.read_text(errors="replace")
        if re.search(r"ADR-0085|0\.62\.0", text):
            bad.append(f"{f.relative_to(ROOT)} mentions ADR-0085 or 0.62.0")
for line in bad:
    print("FAIL:", line)
if bad:
    sys.exit(1)
print("release 0.63.0 + ADR-0086 consistent")
