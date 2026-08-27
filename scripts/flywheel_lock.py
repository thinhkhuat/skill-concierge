#!/usr/bin/env python3
"""
flywheel_lock.py — cross-process mutual exclusion for the retrieval flywheel.

Both the detached auto-flywheel (hooks/scripts/auto_flywheel.py, SessionStart)
and a manual `scripts/flywheel.py --generate` touch the SAME durable state:

  • eval/triggers.json   (read-modify-write)
  • ~/.claude/skill-concierge/.flywheel-cache.json
  • ~/.claude/skill-concierge/flywheel-manifest.json
  • Qdrant points via the final reindex

With no lock they overlap freely. Live overlap was observed 2026-08-27:
two manifest runs 13 s apart (`03:29:12Z` and `03:29:25Z`) while a capped run
needs ~3 min (25 skills × 6 s + reindex) — i.e. two generators raced. The
doubled concurrency doubles the LLM request rate and is the likely multiplier
behind that night's 11-error spike (vs the normal 0-4).

Design:

  • Single lock file: ~/.claude/skill-concierge/.flywheel.lock  (same durable
    home as the cache/manifest, not the ephemeral plugin cache dir). Override
    with $FLYWHEEL_LOCK or $SKILL_CONCIERGE_HOME.
  • flock where available (macOS/Linux) — kernel releases on process death, so
    a crash never leaves a stale hold. Advisory, non-blocking for the check.
  • Fallback to O_CREAT|O_EXCL for platforms without fcntl (Windows) with a
    staleness timeout (2 h) + PID-liveness probe.
  • Lock file body (when held): "<pid> <epoch-seconds>\\n" for diagnostics.
    Readers that only need the held/not-held answer do not parse it.
  • Stdlib only.

Usage:

  from flywheel_lock import acquire, release, is_locked, holder

  if not acquire(block=False):          # manual run — bail with a clear message
      info = holder()
      print(f"another run holds lock {info}", file=sys.stderr)
      sys.exit(4)

  try:
      ... generate ...
  finally:
      release()

  # Hook (auto): fail-open — if locked, skip spawning.
  if is_locked():
      return 0

Stale window: a normal capped run is ~5 min; the fallback stale timeout is
2 h (7200 s) so only a truly orphaned file is reclaimed and a slow run is
never mistaken for stale.
"""
import os
import time
from pathlib import Path

try:
    import fcntl  # Unix
    _HAS_FCNTL = True
except ImportError:
    fcntl = None  # type: ignore
    _HAS_FCNTL = False

HOME = Path(os.environ.get("SKILL_CONCIERGE_HOME", Path.home() / ".claude" / "skill-concierge"))
LOCK_PATH = Path(os.environ.get("FLYWHEEL_LOCK", HOME / ".flywheel.lock"))
STALE_S = int(os.environ.get("FLYWHEEL_LOCK_STALE_S", "7200"))

_fd = None  # held file descriptor while this process owns the lock (fcntl path)
_excl_path = None  # marker for the O_EXCL fallback path


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ValueError, OverflowError):
        return False


def holder():
    """Return (pid:int|None, since:float|None) from the lock file body, or (None,None)."""
    try:
        text = LOCK_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return (None, None)
    if not text:
        return (None, None)
    parts = text.split()
    try:
        pid = int(parts[0])
    except (ValueError, IndexError):
        pid = None
    try:
        since = float(parts[1]) if len(parts) > 1 else None
    except ValueError:
        since = None
    return (pid, since)


def _is_stale() -> bool:
    pid, since = holder()
    if pid is not None and _pid_alive(pid):
        return False
    # No PID or dead PID — fall back to mtime.
    try:
        age = time.time() - LOCK_PATH.stat().st_mtime
    except OSError:
        return False
    return age > STALE_S


def is_locked() -> bool:
    """True if another process currently holds the lock (non-blocking probe).

    Never raises. Fail-open (False) on any unexpected error so callers never
    block session start because the probe itself broke.
    """
    if _HAS_FCNTL:
        try:
            fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_RDWR, 0o644)
        except OSError:
            return False
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)  # type: ignore
            # We got it — not locked by anyone else. Release immediately.
            fcntl.flock(fd, fcntl.LOCK_UN)  # type: ignore
            return False
        except OSError:
            return True
        finally:
            try:
                os.close(fd)
            except OSError:
                pass
    # Fallback (no fcntl): existence + staleness.
    if not LOCK_PATH.exists():
        return False
    if _is_stale():
        return False
    return True


def acquire(block: bool = False) -> bool:
    """Try to acquire the flywheel lock. Returns True on success.

    block=False  → non-blocking (typical: manual run, hook probe)
    block=True   → blocking with fcntl (not used today, but available)

    On success the lock file contains "<pid> <epoch>".
    Caller must call release() (typically in a finally block).
    """
    global _fd, _excl_path
    if _HAS_FCNTL:
        try:
            LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_RDWR, 0o644)
        except OSError:
            return False
        try:
            flags = fcntl.LOCK_EX | (0 if block else fcntl.LOCK_NB)  # type: ignore
            fcntl.flock(fd, flags)  # type: ignore
        except OSError:
            try:
                os.close(fd)
            except OSError:
                pass
            return False
        # Held — record owner for diagnostics.
        try:
            os.ftruncate(fd, 0)
            os.write(fd, f"{os.getpid()} {time.time():.0f}\n".encode())
        except OSError:
            pass
        _fd = fd
        return True

    # Fallback: atomic create.
    try:
        LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    if LOCK_PATH.exists() and _is_stale():
        try:
            LOCK_PATH.unlink()
        except OSError:
            pass
    try:
        fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        os.write(fd, f"{os.getpid()} {time.time():.0f}\n".encode())
        os.close(fd)
        _excl_path = LOCK_PATH
        return True
    except FileExistsError:
        return False
    except OSError:
        return False


def release() -> None:
    """Release the lock held by this process. No-op if not held."""
    global _fd, _excl_path
    if _HAS_FCNTL and _fd is not None:
        try:
            fcntl.flock(_fd, fcntl.LOCK_UN)  # type: ignore
        except OSError:
            pass
        try:
            os.close(_fd)
        except OSError:
            pass
        _fd = None
        # Keep the file on disk for diagnostics (unlocked — is_locked() will
        # correctly report unlocked via flock). Truncating would lose the last
        # holder's PID that doctor/log readers may want. Do not unlink.
        return
    if _excl_path is not None:
        try:
            _excl_path.unlink()
        except OSError:
            pass
        _excl_path = None


def _selftest():
    import tempfile
    import shutil
    global LOCK_PATH, _fd, _excl_path

    real_lock = LOCK_PATH
    real_fd = _fd
    real_excl = _excl_path
    tmp_dir = Path(tempfile.mkdtemp())
    LOCK_PATH = tmp_dir / ".flywheel.lock"
    _fd = None
    _excl_path = None
    try:
        assert not is_locked(), "fresh tmp dir should not be locked"
        assert acquire(block=False) is True, "first acquire should succeed"
        assert is_locked() is True, "is_locked() should be True while we hold it"
        pid, since = holder()
        assert pid == os.getpid(), f"holder pid should be ours, got {pid}"
        assert since is not None and since > 0

        # Second acquire (simulating a concurrent process) must fail
        # For fcntl path we need a separate fd to probe; acquire() uses the
        # same global _fd so we test via is_locked() + a raw flock on a new fd.
        if _HAS_FCNTL:
            fd2 = os.open(str(LOCK_PATH), os.O_RDWR)
            try:
                try:
                    fcntl.flock(fd2, fcntl.LOCK_EX | fcntl.LOCK_NB)  # type: ignore
                    assert False, "second flock should have failed"
                except OSError:
                    pass  # expected — locked
            finally:
                os.close(fd2)
        else:
            assert acquire(block=False) is False, "second O_EXCL acquire should fail"

        release()
        assert not is_locked(), "after release, is_locked() should be False"

        # Re-acquire after release should succeed
        assert acquire(block=False) is True
        release()
        assert not is_locked()

        # Stale fallback: create a file with dead PID + old mtime, is_locked should be False
        if not _HAS_FCNTL:
            LOCK_PATH.write_text("999999 0\n", encoding="utf-8")
            old = time.time() - STALE_S - 10
            os.utime(str(LOCK_PATH), (old, old))
            assert not is_locked(), "stale lock should not count as locked"
            assert acquire(block=False) is True, "should be able to acquire stale lock"
            release()

        print("PASS")
    finally:
        # Clean up any held fd before removing tmp dir
        try:
            if _fd is not None:
                fcntl.flock(_fd, fcntl.LOCK_UN)  # type: ignore
                os.close(_fd)
        except Exception:
            pass
        _fd = real_fd
        _excl_path = real_excl
        LOCK_PATH = real_lock
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        _selftest()
    else:
        print(__doc__)
