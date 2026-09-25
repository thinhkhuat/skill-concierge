"""Every harness's offer must drop every skill copy it cannot invoke.

The per-harness foreign-scope tuples in hooks/scripts/enforcer.py are hand-written (they encode
shelf and provider rules), and they drifted: Claude, Codex and OMP all missed the omp-*/zcode-*
scopes, so OMP-managed and ZCode-plugin skills entered those offers as if invocable. This test
closes the class: for every harness, every machine-wide scope the engine can emit is either the
harness's own, on a short named list of scopes that harness reads natively, or foreign. A new
discovery root that forgets the tuples fails here instead of leaking silently.

It also pins the enforcer's stdlib copy of the scope->harness rule to the engine's, and the
project-scope rule (a project row is foreign by path, never by name)."""
import importlib.util
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Scopes a harness invokes natively even though another harness's roots hold the copy. Each
# entry is a documented reading rule, not a convenience: change one only with its evidence.
READS_NATIVELY = {
    "claude": set(),
    # Codex discovery walks the Claude personal root first, so a skill in both personal roots
    # is tagged `personal` while Codex can still invoke it (ADR-0034).
    "codex": {"personal"},
    # Command Code / ZCode / DSH / Cline: `personal` only through a shared-shelf symlink
    # (~/.commandcode/skills or ~/.agents/skills -> ~/.claude/skills; ADR-0057/0042/0059);
    # the tuple adds it when the shelf is absent, so either verdict is legal here.
    "commandcode": {"personal"},
    "zcode": {"personal"},
    # OMP's provider union reads ~/.claude/skills, the Claude plugin registry and ~/.codex/skills
    # (ADR-0039), but not the Codex plugin cache.
    "omp": {"personal", "plugin", "codex-personal"},
    "dsh": {"personal"},
    "cline": {"personal"},
}
OWN_HEAD = {"claude": ("personal", "plugin", "claude-synced")}


@pytest.fixture(scope="module")
def mods(tmp_path_factory):
    saved = dict(os.environ)
    for flag in ("SKILL_CODEX_ROOTS", "SKILL_COMMANDCODE_ROOTS", "SKILL_OMP_ROOTS",
                 "SKILL_ZCODE_ROOTS", "SKILL_DSH_ROOTS", "SKILL_CLINE_ROOTS", "SKILL_SYNCED_ROOTS"):
        os.environ[flag] = "1"
    tmp = tmp_path_factory.mktemp("engine")
    os.environ.pop("SKILL_QDRANT_URL", None)   # the server module opens a store at import: keep it scratch
    os.environ.update({"SKILL_CONCIERGE_HARNESS": "claude", "SKILL_QDRANT_PATH": str(tmp / "q"),
                       "SKILL_META_PATH": str(tmp / "m.json"), "SKILL_VECTOR_SIZE": "384",
                       "SKILL_TRIGGERS": str(tmp / "none.json"),
                       "SKILL_CONCIERGE_CATALOG_ROOTS": str(tmp / "none-cat.json")})
    sys.path.insert(0, str(ROOT / "vendor" / "skill-search"))
    try:
        from skill_search import server, skills_discovery as sd
        spec = importlib.util.spec_from_file_location("enforcer_scopes", ROOT / "hooks" / "scripts" / "enforcer.py")
        enf = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(enf)
        yield sd, enf
        server._qdrant.close()
    finally:
        os.environ.clear()
        os.environ.update(saved)


def _machine_wide(sd):
    return sorted(s for s in sd.visible_scopes() if ":" not in s)


@pytest.mark.parametrize("harness", sorted(READS_NATIVELY))
def test_every_scope_is_own_native_or_foreign(harness, mods, monkeypatch):
    sd, enf = mods
    monkeypatch.setattr(enf, "RUNNING_HARNESS", harness)
    foreign = set(enf._foreign_scopes())
    for scope in _machine_wide(sd):
        own = scope in OWN_HEAD.get(harness, ()) or (harness != "claude" and scope.startswith(harness + "-"))
        if own:
            assert scope not in foreign, f"{harness}: its own scope {scope} is marked foreign"
            continue
        assert scope in foreign or scope in READS_NATIVELY[harness], (
            f"{harness}: scope {scope!r} is neither foreign nor a documented native read — "
            "its skills would enter this harness's offer as if invocable")


def test_scope_harness_matches_the_engine_rule(mods):
    sd, enf = mods
    from skill_search import server
    for scope in sd.visible_scopes():
        if scope.startswith("catalog:"):
            continue
        want = "claude" if scope == "claude-synced" else server._origin(scope)
        assert enf._scope_harness(scope) == want, scope


def test_each_annex_row_names_its_own_harness(mods):
    _sd, enf = mods
    out = enf._ranked_mandate([("inst", "d", 0.9)],
                              foreign=[("pl:x", "dx", 0.5, "omp"), ("y", "dy", 0.45, "zcode")])
    assert "pl:x [omp]" in out and "y [zcode]" in out
    assert "installed under omp/zcode," in out   # the header names only the harnesses shown


def test_project_rows_are_foreign_by_path(mods, tmp_path, monkeypatch):
    _sd, enf = mods
    here, other = tmp_path / "here", tmp_path / "other"
    for d in (here / "sub", other):
        d.mkdir(parents=True)
    monkeypatch.chdir(here)
    row = f"project:{other / '.claude' / 'skills'}"
    assert enf._project_row_verdict(row, "kit-skill") == "other"
    # this project, an ancestor, or a descendant: kept (nested layouts are never guessed at)
    assert enf._project_row_verdict(f"project:{here / '.claude' / 'skills'}", "x") == "this"
    assert enf._project_row_verdict(f"project:{here / 'sub' / '.claude' / 'skills'}", "x") == "this"
    monkeypatch.chdir(here / "sub")
    assert enf._project_row_verdict(f"project:{here / '.claude' / 'skills'}", "x") == "this"
    monkeypatch.chdir(here)
    # a shared kit: this project holds the same skill at the same relative path -> kept
    (here / ".claude" / "skills" / "kit-skill").mkdir(parents=True)
    (here / ".claude" / "skills" / "kit-skill" / "SKILL.md").write_text("---\nname: kit-skill\n---\n")
    assert enf._project_row_verdict(row, "kit-skill") == "this"
    # machine-wide and catalog scopes are not project rows
    assert enf._project_row_verdict("personal", "x") == ""
    assert enf._project_row_verdict("catalog:anti", "x") == ""


def test_same_project_harness_rows_follow_that_harness_personal_verdict(mods, monkeypatch):
    _sd, enf = mods
    monkeypatch.setattr(enf, "RUNNING_HARNESS", "claude")
    monkeypatch.setattr(enf, "FOREIGN_SCOPES", enf._foreign_scopes())
    assert enf._scope_is_foreign("codex-project:/p/.codex/skills")
    assert not enf._scope_is_foreign("project:/p/.claude/skills")
    monkeypatch.setattr(enf, "RUNNING_HARNESS", "omp")
    monkeypatch.setattr(enf, "FOREIGN_SCOPES", enf._foreign_scopes())
    assert not enf._scope_is_foreign("codex-project:/p/.codex/skills")   # OMP reads <cwd>/.codex/skills
    assert enf._scope_is_foreign("zcode-project:/p/.zcode/skills")


def _groups(rows):
    return {"result": {"groups": [{"id": n, "hits": [{"score": s, "payload": {
        "name": n, "description": "d-" + n, "scope": sc}}]} for (n, s, sc) in rows]}}


@pytest.mark.parametrize("harness", sorted(READS_NATIVELY))
def test_retrieve_itself_drops_every_foreign_row(harness, mods, monkeypatch):
    """The tuples are only half the filter: under DSH and Cline the plugin registry is None by
    design, and before v0.49.0 that switched the whole drop off. Run `_retrieve` per harness."""
    _sd, enf = mods
    monkeypatch.setattr(enf, "RUNNING_HARNESS", harness)
    monkeypatch.setattr(enf, "FOREIGN_SCOPES", enf._foreign_scopes())
    monkeypatch.setattr(enf, "INVOCABLE_PLUGIN_IDS", None if harness in ("dsh", "cline") else set())
    monkeypatch.setattr(enf, "_invocable_twin", lambda name: False)
    rows = [(f"only-{sc}", 0.9 - i / 100, sc) for i, sc in enumerate(
        ("omp-managed", "zcode-plugin", "codex-plugin", "dsh-personal", "cline-personal"))]
    other_project = ("elsewhere-kit", 0.95, "project:/nonexistent-sc049/elsewhere/.claude/skills")
    rows += [other_project]
    rows += [(f"filler-{k}", 0.5 - k / 100, "project:" + str(Path.cwd() / ".claude" / "skills"))
             for k in range(enf.TOP_K)]
    monkeypatch.setattr(enf, "_post_json", lambda url, payload, timeout: _groups(rows))
    got = {n for n, _d, _s in enf._retrieve([0.1])}
    for name, _s, scope in rows[:5]:
        own = enf._scope_harness(scope) == harness
        assert (name in got) == own, (harness, scope, sorted(got))
    assert "elsewhere-kit" not in got, f"{harness}: another project's skill reached the offer"
    assert "filler-0" in got, f"{harness}: this project's skill must stay"


def test_main_injects_the_offer_with_per_row_annex_and_logs_xh(mods, monkeypatch, tmp_path):
    """End to end through main(): a shape slip in the annex rows raises inside main(), which
    swallows it and injects NOTHING — so pin that the offer arrives and the ledger row carries xh."""
    import io
    import json
    _sd, enf = mods
    monkeypatch.setattr(enf, "RUNNING_HARNESS", "claude")
    monkeypatch.setattr(enf, "FOREIGN_SCOPES", enf._foreign_scopes())
    monkeypatch.setattr(enf, "INVOCABLE_PLUGIN_IDS", set())
    monkeypatch.setattr(enf, "_embed", lambda text: [0.1])
    installed = [(f"inst-{k}", 0.8 - k / 100, "personal") for k in range(enf.TOP_K)]

    def fake_post(url, payload, timeout):
        must = (payload.get("filter") or {}).get("must") or []
        if any(c.get("key") == "scope" for c in must):          # the other-harness annex
            return _groups([("omp-thing", 0.85, "omp-managed")])   # beats the installed top
        if must:                                                 # external annex
            return {"result": {"groups": []}}
        return _groups(installed)
    monkeypatch.setattr(enf, "_post_json", fake_post)
    injected, logged = [], []
    monkeypatch.setattr(enf, "_inject", injected.append)
    monkeypatch.setattr(enf, "_append_offer", lambda *a, **k: logged.append(k))
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(
        {"hook_event_name": "UserPromptSubmit", "session_id": "t-main",
         "prompt": "design the postgres schema migration for the billing tables"})))
    assert enf.main() == 0
    assert injected and "omp-thing [omp]" in injected[0] and "installed under omp," in injected[0]
    assert logged and logged[-1].get("xh") == [["omp-thing", 0.85]]


def test_a_shared_kit_copy_in_a_parent_dir_keeps_the_row(mods, tmp_path, monkeypatch):
    """One index point per name: the scope names whichever project indexed last. A copy of the
    same skill in the session dir OR a parent (Claude Code loads .claude/skills up to the repo
    root) keeps the row — the live case was `graft`, in two projects, indexed under one."""
    _sd, enf = mods
    repo, other = tmp_path / "repo", tmp_path / "other"
    (repo / "pkg" / "sub").mkdir(parents=True)
    other.mkdir()
    kit = repo / ".claude" / "skills" / "graft"
    kit.mkdir(parents=True)
    (kit / "SKILL.md").write_text("---\nname: graft\n---\n")
    monkeypatch.chdir(repo / "pkg" / "sub")
    assert enf._project_row_verdict(f"project:{other / '.claude' / 'skills'}", "graft") == "this"
    assert enf._project_row_verdict(f"project:{other / '.claude' / 'skills'}", "not-here") == "other"


@pytest.mark.parametrize("harness,foreign", [("claude", True), ("omp", False), ("codex", False),
                                             ("zcode", False), ("dsh", False), ("cline", False)])
def test_project_agents_rows_follow_the_agents_convention(harness, foreign, mods, monkeypatch):
    """<project>/.agents/skills is indexed under zcode-project but read by ZCode, OMP, Codex, DSH
    and Cline — only Claude Code ignores it."""
    _sd, enf = mods
    monkeypatch.setattr(enf, "RUNNING_HARNESS", harness)
    monkeypatch.setattr(enf, "FOREIGN_SCOPES", enf._foreign_scopes())
    assert enf._scope_is_foreign("zcode-project:/p/.agents/skills") is foreign


def test_a_symlinked_skills_dir_is_judged_by_its_project_not_its_target(mods, tmp_path, monkeypatch):
    """The engine records `<project>/.claude/skills` unresolved. Resolving before taking the
    project root follows the link: a skills dir linked outside the project dropped the session's
    OWN rows, and a `../skills` link leaked a project's rows into every sibling project."""
    _sd, enf = mods
    kit = tmp_path / "kit" / "lib" / "skills"
    kit.mkdir(parents=True)
    proj = tmp_path / "proj"
    (proj / ".claude").mkdir(parents=True)
    (proj / ".claude" / "skills").symlink_to(kit)
    monkeypatch.chdir(proj)
    assert enf._project_row_verdict(f"project:{proj / '.claude' / 'skills'}", "foo") == "this"

    env = tmp_path / "env"
    (env / "skills").mkdir(parents=True)
    a, b = env / "a", env / "b"
    for d in (a, b):
        (d / ".claude").mkdir(parents=True)
    (a / ".claude" / "skills").symlink_to(Path("..") / ".." / "skills")
    monkeypatch.chdir(b)
    assert enf._project_row_verdict(f"project:{a / '.claude' / 'skills'}", "a-only") == "other"
