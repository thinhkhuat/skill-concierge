#!/usr/bin/env bash
# skill-concierge — portable setup for the vendored skill-search engine.
# Builds a STABLE venv (survives plugin reinstalls), the Qdrant server, the multilingual
# index, and the curated name-only overrides. Idempotent; safe to re-run.
# Requires: Python 3.10-3.12, Docker/OrbStack (Qdrant).
#
# ponytail: Docker assumed for the Qdrant server tier. For the service-free embedded tier,
# skip step 2 and unset SKILL_QDRANT_URL. Override SKILL_PYTHON / SKILL_CONCIERGE_VENV /
# SKILL_QDRANT_URL / SKILL_EMBED_MODEL via env.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENDOR="$ROOT/vendor/skill-search"
VENV="${SKILL_CONCIERGE_VENV:-$HOME/.local/share/skill-concierge/venv}"
QNAME="${SKILL_QDRANT_CONTAINER:-skill-search-qdrant}"
QIMAGE="${SKILL_QDRANT_IMAGE:-qdrant/qdrant:1.18.2}"
ENAME="${SKILL_EMBED_CONTAINER:-skill-concierge-embed-shim}"
EIMAGE="${SKILL_EMBED_IMAGE:-skill-concierge-embed-shim:latest}"
EPORT="${EMBED_SHIM_PORT:-6363}"

PYTHON="${SKILL_PYTHON:-}"
if [ -z "$PYTHON" ]; then
  for c in python3.12 python3.11 python3.10; do
    command -v "$c" >/dev/null 2>&1 && { PYTHON="$c"; break; }
  done
fi
[ -n "$PYTHON" ] || { echo "! need Python 3.10-3.12 (set SKILL_PYTHON=/path/to/python3.12)" >&2; exit 1; }

# Single source of truth for embedder + store = .mcp.json (so the built index can't
# diverge from the model the live MCP uses). Env overrides win.
read_mcp() { "$PYTHON" -c "import json,sys;print(json.load(open('$ROOT/.mcp.json'))['mcpServers']['skill-search']['env'].get(sys.argv[1],''))" "$1"; }
QURL="${SKILL_QDRANT_URL:-$(read_mcp SKILL_QDRANT_URL)}"
MODEL="${SKILL_EMBED_MODEL:-$(read_mcp SKILL_EMBED_MODEL)}"
echo "python=$PYTHON  venv=$VENV  qdrant=$QURL  model=$MODEL"

echo "[1/4] venv + deps at a STABLE path (survives plugin reinstalls)"
mkdir -p "$(dirname "$VENV")"
[ -d "$VENV" ] || "$PYTHON" -m venv "$VENV"
"$VENV/bin/pip" -q install --upgrade pip >/dev/null
"$VENV/bin/pip" -q install "$VENDOR" tiktoken   # non-editable: copies the engine in, so a cache wipe can't break it

echo "[2/4] Qdrant server (Docker container '$QNAME')"
command -v docker >/dev/null 2>&1 || { echo "! docker not found — install Docker/OrbStack and re-run." >&2; exit 1; }
docker info >/dev/null 2>&1 || { echo "! docker daemon not running — start Docker/OrbStack, then re-run." >&2; exit 1; }
if docker ps -a --format '{{.Names}}' | grep -qx "$QNAME"; then
  docker start "$QNAME" >/dev/null 2>&1 || true
else
  docker run -d --name "$QNAME" --restart unless-stopped \
    -p 6333:6333 -p 6334:6334 \
    -v "$HOME/.cache/skill-search/qdrant-server:/qdrant/storage" \
    "$QIMAGE"
fi

echo "[2b/4] warm embed shim (Docker sidecar '$ENAME' next to Qdrant)"
# The per-turn enforcer hook POSTs queries here to embed in ~tens of ms instead
# of paying a cold model load. Sidecar mirrors Qdrant's restart policy. Bound to
# 127.0.0.1 only — never exposed off-host. Skip cleanly if not already listening.
if ! curl -s -m 2 "http://127.0.0.1:$EPORT/health" >/dev/null 2>&1; then
  docker build -t "$EIMAGE" "$ROOT"
  if docker ps -a --format '{{.Names}}' | grep -qx "$ENAME"; then
    docker rm -f "$ENAME" >/dev/null 2>&1 || true
  fi
  docker run -d --name "$ENAME" --restart unless-stopped \
    -p "127.0.0.1:$EPORT:6363" \
    "$EIMAGE"
else
  echo "  embed shim already listening on 127.0.0.1:$EPORT — leaving it."
fi

echo "[3/4] build/refresh the multilingual index @ $QURL"
env_run() { SKILL_QDRANT_URL="$QURL" SKILL_EMBED_BACKEND=fastembed SKILL_EMBED_MODEL="$MODEL" "$@"; }
env_run "$VENV/bin/skill-search" --reindex
# Re-apply the trigger-phrase enrichment overlay (vector-only) that a reindex rewrites bare.
# Idempotent + a no-op when the index was never enriched, so this is safe on a fresh install.
env_run "$VENV/bin/python" "$ROOT/scripts/enrich_index.py" --reapply
env_run "$VENV/bin/skill-search" --health

echo "[4/4] apply curated name-only overrides to ~/.claude/settings.json (backed up first)"
"$VENV/bin/python" "$ROOT/scripts/apply-overrides.py"

cat <<EOF

Done. The MCP launcher (bin/skill-search-mcp) runs this stable venv:
  $VENV
so it survives plugin reinstalls. To go live:
  • If skill-search was registered user-scope, remove it (single source = the plugin):
        claude mcp remove skill-search -s user
  • Restart Claude Code so the MCP + overrides take effect.
  • Re-run setup.sh after a plugin UPDATE to refresh the engine.
  • Qdrant + embed shim must be up each session:
        docker start $QNAME $ENAME
EOF
