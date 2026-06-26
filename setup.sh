#!/usr/bin/env bash
# skill-concierge — portable setup for the vendored skill-search engine.
# Reproduces the runtime the plugin can't embed: a plugin-local venv + deps, the
# Qdrant server, the multilingual index, and the curated name-only overrides.
# Idempotent; safe to re-run. Requires: Python 3.10-3.12, Docker/OrbStack (Qdrant).
#
# ponytail: Docker assumed for the Qdrant server tier (concurrent sessions). For the
# service-free embedded tier, skip step 2 and unset SKILL_QDRANT_URL. Override
# SKILL_PYTHON / SKILL_QDRANT_URL / SKILL_EMBED_MODEL via env.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENDOR="$ROOT/vendor/skill-search"
VENV="$ROOT/vendor/.venv"
QNAME="${SKILL_QDRANT_CONTAINER:-skill-search-qdrant}"
QIMAGE="${SKILL_QDRANT_IMAGE:-qdrant/qdrant:1.18.2}"

# Pick a compatible interpreter: engine needs >=3.10; 3.13+ risks fastembed/onnxruntime
# wheels (the deploy pinned 3.12). Override with SKILL_PYTHON.
PYTHON="${SKILL_PYTHON:-}"
if [ -z "$PYTHON" ]; then
  for c in python3.12 python3.11 python3.10; do
    command -v "$c" >/dev/null 2>&1 && { PYTHON="$c"; break; }
  done
fi
[ -n "$PYTHON" ] || { echo "! need Python 3.10-3.12 (set SKILL_PYTHON=/path/to/python3.12)" >&2; exit 1; }

# Single source of truth for embedder + store = .mcp.json, so the index the engine
# BUILDS can't diverge from the model the live MCP USES. Env overrides win.
read_mcp() { "$PYTHON" -c "import json,sys;print(json.load(open('$ROOT/.mcp.json'))['mcpServers']['skill-search']['env'].get(sys.argv[1],''))" "$1"; }
QURL="${SKILL_QDRANT_URL:-$(read_mcp SKILL_QDRANT_URL)}"
MODEL="${SKILL_EMBED_MODEL:-$(read_mcp SKILL_EMBED_MODEL)}"
echo "python=$PYTHON  qdrant=$QURL  model=$MODEL"

echo "[1/4] venv + deps (editable install of the vendored engine)"
[ -d "$VENV" ] || "$PYTHON" -m venv "$VENV"
"$VENV/bin/pip" -q install --upgrade pip >/dev/null
"$VENV/bin/pip" -q install -e "$VENDOR" tiktoken

echo "[2/4] Qdrant server (Docker container '$QNAME')"
command -v docker >/dev/null 2>&1 || { echo "! docker not found — install Docker/OrbStack and re-run (or use the embedded tier)." >&2; exit 1; }
docker info >/dev/null 2>&1 || { echo "! docker daemon not running — start Docker/OrbStack, then re-run." >&2; exit 1; }
if docker ps -a --format '{{.Names}}' | grep -qx "$QNAME"; then
  docker start "$QNAME" >/dev/null 2>&1 || true
else
  docker run -d --name "$QNAME" --restart unless-stopped \
    -p 6333:6333 -p 6334:6334 \
    -v "$HOME/.cache/skill-search/qdrant-server:/qdrant/storage" \
    "$QIMAGE"
fi

echo "[3/4] build/refresh the multilingual index @ $QURL"
env_run() { SKILL_QDRANT_URL="$QURL" SKILL_EMBED_BACKEND=fastembed SKILL_EMBED_MODEL="$MODEL" "$@"; }
env_run "$VENV/bin/skill-search" --reindex   # incremental: embeds all first time, cheap on re-run
env_run "$VENV/bin/skill-search" --health

echo "[4/4] apply curated name-only overrides to ~/.claude/settings.json (backed up first)"
"$VENV/bin/python" "$ROOT/scripts/apply-overrides.py"

cat <<EOF

Done. To go live:
  • If skill-search was previously registered user-scope, remove it so this plugin's
    .mcp.json is the SINGLE source (avoids double registration):
        claude mcp remove skill-search -s user
  • Run THIS setup BEFORE enabling the plugin — the MCP command lives in vendor/.venv,
    created here. Then restart Claude Code so the MCP + overrides take effect.
  • Qdrant must be up each session (Docker/OrbStack running): docker start $QNAME
  • Re-index after adding/editing skills: the 'reindex' MCP tool, or
        SKILL_QDRANT_URL=$QURL SKILL_EMBED_BACKEND=fastembed SKILL_EMBED_MODEL="$MODEL" "$VENV/bin/skill-search" --reindex
EOF
