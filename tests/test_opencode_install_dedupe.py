"""OpenCode v2 loads every `plugins` entry and rejects a second plugin with the same id.

Every copy of skill-concierge declares id "skill-concierge", so two entries (this checkout plus,
say, an old Claude Code cache copy) make OpenCode show one loaded and one "failed". The installer
must leave exactly one skill-concierge entry, pointing at the copy it ran from, and keep every
other entry untouched. It must never write into a skills folder another harness owns. Doctor
must flag what the installer would fix. Each test runs the real installer from a minimal copy
of this tree (no .git, throwaway HOME and XDG_CONFIG_HOME), so the result never depends on the
checkout's git state or the machine's config.
"""
import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REPO_SKILLS = sorted(d.name for d in (ROOT / "skills").iterdir() if (d / "SKILL.md").is_file())


def _tree(dest: Path) -> Path:
    """The files the installer reads, copied without .git (the git-version check then skips)."""
    for rel in (".claude-plugin", "adapters/opencode", "adapters/lib", "skills", "bin"):
        shutil.copytree(ROOT / rel, dest / rel, dirs_exist_ok=True)
    return dest


@pytest.fixture()
def env(tmp_path):
    repo = _tree(tmp_path / "repo")
    oc = tmp_path / "xdg" / "opencode"
    oc.mkdir(parents=True)
    (tmp_path / "home").mkdir()

    def run(cfg=None, installer_root=repo):
        if cfg is not None:
            (oc / "opencode.json").write_text(json.dumps(cfg, indent=2))
        e = dict(os.environ, HOME=str(tmp_path / "home"), XDG_CONFIG_HOME=str(tmp_path / "xdg"),
                 SKILL_CONCIERGE_VENV=str(tmp_path / "no-venv"))
        p = subprocess.run(["bash", str(installer_root / "adapters" / "opencode" / "install.sh")],
                           env=e, capture_output=True, text=True, timeout=120)
        cfg_now = json.loads((oc / "opencode.json").read_text()) if (oc / "opencode.json").exists() else None
        return p, cfg_now

    return repo, oc, run


def _copy_dir(base: Path, name="skill-concierge-opencode") -> Path:
    d = base / "adapters" / "opencode" / "plugin"
    d.mkdir(parents=True)
    (d / "package.json").write_text(json.dumps({"name": name}))
    return d


def _pkgs(cfg):
    return [e.get("package") if isinstance(e, dict) else e for e in cfg["plugins"]]


def test_installer_replaces_another_copys_entry_and_keeps_options(env, tmp_path):
    repo, oc, run = env
    ours = str(repo / "adapters" / "opencode" / "plugin")
    stale = str(_copy_dir(tmp_path / "old-checkout"))
    dangling = str(tmp_path / "gone" / "skill-concierge" / "adapters" / "opencode" / "plugin")
    other = {"package": "/somewhere/else/my-plugin"}
    p, cfg = run({"plugins": [other, {"package": stale, "options": {"x": 1}}, dangling],
                  "mcp": {"keep": {"type": "local"}}})
    assert p.returncode == 0, p.stderr
    assert cfg["plugins"] == [other, {"package": ours, "options": {"x": 1}}]
    assert cfg["mcp"] == {"keep": {"type": "local"}}
    p, cfg2 = run()                                                   # idempotent
    assert p.returncode == 0 and cfg2 == cfg


def test_installer_keeps_lookalike_and_relative_foreign_entries(env, tmp_path):
    repo, oc, run = env
    lookalike = str(_copy_dir(tmp_path / "proj", name="someone-elses-plugin"))
    rel_missing = "./vendor-plugins/adapters/opencode/plugin"         # not ours, not present
    p, cfg = run({"plugins": [{"package": lookalike}, rel_missing]})
    assert p.returncode == 0, p.stderr
    assert _pkgs(cfg) == [lookalike, rel_missing, str(repo / "adapters" / "opencode" / "plugin")]


def test_a_plugin_cache_copy_never_takes_over_a_checkout(env, tmp_path):
    repo, oc, run = env
    cache = _tree(tmp_path / "home" / ".claude" / "plugins" / "cache" / "skill-concierge" / "0.64.0")
    ours = str(repo / "adapters" / "opencode" / "plugin")
    p, cfg = run({"plugins": [{"package": ours}]}, installer_root=cache)
    assert p.returncode != 0 and "plugin cache" in p.stderr
    assert _pkgs(cfg) == [ours]


def test_installer_never_writes_through_a_shared_skills_folder(env, tmp_path):
    repo, oc, run = env
    claude = tmp_path / "claude-skills"
    (claude / "mine").mkdir(parents=True)
    (claude / "mine" / "SKILL.md").write_text("mine\n")
    (oc / "skills").symlink_to(claude)
    p, cfg = run({"skills": None})
    assert p.returncode == 0, p.stderr
    assert sorted(x.name for x in claude.iterdir()) == ["mine"]     # nothing added
    own = oc / "skill-concierge-skills"
    assert sorted(d.name for d in own.iterdir() if d.is_dir()) == REPO_SKILLS
    assert cfg["skills"] == [str(own)]


def test_installer_retires_its_old_copies_and_keeps_edited_ones(env, tmp_path):
    repo, oc, run = env
    claude = tmp_path / "claude-skills"
    claude.mkdir()
    edited = REPO_SKILLS[0]
    for n in REPO_SKILLS:
        (claude / n).mkdir()
        body = (ROOT / "skills" / n / "SKILL.md").read_text()
        (claude / n / "SKILL.md").write_text(body + ("\nlocal edit\n" if n == edited else ""))
    (claude / ".skill-concierge-managed.json").write_text(json.dumps({"names": REPO_SKILLS + ["../..", 7]}))
    (oc / "skills").symlink_to(claude)
    p, _ = run({})
    assert p.returncode == 0, p.stderr
    assert sorted(x.name for x in claude.iterdir()) == [".skill-concierge-managed.json", edited]
    assert json.loads((claude / ".skill-concierge-managed.json").read_text())["names"] == [edited]


def test_a_malformed_old_marker_is_ignored(env, tmp_path):
    repo, oc, run = env
    (oc / "skills").mkdir()
    (oc / "skills" / ".skill-concierge-managed.json").write_text("[1, 2]")
    p, _ = run({})
    assert p.returncode == 0, p.stderr


def test_known_versions_include_every_committed_version(tmp_path):
    spec = importlib.util.spec_from_file_location("oc_config", ROOT / "adapters" / "opencode" / "oc_config.py")
    oc_config = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(oc_config)
    repo = tmp_path / "r"
    md = repo / "skills" / "doctor" / "SKILL.md"
    md.parent.mkdir(parents=True)
    g = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    for body in ("v1\n", "v2\n"):
        md.write_text(body)
        subprocess.run(g + ["add", "-A"], check=True)
        subprocess.run(g + ["commit", "-qm", body.strip()], check=True)
    md.write_text("v3 uncommitted\n")
    assert oc_config.known_versions(repo, "doctor") == {"v1\n", "v2\n", "v3 uncommitted\n"}


def test_doctor_flags_what_the_installer_fixes(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("doctor_dedupe", ROOT / "scripts" / "doctor.py")
    doctor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(doctor)
    home = tmp_path / "opencode"
    own = home / "skill-concierge-skills"
    own.mkdir(parents=True)
    ours = str(ROOT / "adapters" / "opencode" / "plugin")
    cfg = home / "opencode.json"
    for name, val in (("OPENCODE_HOME", home), ("OPENCODE_JSON", cfg), ("OPENCODE_SKILLS", own),
                      ("OPENCODE_LEGACY_SKILLS", home / "skills")):
        monkeypatch.setattr(doctor, name, val)
    cfg.write_text(json.dumps({"plugins": [{"package": ours}], "skills": [str(own)]}))
    assert "plugin skills missing" in doctor.check_opencode()["detail"]          # empty folder
    for n in REPO_SKILLS:
        (own / n).mkdir()
        (own / n / "SKILL.md").write_text("x")
    assert doctor.check_opencode()["status"] == doctor.OK, doctor.check_opencode()
    lookalike = str(_copy_dir(tmp_path / "proj", name="someone-elses-plugin"))
    cfg.write_text(json.dumps({"plugins": [{"package": ours}, lookalike], "skills": [str(own)]}))
    assert doctor.check_opencode()["status"] == doctor.OK                         # not a copy
    cfg.write_text(json.dumps({"plugins": [{"package": ours}], "skills": str(own)}))
    assert "skills is not a list" in doctor.check_opencode()["detail"]
    (home / "skills").mkdir()
    (home / "skills" / ".skill-concierge-managed.json").write_text('{"names": ["doctor"]}')
    cfg.write_text(json.dumps({"plugins": [{"package": ours}, {"package": str(_copy_dir(tmp_path / "old"))}],
                               "skills": [str(own)]}))
    detail = doctor.check_opencode()["detail"]
    assert "2 skill-concierge" in detail and "old skill copies" in detail
