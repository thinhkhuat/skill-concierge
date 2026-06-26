"""Unit tests for skills_discovery — the single source of truth that BOTH the
indexer and the override generator depend on. Bugs here desync the two halves,
so this is the most important thing to pin."""

from pathlib import Path

from skill_search import skills_discovery as sd


def make_skill(root: Path, name: str, desc="d", body="b", when=None, dirname=None) -> Path:
    d = root / (dirname or name)
    d.mkdir(parents=True, exist_ok=True)
    fm = f"---\nname: {name}\ndescription: {desc}\n"
    if when:
        fm += f"when_to_use: {when}\n"
    fm += "---\n" + body
    path = d / "SKILL.md"
    path.write_text(fm)
    return path


# --- parse_skill ---------------------------------------------------------

def test_parse_skill_basic(tmp_path):
    s = sd.parse_skill(make_skill(tmp_path, "alpha", desc="does alpha",
                                  when="when you need alpha", body="BODY"))
    assert s["name"] == "alpha"
    assert "does alpha" in s["description"]
    assert "when you need alpha" in s["description"]   # when_to_use is appended
    assert s["body"] == "BODY"


def test_parse_skill_name_falls_back_to_dir(tmp_path):
    d = tmp_path / "mydir"
    d.mkdir()
    (d / "SKILL.md").write_text("---\ndescription: x\n---\nbody")
    assert sd.parse_skill(d / "SKILL.md")["name"] == "mydir"


def test_parse_skill_no_frontmatter_returns_none(tmp_path):
    p = tmp_path / "f" / "SKILL.md"
    p.parent.mkdir()
    p.write_text("no frontmatter here")
    assert sd.parse_skill(p) is None


def test_body_is_capped(tmp_path):
    s = sd.parse_skill(make_skill(tmp_path, "big", body="x" * 5000))
    assert len(s["body"]) == 4000


# --- _namespaced_name (plugin id reconstruction) -------------------------

def test_namespaced_name_cache_layout():
    p = Path("/h/.claude/plugins/cache/mkt/myplugin/1.2.3/skills/sk/SKILL.md")
    assert sd._namespaced_name(p, "sk") == "myplugin:sk"


def test_namespaced_name_non_plugin_unchanged(tmp_path):
    assert sd._namespaced_name(tmp_path / "sk" / "SKILL.md", "sk") == "sk"


def test_namespaced_name_marketplaces_not_namespaced():
    # marketplaces/ is catalog source, not an installed plugin -> left bare
    # (and discovery scopes the glob to cache/ so these never get indexed).
    p = Path("/h/.claude/plugins/marketplaces/somemkt/skills/sk/SKILL.md")
    assert sd._namespaced_name(p, "sk") == "sk"


# --- discover_skills (dedup + scoping) -----------------------------------

def test_discover_dedup_precedence_personal_wins(tmp_path, monkeypatch):
    personal, project = tmp_path / "personal", tmp_path / "project"
    make_skill(personal, "dup", desc="PERSONAL")
    make_skill(project, "dup", desc="PROJECT")
    monkeypatch.setattr(sd, "SKILL_DIRS", [personal, project])
    monkeypatch.setattr(sd, "PLUGIN_GLOB", str(tmp_path / "none" / "**" / "SKILL.md"))
    found = {s["name"]: s for s in sd.discover_skills()}
    assert found["dup"]["description"] == "PERSONAL"   # first writer wins


def test_discover_includes_and_namespaces_plugin(tmp_path, monkeypatch):
    plug = tmp_path / "plugins" / "cache" / "mkt" / "myplugin" / "1.0.0" / "skills" / "sk"
    plug.mkdir(parents=True)
    (plug / "SKILL.md").write_text("---\nname: sk\ndescription: d\n---\nb")
    monkeypatch.setattr(sd, "SKILL_DIRS", [tmp_path / "empty"])
    monkeypatch.setattr(sd, "PLUGIN_GLOB",
                        str(tmp_path / "plugins" / "cache" / "**" / "skills" / "*" / "SKILL.md"))
    names = {s["name"] for s in sd.discover_skills()}
    assert "myplugin:sk" in names
