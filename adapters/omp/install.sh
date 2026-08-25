#!/usr/bin/env bash
# skill-concierge — Oh My Pi (OMP) installer / synchronizer (ADR-0039).
#
# Idempotently wires skill-concierge into OMP on this machine:
#   (a) If the OMP marketplace plugin skill-concierge@skill-concierge is already
#       installed -> refresh it via the plugin CLI (its manifest's
#       `omp.extensions` entry is what OMP actually loads at startup).
#   (b) Otherwise, dev mode -> idempotently append the repo path to the
#       `extensions:` list in ~/.omp/agent/config.yml so OMP discovers the
#       extension module directly (no plugin round-trip).
#   (c) Verify the wiring landed.
#
# IMPORTANT — MCP: OMP already imports the marketplace plugin's `.mcp.json`
# (the plugin package carries the skill-search MCP server descriptor). We DO
# NOT write ~/.omp/agent/mcp.json here: a duplicate `skill-search` declaration
# at user scope collides with the plugin-provided server and is a known hazard.
# See adapters/omp/mcp.json for the manual user-scope fallback descriptor.
#
# Claude Code and Codex ignore root package.json — this installer is OMP-only.
#
# Usage:
#   ./adapters/omp/install.sh [--root <path>]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --root)
      ROOT="$(cd "$2" && pwd)"
      shift 2
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

echo "==> Installing skill-concierge for OMP from: $ROOT"

OMP_PLUGINS_JSON="$HOME/.omp/plugins/installed_plugins.json"
OMP_CONFIG="$HOME/.omp/agent/config.yml"
# Marker comment (must match the python edit below) so a re-run is idempotent.
EXT_MARKER="# skill-concierge extension entry (ADR-0039)"
EXT_ENTRY="$ROOT/adapters/omp/skill-concierge.ext.ts"

# ── (a) Marketplace plugin installed? refresh it. ──
if [ -f "$OMP_PLUGINS_JSON" ] && grep -q '"skill-concierge@skill-concierge"' "$OMP_PLUGINS_JSON"; then
  echo "  [•] Marketplace plugin skill-concierge@skill-concierge detected -> refreshing via omp CLI"
  omp plugin marketplace update skill-concierge
  omp plugin upgrade skill-concierge@skill-concierge --scope user
  echo "  [✓] OMP plugin refreshed. Package manifest omp.extensions is loaded at next session."
else
  echo "  [•] No marketplace plugin -> dev mode (config.yml extensions entry)"
  if [ ! -f "$EXT_ENTRY" ]; then
    echo "  [!] Error: extension source not found at $EXT_ENTRY" >&2
    exit 1
  fi

  # ── (b) Idempotently append to ~/.omp/agent/config.yml extensions: ──
  # YAML-safe via python3 (no yq). The marker + entry pair is inserted after the
  # existing `extensions:` block (or the key is created at EOF). Re-runs are
  # no-ops: an existing pair or bare entry is left untouched.
  python3 - "$OMP_CONFIG" "$EXT_ENTRY" "$EXT_MARKER" <<'PYEOF'
import sys
from pathlib import Path

config_path, entry, marker = sys.argv[1], sys.argv[2], sys.argv[3]
entry_line = f"- {entry}"
marker_line = f"  {marker}"
indented_entry = f"  {entry_line}"
p = Path(config_path)
lines = p.read_text(encoding="utf-8").splitlines() if p.exists() else []
out = []
found_ext = False
i = 0
while i < len(lines):
    line = lines[i]
    stripped = line.strip()
    if stripped == entry_line:
        # Bare entry (added by hand or another tool): keep as-is, done.
        found_ext = True
        out.append(line)
        i += 1
        continue
    if stripped == marker:
        # Marker line: keep the pair when the entry follows; drop a stale
        # orphan marker alone.
        if i + 1 < len(lines) and lines[i + 1].strip() == entry_line:
            out.append(line)
            out.append(lines[i + 1])
            i += 2
            found_ext = True
        else:
            i += 1
        continue
    out.append(line)
    i += 1

if not found_ext:
    # Ensure an `extensions:` key exists (YAML block list, 2-space indent to
    # match the rest of ~/.omp/agent/config.yml).
    has_key = any(l.strip() == "extensions:" for l in out)
    if not has_key:
        out.append("extensions:")
    # Insert marker + entry after the extensions: block (or at EOF).
    insert_at = len(out)
    for j in range(len(out) - 1, -1, -1):
        if out[j].strip() == "extensions:":
            # Skip trailing blank/indented lines to land inside the block.
            k = j + 1
            while k < len(out) and (not out[k].strip() or out[k][0].isspace()):
                k += 1
            insert_at = k
            break
    out.insert(insert_at, marker_line)
    out.insert(insert_at + 1, indented_entry)

text = "\n".join(out) + "\n"
p.write_text(text, encoding="utf-8")
print("  [✓] Appended extension entry to", config_path)
PYEOF
fi

# ── (c) Verify wiring ──
if [ -f "$OMP_PLUGINS_JSON" ] && grep -q '"skill-concierge@skill-concierge"' "$OMP_PLUGINS_JSON"; then
  if omp plugin list 2>/dev/null | grep -q "skill-concierge"; then
    echo "  [✓] omp plugin list shows skill-concierge"
  else
    echo "  [!] Warning: 'omp plugin list' did not show skill-concierge (still proceeding; verify manually)" >&2
  fi
else
  if [ -f "$OMP_CONFIG" ] && grep -qF "$EXT_ENTRY" "$OMP_CONFIG"; then
    echo "  [✓] ~/.omp/agent/config.yml extensions: contains $EXT_ENTRY"
  else
    echo "  [!] Warning: config check did not confirm the extension entry" >&2
    exit 1
  fi
fi

# ── MCP decision (documented above): intentionally NOT written. ──
echo "  [•] Skipping ~/.omp/agent/mcp.json: OMP imports the plugin .mcp.json; a duplicate skill-search declaration is a known hazard."
chmod +x "$0" 2>/dev/null || true
echo "==> skill-concierge OMP integration installed successfully."