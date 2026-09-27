"""adapters/lib/safe_write.py — the shared write primitive every installer's JSON/registry
write now goes through, so it is tested once here instead of once per call site."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "adapters" / "lib" / "safe_write.py"


@pytest.fixture(scope="module")
def safe_write():
    spec = importlib.util.spec_from_file_location("safe_write", MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_write_text_creates_a_fresh_file(tmp_path, safe_write):
    target = tmp_path / "settings.json"
    real = safe_write.write_text(target, "hello\n")
    assert real == target
    assert target.read_text() == "hello\n"


def test_write_text_follows_a_symlink_and_updates_the_real_target(tmp_path, safe_write):
    dotfiles = tmp_path / "dotfiles"
    dotfiles.mkdir()
    real_file = dotfiles / "settings.json"
    real_file.write_text("old\n")
    link = tmp_path / "settings.json"
    link.symlink_to(real_file)

    safe_write.write_text(link, "new\n")

    assert link.is_symlink(), "the symlink itself must survive"
    assert link.resolve() == real_file.resolve()
    assert real_file.read_text() == "new\n", "the file the symlink points at must carry the new content"


def test_write_text_never_widens_an_existing_restrictive_mode(tmp_path, safe_write):
    target = tmp_path / "mcp.json"
    target.write_text(json.dumps({"env": {"TOKEN": "s3cr3t"}}))
    target.chmod(0o600)

    safe_write.write_text(target, json.dumps({"env": {"TOKEN": "s3cr3t"}, "added": True}))

    assert oct(target.stat().st_mode & 0o777) == oct(0o600)


def test_write_text_creates_the_parent_directory(tmp_path, safe_write):
    target = tmp_path / "nested" / "dir" / "settings.json"
    safe_write.write_text(target, "x\n")
    assert target.read_text() == "x\n"


def test_write_registry_mutates_and_swaps_in(tmp_path, safe_write):
    reg = tmp_path / "installed_plugins.json"
    reg.write_text(json.dumps({"plugins": {"skill-concierge@skill-concierge": [{"version": "1.0.0"}]}}))

    def bump(data):
        data["plugins"]["skill-concierge@skill-concierge"][0]["version"] = "2.0.0"

    real, backup = safe_write.write_registry(reg, bump, "unittest")
    assert real == reg
    assert json.loads(reg.read_text())["plugins"]["skill-concierge@skill-concierge"][0]["version"] == "2.0.0"
    assert backup.exists()
    assert json.loads(backup.read_text())["plugins"]["skill-concierge@skill-concierge"][0]["version"] == "1.0.0"


def test_write_registry_follows_a_symlink_and_backs_up_beside_the_symlink(tmp_path, safe_write):
    dotfiles = tmp_path / "dotfiles"
    dotfiles.mkdir()
    real_reg = dotfiles / "installed_plugins.json"
    real_reg.write_text(json.dumps({"plugins": {"skill-concierge@skill-concierge": [{"version": "1.0.0"}]}}))
    real_reg.chmod(0o600)
    link_dir = tmp_path / "plugins"
    link_dir.mkdir()
    link = link_dir / "installed_plugins.json"
    link.symlink_to(real_reg)

    def bump(data):
        data["plugins"]["skill-concierge@skill-concierge"][0]["version"] = "2.0.0"

    real, backup = safe_write.write_registry(link, bump, "unittest")

    assert link.is_symlink()
    assert real == Path(real_reg).resolve() or real.resolve() == real_reg.resolve()
    assert oct(real_reg.stat().st_mode & 0o777) == oct(0o600)
    assert backup.parent == link_dir, "the backup must sit beside the path the caller reads, not the symlink target"


def test_write_registry_refuses_when_the_file_changed_since_it_was_read(tmp_path, safe_write):
    reg = tmp_path / "installed_plugins.json"
    reg.write_text(json.dumps({"plugins": {"skill-concierge@skill-concierge": [{"version": "1.0.0"}]}}))

    def bump_and_race(data):
        data["plugins"]["skill-concierge@skill-concierge"][0]["version"] = "2.0.0"
        # Simulate a live session writing the file while this run is mutating in memory.
        reg.write_text(json.dumps({"plugins": {"skill-concierge@skill-concierge": [{"version": "9.9.9"}]}}))

    with pytest.raises(RuntimeError, match="changed while this ran"):
        safe_write.write_registry(reg, bump_and_race, "unittest")

    assert json.loads(reg.read_text())["plugins"]["skill-concierge@skill-concierge"][0]["version"] == "9.9.9", \
        "the concurrent write must survive untouched"
    assert not list(tmp_path.glob("*.tmp-*")), "no leftover tmp file"


def test_write_registry_keeps_only_the_newest_backups(tmp_path, safe_write):
    reg = tmp_path / "installed_plugins.json"
    reg.write_text(json.dumps({"plugins": {"skill-concierge@skill-concierge": [{"version": "1.0.0"}]}}))
    for i in range(6):
        (tmp_path / f"installed_plugins.json.bak-unittest-2026010{i}-000000-1").write_text("{}")

    def bump(data):
        data["plugins"]["skill-concierge@skill-concierge"][0]["version"] = "2.0.0"

    safe_write.write_registry(reg, bump, "unittest", keep=5)
    kept = sorted(tmp_path.glob("installed_plugins.json.bak-unittest-*"))
    assert len(kept) == 5
