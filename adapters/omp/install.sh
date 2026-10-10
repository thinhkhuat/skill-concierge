#!/usr/bin/env bash
# skill-concierge — Oh My Pi (OMP) installer / synchronizer / repair (ADR-0039).
#
# Idempotently wires skill-concierge into OMP on this machine, on par with the
# ZCode and Command Code installers (sync + verify + doctor row):
#   (a) Marketplace plugin skill-concierge@skill-concierge installed ->
#       1. SSOT version read from $ROOT/.claude-plugin/plugin.json
#       2. Fast path: already current -> no writes, straight to verify.
#       3. Otherwise refresh via the omp CLI — then VERIFY the outcome (the CLI
#          can silently lag: OMP cache sat at 0.30.1 against a 0.38.0 SSOT).
#       4. If the CLI did not reach the SSOT, fall back to a manual sync from
#          this checkout: git archive HEAD -> the versioned cache dir
#          cache/plugins/skill-concierge___skill-concierge___<version>/,
#          exec bits ensured, then repoint installed_plugins.json (backup first).
#       One-directional guard: a checkout OLDER than the deployed copy is never
#       synced down (same doctrine as the launcher's engine resync, ADR-0042 —
#       a stale checkout must not downgrade a newer deployed plugin).
#   (b) No marketplace plugin -> dev mode -> idempotently append the repo path
#       to the `extensions:` list in ~/.omp/agent/config.yml.
#   (c) Verify wiring: cache manifest version, launcher exec bit, enforcer
#       byte-identical to this checkout's working tree, omp plugin list, doctor's OMP row.
#
# IMPORTANT — MCP: OMP already imports the marketplace plugin's `.mcp.json`
# (the plugin package carries the skill-search MCP server descriptor). We DO
# NOT write ~/.omp/agent/mcp.json here: a duplicate `skill-search` declaration
# at user scope collides with the plugin-provided server and is a known hazard
# (caveats §22.3). There is deliberately NO --mcp-fallback flag (unlike ZCode):
# see adapters/omp/mcp.json for the plugin-less manual fallback only.
#
# Claude Code and Codex ignore root package.json — this installer is OMP-only.
#
# Usage:
#   ./adapters/omp/install.sh [--root <path>]
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

echo "==> skill-concierge → OMP sync (from: $ROOT)"

OMP_PLUGINS_JSON="$HOME/.omp/plugins/installed_plugins.json"
OMP_CONFIG="$HOME/.omp/agent/config.yml"
OMP_PLUGIN_CACHE="$HOME/.omp/plugins/cache/plugins"
OMP_MARKETPLACE_CLONE="$HOME/.omp/plugins/cache/marketplaces/skill-concierge"
# Marker comment (must match the python edit below) so a re-run is idempotent.
EXT_MARKER="# skill-concierge extension entry (ADR-0039)"
EXT_ENTRY="$ROOT/adapters/omp/skill-concierge.ext.ts"

# Version + installPath + scope OMP's registry records for skill-concierge@skill-concierge.
# The registry keys plugins by '<name>@<marketplace>' and stores a LIST (one
# record per scope) — both list and bare-dict shapes tolerated (doctor parity).
# A \x1f field separator, not a tab: a tab is IFS whitespace, so an empty version field
# would shift the installPath into the version on the `read` below.
_omp_record() {
  python3 - "$OMP_PLUGINS_JSON" <<'PY'
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
# to the registry's record only when the manifest is unreadable (a missing dir included). The
# registry can record a version whose content came from a stale remote (marketplace update before
# the push), so the manifest, not the record, decides "already current".
_deployed_ver() {
  python3 -c "import json,sys;print(json.load(open(sys.argv[1]+'/.claude-plugin/plugin.json'))['version'])" "$1" 2>/dev/null
}

MARKETPLACE=0
if [ -f "$OMP_PLUGINS_JSON" ] && grep -q '"skill-concierge@skill-concierge"' "$OMP_PLUGINS_JSON"; then
  MARKETPLACE=1
fi

VERSION="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["version"])' "$ROOT/.claude-plugin/plugin.json")"
echo "    SSOT version: v$VERSION"

_refuse_unexportable_checkout   # HEAD version / git-dir refusals (adapters/lib/sync.sh)

# _omp_export_to DIR — adapters/lib/sync.sh's _export_to, minus its legacy bare '.staging.*' prune
# (see below): stage this checkout's content beside DIR, then swap it in, so an interrupted copy
# never leaves a half-filled DIR. The staging dir is trapped (EXIT/INT/TERM); one older than
# 60 minutes from a killed run is pruned. An old DIR is kept once, as hidden .DIR.replaced-<time>.
_omp_export_to() {
  local dest="$1" parent base stage old
  parent="$(dirname "$dest")"; base="$(basename "$dest")"
  mkdir -p "$parent"
  find "$parent" -maxdepth 1 -name '.skill-concierge-staging.*' -type d -mmin +60 -exec rm -rf {} + 2>/dev/null || true
  # Deliberately NOT also pruning a bare legacy '.staging.*' here, unlike the claude-code,
  # codex, and zcode adapters: $parent is $OMP_PLUGIN_CACHE ($HOME/.omp/plugins/cache/plugins)
  # — OMP's SHARED plugin-cache parent, holding every installed plugin's own dir side by
  # side, not a directory this plugin owns alone. A bare '.staging.*' there could belong to
  # a different plugin's own (unrelated) staging convention; ownership can't be proven, so it
  # is left untouched.
  stage="$(mktemp -d "$parent/.skill-concierge-staging.XXXXXX")"
  trap 'rm -rf "$stage"; exit 1' EXIT INT TERM
  if _is_own_checkout; then
    if ! git -C "$ROOT" archive HEAD | tar -x -C "$stage"; then
      echo "!! exporting HEAD to $dest failed (see above); nothing was changed" >&2; exit 1
    fi
    echo "    exported HEAD → $dest"
  else
    # A tree with no git metadata at all: copy everything except scratch dirs.
    if ! tar -C "$ROOT" -cf - \
        --exclude='.git' --exclude='.ijfw' --exclude='ijfw' --exclude='.handoff' \
        --exclude='logs' --exclude='graphify-out' --exclude='.claude' \
        --exclude='.zcode' --exclude='.unlazy' \
        --exclude='node_modules' --exclude='__pycache__' --exclude='.venv' \
        --exclude='.pytest_cache' --exclude='.mypy_cache' --exclude='.ruff_cache' \
        . | tar -xf - -C "$stage"; then
      echo "!! copying $ROOT to $dest failed (see above); nothing was changed" >&2; exit 1
    fi
    echo "    copied the working tree (not a git checkout) → $dest"
  fi
  chmod 755 "$stage"   # mktemp makes it 0700; the swapped-in tree must read like the CLI's
  if [ -e "$dest" ]; then
    for old in "$parent/.$base.replaced-"*; do [ -e "$old" ] && rm -rf "$old"; done
    mv "$dest" "$parent/.$base.replaced-$(date +%Y%m%d-%H%M%S)-$$"
  fi
  mv "$stage" "$dest"
  trap - EXIT INT TERM
}

DEST=""
if [ "$MARKETPLACE" = "1" ]; then
  # ── (a) Marketplace plugin: refresh, verify the outcome, sync as fallback. ──
  IFS=$'\x1f' read -r INSTALLED INSTALLED_PATH SCOPE PROJECT_PATH <<<"$(_omp_record)"
  SCOPE="${SCOPE:-user}"
  PINNED="$OMP_PLUGIN_CACHE/skill-concierge___skill-concierge___$VERSION"
  DEPLOYED="$(_deployed_ver "$INSTALLED_PATH" || true)"; DEPLOYED="${DEPLOYED:-$INSTALLED}"

  # Current means the version and the file the MCP server needs; a lost exec bit is repaired
  # below without a CLI call.
  _current() {
    [ "$INSTALLED" = "$VERSION" ] && [ "$DEPLOYED" = "$VERSION" ] && [ -d "$INSTALLED_PATH" ] \
      && [ -f "$INSTALLED_PATH/bin/skill-search-mcp" ]
  }

  if _current; then
    echo "  [✓] Already current: OMP deploy v$INSTALLED (content v$DEPLOYED) == SSOT v$VERSION"
    DEST="$INSTALLED_PATH"
  else
    echo "  [•] OMP deploy v${INSTALLED:-none} (content v${DEPLOYED:-none}) != SSOT v$VERSION -> refreshing via omp CLI"
    if omp plugin marketplace update skill-concierge; then :; else
      echo "    [!] 'omp plugin marketplace update' failed (offline? marketplace down?)" >&2
    fi
    if omp plugin upgrade skill-concierge@skill-concierge --scope user; then :; else
      echo "    [!] 'omp plugin upgrade' failed — falling back to checkout sync" >&2
    fi
    IFS=$'\x1f' read -r INSTALLED INSTALLED_PATH SCOPE PROJECT_PATH <<<"$(_omp_record)"
    SCOPE="${SCOPE:-user}"
    DEPLOYED="$(_deployed_ver "$INSTALLED_PATH" || true)"; DEPLOYED="${DEPLOYED:-$INSTALLED}"

    # A current version with a missing dir or launcher is repaired from this checkout too: the
    # CLI sees nothing to update there.
    if ! _current; then
      # ── Manual sync fallback (ZCode §2-4 parity): export HEAD → cache dir. ──
      if [ -n "$DEPLOYED" ] && ! _ver_ge "$VERSION" "$DEPLOYED"; then
        echo "!! refusing to downgrade: deployed OMP copy v$DEPLOYED is NEWER than" >&2
        echo "   this checkout v$VERSION. Update the checkout (git pull) or keep the" >&2
        echo "   newer deployed copy — a stale checkout never downgrades (ADR-0042)." >&2
        exit 1
      fi
      echo "  [•] CLI did not reach SSOT -> syncing this checkout into the OMP cache"
      DEST="$PINNED"
      _omp_export_to "$DEST"   # staged, then swapped in: no stale files from an older tree survive
      chmod +x "$DEST/bin/"* "$DEST/setup.sh" \
               "$DEST/adapters/omp/install.sh" "$DEST/adapters/zcode/install.sh" \
               "$DEST/adapters/commandcode/install.sh" 2>/dev/null || true
      echo "    bin/ + installer exec bits ensured"

      # ── Registry repoint: only the record this run read (its scope and project). The write
      # goes through adapters/lib/safe_write.py, which resolves the file a symlink points at (a
      # dotfiles setup), keeps its permissions, and swaps it in with os.replace, so no reader ever
      # sees half a file. If the file changes while this runs (a live OMP session writing it), the
      # repoint stops rather than overwrite that change. The backup sits beside the registry path
      # OMP reads; the newest five are kept. ──
      PYTHONPATH="$SCRIPT_DIR/../lib" python3 - "$OMP_PLUGINS_JSON" "$DEST" "$VERSION" "$SCOPE" "$PROJECT_PATH" <<'PY'
import sys
import time

import safe_write

reg_path, install_path, version, scope, project = sys.argv[1:6]
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


try:
    _real, backup = safe_write.write_registry(reg_path, mutate, "omp")
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
else
  # ── (b) No marketplace plugin -> dev mode (config.yml extensions entry). ──
  echo "  [•] No marketplace plugin -> dev mode (config.yml extensions entry)"
  # Dev mode writes this checkout's path into config.yml; a cache copy never does that.
  case "$(cd "$ROOT" && pwd -P)" in */plugins/cache/*)
    echo "!! $ROOT is a plugin cache copy, which the next plugin update deletes; OMP would then break." >&2
    echo "   Clone the repo and run adapters/omp/install.sh from the clone. Nothing was changed." >&2
    exit 1 ;;
  esac
  if [ ! -f "$EXT_ENTRY" ]; then
    echo "  [!] Error: extension source not found at $EXT_ENTRY" >&2
    exit 1
  fi
  # YAML-safe via python3 (no yq). The marker + entry pair is inserted after the
  # existing `extensions:` block (or the key is created at EOF). Re-runs are
  # no-ops: an existing pair or bare entry is left untouched.
  PYTHONPATH="$SCRIPT_DIR/../lib" python3 - "$OMP_CONFIG" "$EXT_ENTRY" "$EXT_MARKER" <<'PYEOF'
import sys
from pathlib import Path

import safe_write

config_path, entry, marker = sys.argv[1], sys.argv[2], sys.argv[3]
entry_line = f"- {entry}"
marker_line = f"  {marker}"
indented_entry = f"  {entry_line}"
p = Path(config_path)
lines = p.read_text(encoding="utf-8").splitlines() if p.exists() else []
out = []
found_ext = False
i = 0
while i < len(lines):
    line = lines[i]
    stripped = line.strip()
    if stripped == entry_line:
        # Bare entry (added by hand or another tool): keep as-is, done.
        found_ext = True
        out.append(line)
        i += 1
        continue
    if stripped == marker:
        # Marker line: keep the pair when the entry follows; drop a stale
        # orphan marker alone.
        if i + 1 < len(lines) and lines[i + 1].strip() == entry_line:
            out.append(line)
            out.append(lines[i + 1])
            i += 2
            found_ext = True
        elif i + 1 < len(lines) and lines[i + 1].strip().startswith("- "):
            # Our pair from a checkout that moved: drop it, the current entry is added below.
            i += 2
        else:
            i += 1
        continue
    out.append(line)
    i += 1

if not found_ext:
    # Ensure an `extensions:` key exists (YAML block list, 2-space indent to
    # match the rest of ~/.omp/agent/config.yml).
    has_key = any(l.strip() == "extensions:" for l in out)
    if not has_key:
        out.append("extensions:")
    # Insert marker + entry after the extensions: block (or at EOF).
    insert_at = len(out)
    for j in range(len(out) - 1, -1, -1):
        if out[j].strip() == "extensions:":
            # Skip trailing blank/indented lines to land inside the block.
            k = j + 1
            while k < len(out) and (not out[k].strip() or out[k][0].isspace()):
                k += 1
            insert_at = k
            break
    out.insert(insert_at, marker_line)
    out.insert(insert_at + 1, indented_entry)

text = "\n".join(out) + "\n"
safe_write.write_text(p, text)
print("  [✓] Appended extension entry to", config_path)
PYEOF
fi

# ── Catalog freshness (every marketplace path). The deploy can be current while OMP's own
# marketplace clone is not: a release installed locally before its push landed leaves the clone
# on the previous version, and the "Already current" path never refreshes it (found 0.61.2,
# doctor WARN "marketplace catalog stale"). Refresh it whenever it lags SSOT; a failure is
# reported, never fatal — the deploy above already serves this version.
if [ "$MARKETPLACE" = "1" ]; then
  _catalog_ver() {
    python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['plugins'][0]['version'])" \
      "$OMP_MARKETPLACE_CLONE/.claude-plugin/marketplace.json" 2>/dev/null
  }
  CATALOG="$(_catalog_ver || true)"
  if [ "$CATALOG" != "$VERSION" ]; then
    echo "  [•] OMP marketplace catalog v${CATALOG:-none} != SSOT v$VERSION -> omp plugin marketplace update"
    omp plugin marketplace update skill-concierge >/dev/null 2>&1 || true
    CATALOG="$(_catalog_ver || true)"
    if [ "$CATALOG" = "$VERSION" ]; then
      echo "    catalog now v$CATALOG"
    else
      echo "    [!] catalog still v${CATALOG:-none}: the remote does not carry v$VERSION yet (push it, then re-run)" >&2
    fi
  fi
fi

# ── Exec bits (self-heal on every path: a CLI-installed copy can ship without them) ──
if [ "$MARKETPLACE" = "1" ] && [ -n "$DEST" ]; then
  chmod +x "$DEST/bin/"* 2>/dev/null || true
fi

# ── (c) Verify wiring (ZCode §6 parity) ──────────────────────────────────────
echo "==> verify:"
if [ "$MARKETPLACE" = "1" ] && [ -n "$DEST" ]; then
  test "$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["version"])' "$DEST/.claude-plugin/plugin.json")" = "$VERSION" \
    && echo "    cache manifest: v$VERSION" \
    || { echo "    !! cache manifest version mismatch" >&2; exit 1; }
  test -x "$DEST/bin/skill-search-mcp" && echo "    launcher executable: yes" \
    || echo "    [!] launcher not executable at $DEST/bin/skill-search-mcp" >&2
  diff -q "$ROOT/hooks/scripts/enforcer.py" "$DEST/hooks/scripts/enforcer.py" >/dev/null 2>&1 \
    && echo "    enforcer byte-identical to this checkout's working tree: yes" \
    || echo "    [!] enforcer differs from this checkout's working tree (deployed copy is a foreign build)" >&2
fi
if [ "$MARKETPLACE" = "1" ]; then
  if omp plugin list 2>/dev/null | grep -q "skill-concierge"; then
    echo "  [✓] omp plugin list shows skill-concierge"
  else
    echo "  [!] Warning: 'omp plugin list' did not show skill-concierge (still proceeding; verify manually)" >&2
  fi
else
  if [ -f "$OMP_CONFIG" ] && grep -qF "$EXT_ENTRY" "$OMP_CONFIG"; then
    echo "  [✓] ~/.omp/agent/config.yml extensions: contains $EXT_ENTRY"
  else
    echo "  [!] Warning: config check did not confirm the extension entry" >&2
    exit 1
  fi
fi
# Doctor's harness-specific row (WARN-only, so we surface it but don't fail on it).
python3 "$ROOT/scripts/doctor.py" 2>/dev/null | grep -i "OMP integration" || true

# ── MCP decision (documented above): intentionally NOT written. ──
echo "  [•] Skipping ~/.omp/agent/mcp.json: OMP imports the plugin .mcp.json; a duplicate skill-search declaration is a known hazard."
chmod +x "$0" 2>/dev/null || true
echo "==> Done. Restart OMP (fresh session) to load v$VERSION — the ext module and .mcp.json"
echo "    re-read at session start. Then confirm: doctor's OMP integration row is OK, and a"
echo "    session's MCP tools list skill-search (mcp:skill-concierge:skill-search)."
