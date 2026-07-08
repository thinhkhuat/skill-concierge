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
        env = json.loads((PLUGIN_ROOT / ".mcp.json").read_text(encoding="utf-8"))[
            "mcpServers"]["skill-search"]["env"]
    except Exception:
        pass
    merged = dict(os.environ)
    # Forward the embedder/store keys AND the trigger-layer keys from .mcp.json so the
    # DETACHED reindex builds the SAME index the query server serves. Without the trigger
    # keys, an auto-reindex silently rebuilds at engine defaults (SKILL_LLM_TRIGGERS off,
    # TRIGGERS_MAX 12) and prunes the utterance points — ADR-0026. real env still wins.
    for k in ("SKILL_QDRANT_URL", "SKILL_EMBED_BACKEND", "SKILL_EMBED_MODEL",
              "SKILL_LLM_TRIGGERS", "TRIGGERS_MAX", "SKILL_TRIGGERS", "SKILL_BODY_TRIGGERS"):
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
            with urllib.request.urlopen(u, timeout=timeout) as r:
                if r.status == 200:
                    return True
        except Exception:
            continue
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
        logf = open(LOGFILE, "a", encoding="utf-8")
        logf.write(f"\n=== auto-reindex {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        logf.flush()
        subprocess.Popen(
            [str(SS_BIN), "--reindex"], env=env,
            stdout=logf, stderr=logf, stdin=subprocess.DEVNULL,
            start_new_session=True,                    # fully detached: outlives the hook, never blocks
        )
    except Exception:
        return 0                                       # fail-silent — never block session start
    return 0


if __name__ == "__main__":
    sys.exit(main())
