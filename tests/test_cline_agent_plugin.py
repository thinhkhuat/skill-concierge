"""Cline Agent Plugin (ADR-0086): the generated plugin folder and the enforcer's Cline lane.

adapters/cline/agent_plugin.py builds ~/.agents/plugins/skill-concierge/ from the repo. Cline
rejects a plugin skill whose frontmatter carries any key outside the agent-plugins.org set, and
expands no ${CLAUDE_PLUGIN_ROOT}; these tests hold the generated copies to both rules.
"""
import importlib.util
import json
import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
SKILLS = sorted(d.name for d in (ROOT / "skills").iterdir() if (d / "SKILL.md").is_file())


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def built(tmp_path):
    ap = _load(ROOT / "adapters" / "cline" / "agent_plugin.py", "agent_plugin")
    dest = tmp_path / "skill-concierge"
    assert ap.sync(dest) == 0
    return ap, dest


def frontmatter(text):
    m = re.match(r"^---\n([\s\S]*?)\n---\n", text)
    assert m, "no frontmatter"
    top = [re.match(r"^([A-Za-z][\w-]*):", l).group(1) for l in m.group(1).splitlines()
           if re.match(r"^[A-Za-z][\w-]*:", l)]
    meta = [l.strip() for l in m.group(1).split("metadata:", 1)[1].splitlines() if l.startswith("  ")] \
        if "metadata:" in m.group(1) else []
    return top, meta, text[m.end():]


def test_every_skill_is_generated_with_cline_legal_frontmatter(built):
    _, dest = built
    assert sorted(p.name for p in (dest / "skills").iterdir()) == SKILLS
    for name in SKILLS:
        text = (dest / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
        top, meta, body = frontmatter(text)
        assert set(top) <= ALLOWED, (name, set(top) - ALLOWED)
        assert top[0] == "name" and f"name: {name}" in text
        assert "CLAUDE_PLUGIN_ROOT" not in body
        # Allowed keys survive verbatim; the body is the source body with the root resolved.
        src = (ROOT / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
        src_top, src_meta, src_body = frontmatter(src)
        assert top == [k for k in src_top if k in ALLOWED]
        # Every metadata value is a quoted string (Cline rejects any other type), same values.
        assert all(re.match(r'^[\w-]+: ".*"$', line) for line in meta), (name, meta)
        assert [l.replace('"', "") for l in meta] == [l.replace('"', "") for l in src_meta]
        # Cline's own limits: name 64, description 1024 characters.
        fm = text.split("---")[1]
        assert len(name) <= 64
        assert len(re.search(r"^description: (.*)$", fm, re.M).group(1)) <= 1024
        assert body == src_body.replace("${CLAUDE_PLUGIN_ROOT}", str(ROOT)).replace("$CLAUDE_PLUGIN_ROOT", str(ROOT))


def test_manifest_and_mcp_point_at_this_checkout(built):
    _, dest = built
    manifest = json.loads((dest / "plugin.json").read_text(encoding="utf-8"))
    ssot = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"]
    assert manifest["$schema"] == "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
    assert manifest["name"] == "skill-concierge" and manifest["version"] == ssot
    mcp = json.loads((dest / "mcp.json").read_text(encoding="utf-8"))
    assert mcp["$schema"] == "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"
    server = mcp["mcpServers"]["skill-search"]
    assert server["type"] == "stdio" and server["command"] == "bash"
    assert server["args"] == [str(ROOT / "bin" / "skill-search-mcp")]
    assert (ROOT / "bin" / "skill-search-mcp").is_file()
    # Generated from .mcp.json, so the engine env cannot drift from Claude Code's.
    claude = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["skill-search"]
    assert server["env"] == claude["env"]


def test_check_flags_drift_and_sync_repairs_and_prunes(built):
    ap, dest = built
    assert ap.stale(dest, ap.plan()) == []
    (dest / "skills" / "doctor" / "SKILL.md").write_text("edited by hand", encoding="utf-8")
    managed = json.loads((dest / ap.MARKER).read_text(encoding="utf-8"))
    managed["files"].append("skills/retired/SKILL.md")
    (dest / ap.MARKER).write_text(json.dumps(managed), encoding="utf-8")
    (dest / "skills" / "retired").mkdir()
    (dest / "skills" / "retired" / "SKILL.md").write_text("old", encoding="utf-8")
    assert ap.stale(dest, ap.plan()) == ["skills/doctor/SKILL.md", "skills/retired/SKILL.md"]
    ap.sync(dest)
    assert ap.stale(dest, ap.plan()) == []
    assert not (dest / "skills" / "retired").exists()




@pytest.fixture()
def enforcer(tmp_path):
    saved = dict(os.environ)
    os.environ.update({
        "SKILL_CONCIERGE_HARNESS": "cline",
        "SKILL_QDRANT_URL": "http://127.0.0.1:9",
        "SKILL_TRIGGERS": "/nonexistent-triggers.json",
        "SKILL_CONCIERGE_CATALOG_ROOTS": "/nonexistent-catalogs.json",
    })
    try:
        mod = _load(ROOT / "hooks" / "scripts" / "enforcer.py", "enforcer_cline")
        mod._CLINE_AGENT_PLUGINS = tmp_path / "plugins"
        yield mod
    finally:
        os.environ.clear()
        os.environ.update(saved)


def test_cline_offers_a_namespaced_skill_only_from_an_installed_agent_plugin(enforcer):
    assert enforcer.RUNNING_HARNESS == "cline"
    assert enforcer._plugin_gate_ok("skill-concierge:doctor") is False
    assert enforcer._invocable_twin("skill-concierge:doctor") is False
    plugin = enforcer._CLINE_AGENT_PLUGINS / "skill-concierge"
    (plugin / "skills" / "doctor").mkdir(parents=True)
    (plugin / "skills" / "doctor" / "SKILL.md").write_text("---\nname: doctor\n---\n", encoding="utf-8")
    (plugin / "plugin.json").write_text("{}", encoding="utf-8")
    assert enforcer._plugin_gate_ok("skill-concierge:doctor") is True
    assert enforcer._invocable_twin("skill-concierge:doctor") is True
    assert enforcer._plugin_gate_ok("skill-concierge:not-shipped") is False
    assert enforcer._plugin_gate_ok("other-plugin:doctor") is False
    assert enforcer._plugin_gate_ok("skill-concierge:../../etc") is False
    assert enforcer._plugin_gate_ok("doctor") is True


def test_sync_refuses_to_write_through_a_symlink(tmp_path):
    ap = _load(ROOT / "adapters" / "cline" / "agent_plugin.py", "agent_plugin_link")
    target = tmp_path / "somebody-elses-folder"
    (target / "skills" / "doctor").mkdir(parents=True)
    (target / "skills" / "doctor" / "SKILL.md").write_text("theirs", encoding="utf-8")
    dest = tmp_path / "skill-concierge"
    dest.symlink_to(target)
    assert ap.sync(dest) == 1
    assert (target / "skills" / "doctor" / "SKILL.md").read_text(encoding="utf-8") == "theirs"
    assert not (target / "plugin.json").exists()


def test_a_tampered_marker_never_prunes_outside_the_plugin_folder(built, tmp_path):
    ap, dest = built
    outside = tmp_path / "outside.txt"
    outside.write_text("keep me", encoding="utf-8")
    managed = json.loads((dest / ap.MARKER).read_text(encoding="utf-8"))
    managed["files"] += ["../outside.txt", str(outside)]
    (dest / ap.MARKER).write_text(json.dumps(managed), encoding="utf-8")
    ap.sync(dest)
    assert outside.read_text(encoding="utf-8") == "keep me"


def test_sync_refuses_a_folder_it_did_not_build(tmp_path):
    ap = _load(ROOT / "adapters" / "cline" / "agent_plugin.py", "agent_plugin_foreign")
    dest = tmp_path / "skill-concierge"
    (dest / "skills").mkdir(parents=True)
    (dest / "plugin.json").write_text("{\"theirs\": true}", encoding="utf-8")
    assert ap.sync(dest) == 1
    assert (dest / "plugin.json").read_text(encoding="utf-8") == "{\"theirs\": true}"


def test_generated_frontmatter_parses_as_yaml_with_string_metadata(built):
    yaml = pytest.importorskip("yaml")
    _, dest = built
    for name in SKILLS:
        fm = yaml.safe_load((dest / "skills" / name / "SKILL.md").read_text(encoding="utf-8").split("---")[1])
        assert set(fm) <= ALLOWED and fm["name"] == name
        assert all(isinstance(v, str) for v in (fm.get("metadata") or {}).values()), (name, fm.get("metadata"))


def test_block_scalar_metadata_stays_valid_yaml():
    yaml = pytest.importorskip("yaml")
    ap = _load(ROOT / "adapters" / "cline" / "agent_plugin.py", "agent_plugin_block")
    src = "---\nname: x\ndescription: d\nuser-invocable: true\nmetadata:\n  version: 1.0\n  note: |\n    line one\n---\nbody\n"
    fm = yaml.safe_load(ap.convert_skill(src).split("---")[1])
    assert fm == {"name": "x", "description": "d", "metadata": {"version": "1.0", "note": "line one\n"}}
