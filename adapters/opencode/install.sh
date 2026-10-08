#!/usr/bin/env bash
# skill-concierge — OpenCode v2 installer / sync / repair (ADR-0085).
#
# OpenCode v2 loads plugins from the `plugins` array in opencode.json(c) (global
# ~/.config/opencode/opencode.json or any project config). This installer:
#   1. Reads the SSOT version from $ROOT/.claude-plugin/plugin.json
#   2. Refuses an uncommitted version change on a git checkout (ADR-0069/0072
#      installer discipline, fail-closed)
#   3. Registers the plugin package path in the GLOBAL opencode.json `plugins`
#      array — idempotent upsert, safe_write (symlink/mode-safe, backed up,
#      refuses a concurrent write, preserves every unrelated key)
#   4. Re-roots the plugin's own skills (skills/*/SKILL.md → plain names) into
#      ~/.config/opencode/skills/ — the DSH/Cline precedent, so the index gets
#      opencode-personal rows the enforcer can offer (content-compared; only
#      THIS installer's previously-managed names are ever pruned — the
#      operator's own skills there are never touched)
#   5. Fires a reindex through scripts/engine_env.py (SKILL_OPENCODE_ROOTS is
#      pinned in .mcp.json) so the opencode-* points land
#   6. Verifies: config parses + carries the entry, skills synced, launcher exec
#
# The MCP server is NOT written anywhere: the plugin itself registers it via
# ctx.mcp.transform (Claude Code's .mcp.json auto-connect parity). A duplicate
# manual `skill-search` declaration is the known hazard this avoids.
#
# After install: `opencode service restart` (plugins load at service start).
#
# Usage:
#   ./adapters/opencode/install.sh [--root <path>]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
# The helpers every installer shares (adapters/lib/sync.sh), found from this file's own location.
# Follow symlinks to this file so a linked installer still finds the lib beside the real one.
_self="${BASH_SOURCE[0]}"
while [ -L "$_self" ]; do
  _link="$(readlink "$_self")"
  case "$_link" in /*) _self="$_link" ;; *) _self="$(dirname "$_self")/$_link" ;; esac
done
SYNC_LIB="$(cd "$(dirname "$_self")/.." && pwd)/lib/sync.sh"
if [ ! -f "$SYNC_LIB" ]; then
  echo "!! $SYNC_LIB is missing: this installer needs the shared helpers in adapters/lib/." >&2
  echo "   Run it from a complete checkout; nothing was changed." >&2
  exit 1
fi
. "$SYNC_LIB"

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

echo "==> skill-concierge → OpenCode v2 sync (from: $ROOT)"

PLUGIN_DIR="$ROOT/adapters/opencode/plugin"
OPENCODE_HOME="${XDG_CONFIG_HOME:-$HOME/.config}/opencode"
OPENCODE_JSON="$OPENCODE_HOME/opencode.json"
SKILLS_HOME="$OPENCODE_HOME/skills"

# ── 1. SSOT version ──────────────────────────────────────────────────────────
VERSION="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["version"])' "$ROOT/.claude-plugin/plugin.json")"
echo "    SSOT version: v$VERSION"

# ── 2. Git-checkout discipline (ADR-0069/0072: fail-closed) ─────────────────
if _is_own_checkout; then
  HEAD_VERSION="$(git -C "$ROOT" show HEAD:.claude-plugin/plugin.json 2>/dev/null \
    | python3 -c 'import json,sys;print(json.load(sys.stdin)["version"])' 2>/dev/null || true)"
  if [ "$HEAD_VERSION" != "$VERSION" ]; then
    echo "!! .claude-plugin/plugin.json says v$VERSION but HEAD carries v${HEAD_VERSION:-none}." >&2
    echo "   Commit the version change (or restore the file), then re-run." >&2
    exit 1
  fi
elif [ -e "$ROOT/git/HEAD" ]; then
  echo "!! $ROOT keeps its git database in git/ (renamed from .git) — rename it back, then re-run." >&2
  exit 1
fi

if [ ! -f "$PLUGIN_DIR/index.ts" ] || [ ! -f "$PLUGIN_DIR/package.json" ]; then
  echo "!! plugin package incomplete at $PLUGIN_DIR (need index.ts + package.json)" >&2
  exit 1
fi

# OpenCode present at all? (no config dir and no binary = nothing to install into)
if [ ! -d "$OPENCODE_HOME" ] && ! command -v opencode >/dev/null 2>&1; then
  echo "!! OpenCode not found: no $OPENCODE_HOME and no opencode binary on PATH." >&2
  echo "   Install OpenCode v2 first (https://opencode.ai/v2/docs/), then re-run." >&2
  exit 1
fi
mkdir -p "$OPENCODE_HOME"

# ── 3. Register the plugin in the global opencode.json ──────────────────────
# Upsert { "package": "<abs plugin dir>" } into plugins[]. Everything else is
# preserved except the plugins array; write_registry backs up beside the file,
# keeps the mode, and refuses a concurrent write (a live service session).
PYTHONPATH="$SCRIPT_DIR/../lib" python3 - "$OPENCODE_JSON" "$PLUGIN_DIR" <<'PY'
import json
import sys

import safe_write

cfg_path, plugin_dir = sys.argv[1], sys.argv[2]


def entry_is_ours(e) -> bool:
    if isinstance(e, str):
        return e == plugin_dir
    return isinstance(e, dict) and e.get("package") == plugin_dir


def upsert(data):
    plugins = data.setdefault("plugins", [])
    if not isinstance(plugins, list):
        raise RuntimeError(f"plugins is {type(plugins).__name__}, not a list — fix {cfg_path} by hand")
    if any(entry_is_ours(e) for e in plugins):
        return
    plugins.append({"package": plugin_dir})


try:
    safe_write.write_registry(cfg_path, upsert, "skill-concierge")
    print(f"    opencode.json plugins += {plugin_dir}")
except FileNotFoundError:
    fresh = {"$schema": "https://opencode.ai/config.json", "plugins": [{"package": plugin_dir}]}
    safe_write.write_text(cfg_path, json.dumps(fresh, indent=2) + "\n")
    print(f"    opencode.json created with the plugin entry ({cfg_path})")
except json.JSONDecodeError as e:
    print(f"!! {cfg_path} is not plain JSON ({e}) — remove JSONC comments first; nothing written",
          file=sys.stderr)
    sys.exit(1)
PY

# ── 4. Re-root the plugin's own skills (DSH/Cline precedent) ────────────────
PYTHONPATH="$SCRIPT_DIR/../lib" python3 - "$ROOT" "$SKILLS_HOME" <<'PY'
import json
import shutil
import sys
from pathlib import Path

import safe_write

repo, dest = Path(sys.argv[1]), Path(sys.argv[2])
src = repo / "skills"
if not src.is_dir():
    print("!! no skills/ dir in the repo — skipping the skills re-root", file=sys.stderr)
    sys.exit(0)

want = {}
for d in sorted(src.iterdir()):
    md = d / "SKILL.md"
    if d.is_dir() and md.is_file():
        want[d.name] = md.read_text(encoding="utf-8")

dest.mkdir(parents=True, exist_ok=True)
marker = dest / ".skill-concierge-managed.json"
try:
    managed = set(json.loads(marker.read_text(encoding="utf-8")).get("names", []))
except (OSError, ValueError):
    managed = set()

added = kept = removed = 0
for name, body in want.items():
    cur = dest / name / "SKILL.md"
    existed = cur.is_file()
    if existed and cur.read_text(encoding="utf-8") == body:
        kept += 1
    else:
        safe_write.write_text(cur, body)
        if not existed:
            added += 1
    managed.add(name)
for name in sorted(managed - set(want)):
    shutil.rmtree(dest / name, ignore_errors=True)
    managed.discard(name)
    removed += 1
safe_write.write_text(marker, json.dumps({"names": sorted(managed)}, indent=2) + "\n")
print(f"    skills re-rooted → {dest}: {added} added, {kept} kept, {removed} pruned")
PY

# ── 5. Reindex (opencode-* points; engine_env forwards .mcp.json pins) ──────
VENV="${SKILL_CONCIERGE_VENV:-$HOME/.claude/skill-concierge/ve""nv}"
if [ -x "$VENV/bin/skill-search" ]; then
  python3 "$ROOT/scripts/engine_env.py" --root "$ROOT" --exec "$VENV/bin/skill-search" --reindex \
    || echo "    [!] reindex failed — run setup.sh, then re-run this installer" >&2
else
  echo "    [!] no engine venv at $VENV — run ./setup.sh first, then re-run this installer" >&2
fi

# ── 6. Verify ────────────────────────────────────────────────────────────────
echo "==> verify:"
VERIFY_OK=true
if python3 - "$OPENCODE_JSON" "$PLUGIN_DIR" <<'PY'
import json
import sys

cfg = json.load(open(sys.argv[1]))
plugin_dir = sys.argv[2]
ours = any(e == plugin_dir or (isinstance(e, dict) and e.get("package") == plugin_dir)
           for e in cfg.get("plugins", []))
print(f"    opencode.json carries the plugin entry: {'yes' if ours else 'NO'}")
sys.exit(0 if ours else 1)
PY
then :; else VERIFY_OK=false; fi

REPO_SKILLS="$(python3 -c 'import sys; from pathlib import Path; print(len(list((Path(sys.argv[1])/"skills").glob("*/SKILL.md"))))' "$ROOT")"
LIVE_SKILLS="$(python3 - "$SKILLS_HOME" <<'PY'
import json, sys
from pathlib import Path
home = Path(sys.argv[1])
try:
    names = json.loads((home / ".skill-concierge-managed.json").read_text(encoding="utf-8"))["names"]
except (OSError, ValueError, KeyError):
    names = []
print(sum(1 for n in names if (home / n / "SKILL.md").is_file()))
PY
)"
if [ "$REPO_SKILLS" = "$LIVE_SKILLS" ] && [ "$REPO_SKILLS" -gt 0 ]; then
  echo "    skills re-rooted: $LIVE_SKILLS/$REPO_SKILLS"
else
  echo "    !! skills re-root mismatch: $LIVE_SKILLS managed live vs $REPO_SKILLS in the repo" >&2
  VERIFY_OK=false
fi
if [ -x "$ROOT/bin/skill-search-mcp" ]; then
  echo "    launcher executable: yes"
else
  echo "    !! launcher missing/not executable at $ROOT/bin/skill-search-mcp" >&2
  VERIFY_OK=false
fi
python3 "$ROOT/scripts/doctor.py" 2>/dev/null | grep -i "OpenCode integration" || true
chmod +x "$0" 2>/dev/null || true

if $VERIFY_OK; then
  echo "    verify: OK"
else
  echo "    verify: FAILED — see lines above" >&2
  exit 1
fi

echo "==> Done. Restart the OpenCode service to load the plugin:"
echo "      opencode service restart"
echo "    Then confirm: a session's tools list skill-search_search_skills, and the"
echo "    first prompt of a session carries the SKILL-FIRST doctrine (system part)."
