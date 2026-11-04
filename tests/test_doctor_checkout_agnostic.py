"""A harness wired to ANY checkout of this plugin is healthy.

doctor runs from one copy of the plugin (the plugin cache, the dev checkout, a release tag) while
Cline and OpenCode wire themselves by path to whichever copy installed them — and RULES [52] makes
the dev checkout the source of truth. The row must judge the wiring by identity and version, never
by equality with the directory doctor happens to run from. Pinned here: a second checkout at this
version is OK, and a stale version, a missing target or a cache-hosted copy is not.
"""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCTOR = ROOT / "scripts" / "doctor.py"


def _load():
    spec = importlib.util.spec_from_file_location("doctor_checkout_agnostic", DOCTOR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _version() -> str:
    return json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"]


def _other_checkout(base: Path, version: str, name: str = "skill-concierge-other") -> Path:
    """A second copy of this plugin, as the dev checkout sits beside the plugin cache."""
    other = base / name
    files = {
        ".claude-plugin/plugin.json": json.dumps({"version": version}),
        "adapters/opencode/plugin/package.json": json.dumps({"name": "skill-concierge-opencode"}),
        "adapters/opencode/plugin/index.ts": "export {}\n",
        "adapters/cline/skill-concierge.cline-plugin.ts": "export {}\n",
        # The Agent Plugin builder, reduced to "the copy matches" — doctor only asks it to check.
        "adapters/cline/agent_plugin.py": "import sys\nsys.exit(0)\n",
    }
    for rel, body in files.items():
        p = other / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return other


def _wire_cline(dr, tmp_path: Path, target: Path, monkeypatch) -> None:
    loader = tmp_path / "cline-loader.ts"
    loader.write_text(f'export * from "{target}";\n', encoding="utf-8")
    cline = tmp_path / "cline-home"
    cline.mkdir(exist_ok=True)
    agents = tmp_path / "agents"
    agents.mkdir(exist_ok=True)
    (agents / "plugin.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(dr, "CLINE_DIR", cline)
    monkeypatch.setattr(dr, "CLINE_LOADER", loader)
    monkeypatch.setattr(dr, "CLINE_AGENT_DIR", agents)
    monkeypatch.setenv("CLINE_SESSION_BACKEND_MODE", "local")


def _wire_opencode(dr, tmp_path: Path, plugin_dir: Path, monkeypatch) -> None:
    home = tmp_path / "oc-home"
    home.mkdir(exist_ok=True)
    skills = tmp_path / "oc-skills"
    for d in (ROOT / "skills").glob("*"):
        if (d / "SKILL.md").is_file():
            (skills / d.name).mkdir(parents=True, exist_ok=True)
            (skills / d.name / "SKILL.md").write_text("x", encoding="utf-8")
    cfg = home / "opencode.json"
    cfg.write_text(json.dumps({"plugins": [{"package": str(plugin_dir)}], "skills": [str(skills)]}),
                   encoding="utf-8")
    monkeypatch.setattr(dr, "OPENCODE_HOME", home)
    monkeypatch.setattr(dr, "OPENCODE_JSON", cfg)
    monkeypatch.setattr(dr, "OPENCODE_SKILLS", skills)
    monkeypatch.setattr(dr, "OPENCODE_LEGACY_SKILLS", tmp_path / "oc-legacy")


def test_cline_accepts_another_checkout_at_this_version(tmp_path, monkeypatch):
    dr = _load()
    other = _other_checkout(tmp_path, _version())
    _wire_cline(dr, tmp_path, other / "adapters" / "cline" / "skill-concierge.cline-plugin.ts", monkeypatch)
    row = dr.check_cline()
    assert row["status"] == dr.OK, row["detail"]


def test_cline_flags_an_older_checkout(tmp_path, monkeypatch):
    dr = _load()
    other = _other_checkout(tmp_path, "0.0.1")
    _wire_cline(dr, tmp_path, other / "adapters" / "cline" / "skill-concierge.cline-plugin.ts", monkeypatch)
    row = dr.check_cline()
    assert row["status"] == dr.WARN
    assert "v0.0.1" in row["detail"]


def test_cline_flags_a_missing_target(tmp_path, monkeypatch):
    dr = _load()
    other = _other_checkout(tmp_path, _version())
    target = other / "adapters" / "cline" / "skill-concierge.cline-plugin.ts"
    _wire_cline(dr, tmp_path, target, monkeypatch)
    target.unlink()
    row = dr.check_cline()
    assert row["status"] == dr.WARN
    assert "missing" in row["detail"]


def test_cline_flags_a_plugin_cache_copy(tmp_path, monkeypatch):
    """A cache copy carries the right version but the next plugin update deletes it."""
    dr = _load()
    cached = _other_checkout(tmp_path / "plugins" / "cache", _version(), name="skill-concierge")
    _wire_cline(dr, tmp_path, cached / "adapters" / "cline" / "skill-concierge.cline-plugin.ts", monkeypatch)
    row = dr.check_cline()
    assert row["status"] == dr.WARN
    assert "plugin cache" in row["detail"]


def test_opencode_accepts_another_checkout_at_this_version(tmp_path, monkeypatch):
    dr = _load()
    other = _other_checkout(tmp_path, _version())
    _wire_opencode(dr, tmp_path, other / "adapters" / "opencode" / "plugin", monkeypatch)
    row = dr.check_opencode()
    assert row["status"] == dr.OK, row["detail"]


def test_opencode_flags_an_older_checkout(tmp_path, monkeypatch):
    dr = _load()
    other = _other_checkout(tmp_path, "0.0.1")
    _wire_opencode(dr, tmp_path, other / "adapters" / "opencode" / "plugin", monkeypatch)
    row = dr.check_opencode()
    assert row["status"] == dr.WARN
    assert "v0.0.1" in row["detail"]


def test_opencode_flags_a_dead_path(tmp_path, monkeypatch):
    dr = _load()
    other = _other_checkout(tmp_path, _version())
    plugin_dir = other / "adapters" / "opencode" / "plugin"
    _wire_opencode(dr, tmp_path, plugin_dir, monkeypatch)
    for f in plugin_dir.iterdir():
        f.unlink()
    plugin_dir.rmdir()
    row = dr.check_opencode()
    assert row["status"] == dr.WARN
    assert "missing" in row["detail"]
