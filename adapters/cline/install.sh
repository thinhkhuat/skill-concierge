#!/usr/bin/env bash
# skill-concierge — Cline installer (ADR-0051).
#
# Cline (CLI/SDK runtime) integrates via its NATIVE file-hook surface — no TS
# adapter vehicle (the OMP/DSH contrast). This installer is idempotent and
# touches ONLY skill-concierge-owned files:
#
#   ./adapters/cline/install.sh            # shims + MCP merge + skills root
#   ./adapters/cline/install.sh --no-mcp   # shims only (skip the MCP merge)
#
# What it does (every step verified or aborted):
#   1. Resolve ROOT + SSOT version from $ROOT/.claude-plugin/plugin.json
#   2. Generate ~/.cline/hooks/UserPromptSubmit.cjs + PostToolUse.cjs from the
#      templates (root-resolved absolute require path). The operator's own
#      extension-less bridge files are NEVER touched — Cline co-fires same-event
#      hook files and merges contexts (hook-file-hooks.ts mergeHookControls).
#   3. Merge the skill-search MCP server into
#      ~/.cline/data/settings/cline_mcp_settings.json (backup first; an existing
#      skill-search row is left alone unless identical — one server, one layer).
#   4. Ensure ~/.cline/data/settings/skills/ exists (the discovery root).
#   5. Verify + print the doctor row.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CLINE_HOOKS="$HOME/.cline/hooks"
CLINE_SETTINGS="$HOME/.cline/data/settings/cline_mcp_settings.json"
CLINE_SKILLS="$HOME/.cline/data/settings/skills"
BRIDGE="$ROOT/adapters/cline/skill-concierge.cline-hook.cjs"

NO_MCP=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-mcp) NO_MCP=1; shift ;;
    *) echo "Unknown option: $1" >&2; echo "usage: $0 [--no-mcp]" >&2; exit 1 ;;
  esac
done

echo "==> skill-concierge → Cline install (from: $ROOT)"
VERSION="$(python3 -c "import json;print(json.load(open('$ROOT/.claude-plugin/plugin.json'))['version'])")"
echo "    SSOT version: $VERSION"

test -f "$BRIDGE" || { echo "!! bridge missing: $BRIDGE" >&2; exit 1; }

# ── 2. Hook shims (self-owned names only) ────────────────────────────────────
mkdir -p "$CLINE_HOOKS"
for evt in UserPromptSubmit PostToolUse; do
  sed "s|__SKILL_CONCIERGE_BRIDGE__|$BRIDGE|g" "$ROOT/adapters/cline/hooks/$evt.cjs" \
    > "$CLINE_HOOKS/$evt.cjs"
done
echo "    shims → $CLINE_HOOKS/{UserPromptSubmit,PostToolUse}.cjs (bridge: $BRIDGE)"

# ── 3. MCP merge (backup first, idempotent) ──────────────────────────────────
if [ "$NO_MCP" = "0" ]; then
  python3 - "$ROOT/adapters/cline/mcp.json" "$CLINE_SETTINGS" <<'PY'
import json, shutil, sys, time
from pathlib import Path
src, cfg_path = Path(sys.argv[1]), Path(sys.argv[2])
server = json.loads(src.read_text(encoding="utf-8"))["mcpServers"]["skill-search"]
cfg_path.parent.mkdir(parents=True, exist_ok=True)
existing = {}
if cfg_path.exists():
    try:
        existing = json.loads(cfg_path.read_text(encoding="utf-8"))
    except ValueError:
        print(f"!! {cfg_path} is not valid JSON — refusing to touch it; merge manually.",
              file=sys.stderr)
        sys.exit(1)
servers = existing.setdefault("mcpServers", {})
if servers.get("skill-search") == server:
    print("    MCP row already in sync — no change")
else:
    backup = cfg_path.with_suffix(".json.bak-skill-concierge-" + time.strftime("%Y%m%d-%H%M%S"))
    if cfg_path.exists():
        shutil.copy2(cfg_path, backup)
        print(f"    backup: {backup.name}")
    if "skill-search" in servers:
        print("    !! an existing skill-search row differs — OVERWRITING (was it manually "
              "edited? compare with the backup)", file=sys.stderr)
    servers["skill-search"] = server
    cfg_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"    merged mcpServers.skill-search → {cfg_path}")
PY
else
  echo "    --no-mcp: skipping the MCP merge"
fi

# ── 4. Personal skills root (discovery root) ─────────────────────────────────
mkdir -p "$CLINE_SKILLS"
echo "    skills root ensured: $CLINE_SKILLS"

# ── 5. Verify ────────────────────────────────────────────────────────────────
echo "==> verify:"
for f in UserPromptSubmit.cjs PostToolUse.cjs; do
  test -f "$CLINE_HOOKS/$f" && echo "    shim present: $f"
done
node -e "require('$BRIDGE')" 2>/dev/null && echo "    bridge module loads: yes" \
  || { echo "    !! bridge failed to load" >&2; exit 1; }
if [ "$NO_MCP" = "0" ] && python3 -c "
import json,sys
c=json.load(open('$CLINE_SETTINGS'))
s=c.get('mcpServers',{}).get('skill-search')
sys.exit(0 if s and s.get('command') else 1)" 2>/dev/null; then
  echo "    MCP row present: skill-search"
fi
python3 "$ROOT/scripts/doctor.py" 2>/dev/null | grep -i "Cline integration" || true
echo "==> Done. Restart any running Cline session (hooks + MCP are read per session)."
echo "    Smoke test: cline -p 'search skills for docker debugging' and check the ledger:"
echo "    tail -5 ~/.claude/logs/skill-invocation-ledger.log  (rows stamped harness=cline)"
