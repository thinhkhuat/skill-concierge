#!/usr/bin/env python3
"""
skill-concierge — index self-heal (SessionStart hook).

The retrieval index goes stale when skills change on disk (added / removed / edited) since
the last build. Left to a manual `doctor --fix` / reindex, that staleness lingers until
someone remembers to run it. This hook removes the dependency on human-or-agent discipline:
on session start it fires a DETACHED, THROTTLED, incremental reindex in the background, so
the index re-freshens itself.

Design contract (mirrors the sibling doctrine / enforcer / ledger hooks):
  • FAIL-SILENT — any error exits 0; a hook must never break or block session start.
  • NON-BLOCKING — the reindex is spawned detached and NOT waited on; the hook returns
    immediately. The engine's reindex is INCREMENTAL (re-embeds only the skills whose
    content changed), so a no-change run is cheap and merely refreshes the freshness stamp.
  • THROTTLED — at most one background reindex per AUTO_REINDEX_THROTTLE_S (default 1800s),
    tracked by a stamp file, so rapid session restarts don't churn the engine.
  • SILENT / ADDITIVE — emits no context; it is maintenance, not a prompt.

Disable by setting AUTO_REINDEX_THROTTLE_S to a huge value, or remove the hook entry.
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

VENV = Path(os.environ.get("SKILL_CONCIERGE_VENV", Path.home() / ".claude/skill-concierge/venv"))
SS_BIN = VENV / "bin" / "skill-search"
LOGDIR = Path(os.environ.get("SKILL_CONCIERGE_LOG", Path.home() / ".claude/skill-concierge/logs"))
STAMP = LOGDIR / ".auto-reindex-stamp"
LOGFILE = LOGDIR / "auto-reindex.log"
THROTTLE_S = int(os.environ.get("AUTO_REINDEX_THROTTLE_S", "1800"))
# hooks/scripts/auto_reindex.py -> plugin root is two parents up; CLAUDE_PLUGIN_ROOT wins.
PLUGIN_ROOT = Path(os.environ.get("CLAUDE_PLUGIN_ROOT", Path(__file__).resolve().parent.parent.parent))


def _mcp_env():
    """Embedder + store come from .mcp.json (single source of truth); real env wins."""
    env = {}
    try:
        configured_env = json.loads((PLUGIN_ROOT / ".mcp.json").read_text(encoding="utf-8"))[
            "mcpServers"]["skill-search"]["env"]
    except (OSError, ValueError, KeyError, TypeError):
        configured_env = {}
    if isinstance(configured_env, dict):
        env = configured_env
    merged = dict(os.environ)
    # Forward the embedder/store keys AND the trigger-layer keys from .mcp.json so the
    # DETACHED reindex builds the SAME index the query server serves. Without the trigger
    # keys, an auto-reindex silently rebuilds at engine defaults (SKILL_LLM_TRIGGERS off,
    # TRIGGERS_MAX 12) and prunes the utterance points — ADR-0026. real env still wins.
    # SKILL_CONCIERGE_CATALOG_ROOTS (ADR-0031) forwarded too: if the catalog config
    # path is ever pinned in .mcp.json (rather than the shared durable-home default),
    # the detached reindex must see the SAME roots the query server does, or it would
    # rebuild without the catalog scopes and prune every external point — the exact
    # ADR-0026 env-forwarding gap class this list exists to close.
    # SKILL_CODEX_ROOTS (ADR-0033) is the same class. It is NOT pinned in .mcp.json today,
    # so this is defensive: if it ever were pinned to 0, a detached reindex missing it would
    # rebuild at the engine default (ON) and re-add every codex-* point the query server was
    # configured to drop — and pinned to 1 against an engine default of 0, it would prune them
    # all. SKILL_OMP_ROOTS (ADR-0038) is the exact same defensive class: the engine defaults
    # it ON, so a detached reindex that never forwards a pinned-to-0 value would silently re-add
    # every omp-* point the query server dropped — the identical prune-war gap this tuple closes
    # for the other harnesses. SKILL_ZCODE_ROOTS (ADR-0042) joins the same defensive class.
    # INVARIANT: every engine-side flag readable from .mcp.json belongs in this tuple.
    for k in ("SKILL_QDRANT_URL", "SKILL_EMBED_BACKEND", "SKILL_EMBED_MODEL",
              "SKILL_LLM_TRIGGERS", "TRIGGERS_MAX", "SKILL_TRIGGERS", "SKILL_BODY_TRIGGERS",
              "SKILL_CONCIERGE_CATALOG_ROOTS", "SKILL_CODEX_ROOTS", "SKILL_COMMANDCODE_ROOTS",
              "SKILL_OMP_ROOTS", "SKILL_ZCODE_ROOTS"):
        if k in env and k not in os.environ:
            merged[k] = env[k]
    return merged, merged.get("SKILL_QDRANT_URL", "http://localhost:6333")


def _recent(path, within):
    try:
        return (time.time() - path.stat().st_mtime) < within
    except FileNotFoundError:
        return False


def _qdrant_up(url, timeout=0.8):
    for u in (url.rstrip("/") + "/healthz", url):
        try:
            with urllib.request.urlopen(u, timeout=timeout) as response:
                status = response.status
        except (OSError, ValueError):
            status = None
        if status == 200:
            return True
    return False


def main() -> int:
    try:
        if not (SS_BIN.exists() and os.access(SS_BIN, os.X_OK)):
            return 0                                   # no engine yet (setup not run) — nothing to heal
        if _recent(STAMP, THROTTLE_S):
            return 0                                   # throttled — a reindex ran recently
        env, qurl = _mcp_env()
        if not _qdrant_up(qurl):
            return 0                                   # store down — a reindex would just fail; skip
        LOGDIR.mkdir(parents=True, exist_ok=True)
        # Stamp BEFORE spawning so a crash-looping engine can't re-spawn every session.
        STAMP.write_text(str(int(time.time())), encoding="utf-8")
        with LOGFILE.open("a", encoding="utf-8") as logf:
            logf.write(f"\n=== auto-reindex {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
            logf.flush()
            subprocess.Popen(
                [str(SS_BIN), "--reindex"], env=env,
                stdout=logf, stderr=logf, stdin=subprocess.DEVNULL,
                start_new_session=True,                # fully detached: outlives the hook, never blocks
            )
    except (OSError, ValueError):
        return 0                                       # fail-silent — never block session start
    return 0


if __name__ == "__main__":
    sys.exit(main())
