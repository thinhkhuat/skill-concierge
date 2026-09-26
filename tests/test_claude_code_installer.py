"""adapters/claude-code/install.sh must keep the marketplace-installed plugin in sync with
this checkout without ever touching enabledPlugins or the stamp file, refuse to downgrade
a copy newer than the checkout, and fall back to a local git-archive sync (backed up first)
whenever `claude plugin update` cannot reach the checkout's version — the normal case for
a version bump that has not been pushed to the marketplace remote yet.

A fake `claude` executable is placed first on PATH for every test; the real binary's own
directory is stripped out of PATH so it structurally cannot be invoked."""
import json
import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = ROOT / "adapters" / "claude-code" / "install.sh"
PLUGIN_ID = "skill-concierge@skill-concierge"

FAKE_CLAUDE = r'''#!/usr/bin/env python3
import json, os, shutil, sys, time
from pathlib import Path

log = os.environ.get("FAKE_CLAUDE_LOG")
if log:
    with open(log, "a", encoding="utf-8") as f:
        f.write(" ".join(sys.argv[1:]) + "\n")

if sys.argv[1:2] == ["--version"]:
    print("2.1.283 (Claude Code)")
    sys.exit(0)

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
    (SSOT version, launcher, enforcer, setup.sh) plus a real git history so
    `git archive HEAD` works."""
    repo = tmp_path / name
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


def _seed_home(tmp_path, *, installed_version, install_path, scope="user"):
    home = tmp_path / "home"
    plugins_dir = home / ".claude" / "plugins"
    plugins_dir.mkdir(parents=True)
    registry = {
        "plugins": {
            PLUGIN_ID: [{
                "scope": scope,
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
    (plugins_dir / "known_marketplaces.json").write_text(json.dumps({
        "skill-concierge": {
            "source": {"source": "git", "url": "https://github.com/thinhkhuat/skill-concierge.git"},
            "installLocation": str(home / ".claude" / "plugins" / "marketplaces" / "skill-concierge"),
            "lastUpdated": "2026-09-01T00:00:00.000Z", "autoUpdate": True,
        }
    }, indent=2) + "\n")
    settings = {"enabledPlugins": {PLUGIN_ID: True, "some-other-plugin@some-marketplace": False}}
    (home / ".claude").mkdir(exist_ok=True)
    (home / ".claude" / "settings.json").write_text(json.dumps(settings, indent=2) + "\n")
    return home


def _fake_claude_dir(tmp_path):
    d = tmp_path / "fakebin"
    d.mkdir(exist_ok=True)
    exe = d / "claude"
    exe.write_text(FAKE_CLAUDE)
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return d


def _sandboxed_path(extra_first_dir):
    """The inherited PATH with the real `claude` binary's directory removed, and
    `extra_first_dir` (holding the fake `claude`) prepended — so the real binary
    is not merely shadowed, it is structurally unreachable on this PATH."""
    real_claude = shutil.which("claude")
    real_claude_dir = str(Path(real_claude).parent) if real_claude else None
    dirs = [d for d in os.environ.get("PATH", "").split(os.pathsep) if d and d != real_claude_dir]
    return os.pathsep.join([str(extra_first_dir)] + dirs)


def _run(tmp_path, root, home, mode, *, source=None, extra_env=None):
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["PATH"] = _sandboxed_path(_fake_claude_dir(tmp_path))
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


# ── Fast path ────────────────────────────────────────────────────────────────

def test_fast_path_is_a_noop_when_already_current(tmp_path):
    repo = _make_repo(tmp_path, "repo", "1.2.0")
    cache_dir = tmp_path / "home" / ".claude" / "plugins" / "cache" / "skill-concierge" / "skill-concierge" / "1.2.0"
    home = _seed_home(tmp_path, installed_version="1.2.0", install_path=cache_dir)
    shutil.copytree(repo, cache_dir, ignore=shutil.ignore_patterns(".git"))
    before = _registry(home)

    r = _run(tmp_path, repo, home, mode="up_to_date_current")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Already current" in r.stdout
    assert _claude_log(tmp_path) == "", "fast path must never invoke the CLI"
    assert _registry(home) == before, "fast path must not write the registry"
    assert not list((home / ".claude" / "plugins").glob("installed_plugins.json.bak-claude-code-*"))


# ── CLI success path ─────────────────────────────────────────────────────────

def test_cli_update_reaching_ssot_skips_the_fallback(tmp_path):
    repo = _make_repo(tmp_path, "repo", "1.3.0")
    old_cache = tmp_path / "home" / ".claude" / "plugins" / "cache" / "skill-concierge" / "skill-concierge" / "1.2.0"
    home = _seed_home(tmp_path, installed_version="1.2.0", install_path=old_cache)
    old_cache.mkdir(parents=True)
    (old_cache / ".claude-plugin").mkdir()
    (old_cache / ".claude-plugin" / "plugin.json").write_text(json.dumps({"version": "1.2.0"}))

    r = _run(tmp_path, repo, home, mode="updated", source=repo)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "claude plugin update" not in r.stdout  # sanity: no literal echo of the command
    assert "CLI outcome: updated" in r.stdout
    reg = _registry(home)
    assert reg["plugins"][PLUGIN_ID][0]["version"] == "1.3.0"
    new_cache = Path(reg["plugins"][PLUGIN_ID][0]["installPath"])
    assert new_cache.name == "1.3.0"
    assert (new_cache / "hooks" / "scripts" / "enforcer.py").read_text() == \
        (repo / "hooks" / "scripts" / "enforcer.py").read_text()
    assert not list((home / ".claude" / "plugins").glob("installed_plugins.json.bak-claude-code-*")), \
        "a CLI update that reached SSOT must not trigger the manual-sync fallback"
    assert PLUGIN_ID in _claude_log(tmp_path)


# ── Fallback path (CLI cannot reach SSOT) ────────────────────────────────────

@pytest.mark.parametrize("mode", ["up_to_date_stale", "error"])
def test_fallback_sync_when_cli_does_not_reach_ssot(tmp_path, mode):
    repo = _make_repo(tmp_path, "repo", "2.0.0")
    old_cache = tmp_path / "home" / ".claude" / "plugins" / "cache" / "skill-concierge" / "skill-concierge" / "1.9.0"
    home = _seed_home(tmp_path, installed_version="1.9.0", install_path=old_cache)
    old_cache.mkdir(parents=True)
    (old_cache / ".claude-plugin").mkdir()
    (old_cache / ".claude-plugin" / "plugin.json").write_text(json.dumps({"version": "1.9.0"}))

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
    backups = list((home / ".claude" / "plugins").glob("installed_plugins.json.bak-claude-code-*"))
    assert len(backups) == 1, "exactly one backup of the registry must be kept"
    assert json.loads(backups[0].read_text())["plugins"][PLUGIN_ID][0]["version"] == "1.9.0"


def test_fallback_is_idempotent_on_rerun(tmp_path):
    repo = _make_repo(tmp_path, "repo", "2.0.0")
    old_cache = tmp_path / "home" / ".claude" / "plugins" / "cache" / "skill-concierge" / "skill-concierge" / "1.9.0"
    home = _seed_home(tmp_path, installed_version="1.9.0", install_path=old_cache)
    old_cache.mkdir(parents=True)
    (old_cache / ".claude-plugin").mkdir()
    (old_cache / ".claude-plugin" / "plugin.json").write_text(json.dumps({"version": "1.9.0"}))

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
    assert not list((home / ".claude" / "plugins").glob("installed_plugins.json.bak-claude-code-*")) or \
        len(list((home / ".claude" / "plugins").glob("installed_plugins.json.bak-claude-code-*"))) == 1


# ── Downgrade refusal ─────────────────────────────────────────────────────────

def test_refuses_to_downgrade_a_deployed_copy_newer_than_the_checkout(tmp_path):
    repo = _make_repo(tmp_path, "repo", "1.0.0")   # checkout is OLDER
    newer_cache = tmp_path / "home" / ".claude" / "plugins" / "cache" / "skill-concierge" / "skill-concierge" / "9.9.9"
    home = _seed_home(tmp_path, installed_version="9.9.9", install_path=newer_cache)
    newer_cache.mkdir(parents=True)
    (newer_cache / ".claude-plugin").mkdir()
    (newer_cache / ".claude-plugin" / "plugin.json").write_text(json.dumps({"version": "9.9.9"}))
    before = _registry(home)

    r = _run(tmp_path, repo, home, mode="up_to_date_stale")
    assert r.returncode != 0, "a checkout older than the deployed copy must be refused"
    assert "refusing to downgrade" in (r.stdout + r.stderr)
    assert _registry(home) == before, "a refused downgrade must leave the registry untouched"
    assert not (home / ".claude" / "plugins" / "cache" / "skill-concierge" / "skill-concierge" / "1.0.0").exists()
    assert not list((home / ".claude" / "plugins").glob("installed_plugins.json.bak-claude-code-*"))


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


# ── enabledPlugins is never touched ──────────────────────────────────────────

@pytest.mark.parametrize("mode", ["up_to_date_current", "updated", "up_to_date_stale", "error"])
def test_enabled_plugins_and_settings_untouched(tmp_path, mode):
    version = "1.2.0" if mode == "up_to_date_current" else "1.4.0"
    repo = _make_repo(tmp_path, "repo", version)
    cache_dir = tmp_path / "home" / ".claude" / "plugins" / "cache" / "skill-concierge" / "skill-concierge" / "1.2.0"
    home = _seed_home(tmp_path, installed_version="1.2.0", install_path=cache_dir)
    cache_dir.mkdir(parents=True)
    (cache_dir / ".claude-plugin").mkdir()
    (cache_dir / ".claude-plugin" / "plugin.json").write_text(json.dumps({"version": "1.2.0"}))
    settings_before = (home / ".claude" / "settings.json").read_text()

    _run(tmp_path, repo, home, mode=mode, source=repo)

    assert (home / ".claude" / "settings.json").read_text() == settings_before


# ── Backup naming convention ─────────────────────────────────────────────────

def test_backup_filename_matches_the_documented_pattern(tmp_path):
    repo = _make_repo(tmp_path, "repo", "3.0.0")
    old_cache = tmp_path / "home" / ".claude" / "plugins" / "cache" / "skill-concierge" / "skill-concierge" / "2.9.0"
    home = _seed_home(tmp_path, installed_version="2.9.0", install_path=old_cache)
    old_cache.mkdir(parents=True)
    (old_cache / ".claude-plugin").mkdir()
    (old_cache / ".claude-plugin" / "plugin.json").write_text(json.dumps({"version": "2.9.0"}))

    r = _run(tmp_path, repo, home, mode="error")
    assert r.returncode == 0, r.stdout + r.stderr
    backups = list((home / ".claude" / "plugins").glob("installed_plugins.json.bak-claude-code-*"))
    assert len(backups) == 1
    suffix = backups[0].name.split("installed_plugins.json.bak-claude-code-", 1)[1]
    assert len(suffix) == len("YYYYMMDD-HHMMSS")
    time.strptime(suffix, "%Y%m%d-%H%M%S")   # raises ValueError if malformed


# ── Real claude binary must never be invoked ─────────────────────────────────

def test_real_claude_binary_is_unreachable_and_never_invoked(tmp_path):
    real_claude = shutil.which("claude")
    if real_claude is None:
        pytest.skip("no real claude binary on this machine's PATH to prove isolation against")
    repo = _make_repo(tmp_path, "repo", "1.5.0")
    old_cache = tmp_path / "home" / ".claude" / "plugins" / "cache" / "skill-concierge" / "skill-concierge" / "1.4.0"
    home = _seed_home(tmp_path, installed_version="1.4.0", install_path=old_cache)
    old_cache.mkdir(parents=True)
    (old_cache / ".claude-plugin").mkdir()
    (old_cache / ".claude-plugin" / "plugin.json").write_text(json.dumps({"version": "1.4.0"}))

    env = dict(os.environ)
    env["HOME"] = str(home)
    env["PATH"] = _sandboxed_path(_fake_claude_dir(tmp_path))
    assert Path(real_claude).parent.as_posix() not in env["PATH"].split(os.pathsep)
    resolved = subprocess.run(["bash", "-c", "command -v claude"], env=env,
                               capture_output=True, text=True).stdout.strip()
    assert resolved == str(_fake_claude_dir(tmp_path) / "claude") or Path(resolved).name == "claude"
    assert resolved != real_claude

    r = _run(tmp_path, repo, home, mode="up_to_date_stale")
    assert r.returncode == 0, r.stdout + r.stderr
    assert _claude_log(tmp_path) != "", "the fake CLI must have been invoked"
