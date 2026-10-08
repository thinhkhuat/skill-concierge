"""The installers' identical shell helpers live once, in adapters/lib/sync.sh.

Five installers (claude-code, codex, omp, zcode, opencode) used to carry byte-identical copies of
the same helpers, and one copy had already drifted. Each now sources the one lib through a path
derived from its own location, defines none of the lib's functions itself, and refuses to run,
before any write, when the lib is missing.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest
from installer_env import installer_env

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "adapters" / "lib" / "sync.sh"
STOCK_BASH = Path("/bin/bash")
INSTALLERS = ("claude-code", "codex", "omp", "zcode", "opencode")
MOVED = {"_ver_ge", "_is_own_checkout", "_export_to", "_refuse_unexportable_checkout"}
SOURCE_LINES = (
    'SYNC_LIB="$(cd "$(dirname "$_self")/.." && pwd)/lib/sync.sh"',
    '. "$SYNC_LIB"',
)
_FUNC_DEF = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\(\)\s*\{", re.M)


def _installer(name: str) -> Path:
    return ROOT / "adapters" / name / "install.sh"


def _functions(path: Path) -> set[str]:
    return set(_FUNC_DEF.findall(path.read_text()))


@pytest.mark.parametrize("name", INSTALLERS)
def test_installer_sources_the_shared_lib_from_its_own_location(name):
    text = _installer(name).read_text()
    assert 'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"' in text
    for line in SOURCE_LINES:
        assert line in text, f"adapters/{name}/install.sh lacks {line!r}"


@pytest.mark.parametrize("name", INSTALLERS)
def test_installer_defines_none_of_the_lib_functions(name):
    assert LIB.is_file(), "adapters/lib/sync.sh is missing"
    shared = _functions(_installer(name)) & _functions(LIB)
    assert not shared, f"adapters/{name}/install.sh still defines {sorted(shared)}"


@pytest.mark.skipif(not STOCK_BASH.exists(), reason="no /bin/bash on this host")
def test_lib_parses_under_stock_bash():
    assert LIB.is_file(), "adapters/lib/sync.sh is missing"
    r = subprocess.run([str(STOCK_BASH), "-n", str(LIB)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr


def test_lib_defines_exactly_the_moved_helpers():
    assert LIB.is_file(), "adapters/lib/sync.sh is missing"
    assert _functions(LIB) == MOVED


@pytest.mark.parametrize("name", INSTALLERS)
def test_a_missing_lib_is_refused_before_anything_runs(tmp_path, name):
    """The lib path comes from the installer's own location: run from this checkout's root (whose
    adapters/lib/ exists), a copy with no adapters/lib/ beside it must still refuse."""
    dest = tmp_path / "repo" / "adapters" / name
    dest.mkdir(parents=True)
    shutil.copy2(_installer(name), dest / "install.sh")
    home = tmp_path / "home"
    home.mkdir()
    r = subprocess.run(["bash", str(dest / "install.sh")], cwd=ROOT, env=installer_env(tmp_path, home),
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 1, r.stdout + r.stderr
    assert f"{tmp_path / 'repo' / 'adapters' / 'lib' / 'sync.sh'} is missing" in r.stderr, r.stderr
    assert r.stdout == "", r.stdout
    assert not any(home.rglob("*")), sorted(str(p) for p in home.rglob("*"))


@pytest.mark.parametrize("name", INSTALLERS)
def test_a_symlinked_installer_still_finds_the_lib(name, tmp_path):
    """The lib is looked up beside the installer's real file, not beside a symlink to it."""
    link = tmp_path / "linked-install.sh"
    link.symlink_to(_installer(name))
    run = subprocess.run(["/bin/bash", str(link), "--not-an-option"], capture_output=True, text=True,
                         timeout=60, env=installer_env(tmp_path, tmp_path / "home"))
    assert "is missing: this installer needs the shared helpers" not in run.stderr, run.stderr
