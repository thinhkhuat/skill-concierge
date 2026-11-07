#!/usr/bin/env bash
# skill-concierge — Hermes Agent installer / sync / repair (ADR-0100).
#
# Hermes Agent is a Python-plugin harness: `~/.hermes/plugins/<name>/` with a `plugin.yaml`
# manifest and an `__init__.py` exposing `register(ctx)`. Its plugin hooks fire in BOTH the CLI
# and the gateway, which is why this adapter is a plugin and not a `~/.hermes/hooks/` entry
# (those are gateway-only and gateway-hooks-only is a partial harness, not a supported one).
#
# What this installer does (idempotent, verified):
#   1. Read the SSOT version from $ROOT/.claude-plugin/plugin.json
#   2. Symlink $HERMES_HOME/plugins/skill-concierge at this checkout's
#      adapters/hermes/plugin, so the checkout stays the one source of truth
#      (RULES [52]: install dev -> global by symlink, never cp)
#   3. Enable the plugin (`hermes plugins enable`, idempotent) — this HOT-RELOADS the
#      hooks into a running gateway; new tools register on the next session
#   4. Register the skill-search MCP server in $HERMES_HOME/config.yaml through
#      `hermes config set` — NEVER a hand-written edit: Hermes's own invariant is that a
#      stray indent in config.yaml breaks the live gateway. `hermes config set` is
#      re-serializing, so it is run only when the entry actually differs.
#   5. Verify: the plugin validates against Hermes's real runtime contracts
#      (`hermes plugins validate`), it is listed+enabled, the MCP server is listed,
#      the launcher is executable, and doctor's Hermes row
#
# MCP: Hermes's native client namespaces every server tool `mcp_<server>_<tool>`, so the
# doctrine and the ledger address `mcp_skill_search_search_skills` / `mcp_skill_search_get_skill`
# for the server named `skill-search`. No `.mcp.json` equivalent is read by Hermes: its
# `mcp_servers:` block is the only seam, which is why this installer writes it.
#
# Usage:
#   ./adapters/hermes/install.sh [--root <path>]
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
# A cache copy never wires a harness to itself (the 2026-10-09 OpenCode duplicate). Checked after
# --root and on the real path, so neither --root nor a symlink gets around it.
case "$(cd "$ROOT" && pwd -P)" in */plugins/cache/*)
  echo "!! $ROOT is a plugin cache copy, which the next plugin update deletes; Hermes would then break." >&2
  echo "   Clone the repo and run adapters/hermes/install.sh from the clone. Nothing was changed." >&2
  exit 1 ;;
esac

echo "==> skill-concierge → Hermes Agent sync (from: $ROOT)"

# ── 1. SSOT version ──────────────────────────────────────────────────────────
VERSION="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["version"])' "$ROOT/.claude-plugin/plugin.json")"
echo "    SSOT version: v$VERSION"

# ── 2. Resolve the Hermes home (profiles included: never a hardcoded ~/.hermes) ──────────────
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
echo "    Hermes home: $HERMES_HOME"

if ! command -v hermes >/dev/null 2>&1; then
  echo "!! 'hermes' is not on PATH — install Hermes Agent first (https://hermes-agent.nousresearch.com)." >&2
  echo "   Nothing was changed." >&2
  exit 1
fi
if [ ! -d "$HERMES_HOME" ]; then
  echo "!! $HERMES_HOME does not exist — run 'hermes setup' once, then re-run this installer." >&2
  exit 1
fi

PLUGIN_DIR="$HERMES_HOME/plugins/skill-concierge"
SOURCE_DIR="$ROOT/adapters/hermes/plugin"

if [ ! -f "$SOURCE_DIR/__init__.py" ] || [ ! -f "$SOURCE_DIR/plugin.yaml" ]; then
  echo "!! this checkout is missing adapters/hermes/plugin/{plugin.yaml,__init__.py}." >&2
  exit 1
fi

# ── 3. Place the plugin: a symlink at the checkout, never a copy ─────────────────────────────
mkdir -p "$HERMES_HOME/plugins"
if [ -L "$PLUGIN_DIR" ]; then
  CURRENT="$(readlink "$PLUGIN_DIR")"
  if [ "$CURRENT" = "$SOURCE_DIR" ]; then
    echo "  [✓] plugin symlink already points at this checkout"
  else
    ln -sfn "$SOURCE_DIR" "$PLUGIN_DIR"
    echo "  [•] plugin symlink repointed: $CURRENT -> $SOURCE_DIR"
  fi
elif [ -e "$PLUGIN_DIR" ]; then
  # A real directory under our plugin's name. Only a previous copy of THIS plugin is replaced
  # (archived, never deleted); anything else is refused rather than overwritten.
  if grep -q '^name: skill-concierge$' "$PLUGIN_DIR/plugin.yaml" 2>/dev/null; then
    ARCHIVE="$HOME/_ARCHIVE/skill-concierge/hermes-plugin-$(date +%Y%m%d-%H%M%S)"
    mkdir -p "$(dirname "$ARCHIVE")"
    mv "$PLUGIN_DIR" "$ARCHIVE"
    ln -sfn "$SOURCE_DIR" "$PLUGIN_DIR"
    echo "  [•] previous plugin copy archived to $ARCHIVE; symlinked to this checkout"
  else
    echo "!! $PLUGIN_DIR exists and is not a skill-concierge plugin copy." >&2
    echo "   Move it aside yourself, then re-run. Nothing was changed." >&2
    exit 1
  fi
else
  ln -sfn "$SOURCE_DIR" "$PLUGIN_DIR"
  echo "  [✓] plugin symlinked: $PLUGIN_DIR -> $SOURCE_DIR"
fi

# ── 4. Enable the plugin (idempotent, hot-reloads hooks into a running gateway) ──────────────
hermes plugins enable skill-concierge >/dev/null 2>&1 || true
echo "  [✓] plugin enabled"

# ── 5. skill-search MCP server, through `hermes config set` (never a hand edit) ──────────────
# Built as JSON and compared before writing: `config set` re-serializes config.yaml, so an
# unnecessary run perturbs a file the live gateway reads. SKILL_CONCIERGE_HARNESS keeps the
# server's own harness-sensitive answers right; SKILL_HERMES_ROOTS indexes the Hermes shelf.
MCP_JSON="$(python3 - "$ROOT" <<'PY'
import json, os, sys
from pathlib import Path

root = Path(sys.argv[1])
home = Path(os.environ.get("HOME", str(Path.home())))
env = {}
# The shipped engine defaults every other harness reads out of .mcp.json.
try:
    shipped = json.loads((root / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["skill-search"]["env"]
    if isinstance(shipped, dict):
        env.update({k: v for k, v in shipped.items() if isinstance(v, str) and v})
except (OSError, ValueError, KeyError, TypeError):
    pass
# ${HOME} is expanded by Claude Code in .mcp.json; Hermes does not expand it.
env = {k: v.replace("${HOME}", str(home)) for k, v in env.items()}
env["SKILL_CONCIERGE_HARNESS"] = "hermes"
env["SKILL_HERMES_ROOTS"] = "1"
print(json.dumps({
    "command": "/bin/bash",
    "args": [str(root / "bin" / "skill-search-mcp")],
    "env": env,
    "connect_timeout": 60,
    "timeout": 120,
}, sort_keys=True))
PY
)"
CURRENT_JSON="$(python3 - "$HERMES_HOME/config.yaml" <<'PY'
import json, sys
try:
    import yaml
except Exception:
    print(""); raise SystemExit(0)
try:
    conf = yaml.safe_load(open(sys.argv[1], encoding="utf-8")) or {}
    entry = (conf.get("mcp_servers") or {}).get("skill-search")
    print(json.dumps(entry, sort_keys=True) if entry else "")
except Exception:
    print("")
PY
)"
if [ -n "$CURRENT_JSON" ] && [ "$CURRENT_JSON" = "$MCP_JSON" ]; then
  echo "  [✓] mcp_servers.skill-search already current"
else
  hermes config set mcp_servers.skill-search "$MCP_JSON" >/dev/null
  echo "  [✓] mcp_servers.skill-search written to $HERMES_HOME/config.yaml"
fi

# ── 5b. Make the MCP tools visible on the surfaces that already use MCP ─────────────────────
# Registering the server is not enough: Hermes resolves a surface's tools from
# `platform_toolsets.<surface>`, and a surface that lists tools explicitly (as this profile does)
# does NOT get a new server's tools for free — measured live 2026-11-08: `search_skills` stayed
# invisible to `hermes chat` until `mcp-skill-search` joined platform_toolsets.cli. Only surfaces
# that already carry an `mcp-<server>` entry are extended: a surface whose owner never opted into
# MCP there is left exactly as it is. Prints one `<surface><TAB><json list>` line per change.
CHANGED_TOOLSETS="$(python3 - "$HERMES_HOME/config.yaml" <<'PY'
import json, sys
try:
    import yaml
except Exception:
    raise SystemExit(0)
try:
    conf = yaml.safe_load(open(sys.argv[1], encoding="utf-8")) or {}
except Exception:
    raise SystemExit(0)
for surface, tools in (conf.get("platform_toolsets") or {}).items():
    if not isinstance(tools, list) or not any(str(t).startswith("mcp-") for t in tools):
        continue
    if "mcp-skill-search" in tools:
        continue
    print(f"{surface}\t{json.dumps(list(tools) + ['mcp-skill-search'])}")
PY
)"
if [ -z "$CHANGED_TOOLSETS" ]; then
  echo "  [✓] platform_toolsets already carry mcp-skill-search (or that profile uses no MCP toolsets)"
else
  while IFS=$(printf '\t') read -r surface tools; do
    [ -n "${surface:-}" ] || continue
    hermes config set "platform_toolsets.$surface" "$tools" >/dev/null
    echo "  [✓] platform_toolsets.$surface += mcp-skill-search"
  done <<< "$CHANGED_TOOLSETS"
fi

# ── 6. Exec bits ─────────────────────────────────────────────────────────────
chmod +x "$ROOT/bin/"* "$ROOT/setup.sh" "$ROOT/adapters/hermes/install.sh" 2>/dev/null || true
echo "    bin/ + installer exec bits ensured"

# ── 7. Verify ────────────────────────────────────────────────────────────────
echo "==> verify:"
VERIFY_OK=true

# Outputs are CAPTURED before they are matched. `producer | grep -q` is a trap under
# `set -o pipefail`: grep -q exits at the first hit and closes the pipe, the producer dies of
# SIGPIPE (141), and pipefail reports the whole check as failed even though the match happened.
VALIDATE_OUT="$(hermes plugins validate "$SOURCE_DIR" 2>&1 || true)"
LIST_OUT="$(hermes plugins list 2>/dev/null || true)"
MCP_OUT="$(hermes mcp list 2>/dev/null || true)"

# 7a. Hermes's own runtime-contract check: manifest, entry, declared vs registered hooks.
case "$VALIDATE_OUT" in
  *"Validation passed"*)
    echo "    plugin validates against Hermes's runtime contracts: yes" ;;
  *)
    echo "    !! 'hermes plugins validate $SOURCE_DIR' did not pass" >&2
    printf '%s\n' "$VALIDATE_OUT" | tail -5 >&2
    VERIFY_OK=false ;;
esac

# 7b. Listed and enabled — the enable column sits on the row the name is on.
PLUGIN_ROW="$(printf '%s\n' "$LIST_OUT" | grep 'skill-concierge' || true)"
case "$PLUGIN_ROW" in
  *enabled*) echo "    plugin listed and enabled: yes" ;;
  *) echo "    !! plugin not listed as enabled (run: hermes plugins list)" >&2
     VERIFY_OK=false ;;
esac

# 7c. MCP server listed.
case "$MCP_OUT" in
  *skill-search*) echo "    MCP server 'skill-search' registered: yes" ;;
  *) echo "    !! MCP server 'skill-search' missing from 'hermes mcp list'" >&2
     VERIFY_OK=false ;;
esac

# 7c'. The MCP tools are reachable on at least one surface.
TOOLSET_OK="$(python3 - "$HERMES_HOME/config.yaml" <<'PY'
import sys
try:
    import yaml
except Exception:
    print("unknown"); raise SystemExit(0)
try:
    conf = yaml.safe_load(open(sys.argv[1], encoding="utf-8")) or {}
except Exception:
    print("unknown"); raise SystemExit(0)
surfaces = [s for s, t in (conf.get("platform_toolsets") or {}).items()
            if isinstance(t, list) and "mcp-skill-search" in t]
print(",".join(surfaces) if surfaces else "none")
PY
)"
case "$TOOLSET_OK" in
  none) echo "    !! no platform_toolsets surface carries mcp-skill-search, so the MCP tools are invisible" >&2
        echo "       (add it: hermes config set platform_toolsets.cli '<list incl mcp-skill-search>')" >&2
        VERIFY_OK=false ;;
  unknown) echo "    (platform_toolsets unreadable — MCP visibility check skipped)" ;;
  *) echo "    MCP toolsets enabled on: $TOOLSET_OK" ;;
esac

# 7d. Launcher + enforcer.
if [ -x "$ROOT/bin/skill-search-mcp" ]; then
  echo "    MCP launcher executable: yes"
else
  echo "    !! MCP launcher missing/not executable at $ROOT/bin/skill-search-mcp" >&2
  VERIFY_OK=false
fi
if [ -f "$ROOT/hooks/scripts/enforcer.py" ]; then
  echo "    enforcer script present: yes"
else
  echo "    !! enforcer script not found at $ROOT/hooks/scripts/enforcer.py" >&2
  VERIFY_OK=false
fi

# 7e. Doctor's Hermes row (a full doctor run takes ~20 s and checks everything else too).
python3 -c 'import importlib.util as u, sys
s = u.spec_from_file_location("doctor", sys.argv[1]); d = u.module_from_spec(s); s.loader.exec_module(d)
r = d.check_hermes(); print("  [" + ("✓" if r["status"] == d.OK else "!") + "] Hermes integration  " + r["detail"])' \
  "$ROOT/scripts/doctor.py" 2>/dev/null || echo "    (doctor Hermes row unavailable — run: python3 scripts/doctor.py)"

if $VERIFY_OK; then
  echo "    verify: OK"
else
  echo "    verify: FAILED — see lines above" >&2
  exit 1
fi

echo "==> Done. The plugin's hooks hot-reload on 'hermes plugins enable'; start a NEW Hermes"
echo "    session for the skill-search MCP tools. Then confirm: a session's tool list carries"
echo "    mcp_skill_search_search_skills, and its first turn opens with the SKILL-FIRST order."
