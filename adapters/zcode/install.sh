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

# ver_ge A B — true iff dotted-integer version A >= B ("0.43.10" >= "0.43.9"). Same
# comparator adapters/claude-code/install.sh uses (the one-directional doctrine).
_ver_ge() {
  [ "$1" = "$2" ] && return 0
  awk -v a="$1" -v b="$2" 'BEGIN{
    na=split(a,A,"."); nb=split(b,B,"."); n=(na>nb)?na:nb
    for(i=1;i<=n;i++){x=(i<=na)?A[i]+0:0; y=(i<=nb)?B[i]+0:0
      if(x>y) exit 0; if(x<y) exit 1}
    exit 0}'
}

# _is_own_checkout — true when $ROOT is its own git top level. Compared by file identity (-ef), so a
# symlinked or case-variant path to a real checkout still counts; a plain directory inside some other
# repo does not.
_is_own_checkout() {
  local top
  top="$(git -C "$ROOT" rev-parse --show-toplevel 2>/dev/null)" || return 1
  [ -n "$top" ] && [ "$ROOT" -ef "$top" ]
}

# A git checkout installs HEAD (`git archive HEAD`), so HEAD's version is the one to install. An
# uncommitted version change (staged or not) would put HEAD's content in a dir named for the new
# version: refuse before any CLI call or write. A checkout git cannot read (git missing, a
# safe.directory refusal, a damaged repo) and one whose git dir is renamed to `git/` (the
# workbench's no-dot toggle) are refused too: copying either as a plain tree would ship its
# untracked files.
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
elif [ -e "$ROOT/.git" ]; then
  echo "!! $ROOT is a git checkout, but git cannot read it (git missing, a safe.directory refusal, or a" >&2
  echo "   damaged repo). Copying it as a plain tree would ship every untracked file. Fix git, then re-run." >&2
  exit 1
fi

# _export_to DIR — put this checkout's content at DIR through a staging dir beside it, so an
# interrupted copy never leaves a half-filled DIR that a later run reads as current. The staging
# dir is trapped (EXIT/INT/TERM) so a killed run removes it instead of leaking it forever
# (bash defers running that trap until the current foreground step — the git archive/tar
# pipeline — actually exits, so cleanup lands once that step ends, not the instant the signal
# arrives), and any
# staging dir older than 60 minutes left over from an earlier killed run is pruned before a fresh
# one is made. An existing DIR is moved aside to the hidden .DIR.replaced-<time>, which skill
# discovery skips, and only the newest such copy is kept.
_export_to() {
  local dest="$1" parent base stage old
  parent="$(dirname "$dest")"; base="$(basename "$dest")"
  mkdir -p "$parent"
  find "$parent" -maxdepth 1 -name '.staging.*' -type d -mmin +60 -exec rm -rf {} + 2>/dev/null || true
  stage="$(mktemp -d "$parent/.staging.XXXXXX")"
  trap 'rm -rf "$stage"; exit 1' EXIT INT TERM
  if _is_own_checkout; then
    if ! git -C "$ROOT" archive HEAD | tar -x -C "$stage"; then
      echo "!! exporting HEAD to $dest failed (see above); nothing was changed" >&2; exit 1
    fi
    echo "    exported HEAD → $dest"
  else
    # Non-git checkout: copy everything except VCS/scratch dirs.
    if ! tar -C "$ROOT" -cf - \
        --exclude='.git' --exclude='.ijfw' --exclude='ijfw' --exclude='.handoff' \
        --exclude='logs' --exclude='graphify-out' --exclude='.claude' \
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
# atomically, backed up only after a change-during-run check passes (same doctrine as the
# claude-code/OMP repoint) ───────────────────────────────────────────────────
python3 - "$REG_FILE" "$DEST" "$VERSION" <<'PY'
import json, os, shutil, sys, time
from pathlib import Path
reg_path = Path(os.path.realpath(sys.argv[1]))
install_path, version = sys.argv[2], sys.argv[3]
raw = reg_path.read_bytes()
data = json.loads(raw.decode("utf-8"))
entry = None
for p in data.get("plugins", []):
    if p.get("id") == "skill-concierge@skill-concierge":
        entry = p
        break
if entry is None:
    print("!! no skill-concierge@skill-concierge entry in the registry — install once via "
          "Settings → Plugin Management → Discover (Get), then re-run this sync.", file=sys.stderr)
    sys.exit(1)
entry["version"] = version
entry["installPath"] = install_path
entry["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
tmp_path = reg_path.with_name(reg_path.name + f".tmp-{os.getpid()}")
tmp_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
shutil.copymode(reg_path, tmp_path)
if reg_path.read_bytes() != raw:
    tmp_path.unlink()
    print("!! installed_plugins.json changed while this ran (a live session?) — not repointed; re-run",
          file=sys.stderr)
    sys.exit(1)
reg_dir = Path(sys.argv[1]).parent
backup = reg_dir / f"installed_plugins.json.bak-zcode-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"
backup.write_bytes(raw)
for old in sorted(reg_dir.glob("installed_plugins.json.bak-zcode-*"))[:-5]:
    old.unlink()
os.replace(tmp_path, reg_path)
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
  && echo "    enforcer byte-identical to this checkout's working tree: yes"
python3 "$ROOT/scripts/doctor.py" 2>/dev/null | grep -i "ZCode integration" || true
echo "==> Done. Restart ZCode to load v$VERSION (hooks + MCP server re-read at session start)."
echo "    Then confirm: Settings → MCP shows the plugin server connected, and a session lists"
echo "    mcp__plugin_skill-concierge_skill-search__search_skills."
