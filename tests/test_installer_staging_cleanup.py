"""adapters/{claude-code,codex,zcode}/install.sh share one `_export_to` helper (adapters/lib/sync.sh;
OMP keeps its own `_omp_export_to`, which skips the legacy-prefix prune) that
stages an export beside its destination (`mktemp -d "$parent/.skill-concierge-staging.XXXXXX"`) before
swapping it in. A run killed between the `mktemp` and the final `mv` used to leave that
staging dir behind forever — nothing removed it. `_export_to` must now remove its own
staging dir on a normal exit, on EXIT/INT/TERM, and prune any stale `.skill-concierge-staging.*` dir left
over from an earlier killed run before it stages a new one."""
import json
import os
import re
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest

import test_codex_installer as cx
import test_sibling_installers as sib
from installer_env import installer_env

ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = {
    "claude-code": ROOT / "adapters" / "claude-code" / "install.sh",
    "codex": ROOT / "adapters" / "codex" / "install.sh",
    "omp": ROOT / "adapters" / "omp" / "install.sh",
    "zcode": ROOT / "adapters" / "zcode" / "install.sh",
}
LIB = ROOT / "adapters" / "lib"
# Where each installer's export function lives: the shared lib, or OMP's own variant.
EXPORT_FN = {
    "claude-code": (LIB / "sync.sh", "_export_to"),
    "codex": (LIB / "sync.sh", "_export_to"),
    "omp": (INSTALL_SH["omp"], "_omp_export_to"),
    "zcode": (LIB / "sync.sh", "_export_to"),
}


def _func_body(text, name):
    """Extracts one bash function's full text verbatim, by brace depth — handles a body
    containing nested `{ … }` blocks (loops, conditionals), unlike a bare line-range slice."""
    lines = text.splitlines(keepends=True)
    start = next(i for i, l in enumerate(lines) if l.startswith(f"{name}() {{"))
    depth = 0
    end = start
    for i in range(start, len(lines)):
        depth += lines[i].count("{") - lines[i].count("}")
        if i > start and depth == 0:
            end = i
            break
    return "".join(lines[start:end + 1])


def _export_to_body(name):
    path, fn = EXPORT_FN[name]
    return _func_body(path.read_text(), fn)


# The staging-cleanup fix itself, not the whole function (the per-harness comments and OMP's
# legacy-prefix prune differ): every installer
# must prune a stale staging dir the same way and trap its own staging dir the same way.
_CLEANUP_LINES = (
    "-mmin +60",
    'trap \'[ -z "$stage" ] || rm -rf "$stage"; exit 1\' EXIT INT TERM',
    "trap - EXIT INT TERM",
    # The export pipelines run in a subshell: a TERM landing while the trapping shell forks a
    # two-process pipeline hangs it (measured: about 2 in 100 kills, bash 3.2 and 5.3). Source pin;
    # the kill tests above exercise it only statistically.
    'if ! ( git -C "$ROOT" archive HEAD | tar -x -C "$stage" ); then',
    '. | tar -xf - -C "$stage" ); then',
)


def test_export_to_cleanup_is_identical_across_the_four_installers():
    """Sibling parity: fixing the staging-dir cleanup in one installer without syncing the
    other three would leave three of them still leaking staging dirs."""
    bodies = {name: _export_to_body(name) for name in INSTALL_SH}
    for name, body in bodies.items():
        for line in _CLEANUP_LINES:
            assert line in body, f"the export function adapters/{name}/install.sh uses is missing: {line!r}"


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
    assert not list(cache_base.glob(".skill-concierge-staging.*")), \
        "a failed export must not leave its (even partially populated) staging dir behind"
    assert not (cache_base / "2.0.0").exists(), "a failed export must never land at the destination"


def test_a_stale_staging_dir_is_pruned_while_a_fresh_one_is_left_alone(tmp_path):
    """Only a staging dir older than 60 minutes is abandoned-run debris; anything newer
    could belong to a run genuinely still in flight and must not be touched."""
    repo = _make_repo(tmp_path, "2.0.0")
    home, cache_base = _seed_claude_home(tmp_path, installed_version="1.9.0")
    cache_base.mkdir(parents=True, exist_ok=True)
    stale = cache_base / ".skill-concierge-staging.stale01"
    stale.mkdir()
    (stale / "leftover.txt").write_text("from a killed run")
    old_time = time.time() - 3700   # > 60 minutes old
    os.utime(stale, (old_time, old_time))
    fresh = cache_base / ".skill-concierge-staging.fresh01"
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
            hits = list(cache_base.glob(".skill-concierge-staging.*"))
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
    assert not list(cache_base.glob(".skill-concierge-staging.*")), "a killed export must not leave its staging dir behind"
    assert not (cache_base / "2.0.0").exists(), "an interrupted export must never land at the destination"


def test_a_successful_export_leaves_no_staging_dir_behind(tmp_path):
    repo = _make_repo(tmp_path, "2.0.0")
    home, cache_base = _seed_claude_home(tmp_path, installed_version="1.9.0")
    env = installer_env(tmp_path, home, _fake_claude_dir(tmp_path))

    r = subprocess.run(["bash", str(INSTALL_SH["claude-code"]), "--root", str(repo)],
                       env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    assert not list(cache_base.glob(".skill-concierge-staging.*")), \
        "a successful export must swap its staging dir into place, not leave it behind"
    assert (cache_base / "2.0.0" / "bin" / "skill-search-mcp").exists()


def test_omp_stale_prune_only_touches_our_own_prefix_not_a_foreign_tool(tmp_path):
    """The OMP cache parent (~/.omp/plugins/cache/plugins) is shared by every OMP
    plugin, not just this one — a bare `.staging.*` prune glob there could delete
    another tool's own staging dir. The prefix is skill-concierge-specific so the
    prune can never match anything else, while our own stale dir is still pruned."""
    repo = sib._make_repo(tmp_path, "repo", "2.0.0")
    home, cache_dir = sib._seed_omp_home_with_cache(tmp_path, version="1.9.0")
    cache_base = cache_dir.parent   # shared by every OMP plugin's own cache dir

    foreign = cache_base / ".staging.some-other-omp-plugin"
    foreign.mkdir()
    (foreign / "not-ours.txt").write_text("belongs to a different OMP plugin's own staging dir")
    old_time = time.time() - 3700   # > 60 minutes old
    os.utime(foreign, (old_time, old_time))

    ours_stale = cache_base / ".skill-concierge-staging.stale01"
    ours_stale.mkdir()
    os.utime(ours_stale, (old_time, old_time))

    r = sib._run_omp(tmp_path, repo, home)
    assert r.returncode == 0, r.stdout + r.stderr
    assert foreign.exists(), "a foreign tool's own staging dir must never be pruned"
    assert not ours_stale.exists(), "our own stale staging dir must still be pruned"


# ── Sibling kill tests: the same signal-kill proof as claude-code (above), for the
# three installers the rest of the suite only string-checks. Each kill reproduction
# fails on the pre-fix installers and passes on the fixed ones. ──────────

def _kill_during_export(argv, env, cache_base, timeout=30):
    proc = subprocess.Popen(argv, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        stage = None
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            hits = list(cache_base.glob(".skill-concierge-staging.*")) if cache_base.exists() else []
            if hits:
                stage = hits[0]
                break
            if proc.poll() is not None:
                break
            time.sleep(0.02)
        assert stage is not None and stage.is_dir(), "the export never reached the staging step"
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=timeout)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=timeout)
    return proc.returncode


def test_a_signal_killed_zcode_export_leaves_no_staging_dir_behind(tmp_path):
    repo = sib._make_repo(tmp_path, "repo", "2.0.0")
    home = sib._seed_zcode_home(tmp_path, installed_version="1.9.0", install_path=tmp_path / "irrelevant")
    dest_dir = repo / "adapters" / "zcode"
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(INSTALL_SH["zcode"], dest_dir / "install.sh")
    shutil.copytree(LIB, repo / "adapters" / "lib")
    env = installer_env(tmp_path, home, _slow_git_dir(tmp_path))
    cache = home / ".zcode" / "cli" / "plugins" / "cache" / "skill-concierge" / "skill-concierge"

    rc = _kill_during_export(["bash", str(dest_dir / "install.sh")], env, cache)
    assert rc != 0
    assert not list(cache.glob(".skill-concierge-staging.*"))
    assert not (cache / "2.0.0").exists()


def test_a_signal_killed_omp_export_leaves_no_staging_dir_behind(tmp_path):
    repo = sib._make_repo(tmp_path, "repo", "2.0.0")
    home, _ = sib._seed_omp_home_with_cache(tmp_path, version="1.9.0")
    env = installer_env(tmp_path, home, _slow_git_dir(tmp_path))
    cache = home / ".omp" / "plugins" / "cache" / "plugins"

    rc = _kill_during_export(["bash", str(INSTALL_SH["omp"]), "--root", str(repo)], env, cache)
    assert rc != 0
    assert not list(cache.glob(".skill-concierge-staging.*"))
    reg = json.loads((home / ".omp" / "plugins" / "installed_plugins.json").read_text())
    assert reg["plugins"]["skill-concierge@skill-concierge"][0]["version"] == "1.9.0", \
        "a killed export must never repoint the registry"


def test_a_signal_killed_codex_export_leaves_no_staging_dir_behind(tmp_path):
    # A marketplace remote below SSOT forces the git-archive fallback (the export this
    # test kills); the fake `codex add` still runs first and needs a real enforcer.py.
    home, fakebin = cx._make_home(tmp_path, {"marketplace_registered": True, "plugin_installed": False,
                                             "remote_version": "0.45.0"})
    env = installer_env(tmp_path, home, _slow_git_dir(tmp_path), fakebin,
                        FAKE_CODEX_ENFORCER_SRC=str(cx.ENFORCER_SRC))
    cache = cx._cache_root(home)

    rc = _kill_during_export(["bash", str(cx.INSTALLER)], env, cache)
    assert rc != 0
    assert not list(cache.glob(".skill-concierge-staging.*"))
    assert not (cache / cx.SSOT_VERSION).exists()


# ── The kill that lands between `mktemp` and the trap install ────────────────────────────────
# The tests above kill the installer once the staging dir shows up on disk, which is the instant
# `mktemp` returns. If the installer had not yet registered its trap at that instant, a SIGTERM
# in that gap would hit bash's default action and leave the dir behind (a flake of about 1 in 25
# runs). This pins the gap shut deterministically: a `mktemp` shim that creates the dir and then
# holds the command substitution open, so the signal always arrives "just after mktemp".

def _slow_mktemp_dir(tmp_path, seconds=2):
    real_mktemp = shutil.which("mktemp")
    assert real_mktemp, "no mktemp on PATH to wrap"
    d = tmp_path / "slowmktemp"
    d.mkdir()
    shim = d / "mktemp"
    shim.write_text(
        "#!/bin/sh\n"
        f'"{real_mktemp}" "$@" || exit $?\n'
        f"sleep {seconds}\n"
    )
    shim.chmod(0o755)
    return d


def test_a_kill_right_after_mktemp_in_the_shared_export_leaves_no_staging_dir_behind(tmp_path):
    repo = sib._make_repo(tmp_path, "repo", "2.0.0")
    home = sib._seed_zcode_home(tmp_path, installed_version="1.9.0", install_path=tmp_path / "irrelevant")
    dest_dir = repo / "adapters" / "zcode"
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(INSTALL_SH["zcode"], dest_dir / "install.sh")
    shutil.copytree(LIB, repo / "adapters" / "lib")
    env = installer_env(tmp_path, home, _slow_mktemp_dir(tmp_path))
    cache = home / ".zcode" / "cli" / "plugins" / "cache" / "skill-concierge" / "skill-concierge"

    rc = _kill_during_export(["bash", str(dest_dir / "install.sh")], env, cache)
    assert rc != 0
    assert not list(cache.glob(".skill-concierge-staging.*"))
    assert not (cache / "2.0.0").exists()


def test_a_kill_right_after_mktemp_in_the_omp_export_leaves_no_staging_dir_behind(tmp_path):
    repo = sib._make_repo(tmp_path, "repo", "2.0.0")
    home, _ = sib._seed_omp_home_with_cache(tmp_path, version="1.9.0")
    env = installer_env(tmp_path, home, _slow_mktemp_dir(tmp_path))
    cache = home / ".omp" / "plugins" / "cache" / "plugins"

    rc = _kill_during_export(["bash", str(INSTALL_SH["omp"]), "--root", str(repo)], env, cache)
    assert rc != 0
    assert not list(cache.glob(".skill-concierge-staging.*"))


# ── Legacy `.staging.*` prefix (pre-rename runs) ─────────────────────────────────────────────
# The prefix used to be a bare `.staging.*` before it was renamed to the skill-concierge-
# specific `.skill-concierge-staging.*` above. A run killed under an OLDER version, before
# that rename shipped, can still have left a bare `.staging.*` dir behind — and the renamed
# prune glob no longer matches it. claude-code, codex, and zcode each own their own cache
# parent outright (`.../skill-concierge/skill-concierge`), so a bare `.staging.*` found there
# is provably ours too and gets pruned the same way (>60 minutes old only). OMP's cache
# parent is shared by every OMP plugin, so a bare `.staging.*` there is left untouched —
# already proven by test_omp_stale_prune_only_touches_our_own_prefix_not_a_foreign_tool above.

def test_legacy_bare_staging_prefix_is_pruned_in_claude_code(tmp_path):
    repo = _make_repo(tmp_path, "2.0.0")
    home, cache_base = _seed_claude_home(tmp_path, installed_version="1.9.0")
    cache_base.mkdir(parents=True, exist_ok=True)
    legacy = cache_base / ".staging.legacy01"
    legacy.mkdir()
    (legacy / "leftover.txt").write_text("from a run killed before the prefix rename")
    old_time = time.time() - 3700   # > 60 minutes old
    os.utime(legacy, (old_time, old_time))

    env = installer_env(tmp_path, home, _fake_claude_dir(tmp_path))
    r = subprocess.run(["bash", str(INSTALL_SH["claude-code"]), "--root", str(repo)],
                       env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert not legacy.exists(), "a legacy bare .staging.* dir older than 60 minutes must be pruned too"
    assert (cache_base / "2.0.0" / "bin" / "skill-search-mcp").exists()


def _run_export_to_direct(name, dest):
    """Runs ONLY the export function installer `name` uses (plus the `_is_own_checkout` it
    calls), extracted verbatim from where it is defined, against a throwaway non-git $ROOT —
    never the full installer.
    Codex's `_export_to` is only reached AFTER a successful `codex plugin add`, and this
    repo's own fake `codex` CLI test double faithfully wipes the ENTIRE cache dir on a
    successful `add` (matching real Codex's observed behavior) — so a full end-to-end run
    would remove a pre-seeded legacy dir via THAT wipe regardless of whether `_export_to`'s
    own prune line exists, and could never tell the two apart. Isolating `_export_to` itself
    is the only way to prove this specific fix, not an unrelated side effect upstream of it."""
    export_body = _export_to_body(name)
    is_own_checkout_body = _func_body((LIB / "sync.sh").read_text(), "_is_own_checkout")
    fake_root = dest.parent.parent / "fake-root"
    fake_root.mkdir(parents=True, exist_ok=True)
    (fake_root / "marker.txt").write_text("throwaway non-git root for a direct _export_to call\n")
    script = (f'set -euo pipefail\nROOT="{fake_root}"\n{is_own_checkout_body}\n{export_body}\n'
              f'{EXPORT_FN[name][1]} "$1"\n')
    return subprocess.run(["bash", "-c", script, "_", str(dest)],
                          capture_output=True, text=True, timeout=30)


def test_legacy_bare_staging_prefix_is_pruned_in_codex(tmp_path):
    cache = tmp_path / "cache" / "skill-concierge" / "skill-concierge"
    cache.mkdir(parents=True, exist_ok=True)
    legacy = cache / ".staging.legacy01"
    legacy.mkdir()
    old_time = time.time() - 3700
    os.utime(legacy, (old_time, old_time))

    r = _run_export_to_direct("codex", cache / "2.0.0")
    assert r.returncode == 0, r.stdout + r.stderr
    assert not legacy.exists(), "a legacy bare .staging.* dir older than 60 minutes must be pruned too"
    assert (cache / "2.0.0").exists()


def test_legacy_bare_staging_prefix_is_pruned_in_zcode(tmp_path):
    repo = sib._make_repo(tmp_path, "repo", "2.0.0")
    home = sib._seed_zcode_home(tmp_path, installed_version="1.9.0", install_path=tmp_path / "irrelevant")
    cache = home / ".zcode" / "cli" / "plugins" / "cache" / "skill-concierge" / "skill-concierge"
    cache.mkdir(parents=True, exist_ok=True)
    legacy = cache / ".staging.legacy01"
    legacy.mkdir()
    old_time = time.time() - 3700
    os.utime(legacy, (old_time, old_time))

    r = sib._run_zcode(tmp_path, repo, home)
    assert r.returncode == 0, r.stdout + r.stderr
    assert not legacy.exists(), "a legacy bare .staging.* dir older than 60 minutes must be pruned too"
    assert (cache / "2.0.0").exists()


# ── Non-git export: one exclude list for all four installers ─────────────────────────────────
# ZCode's copy of `_export_to` once lacked `--exclude='.zcode' --exclude='.unlazy'`, so a
# non-git ZCode export shipped those per-machine scratch dirs into its plugin cache.

_SCRATCH_DIRS = (".ijfw", "ijfw", ".handoff", "logs", "graphify-out", ".claude", ".zcode",
                 ".unlazy", "node_modules", "__pycache__", ".venv", ".pytest_cache",
                 ".mypy_cache", ".ruff_cache")


def test_non_git_exclude_list_is_identical_across_the_four_installers():
    lists = {name: re.findall(r"--exclude='([^']+)'", _export_to_body(name)) for name in INSTALL_SH}
    assert len({tuple(v) for v in lists.values()}) == 1, lists


@pytest.mark.parametrize("name", sorted(INSTALL_SH))
def test_non_git_export_ships_no_scratch_dir(tmp_path, name):
    cache = tmp_path / "cache" / "skill-concierge" / "skill-concierge"
    cache.mkdir(parents=True)
    for d in _SCRATCH_DIRS:   # cache.parent/fake-root is the $ROOT _run_export_to_direct exports
        (cache.parent / "fake-root" / d).mkdir(parents=True)
        (cache.parent / "fake-root" / d / "f.txt").write_text("scratch\n")

    r = _run_export_to_direct(name, cache / "2.0.0")
    assert r.returncode == 0, r.stdout + r.stderr
    shipped = {p.name for p in (cache / "2.0.0").iterdir()}
    assert "marker.txt" in shipped
    assert not shipped & set(_SCRATCH_DIRS), sorted(shipped & set(_SCRATCH_DIRS))
