#!/usr/bin/env bash
# skill-concierge — ZCode verifier / repair script (ADR-0042).
#
# ZCode is the one harness in the set that needs NO adapter vehicle: it natively reads
# `.claude-plugin/` manifests, fires the plugin hooks/hooks.json (SessionStart doctrine +
# self-heals, UserPromptSubmit enforcer + ledger, PostToolUse ledger — all verified live),
# and auto-connects the plugin `.mcp.json`. Installation therefore rides the skill-concierge
# MARKETPLACE; this script only repairs the two cache-side defects observed live on
# 2026-08-28 and offers an optional manual MCP fallback:
#   1. chmod +x the cached bin/ — ZCode's cache copy shipped bin/skill-search-mcp as
#      -rw-r--r--, killing the MCP with spawn Permission denied (cosmetic once the
#      interpreter-form .mcp.json is deployed, but repaired anyway);
#   2. --mcp-fallback: merge adapters/zcode/mcp.json's server into
#      ~/.zcode/cli/config.json mcp.servers (backup first). OFF by default — the plugin
#      layer is primary and running both layers for one server is config noise.
#
# Usage:
#   ./adapters/zcode/install.sh [--mcp-fallback]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ZCODE_PLUGINS="$HOME/.zcode/cli/plugins"
CACHE_BASE="$ZCODE_PLUGINS/cache/skill-concierge/skill-concierge"
CONFIG_FILE="$HOME/.zcode/cli/config.json"

MCP_FALLBACK=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --mcp-fallback) MCP_FALLBACK=1; shift ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

echo "==> skill-concierge ZCode surface check (from: $ROOT)"

# ── 1. Locate the newest cached plugin copy ──────────────────────────────────
if [ ! -d "$CACHE_BASE" ]; then
  echo "!! No ZCode plugin cache at $CACHE_BASE." >&2
  echo "   Install via ZCode: Settings → Plugin Management → Discover → add the skill-concierge" >&2
  echo "   marketplace (github.com/thinhkhuat/skill-concierge), then install the plugin." >&2
  exit 1
fi
NEWEST="$(ls -1 "$CACHE_BASE" | sort -t. -k1,1n -k2,2n -k3,3n | tail -1)"
echo "    cache: $CACHE_BASE/$NEWEST"

# ── 2. Repair exec bits (ZCode's cache copy has shipped without them) ────────
if [ -d "$CACHE_BASE/$NEWEST/bin" ]; then
  chmod +x "$CACHE_BASE/$NEWEST/bin"/* 2>/dev/null || true
  echo "    bin/ exec bits ensured (interpreter-form .mcp.json makes them cosmetic)"
fi

# ── 3. Optional manual MCP fallback merge ────────────────────────────────────
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

# ── 4. Verify with doctor ────────────────────────────────────────────────────
echo "==> doctor zcode row:"
python3 "$ROOT/scripts/doctor.py" 2>/dev/null | grep -i "zcode" || true
echo "==> Done. Restart ZCode and verify:"
echo "    - Settings → MCP: plugin server 'skill-concierge:skill-search' connected"
echo "    - a session lists the tool mcp__plugin_skill-concierge_skill-search__search_skills"
