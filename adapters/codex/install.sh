#!/usr/bin/env bash
# skill-concierge — Codex installer / synchronizer / repair (ADR-0033).
#
# Codex is the one harness in the set with NO plugin-update verb and NO local
# install-record file: enablement lives only in ~/.codex/config.toml (TOML, not
# stdlib-parseable — it carries just the marketplace source + an enabled flag,
# no version), and the deployed content is auto-discovered by walking
# ~/.codex/plugins/cache/skill-concierge/skill-concierge/<version>/ for the
# newest dir whose own .codex-plugin/plugin.json parses.
#
# What sync does (idempotent, every step verified or aborted):
#   1. Read the SSOT version from $ROOT/.claude-plugin/plugin.json
#   2. One-directional guard: refuse if the cached copy is NEWER than this
#      checkout (ADR-0042 doctrine, OMP/ZCode parity) — no CLI call, no write.
#   3. Fast path: cache already at SSOT with skills/ + plugin.json present ->
#      no CLI calls, straight to verify.
#   4. Otherwise: the canonical Codex update sequence (there is no
#      `codex plugin upgrade` — Codex's own gap, confirmed via
#      `codex plugin --help`):
#        codex plugin marketplace upgrade skill-concierge   # refresh git snapshot
#        codex plugin remove skill-concierge@skill-concierge  # only if installed
#        codex plugin add skill-concierge@skill-concierge
#      then re-read the cache and compare against the SSOT again.
#   5. If the CLI refresh still didn't reach the SSOT (the marketplace is a
#      GIT source: it installs what is PUSHED to the remote, not this
#      checkout — a version gap almost always means the local commit hasn't
#      been pushed yet), fall back to a manual sync from this checkout:
#      git archive HEAD -> the versioned cache dir
#      cache/skill-concierge/skill-concierge/<version>/, exec bits ensured.
#      Older version dirs are left in place, untouched — see the IMPORTANT
#      note below. Proven live in a sandboxed CODEX_HOME with the real codex
#      binary on 2026-09-26 (see the orchestration report's "Fallback probe"
#      section) — Codex keeps NO registry to repoint, so
#      `codex plugin list --json` re-scans the cache dir on every call;
#      dropping a version dir straight into it is discovered with zero CLI
#      involvement. A loud notice accompanies this path every time, since the
#      synced content may not exist on the git remote yet.
#   6. Verify wiring: cache manifest version, skills/ present, launcher exec
#      bit, .codex-plugin/mcp.json + .codex/hooks.json present, enforcer
#      byte-identical to repo HEAD, doctor's Codex row.
#
# IMPORTANT — why the local-checkout-sync fallback (step 5) does NOT repoint
# any registry, unlike OMP/ZCode: proven live (same sandboxed probe) that
# ~/.codex/config.toml carries no version field at all — only the marketplace
# source and an enabled flag — so there is nothing version-shaped to repoint.
#
# IMPORTANT — why the fallback uses a NEW version-named dir under the SAME
# marketplace/plugin cache path, not a same-named local marketplace: adding a
# second local marketplace under the SAME name Codex already has registered
# (`.claude-plugin/marketplace.json`'s own declared name) errors cleanly
# ("marketplace '...' is already added from a different source; remove it
# before adding this source") — proven live, no state corruption, but it means
# the existing git marketplace would have to be torn down first, which is too
# destructive for a routine sync. A DIFFERENT marketplace name was also proven
# live to coexist as a wholly SEPARATE, simultaneously-enabled plugin — not a
# substitute for the original — which would double-load hooks and collide on
# the shared "skill-search" MCP server name (the exact hazard OMP's own docs
# already flag for a duplicate declaration). Neither is used here.
#
# IMPORTANT — _cached_version() sorts candidate version dirs by a proper
# dotted-integer key, NOT by the naive python `sorted(..., reverse=True)`
# lexical-string sort. Proven live: with cache dirs "0.9.0" and "0.52.3" both
# present, the real `codex plugin list --json` reports "0.52.3" (Codex's own
# resolution is semver-aware), while a lexical-string sort ranks "0.9.0"
# first ('9' > '5' at the first differing character). This script's downgrade
# guard and verify step must agree with what Codex ACTUALLY resolves;
# scripts/doctor.py's _codex_cached_version() uses the same dotted-integer key.
#
# IMPORTANT — the fallback NEVER deletes an older version dir, unlike a
# first-pass draft of this script did. Reasons: (a) this cache dir also holds
# non-version staging dirs Codex itself creates and owns (e.g. a stale
# plugin-install-<random>/ from an interrupted install, observed live on the
# real machine) — a version-shaped glob over it is not a safe basis for
# deletion; (b) the same live probe that proved this fallback safe ALSO proved
# Codex's own resolution is a semver-max scan, so a stale sibling dir is
# provably harmless, never loaded, once a newer one exists — pruning buys
# nothing; (c) a running Codex session could be actively using the older dir
# right now; (d) no sibling installer (OMP, ZCode) deletes anything, and
# nothing here can back up a directory before removing it the way contract
# item 6 requires for an edited file. The fast path and the verify step both
# key off _cached_version()'s semver-max resolution, so an old dir sitting
# alongside the current one changes nothing this script or Codex does.
#
# IMPORTANT — MCP: Codex auto-discovers .codex-plugin/mcp.json and
# .codex/hooks.json from the cached plugin tree (ADR-0033); there is no
# manual-fallback MCP config to merge here, so there is deliberately no
# --mcp-fallback flag (unlike ZCode).
#
# IMPORTANT — bootstrap: this script SYNCS an existing registration; it does
# not bootstrap Codex onto skill-concierge from zero (ZCode parity — that
# installer errors the same way when the plugin was never "Get"'d once via the
# GUI). If neither the marketplace nor the plugin is registered yet, run the
# one-time bootstrap Codex commands this script prints, then re-run it.
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

# ver_gt A B — true iff dotted-integer version A > B. Same one-directional
# doctrine as OMP/ZCode's comparator: a stale checkout must never downgrade a
# newer deployed copy.
_ver_gt() {
  [ "$1" = "$2" ] && return 1
  awk -v a="$1" -v b="$2" 'BEGIN{
    na=split(a,A,"."); nb=split(b,B,"."); n=(na>nb)?na:nb
    for(i=1;i<=n;i++){x=(i<=na)?A[i]+0:0; y=(i<=nb)?B[i]+0:0
      if(x>y) exit 0; if(x<y) exit 1}
    exit 1}'
}

# _cached_version — the version the newest Codex-cached content dir declares
# in its own .codex-plugin/plugin.json, or "" when the cache is absent/
# unreadable. Sorts candidate version dirs by a DOTTED-INTEGER key (newest
# first), matching what the real `codex plugin list --json` resolves —
# proven live to diverge from a naive lexical-string sort once digit widths
# differ (e.g. "0.9.0" vs "0.52.3": lexically "0.9.0" sorts higher, but Codex
# — and this function — correctly resolve "0.52.3").
_cached_version() {
  python3 - "$CODEX_PLUGIN_CACHE" <<'PY'
import json, sys
from pathlib import Path

def ver_key(name):
    return tuple(int(p) if p.isdigit() else -1 for p in name.split("."))

base = Path(sys.argv[1])
result = ""
if base.is_dir():
    candidates = sorted((d for d in base.iterdir() if d.is_dir()),
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

CACHED="$(_cached_version)"
DEST="$CODEX_PLUGIN_CACHE/$CACHED"

# ── One-directional downgrade guard — before any CLI call, no writes ────────
if [ -n "$CACHED" ] && _ver_gt "$CACHED" "$VERSION"; then
  echo "!! refusing to downgrade: Codex cache v$CACHED is NEWER than this checkout v$VERSION." >&2
  echo "   Update the checkout (git pull) or keep the newer cached copy — a stale checkout" >&2
  echo "   never downgrades a live install (ADR-0042 doctrine)." >&2
  exit 1
fi

if [ "$CACHED" = "$VERSION" ] && [ -d "$DEST/skills" ] && [ -f "$DEST/.codex-plugin/plugin.json" ]; then
  # ── Fast path: already current, no CLI calls, no writes ────────────────────
  echo "  [✓] Already current: Codex cache v$CACHED == SSOT v$VERSION"
else
  echo "  [•] Codex cache v${CACHED:-none} != SSOT v$VERSION -> checking Codex registration"

  MKT_JSON="$(mktemp)"
  PLG_JSON="$(mktemp)"
  trap 'rm -f "$MKT_JSON" "$PLG_JSON"' EXIT

  codex plugin marketplace list --json >"$MKT_JSON" 2>/dev/null || echo '{"marketplaces":[]}' >"$MKT_JSON"
  codex plugin list --json >"$PLG_JSON" 2>/dev/null || echo '{"installed":[]}' >"$PLG_JSON"

  MKT_REGISTERED="$(python3 -c "
import json
d = json.load(open('$MKT_JSON'))
names = [m.get('name') for m in d.get('marketplaces', [])]
print('1' if '$MARKETPLACE_NAME' in names else '0')
")"
  PLUGIN_INSTALLED="$(python3 -c "
import json
d = json.load(open('$PLG_JSON'))
found = any(p.get('pluginId') == '$PLUGIN_SELECTOR' and p.get('installed') for p in d.get('installed', []))
print('1' if found else '0')
")"

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

  if [ "$PLUGIN_INSTALLED" = "1" ]; then
    if codex plugin remove "$PLUGIN_SELECTOR"; then :; else
      echo "    [!] 'codex plugin remove $PLUGIN_SELECTOR' failed" >&2
    fi
  fi

  if codex plugin add "$PLUGIN_SELECTOR"; then :; else
    echo "    [!] 'codex plugin add $PLUGIN_SELECTOR' failed" >&2
  fi

  CACHED="$(_cached_version)"
  DEST="$CODEX_PLUGIN_CACHE/$CACHED"

  if [ "$CACHED" != "$VERSION" ]; then
    # ── Manual sync fallback (OMP/ZCode pattern, proven live for Codex — see
    # the header comment): the git-tracked marketplace lags this checkout, so
    # export HEAD straight into the versioned cache dir. One-directional guard
    # applies again first: the CLI refresh could in principle have installed
    # something NEWER than this checkout (a teammate pushed ahead of us).
    if [ -n "$CACHED" ] && _ver_gt "$CACHED" "$VERSION"; then
      echo "!! refusing to downgrade: after the CLI refresh, Codex cache v$CACHED is NEWER" >&2
      echo "   than this checkout v$VERSION. Update the checkout (git pull) and re-run." >&2
      exit 1
    fi

    echo "  [•] '$MARKETPLACE_NAME' marketplace still v${CACHED:-none} after the CLI refresh" \
         "(the git remote lags this checkout) -> syncing this checkout into the Codex cache"
    echo "  !! NOTE: this deploys the LOCAL checkout DIRECTLY — it may include commits not" >&2
    echo "     yet pushed to the '$MARKETPLACE_NAME' marketplace's git remote" \
         "(https://github.com/thinhkhuat/skill-concierge.git). Once pushed, a plain" >&2
    echo "     'codex plugin marketplace upgrade $MARKETPLACE_NAME' will replace this with the" >&2
    echo "     canonical git-tracked copy." >&2

    DEST="$CODEX_PLUGIN_CACHE/$VERSION"
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
             "$DEST/adapters/codex/install.sh" "$DEST/adapters/omp/install.sh" \
             "$DEST/adapters/zcode/install.sh" "$DEST/adapters/dsh/install.sh" \
             "$DEST/adapters/cline/install.sh" "$DEST/adapters/commandcode/install.sh" 2>/dev/null || true
    echo "    bin/ + installer exec bits ensured"

    # Older version dirs under this cache path are left in place, deliberately —
    # same ZCode doctrine ("discovery is registry-enumerated" there; here it's
    # "discovery is a live semver-max scan," proven live: Codex resolves the
    # newest dir by dotted-integer version, so a stale sibling dir is harmless,
    # never loaded). Never delete: this cache also holds non-version staging
    # dirs Codex itself owns (e.g. plugin-install-<random>/), and a live Codex
    # session could be using an older dir right now.

    CACHED="$(_cached_version)"
    DEST="$CODEX_PLUGIN_CACHE/$CACHED"
    if [ "$CACHED" != "$VERSION" ]; then
      echo "!! sync into the Codex cache did not take (cache now v${CACHED:-none}) — see output above." >&2
      exit 1
    fi
    echo "  [✓] Codex cache now v$CACHED == SSOT v$VERSION (synced from local checkout)"
  else
    echo "  [✓] Codex cache now v$CACHED == SSOT v$VERSION"
  fi
fi

# ── Exec bits (self-heal; a CLI-installed clone can ship without them, same
# class of hazard as ZCode's marketplace cache) ──────────────────────────────
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
python3 "$ROOT/scripts/doctor.py" 2>/dev/null | grep -i "Codex integration" || true

if $VERIFY_OK; then
  echo "==> Done. Restart Codex (fresh session) to load v$VERSION — hooks and .mcp.json"
  echo "    are auto-discovered from the cache at session start. Then confirm: doctor's"
  echo "    Codex integration row is OK, and a session's MCP tools list skill-search."
else
  echo "    verify: FAILED — see lines above" >&2
  exit 1
fi
