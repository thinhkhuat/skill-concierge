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
import hashlib
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


def _meta_path() -> Path:
    """Where the last reindex recorded what it landed. Mirrors server.META_PATH,
    including its per-project key — the hook shares this session's CWD, so it
    derives the same file the engine wrote."""
    env = os.environ.get("SKILL_META_PATH")
    if env:
        return Path(env)
    key = hashlib.md5(str(Path.cwd() / ".claude" / "skills").encode()).hexdigest()[:8]
    return Path.home() / ".cache" / "skill-search" / f"index_meta-{key}.json"


def _indexed_count():
    """Skills the last completed reindex put in the index, or None if unknown."""
    try:
        return int(json.loads(_meta_path().read_text(encoding="utf-8"))["indexed"])
    except Exception:
        return None


def _disk_count():
    """Skills discoverable on disk right now, via the engine's own discovery.

    Shells out to the engine venv because skills_discovery is dep-free but lives
    in the venv, while this hook runs under the system interpreter.
    """
    try:
        out = subprocess.run(
            [str(PY_BIN), "-c",
             "from skill_search.skills_discovery import discover_skills;"
             "print(len(discover_skills()))"],
            capture_output=True, text=True, timeout=30)
        return int(out.stdout.strip())
    except Exception:
        return None


def _index_lags_disk() -> bool:
    """True when the index holds FEWER skills than disk — i.e. a reindex has not
    landed yet. Coverage measured now would report a false '0 missing'.

    Fails open (False) when either count is unknown: a fresh install with no
    manifest must not wedge the flywheel off permanently. An index LARGER than
    disk is normal on a shared collection (another session's project skills) and
    is not a reason to defer.
    """
    idx, disk = _indexed_count(), _disk_count()
    if idx is None or disk is None:
        return False
    return idx < disk


def _ping_ok() -> bool:
    """Endpoint reachability, isolated so tests can stub it without a network."""
    sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
    import flywheel_llm                            # noqa: E402 — stdlib-only, cheap import
    ok, _detail = flywheel_llm.ping()
    return ok


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

        # auto_reindex fires from the same SessionStart batch, detached and unordered.
        # Measuring coverage before it lands yields a false "0 missing", and stamping
        # on that lie silences the flywheel for THROTTLE_S. Defer WITHOUT stamping so
        # the next session start retries against a settled index.
        if _index_lags_disk():
            return 0

        if not _ping_ok():
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
