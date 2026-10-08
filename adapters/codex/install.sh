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
#   3. Fast path: cache already at SSOT with every file Codex reads present, and
#      `codex plugin list --json` showing the plugin installed -> no mutating CLI
#      call, straight to verify. A complete cache Codex does not list takes the
#      refresh path, whose `add` registers it.
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
#      only complaining afterward.
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
#      concierge/ directory — every version dir and anything else inside it
#      (Codex keeps its own plugin-install-<random>/ staging one level up),
#      first install or refresh alike —
#      before installing the fresh version. That is Codex's own behavior at
#      step 4/6, not this script's; the fallback only ever runs AFTER `add`
#      already succeeded, so it starts from whatever `add` just left behind
#      (the one version dir it installed) and only ever adds to that.
#   8. Verify: cache manifest version, skills/, launcher exec bit,
#      .codex-plugin/mcp.json + .codex/hooks.json, enforcer identical to this
#      checkout's, `codex plugin list --json` installed state (every path; a
#      failed or unreadable listing is reported as such, never as "not
#      installed"), doctor's Codex row.
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
# The helpers every installer shares (adapters/lib/sync.sh), found from this file's own location.
SYNC_LIB="$(cd "$SCRIPT_DIR/.." && pwd)/lib/sync.sh"
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

echo "==> skill-concierge → Codex sync (from: $ROOT)"

MARKETPLACE_NAME="skill-concierge"
PLUGIN_SELECTOR="skill-concierge@skill-concierge"
CODEX_PLUGIN_CACHE="$HOME/.codex/plugins/cache/skill-concierge/skill-concierge"

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

VERSION="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["version"])' "$ROOT/.claude-plugin/plugin.json")"
echo "    SSOT version: v$VERSION"

# A git checkout installs HEAD (`git archive HEAD`), so HEAD's version is the one to install; Codex
# names and scans the cache by .codex-plugin/plugin.json, so HEAD's copy of that manifest must agree
# too. An uncommitted version change (staged or not) would put HEAD's content in a dir named for the
# new version: refuse before any CLI call or write. A checkout git cannot read (git missing, a
# safe.directory refusal, a damaged repo) and one whose git dir is renamed to `git/` (the
# workbench's no-dot toggle) are refused too: copying either as a plain tree would ship its
# untracked files.
_head_version() {
  git -C "$ROOT" show "HEAD:$1" 2>/dev/null \
    | python3 -c "import json,sys;print(json.load(sys.stdin)['version'])" 2>/dev/null || true
}
if _is_own_checkout; then
  HEAD_VERSION="$(_head_version .claude-plugin/plugin.json)"
  HEAD_CODEX_VERSION="$(_head_version .codex-plugin/plugin.json)"
  if [ "$HEAD_VERSION" != "$VERSION" ]; then
    echo "!! .claude-plugin/plugin.json says v$VERSION but HEAD carries v${HEAD_VERSION:-none}; this installer" >&2
    echo "   installs HEAD. Commit the version change (or restore the file), then re-run." >&2
    exit 1
  fi
  if [ "$HEAD_CODEX_VERSION" != "$VERSION" ]; then
    echo "!! HEAD's .codex-plugin/plugin.json carries v${HEAD_CODEX_VERSION:-none}, not v$VERSION; Codex would" >&2
    echo "   file this install under another version. Commit both manifests at one version, then re-run." >&2
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

CACHED="$(_cached_version)"
DEST="$CODEX_PLUGIN_CACHE/$CACHED"

# ── One-directional downgrade guard — before any CLI call, no writes ────────
if [ -n "$CACHED" ] && ! _ver_ge "$VERSION" "$CACHED"; then
  echo "!! refusing to downgrade: Codex cache v$CACHED is NEWER than this checkout v$VERSION." >&2
  echo "   Update the checkout (git pull) or keep the newer cached copy — a stale checkout" >&2
  echo "   never downgrades a live install (ADR-0042 doctrine)." >&2
  exit 1
fi

# _codex_json WHAT… — run `codex plugin WHAT… --json`, print its stdout; on a failed run print
# "error:" and the CLI's own message instead, so a broken Codex is never read as an empty listing.
_codex_json() {
  local out errf rc=0
  errf="$(mktemp)"
  out="$(codex plugin "$@" --json 2>"$errf")" || rc=$?
  if [ "$rc" != 0 ]; then
    echo "error:'codex plugin $* --json' exited $rc: $(head -c 400 "$errf" | tr '\n' ' ')"
  else
    printf '%s' "$out"
  fi
  rm -f "$errf"
}

# _plugin_state — Codex's own view of this plugin: enabled | disabled | not-installed, or
# "error:<why>" when the listing failed or was not JSON. A record without an `enabled` field
# counts as enabled, the same default everywhere in this script.
_plugin_state() {
  local out
  out="$(_codex_json list)"
  case "$out" in error:*) echo "$out"; return ;; esac
  python3 - "$out" "$PLUGIN_SELECTOR" <<'PY'
import json, sys
try:
    plg = json.loads(sys.argv[1])
    rec = next((p for p in plg.get("installed", [])
                if p.get("pluginId") == sys.argv[2] and p.get("installed")), None)
except (ValueError, AttributeError, TypeError):
    print("error:'codex plugin list --json' printed something other than the expected JSON")
    sys.exit(0)
print("not-installed" if not rec else ("enabled" if rec.get("enabled", True) else "disabled"))
PY
}

REFRESHED=0
STATE=""
command -v codex >/dev/null 2>&1 && STATE="$(_plugin_state)"
# Codex starts ./bin/skill-search-mcp directly and reads the MCP and hooks files from the cached
# tree, so a copy without them is not current, whatever its manifest says; nor is one Codex does
# not list as installed.
_complete() {
  [ -d "$1/skills" ] && [ -f "$1/.codex-plugin/plugin.json" ] && [ -f "$1/bin/skill-search-mcp" ] \
    && [ -f "$1/.codex-plugin/mcp.json" ] && [ -f "$1/.codex/hooks.json" ]
}
if [ "$CACHED" = "$VERSION" ] && _complete "$DEST" && { [ "$STATE" = enabled ] || [ "$STATE" = disabled ]; }; then
  # ── Fast path: already current; one read-only `codex plugin list`, no content writes (the
  # self-heal exec-bit chmod below still runs on every path) ─────────────────
  echo "  [✓] Already current: Codex cache v$CACHED == SSOT v$VERSION"
else
  REFRESHED=1
  echo "  [•] Codex cache v${CACHED:-none} != SSOT v$VERSION (or incomplete, or not listed) -> checking Codex registration"
  if ! command -v codex >/dev/null 2>&1; then
    echo "!! the codex CLI is not on PATH — this installer refreshes through it. Install Codex first." >&2
    exit 1
  fi
  case "$STATE" in
    error:*) echo "!! ${STATE#error:}" >&2
             echo "   Fix Codex (the message above is its own), then re-run; nothing was changed." >&2
             exit 1 ;;
  esac

  MKT_JSON="$(_codex_json marketplace list)"
  case "$MKT_JSON" in
    error:*) echo "!! ${MKT_JSON#error:}" >&2
             echo "   Fix Codex (the message above is its own), then re-run; nothing was changed." >&2
             exit 1 ;;
  esac
  MKT_REGISTERED="$(python3 - "$MKT_JSON" "$MARKETPLACE_NAME" <<'PY'
import json, sys
try:
    mkt = json.loads(sys.argv[1])
    print("1" if sys.argv[2] in [m.get("name") for m in mkt.get("marketplaces", [])] else "0")
except (ValueError, AttributeError, TypeError):
    print("error")
PY
)"
  if [ "$MKT_REGISTERED" = "error" ]; then
    echo "!! 'codex plugin marketplace list --json' printed something other than the expected JSON;" >&2
    echo "   nothing was changed." >&2
    exit 1
  fi
  PLUGIN_INSTALLED=0; ENABLED_BEFORE=na
  case "$STATE" in
    enabled) PLUGIN_INSTALLED=1; ENABLED_BEFORE=1 ;;
    disabled) PLUGIN_INSTALLED=1; ENABLED_BEFORE=0 ;;
  esac

  # ── Disabled-plugin guard — before any mutating CLI call (header step 5) ──
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

  STATE="$(_plugin_state)"
  INSTALLED_AFTER=0
  case "$STATE" in
    enabled|disabled) INSTALLED_AFTER=1 ;;
    error:*) echo "!! ${STATE#error:}" >&2 ;;
  esac

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

  CACHED="$(_cached_version)"
  DEST="$CODEX_PLUGIN_CACHE/$CACHED"

  if [ "$CACHED" != "$VERSION" ] || ! _complete "$DEST"; then
    # ── Manual sync fallback — only reached with the plugin confirmed
    # installed above (see header step 7). The downgrade guard applies again:
    # the CLI refresh could in principle have installed something NEWER than
    # this checkout (a teammate pushed ahead of us).
    if [ -n "$CACHED" ] && ! _ver_ge "$VERSION" "$CACHED"; then
      echo "!! refusing to downgrade: after the CLI refresh, Codex cache v$CACHED is NEWER" >&2
      echo "   than this checkout v$VERSION. Update the checkout (git pull) and re-run." >&2
      exit 1
    fi

    echo "  [•] '$MARKETPLACE_NAME' marketplace still v${CACHED:-none} (or an incomplete copy) after the CLI" \
         "refresh (the git remote lags this checkout) -> syncing this checkout into the Codex cache"
    echo "  !! NOTE: this deploys the LOCAL checkout DIRECTLY — it may include commits not" >&2
    echo "     yet pushed to the '$MARKETPLACE_NAME' marketplace's git remote" \
         "(https://github.com/thinhkhuat/skill-concierge.git). Once pushed, a plain" >&2
    echo "     'codex plugin marketplace upgrade $MARKETPLACE_NAME' followed by 'codex plugin" >&2
    echo "     add $PLUGIN_SELECTOR' will replace this with the canonical git-tracked copy." >&2

    DEST="$CODEX_PLUGIN_CACHE/$VERSION"
    _export_to "$DEST"
    chmod +x "$DEST/bin/"* "$DEST/setup.sh" "$DEST"/adapters/*/install.sh 2>/dev/null || true
    echo "    bin/ + installer exec bits ensured"

    # Older version dirs under this cache path are left in place, deliberately
    # — see header step 7. A replaced incomplete copy is kept as .<version>.replaced-<time>.

    CACHED="$(_cached_version)"
    DEST="$CODEX_PLUGIN_CACHE/$CACHED"
    # The export writes HEAD, whose two manifests the up-front check made equal to $VERSION, so the new
    # dir cannot carry another version's content. Reaching this means the export itself failed.
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
test "$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["version"])' "$DEST/.codex-plugin/plugin.json" 2>/dev/null)" = "$VERSION" \
  && echo "    cache manifest: v$VERSION" \
  || { echo "    !! cache manifest version mismatch" >&2; VERIFY_OK=false; }
test -d "$DEST/skills" && echo "    skills/ present: yes" \
  || { echo "    !! skills/ missing at $DEST" >&2; VERIFY_OK=false; }
# Codex runs the launcher itself and reads the MCP and hooks files from this tree: each is required.
test -x "$DEST/bin/skill-search-mcp" && echo "    launcher executable: yes" \
  || { echo "    !! launcher missing or not executable at $DEST/bin/skill-search-mcp" >&2; VERIFY_OK=false; }
test -f "$DEST/.codex-plugin/mcp.json" && echo "    .codex-plugin/mcp.json present: yes" \
  || { echo "    !! .codex-plugin/mcp.json missing at $DEST" >&2; VERIFY_OK=false; }
test -f "$DEST/.codex/hooks.json" && echo "    .codex/hooks.json present: yes" \
  || { echo "    !! .codex/hooks.json missing at $DEST" >&2; VERIFY_OK=false; }
diff -q "$ROOT/hooks/scripts/enforcer.py" "$DEST/hooks/scripts/enforcer.py" >/dev/null 2>&1 \
  && echo "    enforcer identical to this checkout's: yes" \
  || echo "    [!] enforcer differs from this checkout's (deployed copy is another build)" >&2
# Registry state on every path, not just files on disk: Codex loads only an installed, enabled plugin.
# The fast path already asked Codex; the refresh path asks again after its own changes.
LOADS=false
if ! command -v codex >/dev/null 2>&1; then
  echo "    !! the codex CLI is not on PATH — cannot confirm Codex has the plugin installed" >&2
  VERIFY_OK=false
else
  [ "$REFRESHED" = 1 ] && STATE="$(_plugin_state)"
  case "$STATE" in
    enabled) echo "    codex plugin list: installed, enabled"; LOADS=true ;;
    disabled) echo "    [!] codex plugin list: installed but DISABLED — Codex will not load it until it is enabled" >&2 ;;
    error:*) echo "    !! ${STATE#error:}" >&2; VERIFY_OK=false ;;
    *) echo "    !! codex plugin list --json does not show '$PLUGIN_SELECTOR' installed; run" >&2
       echo "       'codex plugin add $PLUGIN_SELECTOR', then re-run this installer" >&2
       VERIFY_OK=false ;;
  esac
fi
python3 "$ROOT/scripts/doctor.py" 2>/dev/null | grep -i "Codex integration" || true

if $VERIFY_OK && ! $LOADS; then
  echo "==> Done. The cache is at v$VERSION; the plugin stays disabled in Codex, as it was."
elif $VERIFY_OK; then
  echo "==> Done. Restart Codex (fresh session) to load v$VERSION — hooks and .mcp.json"
  echo "    are auto-discovered from the cache at session start. Then confirm: doctor's"
  echo "    Codex integration row is OK, and a session's MCP tools list skill-search."
else
  echo "    verify: FAILED — see lines above" >&2
  exit 1
fi
