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
#       byte-identical to HEAD, omp plugin list, doctor's OMP row.
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
# Marker comment (must match the python edit below) so a re-run is idempotent.
EXT_MARKER="# skill-concierge extension entry (ADR-0039)"
EXT_ENTRY="$ROOT/adapters/omp/skill-concierge.ext.ts"

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

# Version + installPath OMP's registry records for skill-concierge@skill-concierge.
# The registry keys plugins by '<name>@<marketplace>' and stores a LIST (one
# record per scope) — both list and bare-dict shapes tolerated (doctor parity).
_omp_record() {
  python3 - "$OMP_PLUGINS_JSON" <<'PY'
import json, sys
try:
    rec = json.load(open(sys.argv[1]))
    e = rec["plugins"]["skill-concierge@skill-concierge"]
    recs = e if isinstance(e, list) else [e]
    r = recs[0]
    print(r.get("version", ""), r.get("installPath", ""), sep="\t")
except Exception:
    print("\t", end="")
PY
}

MARKETPLACE=0
if [ -f "$OMP_PLUGINS_JSON" ] && grep -q '"skill-concierge@skill-concierge"' "$OMP_PLUGINS_JSON"; then
  MARKETPLACE=1
fi

VERSION="$(python3 -c "import json;print(json.load(open('$ROOT/.claude-plugin/plugin.json'))['version'])")"
echo "    SSOT version: v$VERSION"

DEST=""
if [ "$MARKETPLACE" = "1" ]; then
  # ── (a) Marketplace plugin: refresh, verify the outcome, sync as fallback. ──
  IFS=$'\t' read -r INSTALLED INSTALLED_PATH <<<"$(_omp_record)"
  PINNED="$OMP_PLUGIN_CACHE/skill-concierge___skill-concierge___$VERSION"

  if [ "$INSTALLED" = "$VERSION" ] && [ -d "$INSTALLED_PATH" ] \
     && [ -f "$INSTALLED_PATH/adapters/omp/skill-concierge.ext.ts" ]; then
    echo "  [✓] Already current: OMP deploy v$INSTALLED == SSOT v$VERSION"
    DEST="$INSTALLED_PATH"
  else
    echo "  [•] OMP deploy v${INSTALLED:-none} != SSOT v$VERSION -> refreshing via omp CLI"
    if omp plugin marketplace update skill-concierge; then :; else
      echo "    [!] 'omp plugin marketplace update' failed (offline? marketplace down?)" >&2
    fi
    if omp plugin upgrade skill-concierge@skill-concierge --scope user; then :; else
      echo "    [!] 'omp plugin upgrade' failed — falling back to checkout sync" >&2
    fi
    IFS=$'\t' read -r INSTALLED INSTALLED_PATH <<<"$(_omp_record)"

    if [ "$INSTALLED" != "$VERSION" ]; then
      # ── Manual sync fallback (ZCode §2-4 parity): export HEAD → cache dir. ──
      if [ -n "$INSTALLED" ] && ! _ver_ge "$VERSION" "$INSTALLED"; then
        echo "!! refusing to downgrade: deployed OMP copy v$INSTALLED is NEWER than" >&2
        echo "   this checkout v$VERSION. Update the checkout (git pull) or keep the" >&2
        echo "   newer deployed copy — a stale checkout never downgrades (ADR-0042)." >&2
        exit 1
      fi
      echo "  [•] CLI did not reach SSOT -> syncing this checkout into the OMP cache"
      DEST="$PINNED"
      mkdir -p "$DEST"
      if [ -d "$ROOT/.git" ]; then
        git -C "$ROOT" archive HEAD | tar -x -C "$DEST"
      else
        # Non-git checkout: copy everything except VCS/scratch dirs.
        tar -C "$ROOT" -cf - \
            --exclude='.git' --exclude='.ijfw' --exclude='ijfw' --exclude='.handoff' \
            --exclude='logs' --exclude='graphify-out' --exclude='.claude' \
            --exclude='.zcode' --exclude='.unlazy' \
            --exclude='node_modules' --exclude='__pycache__' --exclude='.venv' \
            . | tar -xf - -C "$DEST"
      fi
      echo "    exported HEAD → $DEST"
      chmod +x "$DEST/bin/"* "$DEST/setup.sh" \
               "$DEST/adapters/omp/install.sh" "$DEST/adapters/zcode/install.sh" \
               "$DEST/adapters/commandcode/install.sh" 2>/dev/null || true
      echo "    bin/ + installer exec bits ensured"

      # ── Registry repoint (backup first) — OMP schema: map of LISTS. ──
      python3 - "$OMP_PLUGINS_JSON" "$DEST" "$VERSION" <<'PY'
import json, shutil, sys, time
from pathlib import Path
reg_path, install_path, version = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
data = json.loads(reg_path.read_text(encoding="utf-8"))
plugins = data.get("plugins", {})
entry = plugins.get("skill-concierge@skill-concierge")
if not entry:
    print("!! registry lost the skill-concierge@skill-concierge entry mid-run", file=sys.stderr)
    sys.exit(1)
records = entry if isinstance(entry, list) else [entry]
backup = reg_path.with_suffix(".json.bak-sc-" + time.strftime("%Y%m%d-%H%M%S"))
shutil.copy2(reg_path, backup)
now = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
for rec in records:
    rec["version"] = version
    rec["installPath"] = install_path
    rec["lastUpdated"] = now
reg_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
print(f"    registry → v{version} (backup: {backup.name})")
PY
    else
      DEST="$INSTALLED_PATH"
    fi
  fi
else
  # ── (b) No marketplace plugin -> dev mode (config.yml extensions entry). ──
  echo "  [•] No marketplace plugin -> dev mode (config.yml extensions entry)"
  if [ ! -f "$EXT_ENTRY" ]; then
    echo "  [!] Error: extension source not found at $EXT_ENTRY" >&2
    exit 1
  fi
  # YAML-safe via python3 (no yq). The marker + entry pair is inserted after the
  # existing `extensions:` block (or the key is created at EOF). Re-runs are
  # no-ops: an existing pair or bare entry is left untouched.
  python3 - "$OMP_CONFIG" "$EXT_ENTRY" "$EXT_MARKER" <<'PYEOF'
import sys
from pathlib import Path

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
p.write_text(text, encoding="utf-8")
print("  [✓] Appended extension entry to", config_path)
PYEOF
fi

# ── (c) Verify wiring (ZCode §6 parity) ──────────────────────────────────────
echo "==> verify:"
if [ "$MARKETPLACE" = "1" ] && [ -n "$DEST" ]; then
  test "$(python3 -c "import json;print(json.load(open('$DEST/.claude-plugin/plugin.json'))['version'])")" = "$VERSION" \
    && echo "    cache manifest: v$VERSION" \
    || { echo "    !! cache manifest version mismatch" >&2; exit 1; }
  test -x "$DEST/bin/skill-search-mcp" && echo "    launcher executable: yes" \
    || echo "    [!] launcher not executable at $DEST/bin/skill-search-mcp" >&2
  diff -q "$ROOT/hooks/scripts/enforcer.py" "$DEST/hooks/scripts/enforcer.py" >/dev/null 2>&1 \
    && echo "    enforcer byte-identical to repo HEAD: yes" \
    || echo "    [!] enforcer differs from repo HEAD (deployed copy is a foreign build)" >&2
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
