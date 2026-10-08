#!/usr/bin/env bash
# skill-concierge — Claude Code installer / synchronizer / repair.
#
# Claude Code is the reference harness for this plugin format: it natively reads
# `.claude-plugin/` manifests, fires the plugin hooks, and auto-connects the
# plugin `.mcp.json` (its `${CLAUDE_PLUGIN_ROOT}` expansion is what every other
# adapter's fallback exists to work around). This installer keeps the marketplace
# install in sync with THIS checkout, on par with the OMP/ZCode installers
# (sync + verify; doctor's "Claude Code integration" row reports the result):
#   1. SSOT version read from $ROOT/.claude-plugin/plugin.json
#   2. One-directional guard: refuse if the deployed copy is NEWER than this
#      checkout — before any CLI call, no writes (same ADR-0042 doctrine as the
#      re-check after the CLI, below).
#   3. Fast path: registry + cache content already at SSOT -> no writes, verify only.
#   4. Otherwise refresh via `claude plugin update` — then VERIFY the outcome (the
#      CLI pulls from the marketplace's git remote, so it can only ever reach
#      whatever is PUSHED to that remote; a local checkout ahead of origin will
#      not be reached by the CLI at all).
#   5. If the CLI did not reach the SSOT (the normal case for an unpushed
#      checkout, or if the CLI errored), fall back to a manual sync from this
#      checkout: git archive HEAD -> the versioned cache dir
#      cache/skill-concierge/skill-concierge/<version>/, exec bits ensured,
#      then repoint installed_plugins.json (backup first, written atomically).
#      This installs code that has NOT been published to the marketplace
#      remote — the script says so on stderr with a `!!` notice.
#
# IMPORTANT — MCP: the plugin package carries `.mcp.json` with
# `${CLAUDE_PLUGIN_ROOT}` interpolation, and Claude Code expands that natively
# (the OMP precedent). We DO NOT write a second, manual MCP entry anywhere:
# a duplicate `skill-search` declaration is a known hazard. There is
# deliberately no --no-mcp / --mcp-fallback flag here (unlike ZCode).
#
# `-y` is passed to `claude plugin update` because a non-interactive run needs
# it. Per --help, `-y` accepts "the displayed marketplace-declared command"
# without the confirmation prompt, so it WOULD auto-accept a command the
# marketplace declares. This repo's marketplace declares none today. If it
# ever does, switch to the narrower `--accept-command <sha256>`, which accepts
# only that exact command.
#
# Usage:
#   ./adapters/claude-code/install.sh [--root <path>]
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

echo "==> skill-concierge → Claude Code sync (from: $ROOT)"

PLUGIN_ID="skill-concierge@skill-concierge"
CLAUDE_PLUGINS_JSON="$HOME/.claude/plugins/installed_plugins.json"
CLAUDE_PLUGIN_CACHE="$HOME/.claude/plugins/cache/skill-concierge/skill-concierge"

# Version + installPath + scope Claude Code's registry records for skill-concierge.
# The registry keys plugins by '<name>@<marketplace>' and stores a LIST (one
# record per install scope) — same shape as OMP's installed_plugins.json.
_claude_record() {
  python3 - "$CLAUDE_PLUGINS_JSON" <<'PY'
import json, sys
try:
    rec = json.load(open(sys.argv[1]))
    e = rec["plugins"]["skill-concierge@skill-concierge"]
    recs = e if isinstance(e, list) else [e]
    r = recs[0]
    print(r.get("version", ""), r.get("installPath", ""), r.get("scope", "user"), r.get("projectPath", ""),
          sep="\x1f")
except Exception:
    print("\x1f\x1f\x1f", end="")
PY
}

# _deployed_ver PATH — the version the cache CONTENT carries (its own manifest); callers fall back
# to the registry's record only when the manifest is unreadable (a missing dir included).
# The registry can record a version whose content came from a stale marketplace
# pull, so the manifest, not the record, decides "already current".
_deployed_ver() {
  python3 -c "import json,sys;print(json.load(open(sys.argv[1]+'/.claude-plugin/plugin.json'))['version'])" "$1" 2>/dev/null
}

VERSION="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["version"])' "$ROOT/.claude-plugin/plugin.json")"
echo "    SSOT version: v$VERSION"

_refuse_unexportable_checkout   # HEAD version / git-dir refusals (adapters/lib/sync.sh)

if [ ! -f "$CLAUDE_PLUGINS_JSON" ] || ! grep -q "\"$PLUGIN_ID\"" "$CLAUDE_PLUGINS_JSON"; then
  echo "!! no skill-concierge@skill-concierge entry in $CLAUDE_PLUGINS_JSON" >&2
  echo "   Install it once via:" >&2
  echo "     claude plugin marketplace add https://github.com/thinhkhuat/skill-concierge.git" >&2
  echo "     claude plugin install skill-concierge@skill-concierge --scope user -y" >&2
  echo "   then re-run this installer." >&2
  exit 1
fi

IFS=$'\x1f' read -r INSTALLED INSTALLED_PATH SCOPE PROJECT_PATH <<<"$(_claude_record)"
SCOPE="${SCOPE:-user}"
DEPLOYED="$(_deployed_ver "$INSTALLED_PATH" || true)"; DEPLOYED="${DEPLOYED:-$INSTALLED}"

# Current means the version and the files the MCP server needs; a lost exec bit is repaired below
# without a CLI call.
_current() {
  [ "$INSTALLED" = "$VERSION" ] && [ "$DEPLOYED" = "$VERSION" ] && [ -d "$INSTALLED_PATH" ] \
    && [ -f "$INSTALLED_PATH/bin/skill-search-mcp" ]
}

DEST=""
if _current; then
  echo "  [✓] Already current: Claude Code deploy v$INSTALLED (content v$DEPLOYED) == SSOT v$VERSION"
  DEST="$INSTALLED_PATH"
else
  # ── One-directional downgrade guard — before any CLI call, no writes ──────
  if [ -n "$DEPLOYED" ] && ! _ver_ge "$VERSION" "$DEPLOYED"; then
    echo "!! refusing to downgrade: deployed Claude Code copy v$DEPLOYED is NEWER than" >&2
    echo "   this checkout v$VERSION. Update the checkout (git pull) or keep the newer" >&2
    echo "   deployed copy — a stale checkout never downgrades (ADR-0042 doctrine)." >&2
    exit 1
  fi

  echo "  [•] Claude Code deploy v${INSTALLED:-none} (content v${DEPLOYED:-none}) != SSOT v$VERSION -> refreshing via claude CLI"
  if command -v claude >/dev/null 2>&1; then
    if claude plugin update "$PLUGIN_ID" --scope "$SCOPE" --json -y; then :; else
      echo "    [!] 'claude plugin update' failed — falling back to checkout sync" >&2
    fi
  else
    echo "    [!] 'claude' binary not on PATH — skipping CLI refresh, falling back to checkout sync" >&2
  fi

  IFS=$'\x1f' read -r INSTALLED INSTALLED_PATH SCOPE PROJECT_PATH <<<"$(_claude_record)"
  SCOPE="${SCOPE:-user}"
  DEPLOYED="$(_deployed_ver "$INSTALLED_PATH" || true)"; DEPLOYED="${DEPLOYED:-$INSTALLED}"

  # A current version with a missing dir or launcher is repaired from this checkout too: the CLI
  # sees nothing to update there.
  if ! _current; then
    # ── Manual sync fallback (OMP/ZCode parity): export HEAD → cache dir. ──
    if [ -n "$DEPLOYED" ] && ! _ver_ge "$VERSION" "$DEPLOYED"; then
      echo "!! refusing to downgrade: after the CLI refresh, deployed Claude Code copy v$DEPLOYED" >&2
      echo "   is NEWER than this checkout v$VERSION. Update the checkout (git pull) and re-run." >&2
      exit 1
    fi
    echo "  [•] CLI did not reach SSOT -> syncing this checkout into the Claude Code cache"
    echo "!! This deploys code from the local checkout that the marketplace remote" >&2
    echo "   (github.com/thinhkhuat/skill-concierge) may not carry yet — the normal" >&2
    echo "   case when a version bump has not been pushed." >&2
    DEST="$CLAUDE_PLUGIN_CACHE/$VERSION"
    _export_to "$DEST"   # staged, then swapped in: no stale files from an older tree survive
    chmod +x "$DEST/bin/"* "$DEST/setup.sh" "$DEST"/adapters/*/install.sh 2>/dev/null || true
    echo "    bin/ + installer exec bits ensured"

    HEAD_SHA=""
    if _is_own_checkout; then HEAD_SHA="$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || echo "")"; fi

    # ── Registry repoint: only the record this run read (its scope and project). The write
    # goes through adapters/lib/safe_write.py, which resolves the file a symlink points at (a
    # dotfiles setup), keeps its permissions, and swaps it in with os.replace, so no reader ever
    # sees half a file. If the file changed since it was read (a live Claude Code session writing
    # it), the repoint stops rather than overwrite that change; a write in the instant between
    # that last check and the swap is not caught. The backup sits beside the registry path Claude
    # Code reads; the newest five are kept. ──
    PYTHONPATH="$SCRIPT_DIR/../lib" python3 - "$CLAUDE_PLUGINS_JSON" "$DEST" "$VERSION" "$HEAD_SHA" "$SCOPE" "$PROJECT_PATH" <<'PY'
import sys
import time

import safe_write

reg_path, install_path, version, head_sha, scope, project = sys.argv[1:7]
now = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())


def mutate(data):
    entry = data.get("plugins", {}).get("skill-concierge@skill-concierge")
    if not entry:
        raise RuntimeError("registry lost the skill-concierge@skill-concierge entry mid-run")
    records = entry if isinstance(entry, list) else [entry]
    targets = [r for r in records
               if r.get("scope", "user") == scope and (r.get("projectPath") or "") == project] or records[:1]
    for rec in targets:
        rec["version"] = version
        rec["installPath"] = install_path
        rec["lastUpdated"] = now
        if head_sha:
            rec["gitCommitSha"] = head_sha
        else:
            rec.pop("gitCommitSha", None)   # a plain copy has no commit of its own


try:
    _real, backup = safe_write.write_registry(reg_path, mutate, "claude-code")
except RuntimeError as e:
    print(f"!! {e}", file=sys.stderr)
    sys.exit(1)
where = f"scope {scope}" + (f", project {project}" if project else "")
print(f"    registry → v{version} for {where} (backup: {backup.name})")
PY
  else
    DEST="$INSTALLED_PATH"
  fi
fi

# ── Exec bits (self-heal on every path: a CLI-installed copy can ship without them) ──
[ -n "$DEST" ] && chmod +x "$DEST/bin/"* 2>/dev/null || true

# ── Verify (OMP/ZCode parity) ────────────────────────────────────────────────
echo "==> verify:"
VERIFY_OK=true
if [ -n "$DEST" ]; then
  if test "$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["version"])' "$DEST/.claude-plugin/plugin.json")" = "$VERSION"; then
    echo "    cache manifest: v$VERSION"
  else
    echo "    !! cache manifest version mismatch" >&2
    VERIFY_OK=false
  fi
  # The MCP server starts through this launcher; Claude Code runs it with bash, so a missing file
  # fails the verify and a missing exec bit only warns.
  if test -x "$DEST/bin/skill-search-mcp"; then
    echo "    launcher executable: yes"
  elif test -f "$DEST/bin/skill-search-mcp"; then
    echo "    [!] launcher not executable at $DEST/bin/skill-search-mcp" >&2
  else
    echo "    !! launcher missing at $DEST/bin/skill-search-mcp" >&2
    VERIFY_OK=false
  fi
  if diff -q "$ROOT/hooks/scripts/enforcer.py" "$DEST/hooks/scripts/enforcer.py" >/dev/null 2>&1; then
    echo "    enforcer identical to this checkout's: yes"
  else
    echo "    [!] enforcer differs from this checkout's (deployed copy is another build)" >&2
  fi
fi
IFS=$'\x1f' read -r FINAL_INSTALLED _ _ _ <<<"$(_claude_record)"
if [ "$FINAL_INSTALLED" = "$VERSION" ]; then
  echo "    installed_plugins.json: v$VERSION"
else
  echo "    !! installed_plugins.json still shows v${FINAL_INSTALLED:-none}, expected v$VERSION" >&2
  VERIFY_OK=false
fi
echo "  [•] enabledPlugins untouched (this installer never edits ~/.claude/settings.json)"
python3 "$ROOT/scripts/doctor.py" 2>/dev/null | grep -i "Claude Code integration" || true
chmod +x "$0" 2>/dev/null || true

if $VERIFY_OK; then
  echo "    verify: OK"
else
  echo "    verify: FAILED — see lines above" >&2
  exit 1
fi

echo "==> Done. Restart Claude Code (new session) to load v$VERSION — the plugin cache,"
echo "    .mcp.json, and hooks are re-read at session start. Then confirm: a session's"
echo "    MCP tools list mcp__plugin_skill-concierge_skill-search__search_skills."
