"""Helpers shared by the SessionStart self-heal hooks (auto_reindex, auto_overrides, auto_flywheel).

Each hook imports these by name, so a test still patches them as the hook's own attributes.
Stdlib only, Python 3.9-safe.
"""
import os
import sys
import time
import urllib.request


def recent(path, within):
    try:
        return (time.time() - path.stat().st_mtime) < within
    except FileNotFoundError:
        return False


def mcp_env(plugin_root):
    """The query server's engine settings (scripts/engine_env.py); fail-silent to the process
    env. The store URL comes from skill_search.ports (the one place that reads
    SKILL_QDRANT_URL and applies the shared port grammar); fail-silent to the fixed
    well-known default if the vendored package can't be imported."""
    try:
        sys.path.insert(0, str(plugin_root / "scripts"))
        import engine_env
        merged = engine_env.engine_env(plugin_root)
    except Exception:
        merged = dict(os.environ)
    try:
        sys.path.insert(0, str(plugin_root / "vendor" / "skill-search"))
        from skill_search import ports
        url = ports.qdrant_url(env=merged, default_port=6333)
    except Exception:
        url = "http://localhost:6333"
    return merged, url


def qdrant_up(url, timeout=0.8):
    for u in (url.rstrip("/") + "/healthz", url):
        try:
            with urllib.request.urlopen(u, timeout=timeout) as response:
                status = response.status
        except (OSError, ValueError):
            status = None
        if status == 200:
            return True
    return False


def flywheel_locked(plugin_root) -> bool:
    """True while a flywheel run (auto or manual) or a trigger backfill holds the lock
    (scripts/flywheel_lock.py). A reindex would embed a triggers.json that is mid-rewrite, and two
    generation runs would double the LLM request rate (observed 2026-08-27: 13 s-apart runs).
    Fail-open (False) if the lock module cannot be imported."""
    try:
        sys.path.insert(0, str(plugin_root / "scripts"))
        import flywheel_lock
        return flywheel_lock.is_locked()
    except Exception:
        return False
