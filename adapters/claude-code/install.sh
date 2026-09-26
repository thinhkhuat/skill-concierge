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
# deliberately no --no-mcp / --mcp-fallback flag here (unlike Cline / ZCode).
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

# ver_ge A B — true iff dotted-integer version A >= B ("0.43.10" >= "0.43.9").
# Same comparator as bin/skill-search-mcp (the one-directional doctrine).
_ver_ge() {
  [ "$1" = "$2" ] && return 0
  awk -v a="$1" -v b="$2" 'BEGIN{
    na=split(a,A,"."); nb=split(b,B,"."); n=(na>nb)?na:nb
    for(i=1;i<=n;i++){x=(i<=na)?A[i]+0:0; y=(i<=nb)?B[i]+0:0
      if(x>y) exit 0; if(x<y) exit 1}
    exit 0}'
}

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
    print(r.get("version", ""), r.get("installPath", ""), r.get("scope", "user"), sep="\t")
except Exception:
    print("\t\t", end="")
PY
}

# _deployed_ver PATH — the version the cache CONTENT carries (its own manifest),
# falling back to the registry's record only when the manifest is unreadable.
# The registry can record a version whose content came from a stale marketplace
# pull, so the manifest, not the record, decides "already current".
_deployed_ver() {
  python3 -c "import json,sys;print(json.load(open(sys.argv[1]+'/.claude-plugin/plugin.json'))['version'])" "$1" 2>/dev/null
}

VERSION="$(python3 -c "import json;print(json.load(open('$ROOT/.claude-plugin/plugin.json'))['version'])")"
echo "    SSOT version: v$VERSION"

# A git checkout installs HEAD (`git archive HEAD`), so HEAD's version is the one to install. An
# uncommitted version change would put HEAD's content in a dir named for the new version: refuse
# before any CLI call or write.
if [ "$(git -C "$ROOT" rev-parse --show-toplevel 2>/dev/null)" = "$(cd "$ROOT" && pwd -P)" ]; then
  HEAD_VERSION="$(git -C "$ROOT" show HEAD:.claude-plugin/plugin.json 2>/dev/null \
    | python3 -c "import json,sys;print(json.load(sys.stdin)['version'])" 2>/dev/null || true)"
  if [ "$HEAD_VERSION" != "$VERSION" ]; then
    echo "!! .claude-plugin/plugin.json says v$VERSION but HEAD carries v${HEAD_VERSION:-none}; this installer" >&2
    echo "   installs HEAD. Commit the version change (or restore the file), then re-run." >&2
    exit 1
  fi
fi

if [ ! -f "$CLAUDE_PLUGINS_JSON" ] || ! grep -q "\"$PLUGIN_ID\"" "$CLAUDE_PLUGINS_JSON"; then
  echo "!! no skill-concierge@skill-concierge entry in $CLAUDE_PLUGINS_JSON" >&2
  echo "   Install it once via:" >&2
  echo "     claude plugin marketplace add https://github.com/thinhkhuat/skill-concierge.git" >&2
  echo "     claude plugin install skill-concierge@skill-concierge --scope user -y" >&2
  echo "   then re-run this installer." >&2
  exit 1
fi

IFS=$'\t' read -r INSTALLED INSTALLED_PATH SCOPE <<<"$(_claude_record)"
SCOPE="${SCOPE:-user}"
DEPLOYED="$(_deployed_ver "$INSTALLED_PATH")"; DEPLOYED="${DEPLOYED:-$INSTALLED}"

DEST=""
if [ "$INSTALLED" = "$VERSION" ] && [ "$DEPLOYED" = "$VERSION" ] && [ -d "$INSTALLED_PATH" ] \
   && [ -x "$INSTALLED_PATH/bin/skill-search-mcp" ]; then
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

  IFS=$'\t' read -r INSTALLED INSTALLED_PATH SCOPE <<<"$(_claude_record)"
  SCOPE="${SCOPE:-user}"
  DEPLOYED="$(_deployed_ver "$INSTALLED_PATH")"; DEPLOYED="${DEPLOYED:-$INSTALLED}"

  if [ "$INSTALLED" != "$VERSION" ] || [ "$DEPLOYED" != "$VERSION" ]; then
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
    mkdir -p "$DEST"
    if [ "$(git -C "$ROOT" rev-parse --show-toplevel 2>/dev/null)" = "$(cd "$ROOT" && pwd -P)" ]; then
      git -C "$ROOT" archive HEAD | tar -x -C "$DEST"
      echo "    exported HEAD → $DEST"
    else
      # Non-git checkout: copy everything except VCS/scratch dirs.
      tar -C "$ROOT" -cf - \
          --exclude='.git' --exclude='.ijfw' --exclude='ijfw' --exclude='.handoff' \
          --exclude='logs' --exclude='graphify-out' --exclude='.claude' \
          --exclude='.zcode' --exclude='.unlazy' \
          --exclude='node_modules' --exclude='__pycache__' --exclude='.venv' \
          --exclude='.pytest_cache' --exclude='.mypy_cache' --exclude='.ruff_cache' \
          . | tar -xf - -C "$DEST"
      echo "    copied the working tree (not a git checkout) → $DEST"
    fi
    chmod +x "$DEST/bin/"* "$DEST/setup.sh" "$DEST"/adapters/*/install.sh 2>/dev/null || true
    echo "    bin/ + installer exec bits ensured"

    HEAD_SHA="$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || echo "")"

    # ── Registry repoint (backup first, written atomically) — map of LISTS,
    # one record per scope. A plain write-in-place would race a live Claude
    # Code session's own read-modify-write of the same file; write a temp
    # file in the same directory and os.replace() it into place instead. ──
    python3 - "$CLAUDE_PLUGINS_JSON" "$DEST" "$VERSION" "$HEAD_SHA" <<'PY'
import json, os, shutil, sys, time
from pathlib import Path
reg_path, install_path, version, head_sha = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
data = json.loads(reg_path.read_text(encoding="utf-8"))
plugins = data.get("plugins", {})
entry = plugins.get("skill-concierge@skill-concierge")
if not entry:
    print("!! registry lost the skill-concierge@skill-concierge entry mid-run", file=sys.stderr)
    sys.exit(1)
records = entry if isinstance(entry, list) else [entry]
backup = reg_path.with_suffix(".json.bak-claude-code-" + time.strftime("%Y%m%d-%H%M%S"))
shutil.copy2(reg_path, backup)
now = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
for rec in records:
    rec["version"] = version
    rec["installPath"] = install_path
    rec["lastUpdated"] = now
    if head_sha:
        rec["gitCommitSha"] = head_sha
tmp_path = reg_path.with_name(reg_path.name + f".tmp-{os.getpid()}")
tmp_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
os.replace(tmp_path, reg_path)
print(f"    registry → v{version} (backup: {backup.name})")
PY
  else
    DEST="$INSTALLED_PATH"
  fi
fi

# ── Verify (OMP/ZCode parity) ────────────────────────────────────────────────
echo "==> verify:"
VERIFY_OK=true
if [ -n "$DEST" ]; then
  if test "$(python3 -c "import json;print(json.load(open('$DEST/.claude-plugin/plugin.json'))['version'])")" = "$VERSION"; then
    echo "    cache manifest: v$VERSION"
  else
    echo "    !! cache manifest version mismatch" >&2
    VERIFY_OK=false
  fi
  if test -x "$DEST/bin/skill-search-mcp"; then
    echo "    launcher executable: yes"
  else
    echo "    [!] launcher not executable at $DEST/bin/skill-search-mcp" >&2
  fi
  if diff -q "$ROOT/hooks/scripts/enforcer.py" "$DEST/hooks/scripts/enforcer.py" >/dev/null 2>&1; then
    echo "    enforcer byte-identical to repo HEAD: yes"
  else
    echo "    [!] enforcer differs from repo HEAD (deployed copy is a foreign build)" >&2
  fi
fi
IFS=$'\t' read -r FINAL_INSTALLED _ _ <<<"$(_claude_record)"
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
