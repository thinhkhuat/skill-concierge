"""adapters/{claude-code,codex,omp,zcode}/install.sh share one `_export_to` helper that
stages an export beside its destination (`mktemp -d "$parent/.staging.XXXXXX"`) before
swapping it in. A run killed between the `mktemp` and the final `mv` used to leave that
staging dir behind forever — nothing removed it. `_export_to` must now remove its own
staging dir on a normal exit, on EXIT/INT/TERM, and prune any stale `.staging.*` dir left
over from an earlier killed run before it stages a new one."""
import json
import shutil
import signal
import subprocess
import time
from pathlib import Path

from installer_env import installer_env

ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = {
    "claude-code": ROOT / "adapters" / "claude-code" / "install.sh",
    "codex": ROOT / "adapters" / "codex" / "install.sh",
    "omp": ROOT / "adapters" / "omp" / "install.sh",
    "zcode": ROOT / "adapters" / "zcode" / "install.sh",
}


def _export_to_body(text):
    lines = text.splitlines(keepends=True)
    start = next(i for i, l in enumerate(lines) if l.startswith("_export_to() {"))
    depth = 0
    end = start
    for i in range(start, len(lines)):
        depth += lines[i].count("{") - lines[i].count("}")
        if i > start and depth == 0:
            end = i
            break
    return "".join(lines[start:end + 1])


# The staging-cleanup fix itself, not the whole function (a pre-existing, unrelated wording/
# exclude-list difference already sits in ZCode's non-git-checkout branch): every installer
# must prune a stale staging dir the same way and trap its own staging dir the same way.
_CLEANUP_LINES = (
    "-mmin +60",
    'trap \'rm -rf "$stage"; exit 1\' EXIT INT TERM',
    "trap - EXIT INT TERM",
)


def test_export_to_cleanup_is_identical_across_the_four_installers():
    """Sibling parity: fixing the staging-dir cleanup in one installer without syncing the
    other three would leave three of them still leaking staging dirs."""
    bodies = {name: _export_to_body(path.read_text()) for name, path in INSTALL_SH.items()}
    for name, body in bodies.items():
        for line in _CLEANUP_LINES:
            assert line in body, f"_export_to in adapters/{name}/install.sh is missing: {line!r}"


def _make_repo(tmp_path, version):
    repo = tmp_path / "repo"
    (repo / ".claude-plugin").mkdir(parents=True)
    (repo / ".claude-plugin" / "plugin.json").write_text(json.dumps({"version": version}))
    (repo / "bin").mkdir()
    launcher = repo / "bin" / "skill-search-mcp"
    launcher.write_text("#!/bin/sh\necho fixture-launcher\n")
    launcher.chmod(0o755)
    (repo / "hooks" / "scripts").mkdir(parents=True)
    (repo / "hooks" / "scripts" / "enforcer.py").write_text(f"# enforcer fixture v{version}\n")
    setup = repo / "setup.sh"
    setup.write_text("#!/bin/sh\n")
    setup.chmod(0o755)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init"],
                    cwd=repo, check=True)
    return repo


def _seed_claude_home(tmp_path, *, installed_version):
    home = tmp_path / "home"
    plugins_dir = home / ".claude" / "plugins"
    plugins_dir.mkdir(parents=True)
    plugin_id = "skill-concierge@skill-concierge"
    cache_base = plugins_dir / "cache" / "skill-concierge" / "skill-concierge"
    old_dir = cache_base / installed_version
    old_dir.mkdir(parents=True)
    (old_dir / ".claude-plugin").mkdir()
    (old_dir / ".claude-plugin" / "plugin.json").write_text(json.dumps({"version": installed_version}))
    registry = {"plugins": {plugin_id: [{
        "scope": "user", "installPath": str(old_dir), "version": installed_version,
        "installedAt": "2026-06-26T06:44:59.002Z", "lastUpdated": "2026-09-01T00:00:00.000Z",
        "gitCommitSha": "deadbeef" * 5,
    }]}}
    (plugins_dir / "installed_plugins.json").write_text(json.dumps(registry, indent=2) + "\n")
    (home / ".claude").mkdir(exist_ok=True)
    (home / ".claude" / "settings.json").write_text(
        json.dumps({"enabledPlugins": {plugin_id: True}}, indent=2) + "\n")
    return home, cache_base


def _failing_git_dir(tmp_path):
    """A `git` on PATH that, for `archive` only, writes one real file into the pipeline
    (so `tar -x` extracts something into the staging dir) and then exits 1 — the
    "fails partway through" case: `_export_to`'s `git archive | tar -x` pipeline must
    still fail (via `pipefail`) and the staging dir must still be cleaned up even though
    it is not empty."""
    real_git = shutil.which("git")
    real_tar = shutil.which("tar")
    assert real_git and real_tar, "no git/tar on PATH to wrap"
    payload = tmp_path / "one-file-payload"
    payload.mkdir()
    (payload / "partial.txt").write_text("this much made it into the staging dir\n")
    d = tmp_path / "failgit"
    d.mkdir()
    wrapper = d / "git"
    wrapper.write_text(
        "#!/bin/sh\n"
        "for a in \"$@\"; do\n"
        "  if [ \"$a\" = archive ]; then\n"
        f"    \"{real_tar}\" -cf - -C \"{payload}\" .\n"
        "    exit 1\n"
        "  fi\n"
        "done\n"
        f'exec "{real_git}" "$@"\n'
    )
    wrapper.chmod(0o755)
    return d


def _slow_git_dir(tmp_path, seconds=2):
    """A `git` on PATH that sleeps for `archive` only. bash defers running a caught
    INT/TERM's trap until the current foreground step (this sleep, standing in for a real
    `git archive`) actually returns — real bash behavior, not a harness quirk — so a test
    that sends the signal must then wait past `seconds`, not assume instant cleanup."""
    real_git = shutil.which("git")
    assert real_git, "no git on PATH to wrap"
    d = tmp_path / "slowgit"
    d.mkdir()
    wrapper = d / "git"
    wrapper.write_text(
        "#!/bin/sh\n"
        f'for a in "$@"; do if [ "$a" = "archive" ]; then sleep {seconds}; break; fi; done\n'
        f'exec "{real_git}" "$@"\n'
    )
    wrapper.chmod(0o755)
    return d


def _fake_claude_dir(tmp_path):
    """`claude plugin update` always errors, so the installer takes the git-archive
    fallback through `_export_to` on every run."""
    d = tmp_path / "fakebin"
    d.mkdir(exist_ok=True)
    exe = d / "claude"
    exe.write_text("#!/bin/sh\necho simulated marketplace fetch error >&2\nexit 1\n")
    exe.chmod(0o755)
    docker = d / "docker"
    docker.write_text("#!/bin/sh\nexit 1\n")
    docker.chmod(0o755)
    return d


def test_an_export_that_fails_partway_leaves_no_staging_dir_behind(tmp_path):
    """git exits 1 after tar has already extracted one file into the staging dir — the
    trap must remove that non-empty staging dir on the way out, not just an empty one."""
    repo = _make_repo(tmp_path, "2.0.0")
    home, cache_base = _seed_claude_home(tmp_path, installed_version="1.9.0")
    env = installer_env(tmp_path, home, _failing_git_dir(tmp_path), _fake_claude_dir(tmp_path))

    r = subprocess.run(["bash", str(INSTALL_SH["claude-code"]), "--root", str(repo)],
                       env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode != 0, r.stdout + r.stderr
    assert not list(cache_base.glob(".staging.*")), \
        "a failed export must not leave its (even partially populated) staging dir behind"
    assert not (cache_base / "2.0.0").exists(), "a failed export must never land at the destination"


def test_a_stale_staging_dir_is_pruned_while_a_fresh_one_is_left_alone(tmp_path):
    """Only a staging dir older than 60 minutes is abandoned-run debris; anything newer
    could belong to a run genuinely still in flight and must not be touched."""
    import os
    repo = _make_repo(tmp_path, "2.0.0")
    home, cache_base = _seed_claude_home(tmp_path, installed_version="1.9.0")
    cache_base.mkdir(parents=True, exist_ok=True)
    stale = cache_base / ".staging.stale01"
    stale.mkdir()
    (stale / "leftover.txt").write_text("from a killed run")
    old_time = time.time() - 3700   # > 60 minutes old
    os.utime(stale, (old_time, old_time))
    fresh = cache_base / ".staging.fresh01"
    fresh.mkdir()
    (fresh / "still-going.txt").write_text("a run that could still be in flight")

    env = installer_env(tmp_path, home, _fake_claude_dir(tmp_path))
    r = subprocess.run(["bash", str(INSTALL_SH["claude-code"]), "--root", str(repo)],
                       env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert not stale.exists(), "a staging dir older than 60 minutes must be pruned"
    assert fresh.exists(), "a staging dir under 60 minutes old must be left alone"
    assert (cache_base / "2.0.0" / "bin" / "skill-search-mcp").exists()


def test_a_signal_killed_export_leaves_no_staging_dir_behind(tmp_path):
    """The genuine bug this fix closes: a run killed while `git archive`/`tar` is still
    writing into the staging dir — not one that has already reached a checked failure
    branch — used to leave that directory behind forever."""
    repo = _make_repo(tmp_path, "2.0.0")
    home, cache_base = _seed_claude_home(tmp_path, installed_version="1.9.0")
    env = installer_env(tmp_path, home, _slow_git_dir(tmp_path), _fake_claude_dir(tmp_path))

    proc = subprocess.Popen(["bash", str(INSTALL_SH["claude-code"]), "--root", str(repo)],
                            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        stage = None
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            hits = list(cache_base.glob(".staging.*"))
            if hits:
                stage = hits[0]
                break
            if proc.poll() is not None:
                break
            time.sleep(0.02)
        assert stage is not None and stage.is_dir(), "the export never reached the staging step"
        proc.send_signal(signal.SIGTERM)
        # bash defers the trap until the slow-git sleep above returns — wait comfortably
        # past that, never assume the signal is handled the instant it is sent.
        proc.wait(timeout=15)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=15)

    assert proc.returncode != 0
    assert not list(cache_base.glob(".staging.*")), "a killed export must not leave its staging dir behind"
    assert not (cache_base / "2.0.0").exists(), "an interrupted export must never land at the destination"


def test_a_successful_export_leaves_no_staging_dir_behind(tmp_path):
    repo = _make_repo(tmp_path, "2.0.0")
    home, cache_base = _seed_claude_home(tmp_path, installed_version="1.9.0")
    env = installer_env(tmp_path, home, _fake_claude_dir(tmp_path))

    r = subprocess.run(["bash", str(INSTALL_SH["claude-code"]), "--root", str(repo)],
                       env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    assert not list(cache_base.glob(".staging.*")), \
        "a successful export must swap its staging dir into place, not leave it behind"
    assert (cache_base / "2.0.0" / "bin" / "skill-search-mcp").exists()
