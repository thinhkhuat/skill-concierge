"""M6: `stop_owner` must never claim success on a process that ignored SIGTERM — it has to
exit non-zero with a clear message and keep the pid file, so a stale/undead owner is never
silently forgotten. Exercised against real throwaway child processes (never the real staging
owner, never Docker, never a live Qdrant).
"""
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import migrate_qdrant_to_local as M  # noqa: E402


@pytest.fixture(autouse=True)
def _fast_wait(monkeypatch):
    # stop_owner()'s wait loop polls os.kill(pid, 0) up to 60x with a real time.sleep(0.25)
    # between checks (~15s worst case). Shrink each sleep to 10ms (still real wall-clock, so
    # the kernel has time to actually deliver SIGTERM and reap the child) instead of zero,
    # which would race the signal and flake.
    real_sleep = time.sleep
    monkeypatch.setattr(M.time, "sleep", lambda s: real_sleep(min(s, 0.01)))


def _spawn(*cmd):
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return proc


def test_stop_owner_reports_and_keeps_pidfile_when_process_ignores_sigterm(tmp_path, monkeypatch):
    proc = _spawn("sh", "-c", "trap '' TERM; while true; do sleep 0.05; done")
    try:
        pidfile = tmp_path / "owner.pid"
        pidfile.write_text(str(proc.pid))
        monkeypatch.setattr(M, "PIDFILE", pidfile)
        with pytest.raises(SystemExit) as exc:
            M.stop_owner()
        assert exc.value.code is not None and str(exc.value.code) != "0"
        assert str(proc.pid) in str(exc.value.code)
        assert "did not stop" in str(exc.value.code)
        # fail-open on the housekeeping side: the pid file survives so a retry can find it
        assert pidfile.exists()
        assert pidfile.read_text().strip() == str(proc.pid)
    finally:
        proc.send_signal(signal.SIGKILL)
        proc.wait(timeout=5)


def test_stop_owner_unlinks_pidfile_when_process_actually_stops(tmp_path, monkeypatch):
    proc = _spawn("sleep", "30")  # default SIGTERM disposition: dies immediately
    # We are this child's parent, so a dead-but-unreaped process stays a zombie (os.kill(pid,
    # 0) keeps succeeding on a zombie's pid) until something calls wait() on it — reap it in
    # the background the instant it exits, exactly as an unrelated `--stop` invocation would
    # never need to (it is never the owner's parent).
    threading.Thread(target=proc.wait, daemon=True).start()
    pidfile = tmp_path / "owner.pid"
    pidfile.write_text(str(proc.pid))
    monkeypatch.setattr(M, "PIDFILE", pidfile)
    M.stop_owner()  # must not raise
    assert not pidfile.exists()


def test_stop_owner_unlinks_pidfile_when_pid_already_gone(tmp_path, monkeypatch):
    proc = _spawn("sh", "-c", "exit 0")
    proc.wait(timeout=5)
    pidfile = tmp_path / "owner.pid"
    pidfile.write_text(str(proc.pid))
    monkeypatch.setattr(M, "PIDFILE", pidfile)
    M.stop_owner()  # must not raise even though the pid is already dead
    assert not pidfile.exists()


def test_stop_owner_no_pidfile_is_a_no_op(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(M, "PIDFILE", tmp_path / "missing.pid")
    M.stop_owner()
    assert "nothing to stop" in capsys.readouterr().out


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
