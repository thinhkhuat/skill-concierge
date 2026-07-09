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


# --- body_triggers (Option 4) ---------------------------------------------

def test_body_triggers_from_header_section(tmp_path):
    body = (
        "\n## When to Use\n\n"
        "- Setting up VLANs on a home network for the first time\n"
        "- Isolating IoT devices from trusted devices\n\n"
        "## How It Works\n\nSome unrelated implementation details.\n"
    )
    s = sd.parse_skill(make_skill(tmp_path, "vlan", body=body))
    assert "Setting up VLANs on a home network for the first time" in s["body_triggers"]
    assert "Isolating IoT devices from trusted devices" in s["body_triggers"]
    assert not any("unrelated implementation" in p for p in s["body_triggers"])


def test_body_triggers_inline_label_line(tmp_path):
    body = "\nTriggers: soccer scores, football scores, live match tracker.\n\nMore body text.\n"
    s = sd.parse_skill(make_skill(tmp_path, "soccer", body=body))
    assert any(p.lower().startswith("triggers:") for p in s["body_triggers"])
    assert not any("more body text" in p.lower() for p in s["body_triggers"])


def test_body_triggers_excludes_negative_section(tmp_path):
    # A "Do NOT use when" exclusion block inside a "When to Use" section often
    # names OTHER skills — must not leak into this skill's trigger phrases.
    body = (
        "\n## When to Use\n\nUse this skill when:\n\n"
        "- An educator wants a grading rubric\n\n"
        "Do NOT use when:\n\n"
        "- The user wants the actual assignment -- use assessment-design instead\n\n"
        "## Process\n\nStep one.\n"
    )
    s = sd.parse_skill(make_skill(tmp_path, "rubric", body=body))
    assert any("educator wants a grading rubric" in p.lower() for p in s["body_triggers"])
    assert not any("assessment-design" in p for p in s["body_triggers"])


def test_body_triggers_empty_when_no_labeled_section(tmp_path):
    s = sd.parse_skill(make_skill(tmp_path, "plain", body="\nJust prose, no sections.\n"))
    assert s["body_triggers"] == []


# --- trigger-purity lint (H4, SKILL_TRIGGER_PURITY, ADR-0023) --------------
# One pure trigger-CONDITION + two impure workflow-SUMMARIES (a process-narration
# line and a numbered step) in the same decision section.
_PURITY_BODY = (
    "\n## When to Use\n\n"
    "- Setting up VLANs on a home network for the first time\n"
    "- Runs the plan then cook then test pipeline end to end\n"
    "- 1. Scaffold the project skeleton\n"
)


def test_purity_shadow_keeps_everything_but_logs(tmp_path, monkeypatch, caplog):
    # SHADOW (default): index is byte-identical to today — impure phrases stay,
    # would-drops are only LOGGED as (skill, phrase).
    monkeypatch.setattr(sd, "SKILL_TRIGGER_PURITY", "shadow")
    import logging
    with caplog.at_level(logging.INFO, logger="skill_search"):
        s = sd.parse_skill(make_skill(tmp_path, "net", body=_PURITY_BODY))
    trigs = s["body_triggers"]
    assert "Setting up VLANs on a home network for the first time" in trigs
    assert any("test pipeline" in p for p in trigs)          # impure kept in shadow
    assert any(p.startswith("1. Scaffold") for p in trigs)   # impure kept in shadow
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "would-drop" in logged and "'net'" in logged
    assert "pipeline" in logged and "Scaffold" in logged


def test_purity_active_drops_impure_keeps_pure(tmp_path, monkeypatch):
    monkeypatch.setattr(sd, "SKILL_TRIGGER_PURITY", "active")
    s = sd.parse_skill(make_skill(tmp_path, "net", body=_PURITY_BODY))
    trigs = s["body_triggers"]
    assert "Setting up VLANs on a home network for the first time" in trigs  # pure kept
    assert not any("pipeline" in p for p in trigs)                           # summary dropped
    assert not any(p.startswith("1. Scaffold") for p in trigs)               # step dropped


def test_purity_off_is_byte_identical_to_today(tmp_path, monkeypatch):
    # `off` skips the predicate entirely — same output as pre-H4 code.
    monkeypatch.setattr(sd, "SKILL_TRIGGER_PURITY", "off")
    s = sd.parse_skill(make_skill(tmp_path, "net", body=_PURITY_BODY))
    assert any("pipeline" in p for p in s["body_triggers"])
    assert any(p.startswith("1. Scaffold") for p in s["body_triggers"])


def test_purity_conservative_keeps_generate_a_report_usecase(tmp_path, monkeypatch):
    # A genuine use-CONDITION that merely mentions "report" must NOT be flagged —
    # guards the false-drop risk the ADR calls out. NOTE it survives because the
    # verb ("generate") is mid-line, not the line LEAD — the predicate is `^`-anchored,
    # it does not read intent. A terse verb-LEAD bullet ("generate a report …") WOULD
    # flag; that FP class is the locked v0 heuristic, disclosed in ADR-0023.
    monkeypatch.setattr(sd, "SKILL_TRIGGER_PURITY", "active")
    body = "\n## When to Use\n\n- When the user wants to generate a report from raw metrics\n"
    s = sd.parse_skill(make_skill(tmp_path, "rep", body=body))
    assert any("generate a report" in p.lower() for p in s["body_triggers"])


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


# --- installed + enabled plugin scoping ----------------------------------
# The cache keeps EVERY historical version of every plugin, installed or not.
# Globbing it wholesale indexed skills from ancient versions and from plugins the
# user has disabled — i.e. results Claude Code cannot actually invoke.

def _make_plugin(root: Path, mkt: str, plug: str, ver: str, skill: str, desc: str) -> Path:
    d = root / "plugins" / "cache" / mkt / plug / ver / "skills" / skill
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(f"---\nname: {skill}\ndescription: {desc}\n---\nbody")
    return root / "plugins" / "cache" / mkt / plug / ver


def _plugin_only(monkeypatch, tmp_path):
    monkeypatch.setattr(sd, "SKILL_DIRS", [tmp_path / "empty"])
    monkeypatch.setattr(sd, "PLUGIN_GLOB",
                        str(tmp_path / "plugins" / "cache" / "**" / "skills" / "*" / "SKILL.md"))


def test_only_the_installed_version_is_indexed(tmp_path, monkeypatch):
    """Cache holds every historical version; index only the installed one."""
    _make_plugin(tmp_path, "mkt", "myplugin", "0.3.0", "sk", "ANCIENT")
    cur = _make_plugin(tmp_path, "mkt", "myplugin", "0.18.1", "sk", "CURRENT")
    _plugin_only(monkeypatch, tmp_path)
    monkeypatch.setattr(sd, "_installed_plugin_roots", lambda: {str(cur)})

    found = {s["name"]: s for s in sd.discover_skills()}
    assert "CURRENT" in found["myplugin:sk"]["description"]
    assert "ANCIENT" not in found["myplugin:sk"]["description"]


def test_disabled_plugins_are_not_indexed(tmp_path, monkeypatch):
    """A plugin the user disabled must not be offered — it cannot be invoked."""
    keep = _make_plugin(tmp_path, "mkt", "kept", "1.0.0", "yes", "d")
    _make_plugin(tmp_path, "mkt", "dropped", "1.0.0", "no", "d")
    _plugin_only(monkeypatch, tmp_path)
    monkeypatch.setattr(sd, "_installed_plugin_roots", lambda: {str(keep)})

    names = {s["name"] for s in sd.discover_skills()}
    assert "kept:yes" in names
    assert "dropped:no" not in names


def test_unreadable_manifest_fails_open(tmp_path, monkeypatch):
    """If Claude Code's manifests can't be read, keep every cache path rather than
    silently emptying the index. A retriever with no skills is worse than a stale one."""
    _make_plugin(tmp_path, "mkt", "myplugin", "1.0.0", "sk", "d")
    _plugin_only(monkeypatch, tmp_path)
    monkeypatch.setattr(sd, "_installed_plugin_roots", lambda: None)

    assert {s["name"] for s in sd.discover_skills()} == {"myplugin:sk"}


# --- scope tagging (multi-session shared collection) ----------------------
# Claude Code spawns one MCP server per session, each with its own CWD, and they
# all write ONE Qdrant collection. SKILL_DIRS[1] is CWD-relative, so without an
# explicit owning scope a reindex in session A prunes session B's project points.

def test_discover_tags_scope_for_each_source(tmp_path, monkeypatch):
    personal, project = tmp_path / "personal", tmp_path / "project"
    make_skill(personal, "p_only", desc="personal")
    make_skill(project, "j_only", desc="project")
    monkeypatch.setattr(sd, "PERSONAL_ROOT", personal)
    monkeypatch.setattr(sd, "PROJECT_ROOT", project)
    monkeypatch.setattr(sd, "SKILL_DIRS", [personal, project])
    monkeypatch.setattr(sd, "PLUGIN_GLOB", str(tmp_path / "none" / "**" / "SKILL.md"))

    found = {s["name"]: s for s in sd.discover_skills()}
    assert found["p_only"]["scope"] == "personal"
    assert found["j_only"]["scope"] == f"project:{project}"


def test_plugin_skills_get_plugin_scope(tmp_path, monkeypatch):
    root = _make_plugin(tmp_path, "mkt", "myplugin", "1.0.0", "sk", "d")
    _plugin_only(monkeypatch, tmp_path)
    monkeypatch.setattr(sd, "_installed_plugin_roots", lambda: {str(root)})
    found = {s["name"]: s for s in sd.discover_skills()}
    assert found["myplugin:sk"]["scope"] == "plugin"


def test_visible_scopes_covers_this_session_only(tmp_path, monkeypatch):
    monkeypatch.setattr(sd, "PROJECT_ROOT", tmp_path / "mine")
    vis = sd.visible_scopes()
    assert "personal" in vis and "plugin" in vis
    assert f"project:{tmp_path / 'mine'}" in vis
    assert f"project:{tmp_path / 'theirs'}" not in vis


def test_manifest_key_differs_per_project(tmp_path, monkeypatch):
    """The index manifest records a CWD-scoped disk signature. One shared manifest
    file therefore flip-flops between sessions with different project roots, and
    each reports 'disk changed since last index' forever. Key it per project."""
    monkeypatch.setattr(sd, "PROJECT_ROOT", tmp_path / "a")
    a = sd.manifest_key()
    monkeypatch.setattr(sd, "PROJECT_ROOT", tmp_path / "b")
    b = sd.manifest_key()
    assert a != b
    monkeypatch.setattr(sd, "PROJECT_ROOT", tmp_path / "a")
    assert sd.manifest_key() == a          # stable for the same root


def test_project_glob_is_not_recursive(tmp_path, monkeypatch):
    """REGRESSION GUARD. A `**` here would walk the whole project tree. On this
    machine that means MY-WORKBENCH/CLONED/ — 6,334 SKILL.md across 208 cloned
    repos (8,163 workbench-wide). SKILL_DIRS must stay exactly one level deep."""
    proj = tmp_path / "proj"
    (proj / "deep" / "nested" / "sk").mkdir(parents=True)
    (proj / "deep" / "nested" / "sk" / "SKILL.md").write_text("---\nname: sk\ndescription: d\n---\nb")
    monkeypatch.setattr(sd, "SKILL_DIRS", [proj])
    monkeypatch.setattr(sd, "PLUGIN_GLOB", str(tmp_path / "none" / "**" / "SKILL.md"))
    assert sd.discover_skill_paths() == []
