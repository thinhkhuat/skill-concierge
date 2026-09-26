#!/usr/bin/env bash
# skill-concierge — Codex installer / synchronizer / repair (ADR-0033).
#
# Codex has no `plugin upgrade` verb and no local install-record file:
# enablement lives only in ~/.codex/config.toml (no version field), and the
# deployed content is discovered by scanning
# ~/.codex/plugins/cache/skill-concierge/skill-concierge/<version>/ for the
# newest all-numeric-dotted dir whose own .codex-plugin/plugin.json parses.
#
# Sync sequence (idempotent):
#   1. Read the SSOT version from $ROOT/.claude-plugin/plugin.json.
#   2. One-directional guard: refuse if the cached copy is NEWER than this
#      checkout — no CLI call, no write.
#   3. Fast path: cache already at SSOT with skills/ + plugin.json present ->
#      no CLI calls, straight to verify.
#   4. Otherwise: `codex plugin marketplace upgrade` (best effort), then
#      `codex plugin add` — NEVER `codex plugin remove`. `remove` deletes the
#      plugin's whole cache tree AND its config.toml entry; a failed `add`
#      right after that would leave Codex with nothing installed while this
#      script still reported success. A bare `add` on an already-installed
#      plugin refreshes it in place with no separate uninstall step, and a
#      FAILED `add` leaves the previous install exactly where it was — a
#      broken refresh never uninstalls.
#   5. `codex plugin add` re-enables the plugin unconditionally — Codex has no
#      plugin enable/disable subcommand and no `-c ...enabled=false` override
#      that persists. If the plugin is already installed
#      but disabled, the script refuses BEFORE `marketplace upgrade` or `add`
#      runs — zero mutating CLI calls — rather than refreshing it first and
#      only complaining afterward. A post-refresh mismatch check remains as a
#      backstop.
#   6. After `add`, `codex plugin list --json` — not just files on disk —
#      decides what happens next: if `add` failed OR the plugin does not show
#      installed, exit 1 immediately and the manual-checkout fallback (step 7)
#      never runs. If it IS installed but the cache version still lags the
#      SSOT (the git marketplace only ever has what is PUSHED to its remote —
#      an unpushed local commit is the normal reason), fall through to the
#      fallback.
#   7. Fallback: `git archive HEAD` (or a plain tar copy for a non-git
#      checkout) straight into a new versioned cache dir. Codex re-scans that
#      dir tree on every `plugin list` call, so a dropped-in version dir is
#      discovered with zero further CLI involvement — there is no registry to
#      repoint. This step NEVER deletes anything itself, and a running Codex
#      session could be using an existing dir right now. NOTE — Codex's OWN
#      `add` (step 4) is far more aggressive than this script: it was observed
#      live to unconditionally wipe the ENTIRE cache/skill-concierge/skill-
#      concierge/ directory — every version dir, every non-version staging
#      dir (e.g. plugin-install-<random>/), first install or refresh alike —
#      before installing the fresh version. That is Codex's own behavior at
#      step 4/6, not this script's; the fallback only ever runs AFTER `add`
#      already succeeded, so it starts from whatever `add` just left behind
#      (the one version dir it installed) and only ever adds to that.
#   8. Verify: cache manifest version, skills/, launcher exec bit,
#      .codex-plugin/mcp.json + .codex/hooks.json, enforcer byte-identical to
#      HEAD, `codex plugin list --json` installed state (refresh path only),
#      doctor's Codex row.
#
# _cached_version() sorts candidate version dirs by a dotted-integer key
# (matching Codex's own semver-aware resolution, and scripts/doctor.py's
# _codex_cached_version()), ignoring any dir whose name is not
# `^\d+(\.\d+)*$` — the cache also holds non-version staging dirs.
#
# MCP: Codex auto-discovers .codex-plugin/mcp.json and .codex/hooks.json from
# the cached plugin tree; there is deliberately no --mcp-fallback flag here.
#
# Bootstrap: this script SYNCS an existing registration. If neither the
# marketplace nor the plugin is registered yet, it prints the one-time
# bootstrap commands and exits 1.
#
# Usage:
#   ./adapters/codex/install.sh [--root <path>]
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

echo "==> skill-concierge → Codex sync (from: $ROOT)"

MARKETPLACE_NAME="skill-concierge"
PLUGIN_SELECTOR="skill-concierge@skill-concierge"
CODEX_PLUGIN_CACHE="$HOME/.codex/plugins/cache/skill-concierge/skill-concierge"

# ver_ge A B — true iff dotted-integer version A >= B. Same one-directional
# doctrine and idiom as OMP/ZCode/Claude Code's comparator: a stale checkout
# must never downgrade a newer deployed copy.
_ver_ge() {
  [ "$1" = "$2" ] && return 0
  awk -v a="$1" -v b="$2" 'BEGIN{
    na=split(a,A,"."); nb=split(b,B,"."); n=(na>nb)?na:nb
    for(i=1;i<=n;i++){x=(i<=na)?A[i]+0:0; y=(i<=nb)?B[i]+0:0
      if(x>y) exit 0; if(x<y) exit 1}
    exit 0}'
}

# _cached_version — the version the newest Codex-cached content dir declares
# in its own .codex-plugin/plugin.json, or "" when the cache is absent/
# unreadable/only holds non-version dirs. See the header for the sort rule.
_cached_version() {
  python3 - "$CODEX_PLUGIN_CACHE" <<'PY'
import json, re, sys
from pathlib import Path

VER_RE = re.compile(r"^\d+(\.\d+)*$")

def ver_key(name):
    return tuple(int(p) for p in name.split("."))

base = Path(sys.argv[1])
result = ""
if base.is_dir():
    candidates = sorted(
        (d for d in base.iterdir() if d.is_dir() and VER_RE.match(d.name)),
        key=lambda d: ver_key(d.name), reverse=True)
    for cand in candidates:
        pf = cand / ".codex-plugin" / "plugin.json"
        if pf.exists():
            try:
                result = json.loads(pf.read_text(encoding="utf-8")).get("version", "")
            except Exception:
                result = ""
            break
print(result)
PY
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

CACHED="$(_cached_version)"
DEST="$CODEX_PLUGIN_CACHE/$CACHED"

# ── One-directional downgrade guard — before any CLI call, no writes ────────
if [ -n "$CACHED" ] && ! _ver_ge "$VERSION" "$CACHED"; then
  echo "!! refusing to downgrade: Codex cache v$CACHED is NEWER than this checkout v$VERSION." >&2
  echo "   Update the checkout (git pull) or keep the newer cached copy — a stale checkout" >&2
  echo "   never downgrades a live install (ADR-0042 doctrine)." >&2
  exit 1
fi

REFRESHED=0
if [ "$CACHED" = "$VERSION" ] && [ -d "$DEST/skills" ] && [ -f "$DEST/.codex-plugin/plugin.json" ]; then
  # ── Fast path: already current, no CLI calls, no content writes (the
  # self-heal exec-bit chmod below still runs on every path) ─────────────────
  echo "  [✓] Already current: Codex cache v$CACHED == SSOT v$VERSION"
else
  REFRESHED=1
  echo "  [•] Codex cache v${CACHED:-none} != SSOT v$VERSION -> checking Codex registration"

  MKT_JSON="$(codex plugin marketplace list --json 2>/dev/null || echo '{"marketplaces":[]}')"
  PLG_JSON="$(codex plugin list --json 2>/dev/null || echo '{"installed":[]}')"

  read -r MKT_REGISTERED PLUGIN_INSTALLED ENABLED_BEFORE <<<"$(python3 - "$MKT_JSON" "$PLG_JSON" "$MARKETPLACE_NAME" "$PLUGIN_SELECTOR" <<'PY'
import json, sys
mkt, plg, mkt_name, plugin_sel = json.loads(sys.argv[1]), json.loads(sys.argv[2]), sys.argv[3], sys.argv[4]
registered = mkt_name in [m.get("name") for m in mkt.get("marketplaces", [])]
rec = next((p for p in plg.get("installed", [])
            if p.get("pluginId") == plugin_sel and p.get("installed")), None)
print("1" if registered else "0",
      "1" if rec else "0",
      ("1" if rec.get("enabled") else "0") if rec else "na")
PY
)"

  # ── Disabled-plugin guard — before any mutating CLI call ────────────────
  # `codex plugin add` always re-enables a plugin, and Codex has no CLI command
  # to disable one or to keep it disabled through a refresh (no plugin enable/
  # disable subcommand, and a '-c ...enabled=false' override does not persist).
  # Refuse now, before 'marketplace upgrade' or 'add' runs,
  # rather than refreshing it first and only complaining afterward.
  if [ "$PLUGIN_INSTALLED" = "1" ] && [ "$ENABLED_BEFORE" = "0" ]; then
    echo "!! '$PLUGIN_SELECTOR' is installed but disabled. 'codex plugin add' would" >&2
    echo "   unconditionally re-enable it, and Codex has no CLI command to disable one" >&2
    echo "   or to keep it disabled through a refresh (no plugin enable/disable" >&2
    echo "   subcommand, and a '-c ...enabled=false' override does not persist)." >&2
    echo "   Refusing to refresh — no marketplace upgrade or plugin add has run." >&2
    echo "   To update it, enable it first (in ~/.codex/config.toml, under" >&2
    echo "   [plugins.\"$PLUGIN_SELECTOR\"], set enabled = true), then re-run this installer;" >&2
    echo "   it stays enabled afterwards. To keep it off, leave it as it is." >&2
    exit 1
  fi

  if [ "$MKT_REGISTERED" != "1" ]; then
    echo "!! Codex has no '$MARKETPLACE_NAME' marketplace registered yet — this script syncs" >&2
    echo "   an EXISTING registration, it does not bootstrap one from zero. Bootstrap once" >&2
    echo "   (one-time, manual):" >&2
    echo "     codex plugin marketplace add <git-remote-or-local-path-to-skill-concierge>" >&2
    echo "     codex plugin add $PLUGIN_SELECTOR" >&2
    echo "   Then re-run this installer to sync." >&2
    exit 1
  fi

  echo "  [•] '$MARKETPLACE_NAME' marketplace registered -> refreshing via codex CLI"
  if codex plugin marketplace upgrade "$MARKETPLACE_NAME"; then :; else
    echo "    [!] 'codex plugin marketplace upgrade $MARKETPLACE_NAME' failed (offline? git remote unreachable?)" >&2
  fi

  # NEVER `codex plugin remove` — see header step 4.
  ADD_OK=1
  codex plugin add "$PLUGIN_SELECTOR" || { ADD_OK=0; echo "!! 'codex plugin add $PLUGIN_SELECTOR' failed." >&2; }

  PLG_JSON="$(codex plugin list --json 2>/dev/null || echo '{"installed":[]}')"
  read -r INSTALLED_AFTER ENABLED_AFTER <<<"$(python3 - "$PLG_JSON" "$PLUGIN_SELECTOR" <<'PY'
import json, sys
plg, plugin_sel = json.loads(sys.argv[1]), sys.argv[2]
rec = next((p for p in plg.get("installed", [])
            if p.get("pluginId") == plugin_sel and p.get("installed")), None)
print("1" if rec else "0", ("1" if rec.get("enabled") else "0") if rec else "na")
PY
)"

  if [ "$ADD_OK" != "1" ] || [ "$INSTALLED_AFTER" != "1" ]; then
    echo "!! Codex does not report '$PLUGIN_SELECTOR' as installed after the refresh attempt." >&2
    echo "   This script never falls back to a manual sync from this state." >&2
    if [ "$PLUGIN_INSTALLED" = "1" ]; then
      echo "   It was installed before this run, and a failed 'add' never uninstalls (Codex's" >&2
      echo "   own behavior) — the previous install should still be intact." >&2
      echo "   Restore steps: run 'codex plugin list --json' to confirm it, fix whatever error" >&2
      echo "   is printed above, then re-run this installer." >&2
    else
      echo "   Restore steps: fix the error above, then run 'codex plugin add $PLUGIN_SELECTOR'" >&2
      echo "   manually (or re-run this installer)." >&2
    fi
    exit 1
  fi

  # Backstop: the guard above already refuses before any mutating call when
  # ENABLED_BEFORE is 0, so this should be unreachable in the normal flow.
  # Kept in case the plugin's enabled state changes underneath this run.
  if [ "$ENABLED_BEFORE" = "0" ] && [ "$ENABLED_AFTER" = "1" ]; then
    echo "!! '$PLUGIN_SELECTOR' was disabled before this sync. 'codex plugin add' always" >&2
    echo "   re-enables a plugin, and Codex has no CLI command to disable one or to keep it" >&2
    echo "   disabled through a refresh (no plugin enable/disable subcommand, and a" >&2
    echo "   '-c ...enabled=false' override does not persist). The plugin is now" >&2
    echo "   enabled — this script refuses to leave that silently in place." >&2
    echo "   Restore step: if that was deliberate, disable it again manually — edit" >&2
    echo "   ~/.codex/config.toml, under [plugins.\"$PLUGIN_SELECTOR\"] set enabled = false." >&2
    exit 1
  fi

  CACHED="$(_cached_version)"
  DEST="$CODEX_PLUGIN_CACHE/$CACHED"

  if [ "$CACHED" != "$VERSION" ]; then
    # ── Manual sync fallback — only reached with the plugin confirmed
    # installed above (see header step 7). The downgrade guard applies again:
    # the CLI refresh could in principle have installed something NEWER than
    # this checkout (a teammate pushed ahead of us).
    if [ -n "$CACHED" ] && ! _ver_ge "$VERSION" "$CACHED"; then
      echo "!! refusing to downgrade: after the CLI refresh, Codex cache v$CACHED is NEWER" >&2
      echo "   than this checkout v$VERSION. Update the checkout (git pull) and re-run." >&2
      exit 1
    fi

    echo "  [•] '$MARKETPLACE_NAME' marketplace still v${CACHED:-none} after the CLI refresh" \
         "(the git remote lags this checkout) -> syncing this checkout into the Codex cache"
    echo "  !! NOTE: this deploys the LOCAL checkout DIRECTLY — it may include commits not" >&2
    echo "     yet pushed to the '$MARKETPLACE_NAME' marketplace's git remote" \
         "(https://github.com/thinhkhuat/skill-concierge.git). Once pushed, a plain" >&2
    echo "     'codex plugin marketplace upgrade $MARKETPLACE_NAME' followed by 'codex plugin" >&2
    echo "     add $PLUGIN_SELECTOR' will replace this with the canonical git-tracked copy." >&2

    DEST="$CODEX_PLUGIN_CACHE/$VERSION"
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

    # Older version dirs under this cache path are left in place, deliberately
    # — see header step 7.

    CACHED="$(_cached_version)"
    DEST="$CODEX_PLUGIN_CACHE/$CACHED"
    # The export writes HEAD, whose version the up-front check made equal to $VERSION, so the new dir
    # cannot carry another version's content. Reaching this means the export itself failed.
    if [ "$CACHED" != "$VERSION" ]; then
      echo "!! sync into the Codex cache did not take (cache now v${CACHED:-none}) — see output above." >&2
      exit 1
    fi
    echo "  [✓] Codex cache now v$CACHED == SSOT v$VERSION (synced from local checkout)"
  else
    echo "  [✓] Codex cache now v$CACHED == SSOT v$VERSION"
  fi
fi

# ── Exec bits (self-heal; a CLI-installed clone can ship without them) ──────
chmod +x "$DEST/bin/"* 2>/dev/null || true

# ── Verify ────────────────────────────────────────────────────────────────
echo "==> verify:"
VERIFY_OK=true
test "$(python3 -c "import json;print(json.load(open('$DEST/.codex-plugin/plugin.json'))['version'])" 2>/dev/null)" = "$VERSION" \
  && echo "    cache manifest: v$VERSION" \
  || { echo "    !! cache manifest version mismatch" >&2; VERIFY_OK=false; }
test -d "$DEST/skills" && echo "    skills/ present: yes" \
  || { echo "    !! skills/ missing at $DEST" >&2; VERIFY_OK=false; }
test -x "$DEST/bin/skill-search-mcp" && echo "    launcher executable: yes" \
  || echo "    [!] launcher not executable at $DEST/bin/skill-search-mcp" >&2
test -f "$DEST/.codex-plugin/mcp.json" && echo "    .codex-plugin/mcp.json present: yes" \
  || echo "    [!] .codex-plugin/mcp.json missing at $DEST" >&2
test -f "$DEST/.codex/hooks.json" && echo "    .codex/hooks.json present: yes" \
  || echo "    [!] .codex/hooks.json missing at $DEST" >&2
diff -q "$ROOT/hooks/scripts/enforcer.py" "$DEST/hooks/scripts/enforcer.py" >/dev/null 2>&1 \
  && echo "    enforcer byte-identical to repo HEAD: yes" \
  || echo "    [!] enforcer differs from repo HEAD (deployed copy is a foreign build)" >&2
if [ "$REFRESHED" = "1" ]; then
  # Registry state, not just files on disk: a filesystem-only check cannot
  # distinguish an actually-failed 'add' from one that merely lags the SSOT.
  if codex plugin list --json 2>/dev/null | python3 -c "
import json, sys
plg = json.load(sys.stdin)
rec = next((p for p in plg.get('installed', [])
            if p.get('pluginId') == '$PLUGIN_SELECTOR' and p.get('installed')), None)
sys.exit(0 if rec else 1)
" >/dev/null 2>&1; then
    echo "    codex plugin list: installed"
  else
    echo "    !! codex plugin list --json does not show '$PLUGIN_SELECTOR' installed" >&2
    VERIFY_OK=false
  fi
fi
python3 "$ROOT/scripts/doctor.py" 2>/dev/null | grep -i "Codex integration" || true

if $VERIFY_OK; then
  echo "==> Done. Restart Codex (fresh session) to load v$VERSION — hooks and .mcp.json"
  echo "    are auto-discovered from the cache at session start. Then confirm: doctor's"
  echo "    Codex integration row is OK, and a session's MCP tools list skill-search."
else
  echo "    verify: FAILED — see lines above" >&2
  exit 1
fi
