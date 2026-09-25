"""Account-synced skills (scope claude-synced) stay out of the two places they must not reach:
settings.json skillOverrides (undocumented for synced skills) and third-party-LLM generation
(their bodies are the user's claude.ai content)."""
import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_apply_overrides_excludes_synced_scope(monkeypatch):
    fake_sd = types.ModuleType("skill_search.skills_discovery")
    fake_sd.discover_skills = lambda: [
        {"name": "mine", "scope": "personal"},
        {"name": "anthropic-skills:skill-creator", "scope": "claude-synced"},
        {"name": "ext:x", "scope": "catalog:ext"},
        {"name": "proj", "scope": "project:/p"},
        {"name": "pl:y", "scope": "plugin"}]
    fake_pkg = types.ModuleType("skill_search")
    fake_pkg.skills_discovery = fake_sd
    monkeypatch.setitem(sys.modules, "skill_search", fake_pkg)
    monkeypatch.setitem(sys.modules, "skill_search.skills_discovery", fake_sd)
    monkeypatch.delenv("SKILL_CONCIERGE_SKILLS_FILE", raising=False)
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))   # apply-overrides imports its sibling _keepon
    ao = _load("apply_overrides_t", ROOT / "scripts" / "apply-overrides.py")
    assert ao.discover_skill_names() == ["mine", "pl:y"]


def test_build_triggers_skips_synced(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    bt = _load("build_triggers_t", ROOT / "scripts" / "build_triggers.py")
    page = {"result": {"points": [
        {"payload": {"name": "mine", "description": "d", "scope": "personal"}},
        {"payload": {"name": "anthropic-skills:a", "description": "d", "scope": "claude-synced"}},
        {"payload": {"name": "ext:b", "description": "d", "scope": "catalog:x", "tier": "external"}},
    ], "next_page_offset": None}}
    monkeypatch.setattr(bt, "_post", lambda url, body: page)
    assert [n for n, _d in bt.scroll_all_points()] == ["mine"]
