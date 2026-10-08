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
#   2. Export the release tree (git archive HEAD; a tar copy for non-git checkouts)
#      into ~/.zcode/cli/plugins/cache/skill-concierge/skill-concierge/<version>/
#   3. chmod +x the bins and installers (ZCode's marketplace cache has shipped without
#      the exec bit — cosmetic under the interpreter-form .mcp.json, repaired anyway)
#   4. Point ~/.zcode/cli/plugins/installed_plugins.json at the new version (backup first)
#
# Refusals (exit 1, nothing written into the cache): no registry record for the plugin, an
# unreadable registry, a registered copy NEWER than this checkout (no downgrades), a checkout
# whose HEAD version disagrees with plugin.json (commit or restore it first), a git database
# renamed to git/ (rename it back to .git first), or a git checkout git cannot read.
#
# Old version dirs are left in place: discovery is registry-enumerated, so they are
# neither indexed nor served. Restart ZCode afterwards to load the new version.
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

_refuse_unexportable_checkout   # HEAD version / git-dir refusals (adapters/lib/sync.sh)

# ── 1b. Registry must already have a skill-concierge@skill-concierge entry, and the
# copy it names must not be newer than this checkout — both checked BEFORE any write to
# the cache, so a missing/broken registry or a stale checkout never leaves an export
# sitting in the cache that this run then aborts out of.
if ! DEPLOYED="$(python3 - "$REG_FILE" <<'PY'
import json, sys
from pathlib import Path
try:
    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
except (OSError, ValueError):
    sys.exit(2)   # registry file missing, empty, or unreadable JSON
for p in data.get("plugins", []):
    if isinstance(p, dict) and p.get("id") == "skill-concierge@skill-concierge":
        ip = p.get("installPath") or ""
        ver = ""
        if ip:
            pf = Path(ip) / ".claude-plugin" / "plugin.json"
            try:
                ver = json.loads(pf.read_text(encoding="utf-8")).get("version") or ""
            except (OSError, ValueError):
                ver = ""   # entry exists but the manifest of its active copy is unreadable
        print(ver)
        sys.exit(0)
sys.exit(1)   # no matching entry in the registry
PY
)"; then
  echo "!! no skill-concierge@skill-concierge entry in $REG_FILE (or the registry is" >&2
  echo "   missing/unreadable) — install it once via Settings → Plugin Management →" >&2
  echo "   Discover (Get), then re-run this sync." >&2
  exit 1
fi
if [ -n "$DEPLOYED" ] && ! _ver_ge "$VERSION" "$DEPLOYED"; then
  echo "!! refusing to downgrade: the ZCode registry's active copy is v$DEPLOYED, newer" >&2
  echo "   than this checkout v$VERSION. Update the checkout (git pull) or keep the newer" >&2
  echo "   deployed copy — a stale checkout never downgrades (ADR-0042 doctrine)." >&2
  exit 1
fi

# ── 2. Export the release tree into the versioned cache dir ──────────────────
DEST="$CACHE_BASE/$VERSION"
_export_to "$DEST"   # staged, then swapped in: no stale files from an older tree survive

# ── 3. Exec bits ─────────────────────────────────────────────────────────────
chmod +x "$DEST/bin/"* "$DEST/setup.sh" \
         "$DEST/adapters/zcode/install.sh" "$DEST/adapters/commandcode/install.sh" \
         "$DEST/adapters/omp/install.sh" 2>/dev/null || true
echo "    bin/ + installer exec bits ensured"

# ── 4. Registry update: only the record this run read, resolved through a symlink, written
# atomically via adapters/lib/safe_write.py (same doctrine as the claude-code/OMP repoint),
# backed up only after a change-during-run check passes ───────────────────────────────────
PYTHONPATH="$SCRIPT_DIR/../lib" python3 - "$REG_FILE" "$DEST" "$VERSION" <<'PY'
import sys
import time

import safe_write

reg_path, install_path, version = sys.argv[1:4]


def mutate(data):
    entry = None
    for p in data.get("plugins", []):
        if p.get("id") == "skill-concierge@skill-concierge":
            entry = p
            break
    if entry is None:
        raise RuntimeError("no skill-concierge@skill-concierge entry in the registry — install once "
                           "via Settings → Plugin Management → Discover (Get), then re-run this sync.")
    entry["version"] = version
    entry["installPath"] = install_path
    entry["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())


try:
    _real, backup = safe_write.write_registry(reg_path, mutate, "zcode")
except RuntimeError as e:
    print(f"!! {e}", file=sys.stderr)
    sys.exit(1)
print(f"    registry → v{version} (backup: {backup.name})")
PY

# ── 5. Optional manual MCP fallback merge ────────────────────────────────────
if [ "$MCP_FALLBACK" = "1" ]; then
  PYTHONPATH="$SCRIPT_DIR/../lib" python3 - "$ROOT/adapters/zcode/mcp.json" "$CONFIG_FILE" <<'PY'
import json, shutil, sys, time
from pathlib import Path

import safe_write

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
safe_write.write_text(cfg_path, json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")
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
  && echo "    enforcer byte-identical to this checkout's working tree: yes"
python3 "$ROOT/scripts/doctor.py" 2>/dev/null | grep -i "ZCode integration" || true
echo "==> Done. Restart ZCode to load v$VERSION (hooks + MCP server re-read at session start)."
echo "    Then confirm: Settings → MCP shows the plugin server connected, and a session lists"
echo "    mcp__plugin_skill-concierge_skill-search__search_skills."
