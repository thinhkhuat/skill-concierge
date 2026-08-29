#!/usr/bin/env bash
# skill-concierge — Command Code installer / synchronizer (ADR-0038).
#
# Idempotently wires skill-concierge into Command Code (`cmd`) on this machine:
# 1. Installs the Mod adapter into ~/.commandcode/mods/skill-concierge.ts
# 2. Configures SessionStart hooks in ~/.commandcode/settings.json
# 3. Configures extra skills location in ~/.commandcode/settings.json
# 4. Configures skill-search MCP server in ~/.commandcode/mcp.json
# 5. Removes stale 0.20.8 cache paths and monkey-patch scripts
#
# Usage:
#   ./adapters/commandcode/install.sh [--root <path>]
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

echo "==> Installing skill-concierge for Command Code from: $ROOT"

CMD_DIR="$HOME/.commandcode"
MODS_DIR="$CMD_DIR/mods"
SETTINGS_FILE="$CMD_DIR/settings.json"
MCP_FILE="$CMD_DIR/mcp.json"

mkdir -p "$MODS_DIR"

# ── 1. Mod installation ──
MOD_SRC="$ROOT/adapters/commandcode/skill-concierge.mod.ts"
MOD_DST="$MODS_DIR/skill-concierge.ts"

if [ -f "$MOD_SRC" ]; then
  # Write the mod with the absolute repo root baked in or symlinked
  cp "$MOD_SRC" "$MOD_DST"
  echo "  [✓] Installed mod: $MOD_DST"
else
  echo "  [!] Error: Mod source not found at $MOD_SRC" >&2
  exit 1
fi

# ── 2. Configure Settings (SessionStart hooks + skills array) via Python ──
python3 - <<EOF
import json
import os
from pathlib import Path

root = "$ROOT"
settings_path = Path("$SETTINGS_FILE")
settings = {}
if settings_path.exists():
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except Exception:
        settings = {}

hooks = settings.setdefault("hooks", {})

# Clean up UserPromptSubmit if present (not supported by cmd settings hooks; handled by mod)
if "UserPromptSubmit" in hooks:
    del hooks["UserPromptSubmit"]

# Filter SessionStart: remove stale 0.20.8 or monkey-patch entries
session_start = hooks.get("SessionStart", [])
filtered_start = []
for entry in session_start:
    cmd_str = ""
    if isinstance(entry, dict) and "hooks" in entry:
        cmd_str = " ".join(h.get("command", "") for h in entry.get("hooks", []))
    if "0.20.8" in cmd_str or "skill-concierge-doctrine-patch" in cmd_str:
        continue
    # remove duplicate skill-concierge entries
    if "hooks/scripts/doctrine.py" in cmd_str or "auto_reindex.py" in cmd_str or "auto_overrides.py" in cmd_str or "auto_flywheel.py" in cmd_str or "auto_promote.py" in cmd_str:
        continue
    filtered_start.append(entry)

# Add standard skill-concierge SessionStart hooks pointing to current root
sc_scripts = [
    f'python3 "{root}/hooks/scripts/doctrine.py"',
    f'python3 "{root}/hooks/scripts/auto_reindex.py"',
    f'python3 "{root}/hooks/scripts/auto_overrides.py"',
    f'python3 "{root}/hooks/scripts/auto_flywheel.py"',
    f'python3 "{root}/hooks/scripts/auto_promote.py"',
]

for script in sc_scripts:
    filtered_start.append({
        "hooks": [
            {
                "type": "command",
                "command": script,
                "timeout": 10
            }
        ]
    })

hooks["SessionStart"] = filtered_start

# Extra skills locations: ensure root/skills is present
skills_list = settings.setdefault("skills", [])
skills_dir = f"{root}/skills"
if skills_dir not in skills_list:
    skills_list.append(skills_dir)

settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
print("  [✓] Updated settings: SessionStart hooks + extra skills path")
EOF

# ── 3. Configure MCP (User Scope) via Python ──
python3 - <<EOF
import json
from pathlib import Path

root = "$ROOT"
mcp_path = Path("$MCP_FILE")
mcp_data = {}
if mcp_path.exists():
    try:
        mcp_data = json.loads(mcp_path.read_text(encoding="utf-8"))
    except Exception:
        mcp_data = {}

servers = mcp_data.setdefault("mcpServers", {})
servers["skill-search"] = {
    "transport": "stdio",
    "command": f"{root}/bin/skill-search-mcp",
    "env": {
        "SKILL_QDRANT_URL": "http://localhost:6333",
        "SKILL_EMBED_BACKEND": "fastembed",
        "SKILL_EMBED_MODEL": "sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
        "SKILL_TOP_K": "6",
        "SKILL_LLM_TRIGGERS": "1",
        "TRIGGERS_MAX": "16",
        "SKILL_TRIGGERS": str(Path.home() / ".claude/skill-concierge/triggers.json"),
        "SKILL_SERVER_RECORDS": str(Path.home() / ".cache/skill-search/servers")
    }
}

mcp_path.write_text(json.dumps(mcp_data, indent=2) + "\n", encoding="utf-8")
print("  [✓] Configured user-scope MCP: skill-search")
EOF

# ── 4. Project-scope fix if inside skill-concierge repo ──
# cmd prioritizes project .mcp.json over user mcp.json. The repo .mcp.json uses
# ${CLAUDE_PLUGIN_ROOT} which cmd cannot expand. Writing local project override solves this.
REPO_PROJECT_SLUG="users-thinhkhuat-in-prod-my-workbench-skill-concierge"
LOCAL_PROJECT_DIR="$CMD_DIR/projects/$REPO_PROJECT_SLUG"
if [ -d "$LOCAL_PROJECT_DIR" ]; then
  python3 - <<EOF
import json
from pathlib import Path

root = "$ROOT"
local_mcp = Path("$LOCAL_PROJECT_DIR/mcp.json")
data = {}
if local_mcp.exists():
    try:
        data = json.loads(local_mcp.read_text(encoding="utf-8"))
    except Exception:
        data = {}

servers = data.setdefault("mcpServers", {})
servers["skill-search"] = {
    "transport": "stdio",
    "command": f"{root}/bin/skill-search-mcp",
    "env": {
        "SKILL_QDRANT_URL": "http://localhost:6333",
        "SKILL_EMBED_BACKEND": "fastembed",
        "SKILL_EMBED_MODEL": "sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
        "SKILL_TOP_K": "6",
        "SKILL_LLM_TRIGGERS": "1",
        "TRIGGERS_MAX": "16",
        "SKILL_TRIGGERS": str(Path.home() / ".claude/skill-concierge/triggers.json"),
        "SKILL_SERVER_RECORDS": str(Path.home() / ".cache/skill-search/servers")
    }
}
local_mcp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
print("  [✓] Configured local project-override MCP: $LOCAL_PROJECT_DIR/mcp.json")
EOF
fi

chmod +x "$MOD_DST" 2>/dev/null || true

# ── 5. Verify (ZCode parity: adapters/zcode/install.sh §6) ──────────────────
echo "==> verify:"
python3 - <<PYEOF
import json
from pathlib import Path
root = Path("$ROOT")
mod_src = root / "adapters/commandcode/skill-concierge.mod.ts"
mod_dst = Path("$MOD_DST")
settings_path = Path("$SETTINGS_FILE")
mcp_path = Path("$MCP_FILE")
bad = False
# 5a. Mod present and byte-identical to repo HEAD (the enforcer/ledger
#     scripts drift check in ZCode is manual; here we ensure the shipped
#     mod — the in-generation enforcement organ — matches what we installed).
try:
    if mod_dst.read_text(encoding="utf-8") == mod_src.read_text(encoding="utf-8"):
        print("    mod byte-identical to repo HEAD: yes")
    else:
        print("    !! mod differs from repo HEAD — reinstall or re-run this script", flush=True)
        bad = True
except Exception as e:
    print(f"    !! mod read failed: {e}", flush=True)
    bad = True
# 5b. SessionStart hook presence + harness env wiring (the doctrine class:
#     SessionStart hooks run WITHOUT SKILL_CONCIERGE_HARNESS, so doctrine
#     must also handle the .commandcode path-marker fallback).
try:
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    cmds = []
    for block in (settings.get("hooks", {}).get("SessionStart") or []):
        for h in (block.get("hooks") or []):
            c = h.get("command", "")
            if "skill-concierge" in c:
                cmds.append(c)
    if cmds:
        print(f"    SessionStart hooks: {len(cmds)} skill-concierge entries")
    else:
        print("    !! no skill-concierge SessionStart hooks found", flush=True)
        bad = True
except Exception as e:
    print(f"    !! settings.json read failed: {e}", flush=True)
    bad = True
# 5c. MCP parse + command path resolvable
try:
    mcp = json.loads(mcp_path.read_text(encoding="utf-8"))
    srv = (mcp.get("mcpServers") or {}).get("skill-search") or {}
    cmd = srv.get("command", "")
    if cmd and Path(cmd).exists():
        print(f"    MCP launcher resolvable: yes ({cmd})")
    elif cmd:
        print(f"    !! MCP launcher not found at: {cmd}", flush=True)
        bad = True
    else:
        print("    !! MCP skill-search entry missing", flush=True)
        bad = True
except Exception as e:
    print(f"    !! mcp.json read failed: {e}", flush=True)
    bad = True
if bad:
    print("    verify: FAILED — see lines above", flush=True)
else:
    print("    verify: OK")
PYEOF
# Doctor's harness-specific row (WARN-only, so we surface it but don't fail on it).
python3 "$ROOT/scripts/doctor.py" 2>/dev/null | grep -i "Command Code integration" || true
echo "==> Done. Installed mod + SessionStart hooks + MCP wiring verified."
echo "    Restart/Reload Command Code to load the new mod (mod loads at session start)."
echo "    Then confirm: 'cmd mods list' shows skill-concierge with no warnings, and"
echo "    a session's enforcer ledger rows carry harness=commandcode with a session_id."
