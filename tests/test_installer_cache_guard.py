"""Installers that write their own checkout path into a harness config refuse to run from a plugin
cache copy: the next plugin update deletes that copy and the harness breaks silently (the
2026-10-09 OpenCode duplicate). Claude Code, Codex and ZCode copy into their own cache and write no
checkout path, so they have no such guard. OMP's dev mode also keeps one extensions entry when the
checkout moves."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
COPIED = (".claude-plugin", "adapters", "bin", "hooks", "scripts", "skills", "config")


def _tree(dest: Path) -> Path:
    """The files an installer reads, without .git (the git-version check then skips)."""
    for rel in COPIED:
        shutil.copytree(ROOT / rel, dest / rel, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__"))
    for rel in (".mcp.json", "package.json"):
        shutil.copy2(ROOT / rel, dest / rel)
    return dest


def _run(installer_root: Path, home: Path, harness: str):
    env = dict(os.environ, HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"),
               SKILL_CONCIERGE_VENV=str(home / "no-venv"), PATH=os.environ["PATH"])
    return subprocess.run(["bash", str(installer_root / "adapters" / harness / "install.sh")],
                          env=env, capture_output=True, text=True, timeout=180)


@pytest.mark.parametrize("harness", ["cline", "commandcode", "dsh", "omp"])
def test_a_plugin_cache_copy_refuses_and_writes_nothing(harness, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    cache = _tree(home / ".claude" / "plugins" / "cache" / "skill-concierge" / "skill-concierge" / "0.66.0")
    before = sorted(p for p in home.rglob("*") if not p.is_relative_to(cache.parents[3]))
    p = _run(cache, home, harness)
    assert p.returncode != 0, p.stdout + p.stderr
    assert "plugin cache" in p.stderr and "clone" in p.stderr, p.stderr
    after = sorted(p for p in home.rglob("*") if not p.is_relative_to(cache.parents[3]))
    assert after == before, f"{harness} wrote {set(after) - set(before)}"


def _omp_entries(home: Path) -> list[str]:
    cfg = home / ".omp" / "agent" / "config.yml"
    return [l.strip() for l in cfg.read_text().splitlines()
            if l.strip().startswith("- ") and "skill-concierge.ext.ts" in l]


def test_omp_dev_mode_keeps_one_entry_when_the_checkout_moves(tmp_path):
    home = tmp_path / "home"
    (home / ".omp" / "agent").mkdir(parents=True)
    first, second = _tree(tmp_path / "a" / "skill-concierge"), _tree(tmp_path / "b" / "skill-concierge")
    _run(first, home, "omp")
    _run(second, home, "omp")
    _run(second, home, "omp")
    entries = _omp_entries(home)
    assert entries == [f"- {second / 'adapters' / 'omp' / 'skill-concierge.ext.ts'}"], entries
