#!/usr/bin/env python3
"""
skill-concierge — usage-promotion self-heal (SessionStart hook, ADR-0032 Phase 3).

External catalog skills (ADR-0031) are search-only + annex citizens (ADR-0032): retrievable
and consumable via get_skill, but NOT registered with Claude Code, so the Skill tool can't
invoke them. When the agent USES one repeatedly, it has earned first-class status. This hook
graduates it: a catalog skill whose external `get_skill` takes span ≥ PROMOTE_MIN_TAKES
DISTINCT sessions is symlink-promoted into ~/.claude/skills via `catalogs.py promote`, becoming
a real installed (Skill-tool-invocable) skill under the concierge's name-only budget. Organic
curation — the resident set grows only by demonstrated usage, never by mass install.

Design contract (mirrors auto_flywheel.py):
  • FAIL-OPEN — no ledger, no catalog config, promote error -> silent no-op, exit 0.
  • NON-BLOCKING — promotion is a symlink (cheap); runs inline but is bounded + throttled.
  • THROTTLED — at most one pass per AUTO_PROMOTE_THROTTLE_S (default 21600s = 6h).
  • IDEMPOTENT — an already-promoted skill (name exists in ~/.claude/skills) is refused by
    catalogs.py promote and skipped; re-running never double-promotes.
  • GATED — PROMOTE_ENABLED=0 disables the hook (default "1" = ON).

Distinct-session counting uses ledger `sid` uniqueness and EXCLUDES subagent rows (`sub`).
"""
import json
import os
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

LOGDIR = Path(os.environ.get("SKILL_CONCIERGE_LOG", Path.home() / ".claude/skill-concierge/logs"))
LEDGER = LOGDIR / "skill-invocation-ledger.log"
STAMP = LOGDIR / ".auto-promote-stamp"
LOGFILE = LOGDIR / "auto-promote.log"
THROTTLE_S = int(os.environ.get("AUTO_PROMOTE_THROTTLE_S", "21600"))
MIN_TAKES = int(os.environ.get("PROMOTE_MIN_TAKES", "3"))
ENABLED = os.environ.get("PROMOTE_ENABLED", "1") != "0"
PLUGIN_ROOT = Path(os.environ.get("CLAUDE_PLUGIN_ROOT", Path(__file__).resolve().parent.parent.parent))
CATALOGS_PY = PLUGIN_ROOT / "scripts" / "catalogs.py"
CATALOG_ROOTS = Path(os.environ.get(
    "SKILL_CONCIERGE_CATALOG_ROOTS",
    Path.home() / ".claude" / "skill-concierge" / "catalog-roots.json"))
LEDGER_TAIL_BYTES = 1_048_576   # scan at most the last 1 MB of the ledger


def _aliases() -> tuple:
    """Configured catalog alias prefixes (`antigravity:` …), or () when none/unreadable."""
    try:
        cfg = json.loads(CATALOG_ROOTS.read_text(encoding="utf-8"))
        return tuple(f"{a}:" for a in cfg if isinstance(a, str) and not a.startswith("_"))
    except Exception:
        return ()


def _distinct_session_takes(aliases: tuple) -> dict:
    """{external_skill_name: set(distinct sids)} from external get_skill takes (sub excluded)."""
    takes = defaultdict(set)
    if not aliases:
        return takes
    try:
        size = LEDGER.stat().st_size
        with LEDGER.open("rb") as f:
            f.seek(max(0, size - LEDGER_TAIL_BYTES))
            lines = f.read().decode("utf-8", "replace").splitlines()
        if size > LEDGER_TAIL_BYTES:
            lines = lines[1:]           # drop the partial first line
    except OSError:
        return takes
    for line in lines:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("ev") != "get_skill" or e.get("sub"):
            continue
        name = e.get("name") or ""
        sid = e.get("sid") or ""
        if sid and isinstance(name, str) and name.startswith(aliases):
            takes[name].add(sid)
    return takes


def _promote(name: str) -> tuple:
    """Run catalogs.py promote for one <alias>:<name>. Returns (ok, message)."""
    try:
        r = subprocess.run(
            [sys.executable, str(CATALOGS_PY), "promote", name],
            capture_output=True, text=True, timeout=15,
            env={**os.environ, "SKILL_CONCIERGE_CATALOG_ROOTS": str(CATALOG_ROOTS)})
        out = (r.stdout or r.stderr or "").strip()
        return r.returncode == 0, (out.splitlines()[0] if out else "")
    except Exception as e:
        return False, str(e)


def _log(msg: str) -> None:
    try:
        LOGDIR.mkdir(parents=True, exist_ok=True)
        with LOGFILE.open("a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except Exception:
        pass


def _recent(path: Path, window: int) -> bool:
    try:
        return (time.time() - path.stat().st_mtime) < window
    except OSError:
        return False


def run_once() -> int:
    """Promote every external skill at/over the distinct-session threshold. Returns count promoted."""
    aliases = _aliases()
    takes = _distinct_session_takes(aliases)
    promoted = 0
    for name, sids in sorted(takes.items()):
        if len(sids) < MIN_TAKES:
            continue
        ok, msg = _promote(name)
        if ok:
            promoted += 1
            _log(f"promoted {name} ({len(sids)} sessions): {msg}")
        else:
            # collision / already promoted / error — idempotent skip, logged at debug volume
            _log(f"skip {name} ({len(sids)} sessions): {msg}")
    return promoted


def main() -> int:
    try:
        if not ENABLED:
            return 0
        if not (CATALOGS_PY.exists() and CATALOG_ROOTS.exists()):
            return 0                                  # feature off / not installed
        if _recent(STAMP, THROTTLE_S):
            return 0                                  # throttled
        LOGDIR.mkdir(parents=True, exist_ok=True)
        STAMP.write_text(str(int(time.time())), encoding="utf-8")   # stamp before work
        n = run_once()
        if n:
            _log(f"pass complete: {n} promoted")
    except Exception:
        return 0                                      # fail-silent — never block session start
    return 0


def _selftest() -> int:
    import tempfile
    global LEDGER, CATALOG_ROOTS, CATALOGS_PY, MIN_TAKES
    saved = (LEDGER, CATALOG_ROOTS, CATALOGS_PY, MIN_TAKES)
    ok = True
    try:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            CATALOG_ROOTS = tdp / "catalog-roots.json"
            CATALOG_ROOTS.write_text(json.dumps({"anti": {"path": str(tdp / "cat")}}))
            aliases = _aliases()
            ok &= aliases == ("anti:",)
            LEDGER = tdp / "ledger.log"
            rows = [
                {"ev": "get_skill", "sid": "s1", "name": "anti:x"},
                {"ev": "get_skill", "sid": "s2", "name": "anti:x"},
                {"ev": "get_skill", "sid": "s3", "name": "anti:x"},   # x: 3 distinct sids
                {"ev": "get_skill", "sid": "s1", "name": "anti:x"},   # dup sid -> not counted twice
                {"ev": "get_skill", "sid": "s1", "name": "anti:y"},
                {"ev": "get_skill", "sid": "s2", "name": "anti:y"},   # y: 2 distinct sids
                {"ev": "get_skill", "sid": "s9", "name": "anti:z", "sub": True},  # subagent -> excluded
                {"ev": "get_skill", "sid": "s4", "name": "installed"},            # non-external
            ]
            LEDGER.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
            takes = _distinct_session_takes(aliases)
            ok &= takes.get("anti:x") == {"s1", "s2", "s3"}
            ok &= takes.get("anti:y") == {"s1", "s2"}
            ok &= "anti:z" not in takes            # subagent row excluded
            ok &= "installed" not in takes         # non-external excluded
            # threshold: at MIN_TAKES=3, only x qualifies; at 2, x and y
            MIN_TAKES = 3
            q3 = sorted(n for n, s in takes.items() if len(s) >= MIN_TAKES)
            ok &= q3 == ["anti:x"]
            MIN_TAKES = 2
            q2 = sorted(n for n, s in takes.items() if len(s) >= MIN_TAKES)
            ok &= q2 == ["anti:x", "anti:y"]
            # empty ledger / no aliases -> no takes, no crash
            ok &= _distinct_session_takes(()) == {}
    finally:
        LEDGER, CATALOG_ROOTS, CATALOGS_PY, MIN_TAKES = saved
    print("auto-promote --selftest " + ("OK" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    sys.exit(main())
