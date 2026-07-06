#!/usr/bin/env python3
"""
skill-concierge — settings-override self-heal (SessionStart hook).

The retrieval index self-heals (auto_reindex.py), but ~/.claude/settings.json
`skillOverrides` did not: it was a one-shot snapshot written at setup. When skills are
installed/removed (or the keep-on allowlist is edited), the override map drifts — newly
installed skills inject their FULL description on every turn ("name-only leak") until
someone remembers to re-run apply-overrides. This hook removes that human dependency:
on session start it fires a DETACHED, THROTTLED reconcile that re-applies the overrides
ONLY when they actually drifted (apply-overrides.py --if-changed), so a no-op session
never rewrites settings or churns a backup.

Design contract (mirrors auto_reindex.py / doctrine / enforcer / ledger):
  • FAIL-SILENT — any error exits 0; a hook must never break or block session start.
  • NON-BLOCKING — the reconcile is spawned detached and NOT waited on; --if-changed is
    idempotent (writes only on real drift).
  • THROTTLED — at most one reconcile per AUTO_OVERRIDES_THROTTLE_S (default 1800s),
    tracked by a stamp file, so rapid restarts don't churn.
  • SILENT / ADDITIVE — emits no context; it is maintenance, not a prompt.
  • OFFLINE — skill discovery is SKILL.md parsing; no Qdrant/embedder needed, so (unlike
    auto_reindex) there is no store-reachability gate. It DOES need the engine venv python,
    because the applier imports the vendored discovery (3.10+ syntax).

Disable by setting AUTO_OVERRIDES_THROTTLE_S to a huge value, or remove the hook entry.
"""
import os
import subprocess
import sys
import time
from pathlib import Path

VENV = Path(os.environ.get("SKILL_CONCIERGE_VENV", Path.home() / ".claude/skill-concierge/venv"))
PY_BIN = VENV / "bin" / "python"
LOGDIR = Path(os.environ.get("SKILL_CONCIERGE_LOG", Path.home() / ".claude/skill-concierge/logs"))
STAMP = LOGDIR / ".auto-overrides-stamp"
LOGFILE = LOGDIR / "auto-overrides.log"
THROTTLE_S = int(os.environ.get("AUTO_OVERRIDES_THROTTLE_S", "1800"))
# hooks/scripts/auto_overrides.py -> plugin root is two parents up; CLAUDE_PLUGIN_ROOT wins.
PLUGIN_ROOT = Path(os.environ.get("CLAUDE_PLUGIN_ROOT", Path(__file__).resolve().parent.parent.parent))
APPLIER = PLUGIN_ROOT / "scripts" / "apply-overrides.py"


def _recent(path, within):
    try:
        return (time.time() - path.stat().st_mtime) < within
    except FileNotFoundError:
        return False


def main() -> int:
    try:
        if not (PY_BIN.exists() and os.access(PY_BIN, os.X_OK)):
            return 0                                   # no engine venv yet (setup not run)
        if not APPLIER.exists():
            return 0
        if _recent(STAMP, THROTTLE_S):
            return 0                                   # throttled — a reconcile ran recently
        LOGDIR.mkdir(parents=True, exist_ok=True)
        # Stamp BEFORE spawning so a crash-looping applier can't re-spawn every session.
        STAMP.write_text(str(int(time.time())), encoding="utf-8")
        logf = open(LOGFILE, "a", encoding="utf-8")
        logf.write(f"\n=== auto-overrides {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        logf.flush()
        subprocess.Popen(
            [str(PY_BIN), str(APPLIER), "--if-changed"],
            stdout=logf, stderr=logf, stdin=subprocess.DEVNULL,
            start_new_session=True,                    # fully detached: outlives the hook, never blocks
        )
    except Exception:
        return 0                                       # fail-silent — never block session start
    return 0


if __name__ == "__main__":
    sys.exit(main())
