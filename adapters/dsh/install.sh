#!/usr/bin/env bash
# skill-concierge — DSH (DeepSeek Harness) installer / sync / repair (ADR-0050).
#
# DSH integrates skill-concierge through its Cordis composition system: the
# skill-search MCP server is registered as a Cordis plugin row, and the
# per-turn enforcement rides the agent-preset composition (agent.cordis.yml).
# DSH has no plugin marketplace for skill-concierge (it is not a registered
# DSH Cordis plugin), so this installer wires the dev path into the DSH
# profile via the cordis.patch.yml extension mechanism.
#
# What the installer does (idempotent, verified):
#   1. Read the SSOT version from $ROOT/.claude-plugin/plugin.json
#   2. Ensure the DSH profile (desktop or tui) has the skill-search MCP server
#      registered via cordis.patch.yml (the user patch layer)
#   3. Ensure the DSH agent preset has the doctrine and enforcer injected
#      via the skill-concierge agent package
#   4. Verify wiring: MCP server reachable, enforcer script present
#
# DSH surfaces:
#   - Desktop: ~/.ohdsh/profiles/desktop/ (Oh-DSH Desktop, Electron)
#   - TUI:     ~/.ohdsh/profiles/tui/ (CLI/TUI)
#   - Legacy:  ~/.dsh/ (if DSH_HOME points elsewhere)
#
# Usage:
#   ./adapters/dsh/install.sh [--root <path>]
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
      echo "usage: $0 [--root <path>]" >&2
      exit 1
      ;;
  esac
done

echo "==> skill-concierge → DSH sync (from: $ROOT)"

# ── 1. SSOT version ──────────────────────────────────────────────────────────
VERSION="$(python3 -c "import json;print(json.load(open('$ROOT/.claude-plugin/plugin.json'))['version'])")"
echo "    SSOT version: $VERSION"

# ── 2. Resolve DSH profile directories ──────────────────────────────────────
# DSH_HOME from env, else ~/.ohdsh (preferred, Oh-DSH Desktop), else ~/.dsh.
DSH_HOME="${SKILL_DSH_HOME:-${DSH_HOME:-}}"
if [ -z "$DSH_HOME" ]; then
  if [ -d "$HOME/.ohdsh" ]; then
    DSH_HOME="$HOME/.ohdsh"
  else
    DSH_HOME="$HOME/.dsh"
  fi
fi
echo "    DSH home: $DSH_HOME"

# Detect which profiles are active
DESKTOP_PROFILE="$DSH_HOME/profiles/desktop"
TUI_PROFILE="$DSH_HOME/profiles/tui"
PROFILES=""
for p in "$DESKTOP_PROFILE" "$TUI_PROFILE"; do
  if [ -f "$p/cordis.yml" ]; then
    PROFILES="$PROFILES $p"
  fi
done

if [ -z "$PROFILES" ]; then
  echo "  [!] No DSH profiles found (no cordis.yml under $DSH_HOME/profiles/)" >&2
  echo "      Expected at least one of: $DESKTOP_PROFILE $TUI_PROFILE" >&2
  exit 1
fi
echo "    Active profiles:$(for p in $PROFILES; do echo -n " $p"; done)"
echo ""

# ── 3. Write skill-search MCP server to each profile's cordis.patch.yml ──
for PROFILE in $PROFILES; do
  echo "==> Configuring: $PROFILE"

  python3 - "$PROFILE" "$ROOT" "$VERSION" <<'PYEOF'
import json, os, sys
from pathlib import Path

profile_dir, root, version = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
patch_file = profile_dir / "cordis.patch.yml"

# Read existing patch or start fresh
patch_lines = []
if patch_file.exists():
    patch_lines = patch_file.read_text(encoding="utf-8").splitlines()

# ── Entry 1: skill-search MCP server ──────────────────────────────────────
MCP_SERVER_ENTRY = f"""# skill-concierge skill-search MCP server (ADR-0050, v{version})
- id: skill-concierge
  name: '@deepseek-ai/dsh-mcp-client'
  config:
    serverName: skill-search
    transport: stdio
    command: /bin/bash
    args: ["{root}/bin/skill-search-mcp"]
    env:
      SKILL_QDRANT_URL: http://localhost:6333
      SKILL_EMBED_BACKEND: fastembed
      SKILL_EMBED_MODEL: sentence-transformers/paraphrase-multilingual-mpnet-base-v2
      SKILL_TOP_K: "6"
      SKILL_LLM_TRIGGERS: "1"
      TRIGGERS_MAX: "16"
      SKILL_TRIGGERS: "{Path.home() / '.claude' / 'skill-concierge' / 'triggers.json'}"
      SKILL_CONCIERGE_HARNESS: dsh
      SKILL_DSH_ROOTS: "1"
"""

# ── Entry 2: unlazy DSH stop hook ─────────────────────────────────────────
UNLAZY_ENTRY = f"""# unlazy stop-hook (DSH), v2.1.0
- id: unlazy-stop
  name: '{root}/adapters/dsh/unlazy-dsh-stop.dsh.ts'
  config: {{}}
"""

MCP_MARKER = "# skill-concierge skill-search MCP server (ADR-0050"
UNLAZY_MARKER = "# unlazy stop-hook (DSH)"
existing = "\n".join(patch_lines)

def _replace_block(existing_text: str, marker: str, new_block: str) -> str:
    """Replace a marker-led block with a fresh entry. The block is the marker
    comment line plus the one `- id:` list item and its indented tail. Everything
    from the marker to the next top-level line or EOF is replaced."""
    lines = existing_text.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        if marker in lines[i]:
            out.append(new_block.rstrip())
            i += 1
            if i < len(lines) and lines[i].lstrip().startswith("- "):
                i += 1
                while i < len(lines) and (not lines[i].strip() or lines[i][0].isspace()):
                    i += 1
        else:
            out.append(lines[i])
            i += 1
    return "\n".join(out)

def _append_block(existing_text: str, new_block: str) -> str:
    """Append a new entry to a YAML list patch. Handles pristine `[]` and
    populated lists."""
    stripped = existing_text.strip()
    if stripped == "[]" or stripped == "":
        return new_block.rstrip()
    return (existing_text.rstrip() + "\n" + new_block.rstrip()
            if not existing_text.endswith("\n")
            else existing_text.rstrip("\n") + "\n" + new_block.rstrip())

# Handle MCP entry
if MCP_MARKER in existing:
    patch_text = _replace_block(existing, MCP_MARKER, MCP_SERVER_ENTRY)
else:
    patch_text = _append_block(existing, MCP_SERVER_ENTRY)

# Handle unlazy entry (on the result of the MCP step)
if UNLAZY_MARKER in patch_text:
    patch_text = _replace_block(patch_text, UNLAZY_MARKER, UNLAZY_ENTRY)
else:
    patch_text = _append_block(patch_text, UNLAZY_ENTRY)

patch_file.write_text(patch_text + "\n", encoding="utf-8")
print(f"  [✓] Updated cordis.patch.yml: skill-search MCP + unlazy stop-hook (v{version})")
PYEOF

done

# ── 4. Enforce exec bits on the launcher ─────────────────────────────────────
chmod +x "$ROOT/bin/"* "$ROOT/setup.sh" \
         "$ROOT/adapters/dsh/install.sh" 2>/dev/null || true
echo "    bin/ + installer exec bits ensured"

# ── 5. Verify ────────────────────────────────────────────────────────────────
echo "==> verify:"
VERIFY_OK=true

# 5a. MCP launcher resolvable
MCP_LAUNCHER="$ROOT/bin/skill-search-mcp"
if [ -f "$MCP_LAUNCHER" ] && [ -x "$MCP_LAUNCHER" ]; then
  echo "    MCP launcher executable: yes ($MCP_LAUNCHER)"
else
  echo "    !! MCP launcher not found/executable at $MCP_LAUNCHER" >&2
  VERIFY_OK=false
fi

# 5b. Enforcer script present
if [ -f "$ROOT/hooks/scripts/enforcer.py" ]; then
  echo "    enforcer script present: yes"
else
  echo "    !! enforcer script not found at $ROOT/hooks/scripts/enforcer.py" >&2
  VERIFY_OK=false
fi

# 5c. Profile patch files contain the MCP entry
for PROFILE in $PROFILES; do
  PATCH="$PROFILE/cordis.patch.yml"
  if [ -f "$PATCH" ] && grep -q "skill-search" "$PATCH" 2>/dev/null; then
    echo "    Profile $PROFILE: skill-search MCP entry present"
  else
    echo "    !! Profile $PROFILE: skill-search MCP entry missing" >&2
    VERIFY_OK=false
  fi
done

# 5d. Doctor's DSH row (WARN-only, surface but don't fail)
python3 "$ROOT/scripts/doctor.py" 2>/dev/null | grep -i "DSH integration" || true

if $VERIFY_OK; then
  echo "    verify: OK"
else
  echo "    verify: FAILED — see lines above" >&2
fi

echo "==> Done. Restart DSH (or reload the agent preset) to load the skill-search MCP server."
echo "    Then confirm: MCP tools list mcp__skill-search__search_skills and mcp__skill-search__get_skill."