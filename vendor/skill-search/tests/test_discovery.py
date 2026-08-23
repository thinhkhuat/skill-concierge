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


def test_parse_skill_name_is_dir_when_frontmatter_omits_it(tmp_path):
    d = tmp_path / "mydir"
    d.mkdir()
    (d / "SKILL.md").write_text("---\ndescription: x\n---\nbody")
    assert sd.parse_skill(d / "SKILL.md")["name"] == "mydir"


def test_parse_skill_name_is_dir_even_when_frontmatter_disagrees(tmp_path):
    """The directory name IS the skill's identity — frontmatter `name:` is ignored.

    Regression: discovery used to prefer frontmatter, so a skill shipping a `name:`
    that differed from its directory got its budget override written under a key
    Claude Code never looks up. The override silently never applied and the full
    description stayed resident every turn. Both shapes below occur in the wild:
      - a valid slug that simply differs  (zread-cli ships `name: zread`)
      - a namespaced/legacy id            (ak-plan ships `name: ak:plan`)
    """
    valid_slug = make_skill(tmp_path, "zread", dirname="zread-cli")
    assert sd.parse_skill(valid_slug)["name"] == "zread-cli"

    legacy_ns = make_skill(tmp_path, "ak:plan", dirname="ak-plan")
    assert sd.parse_skill(legacy_ns)["name"] == "ak-plan"

    spaced = make_skill(tmp_path, "Excel Analysis", dirname="excel-analysis")
    assert sd.parse_skill(spaced)["name"] == "excel-analysis"


def test_parse_skill_description_stops_at_hyphenated_keys(tmp_path):
    """A frontmatter value ends at the next key — including a HYPHENATED one.

    Regression: the terminator was `(?=\\n\\w+:|\\Z)`, and `\\w` excludes `-`, so
    `user-invocable:`, `argument-hint:` and `allowed-tools:` did not stop the capture.
    Their raw key/value lines were swallowed into `description`, which then went into
    the skill listing AND into the embedded text — a vector carrying the literal
    "user-invocable: true" is retrieval noise. Hit 168 of 356 personal skills.
    """
    d = tmp_path / "sk"
    d.mkdir()
    (d / "SKILL.md").write_text(
        "---\n"
        "name: sk\n"
        "description: Plan implementations and roadmaps.\n"
        "user-invocable: true\n"
        'argument-hint: "[task] [--fast]"\n'
        "allowed-tools: Read, Write\n"
        "when_to_use: Invoke when work needs phases.\n"
        "category: utilities\n"
        "---\nbody"
    )
    s = sd.parse_skill(d / "SKILL.md")
    assert "user-invocable" not in s["description"]
    assert "argument-hint" not in s["description"]
    assert "allowed-tools" not in s["description"]
    assert "category" not in s["description"]
    assert s["description"].startswith("Plan implementations and roadmaps.")
    # when_to_use is still captured and appended, and likewise stops at the next key
    assert "Invoke when work needs phases." in s["description"]


def test_parse_skill_description_unwraps_yaml_scalars(tmp_path):
    """A frontmatter value is stored as its TEXT, never with its YAML scalar syntax.

    Regression: the value was taken verbatim from the regex, so `description: >-`
    kept the literal ">-" plus each continuation line's newline and indent, and
    `description: "…"` kept its surrounding quotes. That raw text is what gets
    embedded — the retriever scored skills partly on punctuation. Hit 210 of 416
    skills on the maintainer's machine, 25 of them in the always-on set.
    """
    def parse(fm_body):
        d = tmp_path / f"sk{abs(hash(fm_body))}"
        d.mkdir()
        (d / "SKILL.md").write_text(f"---\n{fm_body}---\nbody")
        return sd.parse_skill(d / "SKILL.md")["description"]

    # double-quoted flow scalar
    got = parse('description: "Plan roadmaps."\ncategory: utilities\n')
    assert got == "Plan roadmaps."

    # single-quoted flow scalar
    assert parse("description: 'Generate briefings.'\n") == "Generate briefings."

    # folded block scalar: marker gone, indent gone, newlines folded to spaces
    got = parse("description: >-\n  Force an agent to own\n  a rule-dodge.\nversion: 1\n")
    assert got == "Force an agent to own a rule-dodge."

    # literal block scalar keeps its line breaks but loses marker and indent
    got = parse("description: |\n  line one\n  line two\n")
    assert got == "line one\nline two"

    # plain wrapped scalar folds to one line
    got = parse("description: Plan roadmaps\n  across phases.\n")
    assert got == "Plan roadmaps across phases."

    # when_to_use is unwrapped too, and still appended
    got = parse('description: "Alpha."\nwhen_to_use: "When alpha."\n')
    assert got == "Alpha.  When alpha."

    # a value that merely CONTAINS quotes is left intact
    got = parse('description: Use the "fast" path.\n')
    assert got == 'Use the "fast" path.'


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


def test_parse_skill_next_skills_list(tmp_path):
    """ADR-0029 chain hints: `next-skills:` parses as a comma/space separated
    successor list, an unauthored skill carries an empty list (never a missing
    key — the enforcer's hint filter uses key presence as catalogue membership),
    and the value never leaks into `description` (sidecar-only, never embedded)."""
    d = tmp_path / "chained"
    d.mkdir()
    (d / "SKILL.md").write_text(
        "---\nname: chained\ndescription: d\nnext-skills: plan, cook test\n---\nbody")
    s = sd.parse_skill(d / "SKILL.md")
    assert s["next_skills"] == ["plan", "cook", "test"]
    assert s["description"] == "d"

    d2 = tmp_path / "plain"
    d2.mkdir()
    (d2 / "SKILL.md").write_text("---\nname: plain\ndescription: d\n---\nbody")
    assert sd.parse_skill(d2 / "SKILL.md")["next_skills"] == []


# ── external catalog roots (ADR-0031) ────────────────────────────────────────

def _write_catalog_cfg(tmp_path, cfg):
    p = tmp_path / "catalog-roots.json"
    import json
    p.write_text(json.dumps(cfg))
    return p


def _isolate_installed(tmp_path, monkeypatch, personal=None):
    """No installed skills unless a personal root is given."""
    monkeypatch.setattr(sd, "SKILL_DIRS", [personal] if personal else [tmp_path / "no-skills"])
    monkeypatch.setattr(sd, "PLUGIN_GLOB", str(tmp_path / "none" / "**" / "SKILL.md"))


def test_catalog_roots_validation(tmp_path, monkeypatch):
    root = tmp_path / "cat"
    root.mkdir()
    cfg = _write_catalog_cfg(tmp_path, {
        "_note": "comment ignored",
        "good": {"path": str(root)},
        "short": str(root),                      # bare-string shorthand
        "Bad Alias!": {"path": str(root)},       # invalid chars -> skipped
        "nopath": {"include": ["x"]},            # no path -> skipped
        "gone": {"path": str(tmp_path / "missing")},  # not a dir -> skipped
    })
    monkeypatch.setattr(sd, "CATALOG_ROOTS_PATH", cfg)
    roots = sd.catalog_roots()
    assert set(roots) == {"good", "short"}
    assert roots["good"]["path"] == root


def test_catalog_roots_absent_or_malformed_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(sd, "CATALOG_ROOTS_PATH", tmp_path / "nope.json")
    assert sd.catalog_roots() == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    monkeypatch.setattr(sd, "CATALOG_ROOTS_PATH", bad)
    assert sd.catalog_roots() == {}


def test_catalog_skills_namespaced_scoped_and_globbed(tmp_path, monkeypatch):
    root = tmp_path / "cat"
    make_skill(root, "seo")
    make_skill(root, "junk-skill")
    cfg = _write_catalog_cfg(tmp_path, {"anti": {"path": str(root),
                                                 "exclude": ["junk-*"]}})
    monkeypatch.setattr(sd, "CATALOG_ROOTS_PATH", cfg)
    _isolate_installed(tmp_path, monkeypatch)
    skills = {s["name"]: s for s in sd.discover_skills()}
    assert set(skills) == {"anti:seo"}
    assert skills["anti:seo"]["scope"] == "catalog:anti"


def test_catalog_include_globs(tmp_path, monkeypatch):
    root = tmp_path / "cat"
    make_skill(root, "keep-me")
    make_skill(root, "drop-me")
    cfg = _write_catalog_cfg(tmp_path, {"a": {"path": str(root), "include": ["keep-*"]}})
    monkeypatch.setattr(sd, "CATALOG_ROOTS_PATH", cfg)
    _isolate_installed(tmp_path, monkeypatch)
    assert {s["name"] for s in sd.discover_skills()} == {"a:keep-me"}


def test_catalog_installed_name_wins_and_promoted_twin_suppressed(tmp_path, monkeypatch):
    personal = tmp_path / "personal"
    root = tmp_path / "cat"
    # name collision: alias-namespacing makes it a NON-event (different ids)…
    make_skill(personal, "seo", desc="installed")
    make_skill(root, "seo", desc="external")
    # …promoted twin: personal/promoted is a SYMLINK to the catalog dir -> the
    # catalog copy must be suppressed (realpath dedup), personal copy stays.
    make_skill(root, "promoted", desc="external")
    (personal / "promoted").symlink_to(root / "promoted")
    cfg = _write_catalog_cfg(tmp_path, {"c": {"path": str(root)}})
    monkeypatch.setattr(sd, "CATALOG_ROOTS_PATH", cfg)
    _isolate_installed(tmp_path, monkeypatch, personal=personal)
    skills = {s["name"]: s for s in sd.discover_skills()}
    assert "seo" in skills and skills["seo"]["description"] == "installed"
    assert "c:seo" in skills and skills["c:seo"]["description"] == "external"
    # the installed-side copy owns the skill (its scope is NOT a catalog scope)…
    assert "promoted" in skills
    assert not skills["promoted"]["scope"].startswith("catalog:")
    assert "c:promoted" not in skills          # …and the catalog twin is suppressed


def test_visible_scopes_include_catalogs(tmp_path, monkeypatch):
    root = tmp_path / "cat"
    root.mkdir()
    cfg = _write_catalog_cfg(tmp_path, {"anti": {"path": str(root)}})
    monkeypatch.setattr(sd, "CATALOG_ROOTS_PATH", cfg)
    assert "catalog:anti" in sd.visible_scopes()
    monkeypatch.setattr(sd, "CATALOG_ROOTS_PATH", tmp_path / "nope.json")
    assert not any(s.startswith("catalog:") for s in sd.visible_scopes())
