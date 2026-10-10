"""Diagnostic only (not part of the suite): repeat the codex kill test's scenario and, when the
installer is still alive 8 s after SIGTERM, dump its process tree and bash stack before killing it.
usage: hang_probe.py N   (run from the worktree root)"""
import os, signal, subprocess, sys, tempfile, time
from pathlib import Path

sys.path.insert(0, str(Path.cwd() / "tests"))
import test_codex_installer as cx
from installer_env import installer_env
import test_installer_staging_cleanup as t

n = int(sys.argv[1])
bad = 0
for i in range(n):
    tmp = Path(tempfile.mkdtemp(prefix="hp-"))
    home, fakebin = cx._make_home(tmp, {"marketplace_registered": True, "plugin_installed": False,
                                        "remote_version": "0.45.0"})
    env = installer_env(tmp, home, t._slow_git_dir(tmp), fakebin, FAKE_CODEX_ENFORCER_SRC=str(cx.ENFORCER_SRC))
    cache = cx._cache_root(home)
    proc = subprocess.Popen(["bash", str(cx.INSTALLER)], env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, start_new_session=True)
    stage = None
    t0 = time.monotonic()
    while time.monotonic() - t0 < 30:
        hits = list(cache.glob(".skill-concierge-staging.*")) if cache.exists() else []
        if hits:
            stage = hits[0]; break
        if proc.poll() is not None:
            break
        time.sleep(0.02)
    if stage is None:
        print(i, "never reached staging", proc.poll()); continue
    ts = time.monotonic()
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=8)
        left = list(cache.glob(".skill-concierge-staging.*"))
        print(i, "rc", proc.returncode, "wait %.2fs" % (time.monotonic() - ts), "leftover", left, flush=True)
        if left: bad += 1
    except subprocess.TimeoutExpired:
        bad += 1
        print(i, "HANG after SIGTERM; process tree:", flush=True)
        print(subprocess.run(["ps", "-o", "pid,ppid,pgid,stat,etime,command", "-g", str(proc.pid)],
                             capture_output=True, text=True).stdout, flush=True)
        print("bash fds:", subprocess.run(["lsof", "-p", str(proc.pid)], capture_output=True, text=True).stdout[-1500:], flush=True)
        print("cache ls:", sorted(p.name for p in cache.iterdir()), flush=True)
        gp = subprocess.run(["pgrep", "-g", str(proc.pid), "-x", "git"], capture_output=True, text=True).stdout.split()
        for g in gp:
            print(subprocess.run(["lsof", "-p", g], capture_output=True, text=True).stdout[-2500:], flush=True)
            print(subprocess.run(["sample", g, "1"], capture_output=True, text=True).stdout[:3000], flush=True)
        print("tar procs:", subprocess.run("ps -ax -o pid,ppid,stat,command | grep '[t]ar -x'", shell=True, capture_output=True, text=True).stdout, flush=True)
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
print("bad", bad, "of", n)
