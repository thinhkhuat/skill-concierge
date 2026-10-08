"""Every installer that exports this checkout installs HEAD (`git archive HEAD`), so HEAD's
version is the version it installs. An uncommitted version change used to put HEAD's content in a
cache dir named for the new version. Each installer must refuse that state before any CLI call or
any write under HOME. So must a git checkout git cannot read, and one whose git dir is renamed to
`git/`: copying either as a plain tree would ship its untracked files."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from installer_env import installer_env

ROOT = Path(__file__).resolve().parents[1]
HARNESSES = ("codex", "claude-code", "omp", "zcode")


def _repo(tmp_path, harness, committed, working, stage=False):
    repo = tmp_path / "repo"
    (repo / "adapters" / harness).mkdir(parents=True)
    shutil.copy2(ROOT / "adapters" / harness / "install.sh", repo / "adapters" / harness / "install.sh")
    shutil.copytree(ROOT / "adapters" / "lib", repo / "adapters" / "lib",
                    ignore=shutil.ignore_patterns("__pycache__"))
    manifests = []
    for d in (".claude-plugin", ".codex-plugin"):
        (repo / d).mkdir()
        manifests.append(repo / d / "plugin.json")
        manifests[-1].write_text(json.dumps({"name": "skill-concierge", "version": committed}))
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init"],
                   cwd=repo, check=True)
    for m in manifests:
        m.write_text(json.dumps({"name": "skill-concierge", "version": working}))
    if stage:
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    return repo


def _run(tmp_path, repo, harness, clis=("codex", "claude", "omp", "zcode")):
    home, fakebin = tmp_path / "home", tmp_path / "fakebin"
    home.mkdir()
    fakebin.mkdir()
    log = tmp_path / "cli.log"
    for cli in clis:
        f = fakebin / cli
        f.write_text(f'#!/bin/sh\necho "{cli} $*" >> "{log}"\nexit 1\n')
        f.chmod(0o755)
    r = subprocess.run(["bash", str(repo / "adapters" / harness / "install.sh")],
                       env=installer_env(tmp_path, home, fakebin), capture_output=True, text=True, timeout=60)
    return r, home, log


def _nothing_ran(r, home, log):
    """Refused: exit 1, no harness CLI called (a failing `git` stub may log), nothing under HOME."""
    assert r.returncode == 1, r.stdout + r.stderr
    calls = log.read_text().splitlines() if log.exists() else []
    assert not [c for c in calls if not c.startswith("git ")], calls
    assert not any(home.rglob("*")), sorted(str(p) for p in home.rglob("*"))


@pytest.mark.parametrize("harness", HARNESSES)
def test_an_uncommitted_version_change_is_refused_before_anything_runs(tmp_path, harness):
    repo = _repo(tmp_path, harness, committed="1.0.0", working="1.0.1")
    r, home, log = _run(tmp_path, repo, harness)
    assert "HEAD carries v1.0.0" in r.stderr, r.stderr
    _nothing_ran(r, home, log)


@pytest.mark.parametrize("harness", HARNESSES)
def test_a_staged_but_uncommitted_version_change_is_refused(tmp_path, harness):
    """`git archive HEAD` exports the commit, not the index."""
    repo = _repo(tmp_path, harness, committed="1.0.0", working="1.0.1", stage=True)
    r, home, log = _run(tmp_path, repo, harness)
    assert "HEAD carries v1.0.0" in r.stderr, r.stderr
    _nothing_ran(r, home, log)


@pytest.mark.parametrize("harness", HARNESSES)
def test_a_checkout_git_cannot_read_is_refused(tmp_path, harness):
    """A `git` that fails (missing, a safe.directory refusal, a damaged repo) must not send a real
    checkout down the plain-copy branch."""
    repo = _repo(tmp_path, harness, committed="1.0.0", working="1.0.0")
    r, home, log = _run(tmp_path, repo, harness, clis=("codex", "claude", "omp", "zcode", "git"))
    assert "git cannot read it" in r.stderr, r.stdout + r.stderr
    _nothing_ran(r, home, log)


@pytest.mark.parametrize("harness", HARNESSES)
def test_a_renamed_git_dir_is_refused(tmp_path, harness):
    repo = _repo(tmp_path, harness, committed="1.0.0", working="1.0.0")
    (repo / ".git").rename(repo / "git")
    r, home, log = _run(tmp_path, repo, harness)
    assert "git/" in r.stderr, r.stdout + r.stderr
    _nothing_ran(r, home, log)


@pytest.mark.parametrize("harness", HARNESSES)
def test_a_committed_version_passes_the_check(tmp_path, harness):
    repo = _repo(tmp_path, harness, committed="1.0.1", working="1.0.1")
    r, _, _ = _run(tmp_path, repo, harness)
    assert "HEAD carries" not in r.stderr and "cannot read" not in r.stderr, r.stderr
