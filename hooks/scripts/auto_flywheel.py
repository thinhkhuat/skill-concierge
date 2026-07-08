#!/usr/bin/env python3
"""
skill-concierge — retrieval-flywheel self-heal (SessionStart hook, ADR-0027 Phase 2).

New/changed skills carry no LLM-generated utterance triggers or eval scenarios until the
flywheel generator runs (scripts/llm_triggers.py, scripts/llm_eval_gen.py). Left to a manual
`flywheel --generate`, that gap lingers. This hook removes the dependency on human-or-agent
discipline: on session start, if a flywheel LLM endpoint is configured and reachable, it fires
a DETACHED, THROTTLED background run of `scripts/flywheel.py --generate` (capped per run) and
returns immediately.

Design contract (mirrors auto_reindex.py):
  • FAIL-OPEN — no endpoint configured, or flywheel_llm.ping() fails, or the engine venv/Qdrant
    isn't up yet -> silent no-op, exit 0. The fallback (description+body retrieval) is untouched.
  • NON-BLOCKING — the generation+reindex is spawned detached and NOT waited on.
  • THROTTLED — at most one background run per AUTO_FLYWHEEL_THROTTLE_S (default 21600s = 6h;
    generation is heavier than a reindex — real LLM calls, not just re-embedding).
  • CAPPED — at most AUTO_FLYWHEEL_MAX_PER_RUN skills (default 25) per background run, so a bulk
    skill import can't stampede a metered LLM endpoint.
  • GATED — SKILL_AUTO_FLYWHEEL=0 disables the hook entirely (default "1" = ON).

Disable per-session with SKILL_AUTO_FLYWHEEL=0, or space runs out with AUTO_FLYWHEEL_THROTTLE_S.
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
PY_BIN = VENV / "bin" / "python3"
LOGDIR = Path(os.environ.get("SKILL_CONCIERGE_LOG", Path.home() / ".claude/skill-concierge/logs"))
STAMP = LOGDIR / ".auto-flywheel-stamp"
LOGFILE = LOGDIR / "auto-flywheel.log"
THROTTLE_S = int(os.environ.get("AUTO_FLYWHEEL_THROTTLE_S", "21600"))
MAX_PER_RUN = int(os.environ.get("AUTO_FLYWHEEL_MAX_PER_RUN", "25"))
# hooks/scripts/auto_flywheel.py -> plugin root is two parents up; CLAUDE_PLUGIN_ROOT wins.
PLUGIN_ROOT = Path(os.environ.get("CLAUDE_PLUGIN_ROOT", Path(__file__).resolve().parent.parent.parent))
FLYWHEEL_PY = PLUGIN_ROOT / "scripts" / "flywheel.py"


def _mcp_env():
    """Embedder + store come from .mcp.json (single source of truth); real env wins.
    Same seam as auto_reindex.py's _mcp_env() — the detached generate+reindex must build/query
    the SAME index the query server serves."""
    env = {}
    try:
        env = json.loads((PLUGIN_ROOT / ".mcp.json").read_text(encoding="utf-8"))[
            "mcpServers"]["skill-search"]["env"]
    except Exception:
        pass
    merged = dict(os.environ)
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
        if os.environ.get("SKILL_AUTO_FLYWHEEL", "1") == "0":
            return 0                                   # explicitly disabled

        # Fail-open: no flywheel endpoint configured at all -> nothing to do, ever.
        if "FLYWHEEL_LLM_ENDPOINT" not in os.environ and "FLYWHEEL_LLM_MODEL" not in os.environ:
            return 0

        if not (SS_BIN.exists() and PY_BIN.exists() and FLYWHEEL_PY.exists()):
            return 0                                   # no engine yet (setup not run) — nothing to heal

        if _recent(STAMP, THROTTLE_S):
            return 0                                   # throttled — a run happened recently

        env, qurl = _mcp_env()
        if not _qdrant_up(qurl):
            return 0                                   # store down — a run would just fail; skip

        sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
        import flywheel_llm                            # noqa: E402 — stdlib-only, cheap import
        ok, _detail = flywheel_llm.ping()
        if not ok:
            return 0                                   # endpoint configured but unreachable — fail-open

        LOGDIR.mkdir(parents=True, exist_ok=True)
        # Stamp BEFORE spawning so a crash-looping engine can't re-spawn every session.
        STAMP.write_text(str(int(time.time())), encoding="utf-8")
        logf = open(LOGFILE, "a", encoding="utf-8")
        logf.write(f"\n=== auto-flywheel {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        logf.flush()
        subprocess.Popen(
            [str(PY_BIN), str(FLYWHEEL_PY), "--generate", "--limit", str(MAX_PER_RUN)],
            env=env, stdout=logf, stderr=logf, stdin=subprocess.DEVNULL,
            start_new_session=True,                    # fully detached: outlives the hook, never blocks
        )
    except Exception:
        return 0                                       # fail-silent — never block session start
    return 0


if __name__ == "__main__":
    sys.exit(main())
