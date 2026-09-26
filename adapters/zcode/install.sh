#!/usr/bin/env bash
# skill-concierge — ZCode installer / sync / repair (ADR-0042).
#
# ZCode is the one harness in the set that needs NO adapter vehicle: it natively reads
# `.claude-plugin/` manifests, fires the plugin hooks/hooks.json, and auto-connects the
# plugin `.mcp.json`. But its GUI has NO plugin-update action (its own diagnosing-plugins
# doc lists only Get/enable/disable/configure/uninstall), so a marketplace-installed copy
# goes stale the moment a new version is released. THIS script is the update mechanism:
#
#   ./adapters/zcode/install.sh                  # sync HEAD → ZCode cache + repair exec bits
#   ./adapters/zcode/install.sh --mcp-fallback   # additionally merge the manual MCP fallback
#
# What sync does (idempotent, every step verified or aborted):
#   1. Read the SSOT version from $ROOT/.claude-plugin/plugin.json
#   2. Export the release tree (git archive HEAD; cp fallback for non-git checkouts)
#      into ~/.zcode/cli/plugins/cache/skill-concierge/skill-concierge/<version>/
#   3. chmod +x the bins and installers (ZCode's marketplace cache has shipped without
#      the exec bit — cosmetic under the interpreter-form .mcp.json, repaired anyway)
#   4. Point ~/.zcode/cli/plugins/installed_plugins.json at the new version (backup first)
#
# Old version dirs are left in place: discovery is registry-enumerated, so they are
# neither indexed nor served. Restart ZCode afterwards to load the new version.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ZCODE_PLUGINS="$HOME/.zcode/cli/plugins"
CACHE_BASE="$ZCODE_PLUGINS/cache/skill-concierge/skill-concierge"
REG_FILE="$ZCODE_PLUGINS/installed_plugins.json"
CONFIG_FILE="$HOME/.zcode/cli/config.json"

MCP_FALLBACK=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --mcp-fallback) MCP_FALLBACK=1; shift ;;
    *) echo "Unknown option: $1" >&2; echo "usage: $0 [--mcp-fallback]" >&2; exit 1 ;;
  esac
done

echo "==> skill-concierge → ZCode sync (from: $ROOT)"

# ── 1. SSOT version ──────────────────────────────────────────────────────────
VERSION="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["version"])' "$ROOT/.claude-plugin/plugin.json")"
echo "    SSOT version: $VERSION"

# _is_own_checkout — true when $ROOT is its own git top level. Compared by file identity (-ef), so a
# symlinked or case-variant path to a real checkout still counts; a plain directory inside some other
# repo does not.
_is_own_checkout() {
  local top
  top="$(git -C "$ROOT" rev-parse --show-toplevel 2>/dev/null)" || return 1
  [ -n "$top" ] && [ "$ROOT" -ef "$top" ]
}

# A git checkout installs HEAD (`git archive HEAD`), so HEAD's version is the one to install. An
# uncommitted version change would put HEAD's content in a dir named for the new version: refuse
# before any CLI call or write. A checkout whose git dir is renamed to `git/` (the workbench's
# no-dot toggle) is refused too: copying it as a plain tree would ship that database and every
# untracked file.
if _is_own_checkout; then
  HEAD_VERSION="$(git -C "$ROOT" show HEAD:.claude-plugin/plugin.json 2>/dev/null \
    | python3 -c "import json,sys;print(json.load(sys.stdin)['version'])" 2>/dev/null || true)"
  if [ "$HEAD_VERSION" != "$VERSION" ]; then
    echo "!! .claude-plugin/plugin.json says v$VERSION but HEAD carries v${HEAD_VERSION:-none}; this installer" >&2
    echo "   installs HEAD. Commit the version change (or restore the file), then re-run." >&2
    exit 1
  fi
elif [ -f "$ROOT/git/HEAD" ]; then
  echo "!! $ROOT keeps its git database in git/ (renamed from .git). Copying it as a plain tree" >&2
  echo "   would ship that database and every untracked file. Rename git/ back to .git, then re-run." >&2
  exit 1
fi

# ── 2. Export the release tree into the versioned cache dir ──────────────────
DEST="$CACHE_BASE/$VERSION"
mkdir -p "$DEST"
if _is_own_checkout; then
  git -C "$ROOT" archive HEAD | tar -x -C "$DEST"
  echo "    exported HEAD → $DEST"
else
  # Non-git checkout: copy everything except VCS/scratch dirs.
  tar -C "$ROOT" -cf - \
      --exclude='.git' --exclude='.ijfw' --exclude='ijfw' --exclude='.handoff' \
      --exclude='logs' --exclude='graphify-out' --exclude='.claude' \
      --exclude='node_modules' --exclude='__pycache__' --exclude='.venv' \
      --exclude='.pytest_cache' --exclude='.mypy_cache' --exclude='.ruff_cache' \
      . | tar -xf - -C "$DEST"
  echo "    copied the working tree (not a git checkout) → $DEST"
fi

# ── 3. Exec bits ─────────────────────────────────────────────────────────────
chmod +x "$DEST/bin/"* "$DEST/setup.sh" \
         "$DEST/adapters/zcode/install.sh" "$DEST/adapters/commandcode/install.sh" \
         "$DEST/adapters/omp/install.sh" 2>/dev/null || true
echo "    bin/ + installer exec bits ensured"

# ── 4. Registry update (backup first) ────────────────────────────────────────
python3 - "$REG_FILE" "$DEST" "$VERSION" <<'PY'
import json, shutil, sys, time
from pathlib import Path
reg_path, install_path, version = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
data = json.loads(reg_path.read_text(encoding="utf-8"))
entry = None
for p in data.get("plugins", []):
    if p.get("id") == "skill-concierge@skill-concierge":
        entry = p
        break
if entry is None:
    print("!! no skill-concierge@skill-concierge entry in the registry — install once via "
          "Settings → Plugin Management → Discover (Get), then re-run this sync.", file=sys.stderr)
    sys.exit(1)
backup = reg_path.with_suffix(".json.bak-sc-" + time.strftime("%Y%m%d-%H%M%S"))
shutil.copy2(reg_path, backup)
entry["version"] = version
entry["installPath"] = install_path
entry["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
reg_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
print(f"    registry → v{version} (backup: {backup.name})")
PY

# ── 5. Optional manual MCP fallback merge ────────────────────────────────────
if [ "$MCP_FALLBACK" = "1" ]; then
  python3 - "$ROOT/adapters/zcode/mcp.json" "$CONFIG_FILE" <<'PY'
import json, shutil, sys, time
from pathlib import Path
src, cfg_path = Path(sys.argv[1]), Path(sys.argv[2])
server = json.loads(src.read_text(encoding="utf-8"))["mcpServers"]["skill-search"]
if not cfg_path.exists():
    print(f"!! No ZCode config at {cfg_path} — nothing to merge into", file=sys.stderr)
    sys.exit(1)
backup = cfg_path.with_suffix(".json.bak-skill-concierge-" + time.strftime("%Y%m%d-%H%M%S"))
shutil.copy2(cfg_path, backup)
cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
mcp = cfg.setdefault("mcp", {})
servers = mcp.setdefault("servers", {})
servers["skill-search"] = server
cfg_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"    merged mcp.servers.skill-search (backup: {backup.name})")
PY
  echo "    NOTE: the plugin .mcp.json layer remains primary; remove this user-scope entry"
  echo "    if the plugin layer is (or becomes) healthy — one server, one layer."
fi

# ── 6. Verify ────────────────────────────────────────────────────────────────
echo "==> verify:"
test "$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["version"])' "$DEST/.claude-plugin/plugin.json")" = "$VERSION" \
  && echo "    cache manifest: v$VERSION" \
  || { echo "    !! cache manifest version mismatch" >&2; exit 1; }
test -x "$DEST/bin/skill-search-mcp" && echo "    launcher executable: yes"
diff -q "$ROOT/hooks/scripts/enforcer.py" "$DEST/hooks/scripts/enforcer.py" >/dev/null \
  && echo "    enforcer byte-identical to repo HEAD: yes"
python3 "$ROOT/scripts/doctor.py" 2>/dev/null | grep -i "ZCode integration" || true
echo "==> Done. Restart ZCode to load v$VERSION (hooks + MCP server re-read at session start)."
echo "    Then confirm: Settings → MCP shows the plugin server connected, and a session lists"
echo "    mcp__plugin_skill-concierge_skill-search__search_skills."
