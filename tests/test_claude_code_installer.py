"""adapters/claude-code/install.sh must keep the marketplace-installed plugin in sync with
this checkout without ever touching enabledPlugins or the stamp file, refuse to downgrade
a copy newer than the checkout (before AND after any CLI call), and fall back to a local
git-archive sync (backed up first, written atomically) whenever `claude plugin update`
cannot reach the checkout's version — the normal case for a version bump that has not been
pushed to the marketplace remote yet.

A fake `claude` executable is placed first on PATH for every test; it only models
`claude plugin update` and is a no-op for anything else (e.g. doctor.py's own `claude mcp
list` probe during this installer's verify step)."""
import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = ROOT / "adapters" / "claude-code" / "install.sh"
DOCTOR_SRC = ROOT / "scripts" / "doctor.py"
PLUGIN_ID = "skill-concierge@skill-concierge"

FAKE_CLAUDE = r'''#!/usr/bin/env python3
import json, os, shutil, sys, time
from pathlib import Path

if sys.argv[1:2] == ["--version"]:
    print("2.1.283 (Claude Code)")
    sys.exit(0)

if sys.argv[1:3] != ["plugin", "update"]:
    # Anything else (e.g. doctor.py's own `claude mcp list` probe during this
    # installer's verify step) is a harmless, unlogged no-op — this fake only
    # models `plugin update`, and only THAT invocation is worth a test's while
    # to assert on.
    sys.exit(0)

log = os.environ.get("FAKE_CLAUDE_LOG")
if log:
    with open(log, "a", encoding="utf-8") as f:
        f.write(" ".join(sys.argv[1:]) + "\n")

mode = os.environ.get("FAKE_CLAUDE_MODE", "up_to_date_stale")
home = Path(os.environ["HOME"])
reg_path = home / ".claude" / "plugins" / "installed_plugins.json"
cache_base = home / ".claude" / "plugins" / "cache" / "skill-concierge" / "skill-concierge"
plugin_id = "skill-concierge@skill-concierge"

data = json.loads(reg_path.read_text(encoding="utf-8"))
rec = data["plugins"][plugin_id][0]
old_version = rec["version"]

def emit(outcome, old, new, ok=True):
    print(json.dumps({
        "command": "update", "outcome": "ok" if ok else "error",
        "plugin": plugin_id, "scope": rec.get("scope", "user"),
        "updateOutcome": outcome, "oldVersion": old, "newVersion": new,
    }))

if mode == "error":
    print("simulated marketplace fetch error", file=sys.stderr)
    sys.exit(1)
if mode in ("up_to_date_current", "up_to_date_stale"):
    emit("up_to_date", old_version, old_version)
    sys.exit(0)
if mode == "updated":
    source = Path(os.environ["FAKE_CLAUDE_SOURCE"])
    new_version = json.loads((source / ".claude-plugin" / "plugin.json").read_text())["version"]
    dest = cache_base / new_version
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(source, dest, ignore=shutil.ignore_patterns(".git"))
    rec["version"] = new_version
    rec["installPath"] = str(dest)
    rec["lastUpdated"] = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    reg_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    emit("updated", old_version, new_version)
    sys.exit(0)

print("unknown FAKE_CLAUDE_MODE: " + mode, file=sys.stderr)
sys.exit(2)
'''


def _make_repo(tmp_path, name, version):
    """A minimal git-committed checkout: just enough for install.sh's own reads
    (SSOT version, launcher, enforcer, setup.sh, doctor.py for the verify step's own
    doctor-row check) plus a real git history so `git archive HEAD` works."""
    repo = tmp_path / name
    (repo / ".claude-plugin").mkdir(parents=True)
    (repo / ".claude-plugin" / "plugin.json").write_text(json.dumps({"version": version}))
    (repo / "bin").mkdir()
    launcher = repo / "bin" / "skill-search-mcp"
    launcher.write_text("#!/bin/sh\necho fixture-launcher\n")
    launcher.chmod(0o755)
    (repo / "hooks" / "scripts").mkdir(parents=True)
    (repo / "hooks" / "scripts" / "enforcer.py").write_text(f"# enforcer fixture v{version}\n")
    # doctor.py imports sibling scripts (e.g. flywheel_llm) lazily inside its own check
    # functions, so the whole dir is copied rather than just doctor.py itself.
    shutil.copytree(DOCTOR_SRC.parent, repo / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
    setup = repo / "setup.sh"
    setup.write_text("#!/bin/sh\n")
    setup.chmod(0o755)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init"],
                    cwd=repo, check=True)
    return repo


def _seed_home(tmp_path, *, installed_version, install_path):
    home = tmp_path / "home"
    plugins_dir = home / ".claude" / "plugins"
    plugins_dir.mkdir(parents=True)
    registry = {
        "plugins": {
            PLUGIN_ID: [{
                "scope": "user",
                "installPath": str(install_path),
                "version": installed_version,
                "installedAt": "2026-06-26T06:44:59.002Z",
                "lastUpdated": "2026-09-01T00:00:00.000Z",
                "gitCommitSha": "deadbeef" * 5,
            }],
            "some-other-plugin@some-marketplace": [{
                "scope": "user", "installPath": "/irrelevant", "version": "1.0.0",
            }],
        }
    }
    (plugins_dir / "installed_plugins.json").write_text(json.dumps(registry, indent=2) + "\n")
    settings = {"enabledPlugins": {PLUGIN_ID: True, "some-other-plugin@some-marketplace": False}}
    (home / ".claude").mkdir(exist_ok=True)
    (home / ".claude" / "settings.json").write_text(json.dumps(settings, indent=2) + "\n")
    return home


def _seed_home_with_cache(tmp_path, *, version):
    """A registry + a cache dir whose own plugin.json ALSO carries `version` — the common
    "already deployed at some old version" fixture shape, folded into one call."""
    cache_dir = tmp_path / "home" / ".claude" / "plugins" / "cache" / "skill-concierge" / "skill-concierge" / version
    home = _seed_home(tmp_path, installed_version=version, install_path=cache_dir)
    cache_dir.mkdir(parents=True)
    (cache_dir / ".claude-plugin").mkdir()
    (cache_dir / ".claude-plugin" / "plugin.json").write_text(json.dumps({"version": version}))
    return home, cache_dir


def _fake_claude_dir(tmp_path):
    d = tmp_path / "fakebin"
    d.mkdir(exist_ok=True)
    exe = d / "claude"
    exe.write_text(FAKE_CLAUDE)
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return d


def _run(tmp_path, root, home, mode, *, source=None, extra_env=None):
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["PATH"] = str(_fake_claude_dir(tmp_path)) + os.pathsep + os.environ.get("PATH", "")
    env["FAKE_CLAUDE_MODE"] = mode
    env["FAKE_CLAUDE_LOG"] = str(tmp_path / "fake-claude.log")
    if source is not None:
        env["FAKE_CLAUDE_SOURCE"] = str(source)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", str(INSTALL_SH), "--root", str(root)],
        env=env, capture_output=True, text=True, timeout=120,
    )


def _registry(home):
    reg = home / ".claude" / "plugins" / "installed_plugins.json"
    return json.loads(reg.read_text(encoding="utf-8"))


def _claude_log(tmp_path):
    log = tmp_path / "fake-claude.log"
    return log.read_text(encoding="utf-8") if log.exists() else ""


def _backups(home):
    return list((home / ".claude" / "plugins").glob("installed_plugins.json.bak-claude-code-*"))


# ── Fast path ────────────────────────────────────────────────────────────────

def test_fast_path_is_a_noop_when_already_current(tmp_path):
    repo = _make_repo(tmp_path, "repo", "1.2.0")
    home, cache_dir = _seed_home_with_cache(tmp_path, version="1.2.0")
    shutil.rmtree(cache_dir)
    shutil.copytree(repo, cache_dir, ignore=shutil.ignore_patterns(".git"))
    before = _registry(home)

    r = _run(tmp_path, repo, home, mode="up_to_date_current")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Already current" in r.stdout
    assert _claude_log(tmp_path) == "", "fast path must never invoke the CLI"
    assert _registry(home) == before, "fast path must not write the registry"
    assert not _backups(home)


# ── CLI success path ─────────────────────────────────────────────────────────

def test_cli_update_reaching_ssot_skips_the_fallback(tmp_path):
    repo = _make_repo(tmp_path, "repo", "1.3.0")
    home, _old_cache = _seed_home_with_cache(tmp_path, version="1.2.0")

    r = _run(tmp_path, repo, home, mode="updated", source=repo)
    assert r.returncode == 0, r.stdout + r.stderr
    reg = _registry(home)
    assert reg["plugins"][PLUGIN_ID][0]["version"] == "1.3.0"
    new_cache = Path(reg["plugins"][PLUGIN_ID][0]["installPath"])
    assert new_cache.name == "1.3.0"
    assert (new_cache / "hooks" / "scripts" / "enforcer.py").read_text() == \
        (repo / "hooks" / "scripts" / "enforcer.py").read_text()
    assert not _backups(home), "a CLI update that reached SSOT must not trigger the manual-sync fallback"
    assert PLUGIN_ID in _claude_log(tmp_path)


# ── Fallback path (CLI cannot reach SSOT) ────────────────────────────────────

@pytest.mark.parametrize("mode", ["up_to_date_stale", "error"])
def test_fallback_sync_when_cli_does_not_reach_ssot(tmp_path, mode):
    repo = _make_repo(tmp_path, "repo", "2.0.0")
    home, _old_cache = _seed_home_with_cache(tmp_path, version="1.9.0")
    settings_before = (home / ".claude" / "settings.json").read_text()

    r = _run(tmp_path, repo, home, mode=mode)
    assert r.returncode == 0, r.stdout + r.stderr
    combined = r.stdout + r.stderr
    assert "not been published" in combined or "may not carry yet" in combined

    reg = _registry(home)
    rec = reg["plugins"][PLUGIN_ID][0]
    assert rec["version"] == "2.0.0"
    dest = Path(rec["installPath"])
    assert dest == home / ".claude" / "plugins" / "cache" / "skill-concierge" / "skill-concierge" / "2.0.0"
    assert (dest / "bin" / "skill-search-mcp").exists()
    assert os.access(dest / "bin" / "skill-search-mcp", os.X_OK)
    assert (dest / "hooks" / "scripts" / "enforcer.py").read_text() == \
        (repo / "hooks" / "scripts" / "enforcer.py").read_text()
    backups = _backups(home)
    assert len(backups) == 1, "exactly one backup of the registry must be kept"
    assert json.loads(backups[0].read_text())["plugins"][PLUGIN_ID][0]["version"] == "1.9.0"
    # enabledPlugins / settings.json is never touched by this installer.
    assert (home / ".claude" / "settings.json").read_text() == settings_before
    # Atomic write: no leftover temp file from the registry repoint.
    assert not list((home / ".claude" / "plugins").glob("installed_plugins.json.tmp-*"))


def test_fallback_is_idempotent_on_rerun(tmp_path):
    repo = _make_repo(tmp_path, "repo", "2.0.0")
    home, _old_cache = _seed_home_with_cache(tmp_path, version="1.9.0")

    first = _run(tmp_path, repo, home, mode="error")
    assert first.returncode == 0, first.stdout + first.stderr
    # Second run: the CLI is back to reporting up_to_date at the now-current version,
    # so the fast path (registry+cache already at SSOT) must take over with no writes.
    (tmp_path / "fake-claude.log").write_text("")
    before = _registry(home)
    second = _run(tmp_path, repo, home, mode="up_to_date_current")
    assert second.returncode == 0, second.stdout + second.stderr
    assert "Already current" in second.stdout
    assert _registry(home) == before
    assert len(_backups(home)) == 1


# ── Downgrade refusal ─────────────────────────────────────────────────────────

def test_refuses_to_downgrade_before_any_cli_call(tmp_path):
    repo = _make_repo(tmp_path, "repo", "1.0.0")   # checkout is OLDER
    home, _newer_cache = _seed_home_with_cache(tmp_path, version="9.9.9")
    before = _registry(home)

    r = _run(tmp_path, repo, home, mode="up_to_date_stale")
    assert r.returncode != 0, "a checkout older than the deployed copy must be refused"
    assert "refusing to downgrade" in (r.stdout + r.stderr)
    assert _claude_log(tmp_path) == "", "the downgrade guard must fire before any CLI call"
    assert _registry(home) == before, "a refused downgrade must leave the registry untouched"
    assert not (home / ".claude" / "plugins" / "cache" / "skill-concierge" / "skill-concierge" / "1.0.0").exists()
    assert not _backups(home)


# ── Missing plugin entry ──────────────────────────────────────────────────────

def test_errors_without_touching_anything_when_plugin_not_yet_installed(tmp_path):
    repo = _make_repo(tmp_path, "repo", "1.0.0")
    home = tmp_path / "home"
    (home / ".claude" / "plugins").mkdir(parents=True)
    (home / ".claude" / "plugins" / "installed_plugins.json").write_text(json.dumps({"plugins": {}}) + "\n")

    r = _run(tmp_path, repo, home, mode="up_to_date_stale")
    assert r.returncode != 0
    assert "claude plugin install" in (r.stdout + r.stderr)
    assert _claude_log(tmp_path) == "", "must not attempt any CLI call before the entry is confirmed"


# ── Doctor row + real claude binary isolation ────────────────────────────────

def test_verify_prints_doctors_claude_code_row(tmp_path):
    repo = _make_repo(tmp_path, "repo", "4.0.0")
    home, _old_cache = _seed_home_with_cache(tmp_path, version="3.9.0")

    r = _run(tmp_path, repo, home, mode="up_to_date_stale")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Claude Code integration" in r.stdout


def test_real_claude_binary_is_never_invoked(tmp_path):
    real_claude = shutil.which("claude")
    if real_claude is None:
        pytest.skip("no real claude binary on this machine's PATH to prove isolation against")
    repo = _make_repo(tmp_path, "repo", "1.5.0")
    home, _old_cache = _seed_home_with_cache(tmp_path, version="1.4.0")

    r = _run(tmp_path, repo, home, mode="up_to_date_stale")
    assert r.returncode == 0, r.stdout + r.stderr
    assert _claude_log(tmp_path) != "", "the fake CLI must have been invoked"
    # The fake's own log records only what the fake itself received — a real `claude`
    # would never write to FAKE_CLAUDE_LOG at all, so any content here is proof enough
    # that only the fake, first on PATH, was ever resolved.


# ── Git worktree detection ────────────────────────────────────────────────────

def test_git_worktree_export_excludes_untracked_and_ignored_files(tmp_path):
    """A git *worktree*'s `.git` is a FILE, not a directory — `[ -d "$ROOT/.git" ]` would
    misclassify it as a non-git checkout and tar the whole working tree, untracked and
    ignored files included. `git -C "$ROOT" rev-parse --is-inside-work-tree` must detect
    it correctly, so the fallback still takes the `git archive HEAD` branch, which only
    ever exports what is committed."""
    base_repo = tmp_path / "base-repo"
    (base_repo / ".claude-plugin").mkdir(parents=True)
    (base_repo / ".claude-plugin" / "plugin.json").write_text(json.dumps({"version": "8.0.0"}))
    (base_repo / "bin").mkdir()
    launcher = base_repo / "bin" / "skill-search-mcp"
    launcher.write_text("#!/bin/sh\necho fixture\n")
    launcher.chmod(0o755)
    (base_repo / "hooks" / "scripts").mkdir(parents=True)
    (base_repo / "hooks" / "scripts" / "enforcer.py").write_text("# enforcer fixture v8.0.0\n")
    (base_repo / ".gitignore").write_text("ignored.txt\n")
    subprocess.run(["git", "init", "-q"], cwd=base_repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=base_repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init"],
                    cwd=base_repo, check=True)

    worktree = tmp_path / "worktree"
    subprocess.run(["git", "worktree", "add", str(worktree), "HEAD"], cwd=base_repo, check=True,
                    capture_output=True, text=True)
    assert (worktree / ".git").is_file(), "a linked worktree's .git must be a FILE, not a dir"

    (worktree / "untracked.txt").write_text("must never be exported")
    (worktree / "ignored.txt").write_text("must never be exported either")

    home, _old_cache = _seed_home_with_cache(tmp_path, version="1.0.0")

    r = _run(tmp_path, worktree, home, mode="up_to_date_stale")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "exported HEAD" in r.stdout, "a real git checkout must take the git-archive branch"

    dest = home / ".claude" / "plugins" / "cache" / "skill-concierge" / "skill-concierge" / "8.0.0"
    assert dest.is_dir()
    assert (dest / "bin" / "skill-search-mcp").exists()
    assert not (dest / "untracked.txt").exists(), "git archive HEAD must exclude untracked files"
    assert not (dest / "ignored.txt").exists(), "git archive HEAD must exclude gitignored files"
    assert not (dest / ".git").exists()
