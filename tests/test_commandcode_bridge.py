"""The Command Code colon-name skill bridge — the fix for "these skills load in Claude Code and
never load in cmd".

Two halves, pinned separately and against each other:
  • `scripts/cmd_skill_bridge.py` materializes a normalized copy of every skill whose frontmatter
    `name` breaks Command Code's rule (a colon, a slash, an underscore, upper case, a name that
    does not match its own directory) into a shelf, rewriting each copy's `name:` and its in-body
    `<prefix>:<slug>` references — without touching a single source file.
  • `adapters/commandcode/skill-bridge.mod.ts` registers that shelf through `cmd.addSkillsPath()`.

The properties that matter are the ones that would make this dangerous rather than helpful: a
source modified in place (`~/.commandcode/skills` is a symlink to `~/.claude/skills`), a copy that
Command Code still cannot load, a reference the copy can no longer resolve, or a silently dropped
collision. Each is a test here.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "scripts" / "cmd_skill_bridge.py"
MOD = ROOT / "adapters" / "commandcode" / "skill-bridge.mod.ts"
MOD_SRC = ROOT / "adapters" / "commandcode" / "skill-concierge.mod.ts"
HARNESS = Path(__file__).with_name("commandcode_mod_harness.mjs")
INSTALLER = ROOT / "adapters" / "commandcode" / "install.sh"
NODE = shutil.which("node")


def _builder():
    """The builder as a module, for the pure name/rewrite functions."""
    spec = importlib.util.spec_from_file_location("cmd_skill_bridge", BUILDER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _skill(dirpath: Path, name, body: str = "body\n", extra: str = "") -> Path:
    dirpath.mkdir(parents=True, exist_ok=True)
    (dirpath / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: d\n{extra}---\n\n# T\n\n{body}", encoding="utf-8")
    return dirpath


@pytest.fixture()
def corpus(tmp_path):
    """A miniature corpus carrying every class the bridge must handle.

    `ak-fix`            a colon name, the common case
    `plug/ak-pptx`      a colon-named skill nested inside a container skill (a skill family)
    `app/templates`     a legal-named module nested inside a skill: payload, NOT a skill to bridge
    `re-claude`         a legal name that does not match its directory
    `defense-in-depth`  a name with spaces and capitals (no colon: the frontmatter rewrite is the
                        only thing that can fix it — the colon pass cannot see it)
    `rg_history`        a name with an underscore, same reason
    `twice`/`twice-b`   two sources normalizing to the same name (the collision case)
    `plain-skill`       already loadable: must be left completely alone
    """
    root = tmp_path / "skills"
    _skill(root / "ak-fix", "ak:fix", "Activate `ak:scout` then /ak:cook. CLI: ak journal create.\n",
           extra="user-invocable: true\n")
    _skill(root / "ak-scout", "ak:scout", "see `ak:fix`\n")
    _skill(root / "ak-cook", "ak:cook", "see ../ak-fix/SKILL.md\n")
    _skill(root / "ak-brainstorm", "ak:brainstorm", "x\n")
    (root / "ak-brainstorm" / "references").mkdir(parents=True)
    (root / "ak-brainstorm" / "references" / "ultra.md").write_text("y\n")
    _skill(root / "plug" / "ak-pptx", "ak:pptx", "x\n")
    (root / "plug" / "ak-pptx" / "refs").mkdir(parents=True)
    # a reference that DOES resolve in the source: three levels up from refs/ is the skills root
    (root / "plug" / "ak-pptx" / "refs" / "a.md").write_text(
        "see ../../../ak-brainstorm/references/ultra.md\n")
    _skill(root / "plug", "plugin:container", "Children: [ak-pptx](ak-pptx/SKILL.md)\n")
    _skill(root / "app" / "templates", "templates", "payload\n")
    _skill(root / "app", "app:builder", "x\n")
    _skill(root / "re-claude", "reclaude", "x\n")
    _skill(root / "defense-in-depth", "Defense-in-Depth Validation", "x\n")
    _skill(root / "rg_history", "rg_history", "x\n")
    _skill(root / "twice", "twice:skill", "x\n")
    _skill(root / "twice-b", "twice:skill", "x\n")
    _skill(root / "plain-skill", "plain-skill", "x\n")
    (root / "plain-skill" / "assets").mkdir(parents=True)
    (root / "plain-skill" / "assets" / "logo.bin").write_bytes(b"\x00\xff\x01")
    return root


def _build(corpus, tmp_path, **kw):
    shelf = tmp_path / "shelf"
    rep = _builder().build([corpus], shelf, quiet=True, **kw)
    return shelf, rep


# ── the name rules ────────────────────────────────────────────────────────────

def test_every_illegal_class_is_named_and_normalizes() -> None:
    """Each rule Command Code states, one input per rule, each reporting ITS reason alone."""
    b = _builder()
    cases = {"ak:fix": "colon", "ak/rest": "slash", "rg_history": "underscore", "a b": "space",
             "Caps": "uppercase", "-lead": "leading-hyphen", "trail-": "trailing-hyphen",
             "a--b": "consecutive-hyphens", "a.b": "illegal-char", "x" * 65: "too-long"}
    for raw, reason in cases.items():
        assert reason in b.illegal_reasons(raw), f"{raw!r} must report {reason}"
        assert not b.is_legal(raw), f"{raw!r} must be rejected by Command Code's rule"
        assert b.is_legal(b.normalize(raw)), f"{b.normalize(raw)!r} (from {raw!r}) must be legal"


def test_normalize_maps_the_real_corpus_names() -> None:
    b = _builder()
    assert b.normalize("ak:fix") == "ak-fix"
    assert b.normalize("ak:ui-ux-pro-max") == "ak-ui-ux-pro-max"
    assert b.normalize("ck:copywriting") == "ck-copywriting"
    assert b.normalize("microsoft-foundry:resource/create") == "microsoft-foundry-resource-create"
    long = b.normalize("ak:" + "x" * 80)
    assert len(long) <= 64 and not long.endswith("-")
    # a name with nothing legal in it normalizes to nothing — the caller must skip, not invent
    assert b.normalize(":::") == "" and not b.is_legal("")


def test_frontmatter_rewrite_touches_only_the_top_level_name() -> None:
    b = _builder()
    fm = "---\nname: ak:fix\ndescription: x\nmetadata:\n  name: keep\n---\n\n# body\n"
    out = b.rewrite_frontmatter_name(fm, "ak-fix")
    assert "name: ak-fix\n" in out and out.count("name: ak-fix") == 1
    assert "  name: keep" in out, "an indented (nested) name: must not be rewritten"
    assert out.endswith("# body\n")
    assert b.rewrite_frontmatter_name("# no frontmatter\n", "x") == "# no frontmatter\n"


def test_colon_references_are_rewritten_but_not_urls_clocks_or_placeholders() -> None:
    b = _builder()
    body = ("Activate `ak:scout` then /ak:cook. See https://x/ak:no and 10:30. "
            "Template: ak:<slug>. File ak:docs.md ends. Word xak:fix stays.")
    got = b.rewrite_colons(body, {"ak"})
    assert "`ak-scout`" in got, "a backticked skill reference must be normalized"
    assert "/ak-cook." in got, "the slash-invocation form (/ak:cook) must be normalized too"
    assert "https://x/ak:no" in got, "a URL must never be rewritten"
    assert "10:30" in got, "a clock time must never be rewritten"
    assert "ak:<slug>" in got and "ak-docs.md" in got and "xak:fix" in got
    assert b.rewrite_colons(body, set()) == body, "no prefixes -> no rewriting at all"
    # an unknown prefix stays, a known one is rewritten whatever its case
    assert "ck:CI" in b.rewrite_colons("x ck:CI y", {"ak"})
    assert b.rewrite_colons("ck:CI", {"ck"}) == "ck-ci"


# ── the shelf ─────────────────────────────────────────────────────────────────

def test_each_unloadable_skill_becomes_a_copy_command_code_can_load(corpus, tmp_path) -> None:
    shelf, rep = _build(corpus, tmp_path)
    b = _builder()
    by_dash = {e["dash"]: e for e in rep["entries"]}
    # `ak-fix` and `ak-pptx` are fixed by the colon pass too; `defense-in-depth-validation` and
    # `rg-history` have no colon at all, so ONLY the frontmatter rewrite can make them legal —
    # they are what stops a broken frontmatter rewrite from hiding behind the colon pass.
    for dash in ("ak-fix", "ak-scout", "ak-cook", "ak-pptx", "reclaude", "twice-skill",
                 "defense-in-depth-validation", "rg-history"):
        assert dash in by_dash, f"{dash} must be bridged"
        skill_md = shelf / dash / "SKILL.md"
        declared = b.frontmatter_name(skill_md.read_text(encoding="utf-8"))
        assert b.is_legal(dash), f"{dash} must be a legal Command Code name"
        assert declared == dash, f"{dash}/SKILL.md must declare `name: {dash}` (dir must match name)"
        assert skill_md.parent.name == dash
    # the two reasons are distinguished, so a report can say WHY each skill was bridged
    assert by_dash["ak-fix"]["reason"] == "colon,illegal-char"
    assert by_dash["reclaude"]["reason"] == "dir-mismatch"
    assert by_dash["defense-in-depth-validation"]["reason"] == "space,uppercase,illegal-char"
    assert by_dash["rg-history"]["reason"] == "underscore,illegal-char"


def test_a_copy_keeps_its_body_but_points_at_the_new_names(corpus, tmp_path) -> None:
    shelf, _ = _build(corpus, tmp_path)
    body = (shelf / "ak-fix" / "SKILL.md").read_text(encoding="utf-8")
    assert "`ak-scout`" in body and "/ak-cook." in body
    assert "ak:scout" not in body and "/ak:cook" not in body
    assert "ak journal create" in body, "the CLI space form is not a skill reference"
    assert "user-invocable: true" in body, "other frontmatter keys must survive verbatim"


def test_no_source_file_is_ever_modified(corpus, tmp_path) -> None:
    before = {p: p.read_bytes() for p in sorted(corpus.rglob("*")) if p.is_file()}
    _build(corpus, tmp_path)
    after = {p: p.read_bytes() for p in sorted(corpus.rglob("*")) if p.is_file()}
    assert before == after, "the bridge must copy, never edit (the shelf machine shares ~/.claude)"


def test_non_text_payload_is_copied_byte_exact(corpus, tmp_path) -> None:
    shelf, _ = _build(corpus, tmp_path)
    # plain-skill is already loadable, so it must NOT be copied; use a bridged skill's payload
    _skill(corpus / "ak-bin", "ak:bin", "x\n")
    (corpus / "ak-bin" / "assets").mkdir(parents=True)
    (corpus / "ak-bin" / "assets" / "logo.bin").write_bytes(b"\x00\xff\x01\xfe")
    shelf, _ = _build(corpus, tmp_path, force=True)
    assert (shelf / "ak-bin" / "assets" / "logo.bin").read_bytes() == b"\x00\xff\x01\xfe"


def test_a_legal_named_module_inside_a_skill_stays_payload(corpus, tmp_path) -> None:
    """`app/templates` holds a SKILL.md but no bridge is needed, so it must not become a top-level
    skill — inventing ten spurious skills is worse than bridging none."""
    shelf, rep = _build(corpus, tmp_path)
    assert "templates" not in {e["dash"] for e in rep["entries"]}
    assert not (shelf / "templates").exists()
    # ... and it must still be there for its parent, as the parent's own file layout expects
    assert (shelf / "app-builder" / "templates" / "SKILL.md").is_file()


def test_a_skill_family_child_is_bridged_and_its_parent_still_links_to_it(corpus, tmp_path) -> None:
    shelf, _ = _build(corpus, tmp_path)
    assert (shelf / "ak-pptx" / "SKILL.md").is_file(), "the nested ak:pptx must be bridged"
    # the container's own relative link to its child must still resolve inside the copy
    parent = (shelf / "plugin-container" / "SKILL.md").read_text(encoding="utf-8")
    assert "[ak-pptx](ak-pptx/SKILL.md)" in parent
    assert (shelf / "plugin-container" / "ak-pptx" / "SKILL.md").is_file()


def test_a_nested_skill_reference_is_re_anchored_for_its_new_depth(corpus, tmp_path) -> None:
    """`ak-pptx` moved from `plug/ak-pptx/` to the shelf's top level, one level shallower, so a
    reference that climbed three levels must now climb two — and must still resolve."""
    shelf, _ = _build(corpus, tmp_path)
    text = (shelf / "ak-pptx" / "refs" / "a.md").read_text(encoding="utf-8").strip()
    ref = text.split("see ", 1)[1]
    assert ref == "../../ak-brainstorm/references/ultra.md", (
        f"the reference must lose exactly one `../` for the flattened copy, got {ref!r}")
    assert os.path.exists(os.path.normpath(
        os.path.join(str(shelf / "ak-pptx" / "refs"), ref))), "and must resolve in the shelf"


def test_a_collision_is_reported_and_the_first_source_wins(corpus, tmp_path) -> None:
    shelf, rep = _build(corpus, tmp_path)
    assert [c["dash"] for c in rep["collisions"]] == ["twice-skill"]
    col = rep["collisions"][0]
    assert col["winner"].endswith("twice") and col["loser"].endswith("twice-b")
    assert "twice-b" in col["loser"]
    assert any("twice-skill" in w for w in rep["warnings"]), "a collision must never be silent"
    assert (shelf / "twice-skill" / "SKILL.md").is_file()


def test_an_already_loadable_skill_is_left_completely_alone(corpus, tmp_path) -> None:
    shelf, rep = _build(corpus, tmp_path)
    assert "plain-skill" not in {e["dash"] for e in rep["entries"]}
    assert not (shelf / "plain-skill").exists()


# ── verify / clean / incremental ──────────────────────────────────────────────

def test_verify_passes_on_a_fresh_shelf_and_names_a_tampered_copy(corpus, tmp_path) -> None:
    b = _builder()
    shelf, _ = _build(corpus, tmp_path)
    assert b.verify(shelf)["ok"] is True, b.verify(shelf)["problems"]
    # a copy that declares something other than its directory is exactly what cmd SKIPS
    (shelf / "ak-fix" / "SKILL.md").write_text(
        "---\nname: ak:fix\ndescription: d\n---\n\nx\n", encoding="utf-8")
    rep = b.verify(shelf)
    assert rep["ok"] is False
    assert any("ak-fix" in p and "declares" in p for p in rep["problems"]), rep["problems"]


def test_verify_reports_a_source_that_changed_since_the_build(corpus, tmp_path) -> None:
    b = _builder()
    shelf, _ = _build(corpus, tmp_path)
    (corpus / "ak-fix" / "SKILL.md").write_text("---\nname: ak:fix\ndescription: edited\n---\n\nx\n")
    rep = b.verify(shelf)
    assert rep["ok"] is False
    assert any("CHANGED" in p for p in rep["problems"]), rep["problems"]


def test_second_build_is_a_no_op_and_a_changed_source_rebuilds(corpus, tmp_path) -> None:
    shelf, first = _build(corpus, tmp_path)
    assert first["status"] == "built"
    marker = shelf / "ak-fix" / "SKILL.md"
    marker.write_text("---\nname: ak-fix\ndescription: tampered\n---\n\nx\n")
    again = _build(corpus, tmp_path)[1]
    assert again["status"] == "unchanged", "an unchanged corpus must not rewrite the shelf"
    assert "tampered" in marker.read_text(encoding="utf-8"), "unchanged really means untouched"
    # a changed source invalidates the fingerprint and rebuilds
    _skill(corpus / "ak-new", "ak:new", "x\n")
    third = _build(corpus, tmp_path)[1]
    assert third["status"] == "built" and (shelf / "ak-new" / "SKILL.md").is_file()


def test_clean_removes_only_what_the_bridge_made(corpus, tmp_path) -> None:
    b = _builder()
    shelf, _ = _build(corpus, tmp_path)
    stranger = shelf / "someone-elses-skill"
    stranger.mkdir()
    (stranger / "SKILL.md").write_text("---\nname: someone-elses-skill\n---\n\nx\n")
    removed = b.clean(shelf)["removed"]
    assert "ak-fix" in removed and len(removed) == len(set(removed))
    assert not (shelf / "ak-fix").exists()
    assert stranger.is_dir(), "a directory the manifest does not name must never be deleted"
    assert not (shelf / "_bridge.json").exists()


def test_clean_refuses_a_manifest_entry_that_points_outside_the_shelf(corpus, tmp_path) -> None:
    """`clean` deletes whole directories, so a tampered or hand-edited manifest must not be able to
    aim it outside the shelf."""
    b = _builder()
    shelf = tmp_path / "shelf"
    _build(corpus, tmp_path)
    outside = tmp_path / "victim"
    outside.mkdir()
    (outside / "keep.txt").write_text("precious\n")
    man = json.loads((shelf / "_bridge.json").read_text(encoding="utf-8"))
    man["entries"].append({"dash": "../victim", "raw": "x", "source": str(corpus)})
    man["entries"].append({"dash": str(outside), "raw": "x", "source": str(corpus)})
    (shelf / "_bridge.json").write_text(json.dumps(man), encoding="utf-8")
    b.clean(shelf)
    assert (outside / "keep.txt").read_text(encoding="utf-8") == "precious\n", \
        "an absolute or relative path in the manifest must never be deleted"


def test_list_is_read_only(corpus, tmp_path, capsys) -> None:
    shelf = tmp_path / "shelf"
    argv = ["list", "--root", str(corpus), "--shelf", str(shelf)]
    assert _builder().main(argv) == 0
    out = capsys.readouterr().out
    assert "ak-fix" in out
    assert not shelf.exists(), "`list` must answer without writing a shelf"


def test_a_reference_that_would_break_in_the_copy_is_reported(corpus, tmp_path) -> None:
    """A copy must not silently lose a working reference. A bridged skill pointing at a sibling
    skill that needs no bridge resolves in the source and cannot in the shelf — the build says so
    (twice over: the rewrite pass and the before/after link check) instead of hiding it."""
    _skill(corpus / "legal-helper", "legal-helper", "x\n")
    (corpus / "legal-helper" / "notes.md").write_text("n\n")
    _skill(corpus / "ak-escape", "ak:escape", "see ../legal-helper/notes.md\n")
    rep = _build(corpus, tmp_path)[1]
    assert any("ak-escape" in w and "legal-helper/notes.md" in w for w in rep["warnings"]), \
        rep["warnings"]
    assert any("resolved in the source but not in the copy" in w for w in rep["warnings"]), \
        "the before/after link check must name the regression, not only the rewrite pass"


def test_a_reference_that_leaves_the_corpus_is_kept_by_absolute_path(corpus, tmp_path) -> None:
    """A skill citing a file ABOVE the corpus root (`~/.claude/rules/…` via `../../`) resolves where it
    lives and cannot survive a copy at a different depth. The bridge rewrites such a reference to the
    absolute path it resolved to — a warning would leave the copy broken, and moving the shelf under
    `~/.claude/` would put Command Code's derived data in Claude Code's config tree."""
    (tmp_path / "rules").mkdir()
    (tmp_path / "rules" / "primary-workflow.md").write_text("rules\n")
    missing = "../../../../rules/nowhere.md"           # escapes the corpus AND resolves nowhere
    _skill(corpus / "ak-cites", "ak:cites",
           f"See `../../rules/primary-workflow.md`.\nSee `{missing}`.\n")
    _shelf, rep = _build(corpus, tmp_path)
    text = (tmp_path / "shelf" / "ak-cites" / "SKILL.md").read_text()
    assert os.path.normpath(str(tmp_path / "rules" / "primary-workflow.md")) in text, \
        "the reference that leaves the corpus is absolute in the copy"
    assert missing in text, "a reference that never resolved is left exactly as written"
    assert not any("resolved in the source but not in the copy" in w for w in rep["warnings"]), \
        rep["warnings"]


def test_a_file_with_one_resolving_reference_still_reports_the_broken_one(corpus, tmp_path) -> None:
    """The before/after check compares reference by reference. A file carrying BOTH a reference that
    still resolves and one that does not must report the broken one — an early version passed the
    whole file as soon as any single reference resolved, which hid the `ak-agentkit` case."""
    _skill(corpus / "legal-helper", "legal-helper", "x\n")
    (corpus / "legal-helper" / "notes.md").write_text("n\n")
    _skill(corpus / "ak-mixed", "ak:mixed", "one: ./references/own.md\ntwo: ../legal-helper/notes.md\n")
    (corpus / "ak-mixed" / "references").mkdir()
    (corpus / "ak-mixed" / "references" / "own.md").write_text("own\n")
    _shelf, rep = _build(corpus, tmp_path)
    assert any("ak-mixed" in w and "legal-helper/notes.md" in w
               and "resolved in the source but not in the copy" in w for w in rep["warnings"]), \
        rep["warnings"]


# ── the mod half ──────────────────────────────────────────────────────────────

def _node_imports_ts() -> bool:
    if NODE is None:
        return False
    out = subprocess.run([NODE, "--version"], capture_output=True, text=True).stdout.strip().lstrip("v")
    return tuple(int(x) for x in out.split(".")[:2]) >= (22, 6)


def _drive_mod(mod: Path, env: dict) -> tuple:
    r = subprocess.run([NODE, str(HARNESS), str(mod)], input=json.dumps({"calls": []}),
                       capture_output=True, text=True, timeout=60, env={**os.environ, **env})
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout), r.stderr


needs_node = pytest.mark.skipif(not _node_imports_ts(),
                                reason="needs node 22.6+ (the mod is imported as .ts)")


@needs_node
def test_mod_registers_the_shelf_it_is_pointed_at(tmp_path) -> None:
    shelf = tmp_path / "shelf"
    shelf.mkdir()
    out, err = _drive_mod(MOD, {"SKILL_CONCIERGE_BRIDGE_SHELF": str(shelf)})
    assert f"SKILLS_PATH: {shelf}" in err, err
    assert "NOTICE:" not in err, "a present shelf must register silently"


@needs_node
def test_mod_says_so_once_when_the_shelf_is_missing_instead_of_failing(tmp_path) -> None:
    out, err = _drive_mod(MOD, {"SKILL_CONCIERGE_BRIDGE_SHELF": str(tmp_path / "nope")})
    assert "NOTICE: skill-bridge" in err, err
    assert "SKILLS_PATH:" not in err, "there is nothing to register"
    assert out == [], "the factory must not throw — a missing shelf is not a broken session"


def test_builder_and_mod_agree_on_the_default_shelf_path() -> None:
    """The two halves must not drift: the builder writes where the mod looks."""
    b = _builder()
    ts = MOD.read_text(encoding="utf-8")
    # builder: SHELF_DEFAULT = Path.home() / ".commandcode" / "skill-concierge-bridge"
    assert b.SHELF_DEFAULT.parts[-2:] == (".commandcode", "skill-concierge-bridge")
    assert '".commandcode"' in ts and '"skill-concierge-bridge"' in ts
    assert b.SHELF_ENV in ts, "the mod must honor the same env override as the builder"


# ── the installer ─────────────────────────────────────────────────────────────

def test_installer_builds_the_shelf_installs_the_mod_and_verifies_both() -> None:
    src = INSTALLER.read_text(encoding="utf-8")
    assert '"cmd_skill_bridge.py"' in src and '"build", "--quiet"' in src, \
        "the installer must build the shelf through the builder's own CLI"
    assert '"verify"' in src, "and verify it before finishing"
    assert "skill-bridge.mod.ts" in src and "bridge_mod_dst" in src, "and install the mod"
    assert "auto_bridge.py" in src, "and wire the SessionStart regen"
    # the regen hook must be installed AND de-duplicated on a re-run: the script list, the dedupe
    # filter, and the re-add
    assert src.count("auto_bridge.py") >= 3, "hook script list, dedupe filter and re-add"
    # A root whose mod cannot reach its hooks must be refused with NOTHING written — so the
    # checkout check has to come before the shelf build is CALLED, which writes.
    assert (src.index("no hooks/scripts/enforcer.py under")
            < src.index("bridge_note = build_bridge_shelf(root)")), \
        "the checkout must be validated before the shelf is built"


def test_bridge_selftest_passes() -> None:
    r = subprocess.run([sys.executable, str(BUILDER), "--selftest"],
                       capture_output=True, text=True, timeout=120, cwd=ROOT)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "selftest OK" in r.stdout
