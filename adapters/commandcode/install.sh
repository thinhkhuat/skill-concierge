#!/usr/bin/env bash
# skill-concierge — Command Code installer / synchronizer (ADR-0038).
#
# Idempotently wires skill-concierge into Command Code (`cmd`) on this machine:
# 1. Installs the Mod adapter into ~/.commandcode/mods/skill-concierge.ts
# 2. Configures SessionStart hooks in ~/.commandcode/settings.json
# 3. Configures extra skills location in ~/.commandcode/settings.json
# 4. Configures skill-search MCP server in ~/.commandcode/mcp.json
# 5. Drops hook events Command Code does not support (UserPromptSubmit, PreCompact) and
#    stale 0.20.8 / doctrine-patch SessionStart entries from ~/.commandcode/settings.json
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
REPO_PROJECT_SLUG="users-thinhkhuat-in-prod-my-workbench-skill-concierge"
LOCAL_PROJECT_DIR="$CMD_DIR/projects/$REPO_PROJECT_SLUG"

# ── 0. Preflight: every JSON file this run rewrites must parse AND have the
# expected shape BEFORE anything is written, so a malformed file stops the run
# with nothing half-configured. A file that parses but is the wrong shape
# (e.g. a JSON array, or "mcpServers": null) would otherwise pass this check,
# then crash a later step after earlier steps already wrote their part.
python3 - "$SETTINGS_FILE" "$MCP_FILE" "$LOCAL_PROJECT_DIR/mcp.json" <<'PY'
import json
import sys
from pathlib import Path

bad = []
for arg in sys.argv[1:]:
    path = Path(arg)
    if not path.exists():
        continue
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        bad.append(f"{path}: {exc}")
        continue
    if not isinstance(data, dict):
        bad.append(f"{path}: top level must be a JSON object, found {type(data).__name__}")
        continue
    if "hooks" in data and not isinstance(data["hooks"], dict):
        bad.append(f"{path}: \"hooks\" must be an object, found {type(data['hooks']).__name__}")
    if "mcpServers" in data and not isinstance(data["mcpServers"], dict):
        bad.append(f"{path}: \"mcpServers\" must be an object, found {type(data['mcpServers']).__name__}")
    if "skills" in data and not isinstance(data["skills"], list):
        bad.append(f"{path}: \"skills\" must be an array, found {type(data['skills']).__name__}")
if bad:
    for line in bad:
        print(f"  [!] Cannot use {line}", file=sys.stderr)
    print("  [!] Nothing was changed. Fix or move the file(s) above, then re-run.", file=sys.stderr)
    sys.exit(1)
PY

MOD_SRC="$ROOT/adapters/commandcode/skill-concierge.mod.ts"
MOD_DST="$MODS_DIR/skill-concierge.ts"

# ── 1-4. Compute every JSON transform in memory first; a failure anywhere in this step
# exits before a single byte is written or the mod is copied. Only once every transform has
# succeeded does the commit phase write each file (atomically, symlink- and mode-safe via
# adapters/lib/safe_write.py) and copy the mod — so a shape wrong enough to pass the
# preflight above but wrong at a NESTED level (e.g. "hooks.SessionStart": null, or an entry
# whose own "hooks" list holds something that is not an object) can no longer crash mid-run
# after earlier steps already wrote their part.
PYTHONPATH="$SCRIPT_DIR/../lib" python3 - "$ROOT" "$SETTINGS_FILE" "$MCP_FILE" "$LOCAL_PROJECT_DIR/mcp.json" "$MOD_SRC" "$MOD_DST" <<'PY'
import json
import os
import sys
from pathlib import Path

import safe_write

root = sys.argv[1]
settings_path = Path(sys.argv[2])
mcp_path = Path(sys.argv[3])
project_mcp_path = Path(sys.argv[4])
mod_src = Path(sys.argv[5])
mod_dst = Path(sys.argv[6])
has_project = project_mcp_path.parent.is_dir()

SERVER_ENV = {
    "SKILL_QDRANT_URL": "http://localhost:6333",
    "SKILL_EMBED_BACKEND": "fastembed",
    "SKILL_EMBED_MODEL": "sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
    "SKILL_TOP_K": "6",
    "SKILL_LLM_TRIGGERS": "1",
    "TRIGGERS_MAX": "16",
    "SKILL_TRIGGERS": str(Path.home() / ".claude/skill-concierge/triggers.json"),
    "SKILL_SERVER_RECORDS": str(Path.home() / ".cache/skill-search/servers"),
}


def load_object(path):
    """An absent file starts empty; an existing one must already be a JSON object — the
    preflight above only checked the TOP level, so a nested surprise still raises here,
    before this function's caller has written anything."""
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f'{path}: top level must be a JSON object, found {type(data).__name__}')
    return data


def with_skill_search_server(data, root):
    servers = data.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        raise ValueError(f'{data!r}: "mcpServers" must be an object, found {type(servers).__name__}')
    servers["skill-search"] = {
        "transport": "stdio",
        "command": f"{root}/bin/skill-search-mcp",
        "env": dict(SERVER_ENV),
    }
    return data


def with_session_start_hooks(settings, root):
    hooks = settings.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError(f'"hooks" must be an object, found {type(hooks).__name__}')

    # Clean up events Command Code does not support. Its hook allowlist is exactly
    # PreToolUse/PostToolUse/Stop/SessionStart; a stray key is reported as
    # `unknown hook event "X" — skipped` and shows up in the TUI as a config issue.
    # UserPromptSubmit is handled by the mod (transformInput), PreCompact has no
    # equivalent at all. Idempotent: both keys are simply absent once removed.
    for unsupported in ("UserPromptSubmit", "PreCompact"):
        hooks.pop(unsupported, None)

    # Filter SessionStart: remove stale 0.20.8 or monkey-patch entries.
    session_start = hooks.get("SessionStart", [])
    if not isinstance(session_start, list):
        raise ValueError('"hooks.SessionStart" must be an array, '
                        f'found {type(session_start).__name__}')
    filtered_start = []
    for entry in session_start:
        if not isinstance(entry, dict):
            raise ValueError('each "hooks.SessionStart" entry must be an object, '
                            f'found {type(entry).__name__}')
        block_hooks = entry.get("hooks", [])
        if not isinstance(block_hooks, list):
            raise ValueError('"hooks.SessionStart[].hooks" must be an array, '
                            f'found {type(block_hooks).__name__}')
        cmd_str = ""
        for h in block_hooks:
            if not isinstance(h, dict):
                raise ValueError('each "hooks.SessionStart[].hooks" entry must be an object, '
                                f'found {type(h).__name__}')
            cmd_str += h.get("command", "") + " "
        if "0.20.8" in cmd_str or "skill-concierge-doctrine-patch" in cmd_str:
            continue
        # remove duplicate skill-concierge entries
        if any(name in cmd_str for name in
               ("hooks/scripts/doctrine.py", "auto_reindex.py", "auto_overrides.py",
                "auto_flywheel.py", "auto_promote.py")):
            continue
        filtered_start.append(entry)

    # Add standard skill-concierge SessionStart hooks pointing to current root.
    sc_scripts = [
        f'python3 "{root}/hooks/scripts/doctrine.py"',
        f'python3 "{root}/hooks/scripts/auto_reindex.py"',
        f'python3 "{root}/hooks/scripts/auto_overrides.py"',
        f'python3 "{root}/hooks/scripts/auto_flywheel.py"',
        f'python3 "{root}/hooks/scripts/auto_promote.py"',
    ]
    for script in sc_scripts:
        filtered_start.append({"hooks": [{"type": "command", "command": script, "timeout": 10}]})
    hooks["SessionStart"] = filtered_start

    # Extra skills locations: ensure root/skills is present.
    skills_list = settings.setdefault("skills", [])
    if not isinstance(skills_list, list):
        raise ValueError(f'"skills" must be an array, found {type(skills_list).__name__}')
    skills_dir = f"{root}/skills"
    if skills_dir not in skills_list:
        skills_list.append(skills_dir)
    return settings


def atomic_write(path, data):
    safe_write.write_text(path, json.dumps(data, indent=2) + "\n")


# ── Compute (nothing written yet) ──
try:
    settings = with_session_start_hooks(load_object(settings_path), root)
    mcp_data = with_skill_search_server(load_object(mcp_path), root)
    project_mcp_data = (with_skill_search_server(load_object(project_mcp_path), root)
                        if has_project else None)
    if not mod_src.is_file():
        raise FileNotFoundError(f"mod source not found at {mod_src}")
    mod_bytes = mod_src.read_bytes()
except Exception as e:
    print(f"  [!] computing the new configuration failed: {e}", file=sys.stderr)
    print("  [!] Nothing was changed. Fix or move the file(s) above, then re-run.", file=sys.stderr)
    sys.exit(1)

# ── Commit (every write below only runs once every computation above succeeded) ──
atomic_write(settings_path, settings)
print("  [✓] Updated settings: SessionStart hooks + extra skills path")
atomic_write(mcp_path, mcp_data)
print("  [✓] Configured user-scope MCP: skill-search")
if project_mcp_data is not None:
    atomic_write(project_mcp_path, project_mcp_data)
    print(f"  [✓] Configured local project-override MCP: {project_mcp_path}")
mod_dst.parent.mkdir(parents=True, exist_ok=True)
mod_dst.write_bytes(mod_bytes)
os.chmod(mod_dst, 0o755)
print(f"  [✓] Installed mod: {mod_dst}")
PY

# ── 5. Verify (ZCode parity: adapters/zcode/install.sh §6) ──────────────────
echo "==> verify:"
python3 - "$ROOT" "$MOD_DST" "$SETTINGS_FILE" "$MCP_FILE" <<'PYEOF'
import json
import sys
from pathlib import Path
root = Path(sys.argv[1])
mod_src = root / "adapters/commandcode/skill-concierge.mod.ts"
mod_dst = Path(sys.argv[2])
settings_path = Path(sys.argv[3])
mcp_path = Path(sys.argv[4])
bad = False
# 5a. Mod present and byte-identical to this checkout's file (the enforcer/ledger
#     scripts drift check in ZCode is manual; here we ensure the shipped
#     mod — the in-generation enforcement organ — matches what we installed).
try:
    if mod_dst.read_text(encoding="utf-8") == mod_src.read_text(encoding="utf-8"):
        print("    mod byte-identical to this checkout's file: yes")
    else:
        print("    !! mod differs from this checkout's file — reinstall or re-run this script", flush=True)
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
    sc_hook_scripts = ("doctrine.py", "auto_reindex.py", "auto_overrides.py",
                       "auto_flywheel.py", "auto_promote.py")
    for block in (settings.get("hooks", {}).get("SessionStart") or []):
        for h in (block.get("hooks") or []):
            c = h.get("command", "")
            # Keyed on the installed hook script paths, not a "skill-concierge" substring
            # in the repo dir name — a root whose path doesn't contain that literal
            # string (e.g. a test fixture) still installs real, working hooks.
            if any(f"hooks/scripts/{name}" in c for name in sc_hook_scripts):
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
    sys.exit(1)
print("    verify: OK")
PYEOF
# Doctor's harness-specific row (WARN-only, so we surface it but don't fail on it).
python3 "$ROOT/scripts/doctor.py" 2>/dev/null | grep -i "Command Code integration" || true
echo "==> Done. Installed mod + SessionStart hooks + MCP wiring verified."
echo "    Restart/Reload Command Code to load the new mod (mod loads at session start)."
echo "    Then confirm: 'cmd mods list' shows skill-concierge with no warnings, and"
echo "    a session's enforcer ledger rows carry harness=commandcode with a session_id."
