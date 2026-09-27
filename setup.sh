#!/usr/bin/env bash
# skill-concierge — portable setup for the vendored skill-search engine.
# Builds a STABLE venv (survives plugin reinstalls), starts the local index owner (the
# engine's Qdrant-compatible store + warm embedder, one SQLite file), builds the multilingual
# index, and applies the curated name-only overrides. Idempotent; safe to re-run.
# Requires: Python 3.10-3.12. No Docker.
#
# Override SKILL_PYTHON / SKILL_CONCIERGE_VENV / SKILL_QDRANT_URL / SKILL_EMBED_MODEL /
# SKILL_INDEX_DB via env.
#
# Behavior flags (both DEFAULT ON; export =0 before this run / a session to revert):
#   SKILL_BODY_TRIGGERS=0      description-only trigger layer, no body-derived points (ADR-0016)
#   ENFORCER_AUTHORIZED_SKIP=0 restore the enforcer's old silent getaway/intent_skip (ADR-0015)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENDOR="$ROOT/vendor/skill-search"
VENV="${SKILL_CONCIERGE_VENV:-$HOME/.claude/skill-concierge/venv}"
EPORT="${EMBED_SHIM_PORT:-6363}"
OWNER_TITLE="skill-concierge index owner (Qdrant-compatible subset)"

PYTHON="${SKILL_PYTHON:-}"
if [ -z "$PYTHON" ]; then
  for c in python3.12 python3.11 python3.10; do
    command -v "$c" >/dev/null 2>&1 && { PYTHON="$c"; break; }
  done
fi
[ -n "$PYTHON" ] || { echo "! need Python 3.10-3.12 (set SKILL_PYTHON=/path/to/python3.12)" >&2; exit 1; }

# Single source of truth for embedder + store = .mcp.json (so the built index can't
# diverge from the model the live MCP uses). Env overrides win.
read_mcp() { "$PYTHON" -c "import json,sys
print(json.load(open(sys.argv[1]))['mcpServers']['skill-search']['env'].get(sys.argv[2],''))" "$ROOT/.mcp.json" "$1"; }
QURL="${SKILL_QDRANT_URL:-$(read_mcp SKILL_QDRANT_URL)}"
MODEL="${SKILL_EMBED_MODEL:-$(read_mcp SKILL_EMBED_MODEL)}"
echo "python=$PYTHON  venv=$VENV  qdrant=$QURL  model=$MODEL"

# One-time migration to the canonical home (~/.claude/skill-concierge, ADR-0025): fold the
# ledger/telemetry in from its old location. The venv is NOT migrated — it is rebuilt below (a
# venv can't be relocated: absolute paths bake in). The old ~/.local/share/skill-concierge/venv
# is orphaned after this and safe to delete.
OLD_LOG="$HOME/.claude/skill-telemetry/logs"
NEW_LOG="${SKILL_CONCIERGE_LOG:-$HOME/.claude/skill-concierge/logs}"
if [ -d "$OLD_LOG" ] && [ ! -e "$NEW_LOG" ]; then
  mkdir -p "$NEW_LOG" && cp -R "$OLD_LOG/." "$NEW_LOG/" && echo "  migrated ledger/telemetry -> $NEW_LOG (old copy kept at $OLD_LOG)"
fi

echo "[1/4] venv + deps at a STABLE path (survives plugin reinstalls)"
mkdir -p "$(dirname "$VENV")"
[ -d "$VENV" ] || "$PYTHON" -m venv "$VENV"
"$VENV/bin/pip" -q install --upgrade pip >/dev/null
"$VENV/bin/pip" -q install "$VENDOR" tiktoken   # deps (mcp, fastembed, requests) + tiktoken into the STABLE venv
# Force the ENGINE copy fresh, under the SAME mkdir lock bin/skill-search-mcp's background
# resync uses (.engine-resync.lock) — a concurrent launcher resync and this setup run must
# never race pip against the shared venv. Wait/timeout mirrors the launcher: up to 10
# attempts, 1s apart, stealing a lock whose owner pid is gone. Unlike the launcher's
# best-effort background heal, this reinstall is mandatory, so a failed acquire is fatal
# instead of a silent skip.
ENGINE_LOCK="$VENV/.engine-resync.lock"
_acquire_engine_lock() {
  self_pid="$(sh -c 'echo $PPID')"
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    if mkdir "$ENGINE_LOCK" 2>/dev/null; then
      echo "$self_pid" > "$ENGINE_LOCK/pid"
      return 0
    fi
    old_pid="$(cat "$ENGINE_LOCK/pid" 2>/dev/null || true)"
    if [ -z "$old_pid" ] || ! kill -0 "$old_pid" 2>/dev/null; then
      rm -rf "$ENGINE_LOCK"
      if mkdir "$ENGINE_LOCK" 2>/dev/null; then
        echo "$self_pid" > "$ENGINE_LOCK/pid"
        return 0
      fi
    fi
    sleep 1
  done
  return 1
}
_acquire_engine_lock \
  || { echo "! could not acquire $ENGINE_LOCK (held by a concurrent resync) — rerun setup.sh" >&2; exit 1; }
trap 'rm -f "$ENGINE_LOCK/pid" 2>/dev/null; rmdir "$ENGINE_LOCK" 2>/dev/null' EXIT
# The vendored package version is a static 0.1.0 (pyproject), so a plain `pip install` sees
# "already satisfied" and SKIPS re-copying changed code on a re-run — the exact stale-engine
# trap (ADR-0018). --force-reinstall --no-deps guarantees the current engine code lands
# without re-resolving the (already-present) heavy deps.
"$VENV/bin/pip" -q install --no-cache-dir --force-reinstall --no-deps "$VENDOR"
# Stamp the deployed plugin version so bin/skill-search-mcp can detect a future /plugin update
# and AUTO-resync the engine (ADR-0018) instead of silently serving stale code.
PLUGIN_VER="$("$PYTHON" -c "import json,sys
print(json.load(open(sys.argv[1]))['version'])" "$ROOT/.claude-plugin/plugin.json")"
printf '%s' "$PLUGIN_VER" > "$VENV/.engine-plugin-version"
rm -f "$ENGINE_LOCK/pid" 2>/dev/null; rmdir "$ENGINE_LOCK" 2>/dev/null
trap - EXIT
echo "  engine forced-fresh + stamped @ plugin v$PLUGIN_VER"

echo "[2/4] local index owner (store @ $QURL, embed @ 127.0.0.1:$EPORT)"
OWNER_LOG="$NEW_LOG/index-owner.log"
mkdir -p "$NEW_LOG"
# Stop a running owner so the code just reinstalled takes effect (its stamp watch would exit
# it within a minute anyway; this makes a same-version code change land now). Only a process
# whose `GET /` answers the owner title is signalled — never a container or another service.
store_port="$(printf '%s' "$QURL" | sed -E 's#^[a-z]+://[^:/]+:?([0-9]*).*#\1#')"
store_port="${store_port:-6333}"
if curl -s -m 2 "http://127.0.0.1:$store_port/" 2>/dev/null | grep -qF "$OWNER_TITLE"; then
  for pid in $(lsof -nP -t -iTCP:"$store_port" -sTCP:LISTEN 2>/dev/null); do
    kill "$pid" 2>/dev/null || true
  done
  for _ in $(seq 1 20); do
    curl -s -m 1 "http://127.0.0.1:$store_port/" >/dev/null 2>&1 || break
    sleep 0.5
  done
  echo "  stopped the running index owner (reinstalled code)"
fi
# Detached in its OWN session (start_new_session=True, like enforcer.py/doctor.py) so it
# outlives this shell, the harness and the MCP servers rather than sharing this script's
# process group — a plain `nohup ... &` still leaves the child in the caller's pgid, so a
# kill of that group takes the owner down with it. A duplicate start is harmless — the
# second owner loses the file lock and exits. Path is passed via argv, never interpolated
# into the code string. QURL/EPORT are exported so the owner binds the SAME store/embed
# ports this script just probed and stopped ($store_port above) — QURL/EPORT are plain
# bash vars, never exported by default, so without this the owner would fall back to its
# hardcoded 6333/6363 defaults whenever .mcp.json configures a non-default port (N10).
env SKILL_QDRANT_URL="$QURL" EMBED_SHIM_PORT="$EPORT" "$VENV/bin/python" -c 'import subprocess,sys
subprocess.Popen([sys.executable, "-m", "skill_search.index_owner"],
                  start_new_session=True, stdin=subprocess.DEVNULL,
                  stdout=open(sys.argv[1], "ab"), stderr=subprocess.STDOUT)' \
  "$OWNER_LOG"
for _ in $(seq 1 90); do
  curl -s -m 1 "http://127.0.0.1:$EPORT/health" 2>/dev/null | grep -q '"ok"' && break
  sleep 1
done
curl -s -m 2 "http://127.0.0.1:$EPORT/health" 2>/dev/null | grep -q '"ok"' \
  || { echo "! index owner did not come up — see $OWNER_LOG" >&2; exit 1; }
echo "  index owner up"

echo "[3/4] build/refresh the multilingual index @ $QURL"
# The reindex must build the SAME index the query server serves: every engine setting
# .mcp.json pins (trigger layer, harness roots, synced skills, catalogs) is forwarded by
# scripts/engine_env.py — the one key list every reindex path shares (ADR-0026 forwarding
# class). Real env wins; empty values are never exported ("" would read as ON).
env_run() {
  env SKILL_QDRANT_URL="$QURL" SKILL_EMBED_BACKEND=fastembed SKILL_EMBED_MODEL="$MODEL" \
    "$PYTHON" "$ROOT/scripts/engine_env.py" --root "$ROOT" --exec "$@"
}
env_run "$VENV/bin/skill-search" --reindex
# Multi-vector trigger layer (ADR-0012) is built + maintained by --reindex itself (default on).
# The legacy MEAN enrichment overlay (enrich_index.py) was retired and archived out of the repo.
env_run "$VENV/bin/skill-search" --health

echo "[3b/4] build the actionability-gate corpus (prompt_intent) from the transcript store"
# Reproducible rebuild of the gate's grounding collection (scripts/build_prompt_intent.py +
# the enforcer actionability gate). Fail-soft: too little history / shim down -> gate FAIL-OPEN.
"$VENV/bin/python" "$ROOT/scripts/build_prompt_intent.py" || echo "  (prompt_intent build skipped — gate fails-open)"

echo "[3c/4] build the keep-off offer-suppression map into the durable home (ADR-0011/0054)"
# Idempotent; the generator's data-sufficiency guard writes an empty (inert) map while the
# post-epoch ledger window is thin. The enforcer fails open on anything malformed.
"$VENV/bin/python" "$ROOT/scripts/build_keep_off.py" || echo "  (keep-off build skipped — enforcer fails open)"

echo "[4/4] apply curated name-only overrides to ~/.claude/settings.json (backed up first)"
"$VENV/bin/python" "$ROOT/scripts/apply-overrides.py"

cat <<EOF

Done. The MCP launcher (bin/skill-search-mcp) runs this stable venv:
  $VENV
so it survives plugin reinstalls. To go live:
  • If skill-search was registered user-scope, remove it (single source = the plugin):
        claude mcp remove skill-search -s user
  • Restart Claude Code so the MCP + overrides take effect.
  • After a plugin UPDATE the launcher AUTO-resyncs the engine on next start (ADR-0018) —
    a manual setup.sh rerun is only needed for a dependency change or a broken venv.
  • The index owner restarts itself on demand: the MCP launcher and the per-turn hook start
    it when it is down (SKILL_OWNER_AUTOSTART=0 disables both). Log: $OWNER_LOG
EOF
