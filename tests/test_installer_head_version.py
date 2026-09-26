"""Every installer that exports this checkout installs HEAD (`git archive HEAD`), so HEAD's
version is the version it installs. An uncommitted version change used to put HEAD's content in a
cache dir named for the new version. Each installer must refuse that state before any CLI call or
any write under HOME."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESSES = ("codex", "claude-code", "omp", "zcode")


def _repo(tmp_path, harness, committed, working):
    repo = tmp_path / "repo"
    (repo / ".claude-plugin").mkdir(parents=True)
    (repo / "adapters" / harness).mkdir(parents=True)
    shutil.copy2(ROOT / "adapters" / harness / "install.sh", repo / "adapters" / harness / "install.sh")
    manifest = repo / ".claude-plugin" / "plugin.json"
    manifest.write_text(json.dumps({"name": "skill-concierge", "version": committed}))
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init"],
                   cwd=repo, check=True)
    manifest.write_text(json.dumps({"name": "skill-concierge", "version": working}))
    return repo


def _run(tmp_path, repo, harness):
    home, fakebin = tmp_path / "home", tmp_path / "fakebin"
    home.mkdir()
    fakebin.mkdir()
    log = tmp_path / "cli.log"
    for cli in ("codex", "claude", "omp", "zcode"):
        f = fakebin / cli
        f.write_text(f'#!/bin/sh\necho "{cli} $*" >> "{log}"\nexit 1\n')
        f.chmod(0o755)
    env = {**os.environ, "HOME": str(home), "PATH": f"{fakebin}{os.pathsep}{os.environ['PATH']}"}
    r = subprocess.run(["bash", str(repo / "adapters" / harness / "install.sh")], env=env,
                       capture_output=True, text=True, timeout=60)
    return r, home, log


@pytest.mark.parametrize("harness", HARNESSES)
def test_an_uncommitted_version_change_is_refused_before_anything_runs(tmp_path, harness):
    repo = _repo(tmp_path, harness, committed="1.0.0", working="1.0.1")
    r, home, log = _run(tmp_path, repo, harness)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "HEAD carries v1.0.0" in r.stderr, r.stderr
    assert not log.exists(), log.read_text()
    assert not any(home.rglob("*")), sorted(str(p) for p in home.rglob("*"))


@pytest.mark.parametrize("harness", HARNESSES)
def test_a_committed_version_passes_the_check(tmp_path, harness):
    repo = _repo(tmp_path, harness, committed="1.0.1", working="1.0.1")
    r, _, _ = _run(tmp_path, repo, harness)
    assert "HEAD carries" not in r.stderr, r.stderr
