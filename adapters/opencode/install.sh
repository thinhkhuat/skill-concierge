#!/usr/bin/env bash
# skill-concierge — OpenCode v2 installer / sync / repair (ADR-0085).
#
# OpenCode v2 loads plugins from the `plugins` array in opencode.json(c) (global
# ~/.config/opencode/opencode.json or any project config). This installer:
#   1. Reads the SSOT version from $ROOT/.claude-plugin/plugin.json
#   2. Refuses an uncommitted version change on a git checkout (ADR-0069/0072
#      installer discipline, fail-closed)
#   3. Registers the plugin package path in the GLOBAL opencode.json `plugins`
#      array, replacing any other skill-concierge copy's entry (every copy has the
#      plugin id "skill-concierge"; OpenCode fails all but the first), plus the
#      skills folder below in `skills` — safe_write (symlink/mode-safe, backed up,
#      refuses a concurrent write, preserves every unrelated key)
#   4. Copies the plugin's own skills (skills/*/SKILL.md → plain names) into
#      ~/.config/opencode/skill-concierge-skills/, a folder only this installer
#      writes, so the index gets opencode-personal rows the enforcer can offer.
#      Never ~/.config/opencode/skills: that is often a symlink to
#      ~/.claude/skills. Copies older installers left there are removed when they
#      still match some committed version of the repo's skill; edited ones stay.
#      Run from a plugin-cache copy, it refuses to take over from a checkout
#      OpenCode already runs (the cache copy is deleted on the next update).
#   5. Fires a reindex through scripts/engine_env.py (SKILL_OPENCODE_ROOTS is
#      pinned in .mcp.json) so the opencode-* points land
#   6. Verifies: exactly one plugin entry (this copy), skills folder registered,
#      skills synced, launcher executable
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
# The plugin's own skills go to a folder only this installer writes, registered in opencode.json
# `skills`. Never $OPENCODE_HOME/skills: it is often a symlink to ~/.claude/skills.
SKILLS_HOME="$OPENCODE_HOME/skill-concierge-skills"
LEGACY_SKILLS="$OPENCODE_HOME/skills"

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
# One skill-concierge entry in `plugins` (every copy has the plugin id "skill-concierge"; OpenCode
# fails all but the first) and the owned skills folder in `skills`. Every other key and entry is
# preserved; write_registry backs up beside the file, keeps the mode, and refuses a concurrent
# write (a live service session). What counts as a copy lives in oc_config.py, shared with doctor.
PYTHONPATH="$SCRIPT_DIR/../lib:$SCRIPT_DIR" python3 - "$OPENCODE_JSON" "$PLUGIN_DIR" "$SKILLS_HOME" <<'PY'
import json
import sys
from pathlib import Path

import oc_config
import safe_write

cfg_path, plugin_dir, skills_dir = sys.argv[1], sys.argv[2], sys.argv[3]
cfg_dir = Path(cfg_path).parent


def upsert(data):
    if data.get("plugins") is None:
        data["plugins"] = []
    plugins = data["plugins"]
    if not isinstance(plugins, list):
        raise RuntimeError(f"plugins is {type(plugins).__name__}, not a list — fix {cfg_path} by hand")
    ours = [i for i, e in enumerate(plugins) if oc_config.is_copy(e, cfg_dir)]
    if oc_config.is_plugin_cache(plugin_dir):
        # A versioned cache copy is deleted on the next plugin update; never let it take over
        # from a checkout OpenCode already runs.
        for i in ours:
            other = oc_config.resolve(oc_config.entry_path(plugins[i]), cfg_dir)
            if other.exists() and not oc_config.is_plugin_cache(other) and str(other) != plugin_dir:
                raise SystemExit(f"!! OpenCode already runs skill-concierge from {other}. This copy "
                                 f"({plugin_dir}) is a plugin cache that the next update deletes. Run "
                                 f"{other.parent.parent.parent}/adapters/opencode/install.sh instead. "
                                 "Nothing was changed.")
    for i in reversed(ours[1:]):
        print(f"    opencode.json plugins -= {oc_config.entry_path(plugins.pop(i))} (another skill-concierge copy)")
    if ours:
        old = plugins[ours[0]]
        if oc_config.entry_path(old) != plugin_dir:
            print(f"    opencode.json plugins: {oc_config.entry_path(old)} -> {plugin_dir}")
        plugins[ours[0]] = {**(old if isinstance(old, dict) else {}), "package": plugin_dir}
    else:
        plugins.append({"package": plugin_dir})
        print(f"    opencode.json plugins += {plugin_dir}")
    if data.get("skills") is None:
        data["skills"] = []
    if not isinstance(data["skills"], list):
        raise RuntimeError(f"skills is {type(data['skills']).__name__}, not a list — fix {cfg_path} by hand")
    if Path(skills_dir) not in (oc_config.skills_entries(data, cfg_dir) or []):
        data["skills"].append(skills_dir)
        print(f"    opencode.json skills += {skills_dir}")


try:
    safe_write.write_registry(cfg_path, upsert, "skill-concierge")
except FileNotFoundError:
    fresh = {"$schema": "https://opencode.ai/config.json", "plugins": [{"package": plugin_dir}],
             "skills": [skills_dir]}
    safe_write.write_text(cfg_path, json.dumps(fresh, indent=2) + "\n")
    print(f"    opencode.json created with the plugin entry ({cfg_path})")
except json.JSONDecodeError as e:
    print(f"!! {cfg_path} is not plain JSON ({e}) — remove JSONC comments first; nothing written",
          file=sys.stderr)
    sys.exit(1)
PY

# ── 4. Copy the plugin's own skills into the folder this installer owns ──────
PYTHONPATH="$SCRIPT_DIR/../lib:$SCRIPT_DIR" python3 - "$ROOT" "$SKILLS_HOME" "$LEGACY_SKILLS" <<'PY'
import json
import shutil
import sys
from pathlib import Path

import oc_config
import safe_write

repo, dest, legacy = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
src = repo / "skills"
if not src.is_dir():
    print("!! no skills/ dir in the repo — skipping the skills re-root", file=sys.stderr)
    sys.exit(0)

want = {}
for d in sorted(src.iterdir()):
    md = d / "SKILL.md"
    if d.is_dir() and md.is_file():
        want[d.name] = md.read_text(encoding="utf-8")


def managed_names(marker: Path) -> list | None:
    try:
        names = json.loads(marker.read_text(encoding="utf-8")).get("names")
    except (OSError, ValueError, AttributeError):
        return None
    return [n for n in names if isinstance(n, str) and n and "/" not in n and n not in (".", "..")] \
        if isinstance(names, list) else None


dest.mkdir(parents=True, exist_ok=True)
marker = dest / ".skill-concierge-managed.json"
managed = set(managed_names(marker) or [])

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

# Retire the copies older installers wrote into $OPENCODE_HOME/skills (often ~/.claude/skills,
# where Claude Code then listed them as duplicate personal skills). A copy goes only when its
# folder holds nothing but a SKILL.md equal to some version of the repo's own; an edited one stays.
old_marker = legacy / ".skill-concierge-managed.json"
old = managed_names(old_marker)
if old is not None and legacy.resolve() != dest.resolve():
    keep = []
    for name in old:
        d = legacy / name
        if not d.exists():
            continue
        if (not d.is_symlink() and d.is_dir() and [p.name for p in d.iterdir()] == ["SKILL.md"]
                and (d / "SKILL.md").read_text(encoding="utf-8") in oc_config.known_versions(repo, name)):
            shutil.rmtree(d)
            print(f"    retired old copy {d}")
        else:
            keep.append(name)
            print(f"    !! left {d} in place: it is not an unedited copy of this plugin's skill "
                  "(remove it by hand if unwanted, then remove its name from "
                  f"{old_marker})")
    if keep:
        safe_write.write_text(old_marker, json.dumps({"names": keep}, indent=2) + "\n")
    else:
        old_marker.unlink()
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
if PYTHONPATH="$SCRIPT_DIR" python3 - "$OPENCODE_JSON" "$PLUGIN_DIR" "$SKILLS_HOME" <<'PY'
import json
import sys
from pathlib import Path

import oc_config

cfg_path, plugin_dir, skills_dir = sys.argv[1], sys.argv[2], Path(sys.argv[3])
cfg = json.load(open(cfg_path))
cfg_dir = Path(cfg_path).parent
copies = [oc_config.entry_path(e) for e in cfg.get("plugins") or [] if oc_config.is_copy(e, cfg_dir)]
skills = oc_config.skills_entries(cfg, cfg_dir) or []
ok = copies == [plugin_dir] and skills_dir in skills
print(f"    opencode.json: plugin entries {len(copies)} (want 1, this copy), "
      f"skills folder registered: {'yes' if skills_dir in skills else 'NO'}")
sys.exit(0 if ok else 1)
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
