#!/usr/bin/env python3
"""
skill-concierge — agent-definition bridge self-heal (SessionStart hook).

The agent mirror (`~/.commandcode/agents`) is derived data: one Command Code-native copy per agent
whose source lives in the Claude Code corpus (`~/.claude/agents`), with the `tools:` ids, the `model`
and the delegation/messaging idioms translated to what Command Code reads. Left to a manual rebuild
it silently goes stale the moment an agent is added, renamed or edited, and Command Code keeps
serving yesterday's copy: an agent edited to take a new tool keeps launching without it, and nothing
reports the loss. This hook removes that dependency on human-or-agent discipline.

Design contract (mirrors the sibling auto_bridge / auto_reindex / auto_promote hooks):
  • FAIL-SILENT — any error exits 0 and prints nothing; a hook must never break or block session
    start, and SessionStart stdout becomes model context, so this hook is maintenance, not prompt.
    A failed rebuild IS logged (`auto-agent-bridge.log`) — silence would leave a stale mirror and no
    way to know.
  • THROTTLED — at most one build per AUTO_AGENT_BRIDGE_THROTTLE_S (default 300s), tracked by a
    stamp file. Every SessionStart self-heal hook keeps this contract, and `scripts/smoke.py` lists
    each stamp in SELF_HEAL_STAMPS so a smoke run can never churn live state. The window is short on
    purpose: the builder's own fingerprint check makes the run itself a no-op when nothing changed.
  • INLINE, NOT DETACHED — two reasons, both load-bearing. Command Code re-scans agent files each
    turn, so a half-written mirror is a subagent that launches with the wrong tool set; and the work
    is bounded (45 files, well under a second), with BUILDER_TIMEOUT_S as the hard ceiling.
  • INSTALLED-ONLY — it runs only where the bridge has been installed (the destination exists as a
    real directory). While `~/.commandcode/agents` is still the symlink to the Claude corpus, this
    hook does nothing at all: the builder refuses to write through a symlink, and asking it every
    session would only fill the log with refusals.

Disable with AGENT_BRIDGE=0, or remove the hook entry.
"""
import os
import subprocess
import sys
import time
from pathlib import Path

# hooks/scripts/auto_agent_bridge.py -> plugin root is two parents up; CLAUDE_PLUGIN_ROOT wins.
PLUGIN_ROOT = Path(os.environ.get("CLAUDE_PLUGIN_ROOT", Path(__file__).resolve().parent.parent.parent))
BUILDER = PLUGIN_ROOT / "scripts" / "cmd_agent_bridge.py"
DEST = Path(os.environ.get("AGENT_BRIDGE_DEST") or (Path.home() / ".commandcode" / "agents"))
ENABLED = os.environ.get("AGENT_BRIDGE", "1") != "0"
BUILDER_TIMEOUT_S = 15
LOGDIR = Path(os.environ.get("SKILL_CONCIERGE_LOG", Path.home() / ".claude/skill-concierge/logs"))
STAMP = LOGDIR / ".auto-agent-bridge-stamp"
LOGFILE = LOGDIR / "auto-agent-bridge.log"
try:
    THROTTLE_S = int(os.environ.get("AUTO_AGENT_BRIDGE_THROTTLE_S", "300"))
except ValueError:
    THROTTLE_S = 300                               # an env typo never kills a session-start hook


def _recent(path: Path) -> bool:
    """True when `path` was touched inside the throttle window. A missing stamp is not recent."""
    try:
        return (time.time() - path.stat().st_mtime) < THROTTLE_S
    except OSError:
        return False


def _log(line: str) -> None:
    """A failed rebuild is invisible otherwise — and silence would leave the user with a stale
    mirror and no way to know. Log only on failure, so a healthy session writes nothing."""
    try:
        LOGFILE.parent.mkdir(parents=True, exist_ok=True)
        with LOGFILE.open("a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}\n")
    except (OSError, UnicodeError):
        return


def _installed() -> bool:
    """True only where the bridge owns its destination: a real directory, never the shared corpus
    symlink (writing there would edit the Claude Code originals)."""
    try:
        return DEST.is_dir() and not DEST.is_symlink()
    except OSError:
        return False


def main() -> int:
    try:
        if not ENABLED or not BUILDER.is_file() or not _installed():
            return 0
        if THROTTLE_S > 0 and _recent(STAMP):
            return 0                               # throttled — a build ran recently
        STAMP.parent.mkdir(parents=True, exist_ok=True)
        # Stamp BEFORE the work, so a builder that fails repeatedly cannot re-run every session.
        STAMP.write_text(str(int(time.time())), encoding="utf-8")
        args = [sys.executable, str(BUILDER), "build", "--quiet"]
        if os.environ.get("AGENT_BRIDGE_DEST"):
            args += ["--dest", os.environ["AGENT_BRIDGE_DEST"]]
        run = subprocess.run(args, capture_output=True, text=True,
                             timeout=BUILDER_TIMEOUT_S, check=False)
        if run.returncode != 0:
            _log(f"{BUILDER} exited {run.returncode}: "
                 f"{(run.stdout + run.stderr).strip()[:500] or '(no output)'}")
    except subprocess.TimeoutExpired:
        _log(f"{BUILDER} exceeded {BUILDER_TIMEOUT_S}s — mirror left as it was")
    except (OSError, UnicodeError, ValueError):
        return 0                                   # fail-silent — never block session start
    return 0


def _selftest() -> int:
    """The gate, the installed-only check and the throttle — a hook that runs when disabled, runs
    while the destination is still the shared symlink, or lets a failing builder raise would be
    worse than no hook at all."""
    global BUILDER, DEST, ENABLED, LOGFILE, STAMP, THROTTLE_S
    import tempfile
    saved = (BUILDER, DEST, ENABLED, LOGFILE, STAMP, THROTTLE_S)
    ok = True
    try:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            (tdp / "log").mkdir()
            fake = tdp / "builder.py"
            fake.write_text("import sys, pathlib\n"
                            "pathlib.Path(sys.argv[0] + '.ran').write_text('x')\n"
                            "sys.stderr.write('boom')\nsys.exit(3)")
            dest = tdp / "agents"
            dest.mkdir()
            BUILDER, DEST, ENABLED = fake, dest, True
            LOGFILE, STAMP, THROTTLE_S = tdp / "log" / "auto-agent-bridge.log", tdp / "log" / ".stamp", 300
            # a builder that fails is logged, not raised — and the hook still exits 0
            ok &= main() == 0
            ok &= "exited 3" in LOGFILE.read_text() and "boom" in LOGFILE.read_text()
            # the stamp was written BEFORE the work, and a fresh stamp throttles the next run
            ok &= STAMP.is_file()
            ran = Path(str(fake) + ".ran")
            ran.unlink()
            ok &= main() == 0
            if ran.exists():
                print("  [!] a fresh stamp must throttle the next run")
                ok = False
            THROTTLE_S = 0
            ok &= main() == 0 and ran.exists()
            # disabled -> the builder is never run and nothing is logged
            LOGFILE.unlink()
            ENABLED = False
            ok &= main() == 0 and not LOGFILE.exists()
            # a symlinked destination is never written through: it is the shared Claude corpus
            ENABLED = True
            link = tdp / "link"
            link.symlink_to(dest)
            real, DEST = DEST, link
            ran.unlink()
            ok &= main() == 0
            if ran.exists():
                print("  [!] a symlinked dest must never be built through")
                ok = False
            DEST = real
            # a missing destination (bridge not installed here) is a no-op, not an error
            DEST = tdp / "nope"
            ok &= main() == 0
            # a missing builder is a no-op too
            DEST, BUILDER = real, tdp / "missing.py"
            ok &= main() == 0
    finally:
        BUILDER, DEST, ENABLED, LOGFILE, STAMP, THROTTLE_S = saved
    print("auto-agent-bridge --selftest " + ("OK" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    sys.exit(main())
