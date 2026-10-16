"""The Command Code agent bridge — the fix for "this delegate loads in Claude Code and starts with
almost no tools in cmd".

The corpus is shared on purpose: `~/.commandcode/agents` starts as a symlink to `~/.claude/agents`,
so the
same agent file is read by every harness, and its `tools:` line is written the Claude Code way
(`Read`, `Write`, `Bash`, `TodoWrite`, `Task(Explore)`). Command Code resolves those names against
its OWN tool ids and drops every one it does not know, in silence — a `fullstack-developer` delegate
that must write files and run builds launches able to do neither.

`scripts/cmd_agent_bridge.py` mirrors the corpus into the directory Command Code scans, translating
`tools:`, `model:` and the delegation idioms on the copy. `hooks/scripts/auto_agent_bridge.py` keeps
that mirror current at session start, and `adapters/commandcode/install.sh` swaps the symlink for the
bridge-owned directory.

The properties that matter are the ones that would make this dangerous rather than helpful: a source
modified in place (every harness reads it), a mirror written through the symlink into the Claude
corpus, a Claude tool name that survives untranslated (it would be dropped anyway, silently), a
mirror file deleted that the bridge did not write, or a body rewritten into prose the author never
wrote. Each is a test here.
"""
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "scripts" / "cmd_agent_bridge.py"
HOOK = ROOT / "hooks" / "scripts" / "auto_agent_bridge.py"
INSTALLER = ROOT / "adapters" / "commandcode" / "install.sh"
SMOKE = ROOT / "scripts" / "smoke.py"


def _builder():
    """The builder as a module, for its pure translation functions."""
    spec = importlib.util.spec_from_file_location("cmd_agent_bridge", BUILDER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _agent(dirpath: Path, name: str, tools: str = "Read, Write, Bash", body: str = "Do the work.\n",
           extra: str = "") -> Path:
    dirpath.mkdir(parents=True, exist_ok=True)
    tools_line = f"tools: {tools}\n" if tools is not None else ""
    (dirpath / f"{name}.md").write_text(
        f"---\nname: {name}\ndescription: d\n{tools_line}{extra}---\n\n{body}", encoding="utf-8")
    return dirpath / f"{name}.md"


@pytest.fixture()
def corpus(tmp_path):
    """A miniature corpus carrying every class the bridge must handle.

    `worker`      the common case: Claude tool ids, one dropped spawn, one body idiom
    `notools`     no `tools:` line at all (Claude Code inherits every tool, cmd grants none)
    `denier`      a `disallowedTools:` list to translate alongside `tools:`
    `pinned`      a `model:` Claude alias, which is not a Command Code id
    `explore`     a reserved agent id Command Code ignores
    """
    src = tmp_path / "claude-agents"
    _agent(src, "worker", "Read, Write, Edit, MultiEdit, Bash, Glob, Grep, TodoWrite, SendMessage, "
                          "Task(Explore)",
           body="Delegate broad scans with `Task(Explore)`, then TaskUpdate(status: \"completed\").\n")
    _agent(src, "notools", None, body="Read the draft.\n")
    _agent(src, "denier", "Read, Write, Bash, WebFetch, SendMessage", extra="disallowedTools: Bash\n")
    _agent(src, "pinned", "Read", extra="model: sonnet\n")
    _agent(src, "explore", "Read, Grep, Glob")
    (src / ".DS_Store").write_text("junk")
    return src


def _run(*args, cwd=None):
    return subprocess.run([sys.executable, str(BUILDER), *args], capture_output=True, text=True,
                          timeout=120, cwd=cwd or ROOT)


# ── the translation table ─────────────────────────────────────────────────────

# Every Claude Code tool id the shared corpus actually uses. A name that maps to nothing would be
# silently dropped by Command Code inside every delegate that declares it.
REAL_CORPUS_TOOLS = ("Read", "Bash", "Glob", "Grep", "Write", "Edit", "MultiEdit", "NotebookEdit",
                     "WebFetch", "WebSearch", "TaskCreate", "TaskGet", "TaskUpdate", "TaskList",
                     "SendMessage", "BashOutput", "KillBash", "LS", "TodoWrite",
                     "ListMcpResourcesTool", "ReadMcpResourceTool")


@pytest.mark.parametrize("token", REAL_CORPUS_TOOLS)
def test_every_claude_tool_in_the_corpus_is_accounted_for(token) -> None:
    """Either it translates, or it is a deliberate drop with a stated reason — never a surprise."""
    assert token in _builder().TOOL_MAP, f"{token} has no mapping and would vanish silently"


def test_tool_ids_from_the_real_corpus_translate_to_command_code_ids() -> None:
    mod = _builder()
    mapped, dropped, _notes = mod.translate_tools(list(REAL_CORPUS_TOOLS))
    assert mapped == ["read_file", "shell_command", "glob", "grep", "write_file", "edit_file",
                      "web_fetch", "web_search", "task_create", "task_get", "task_update",
                      "task_list", "shell_output", "kill_shell", "read_directory", "todo_write"]
    # a spawn and the peer-messaging / MCP-resource tools have no Command Code counterpart
    assert {t for t, _w in dropped} == {"SendMessage", "ListMcpResourcesTool", "ReadMcpResourceTool"}
    assert all(why for _t, why in dropped), "a drop must say why"


def test_duplicate_targets_collapse_and_wildcard_and_mcp_pass_through() -> None:
    mod = _builder()
    mapped, dropped, _ = mod.translate_tools(["Write", "Edit", "MultiEdit", "mcp__jira__get_issue"])
    assert mapped == ["write_file", "edit_file", "mcp__jira__get_issue"], "Edit and MultiEdit collapse"
    assert dropped == []
    assert mod.translate_tools(["*"]) == (["*"], [], [])


def test_an_unknown_id_is_dropped_and_named_never_invented() -> None:
    mod = _builder()
    mapped, dropped, _ = mod.translate_tools(["TotallyMadeUpTool"])
    assert mapped == []
    assert dropped == [("TotallyMadeUpTool", "not a Command Code tool id and not an MCP name")]


# ── frontmatter rewrites ──────────────────────────────────────────────────────

def test_only_the_named_key_changes() -> None:
    mod = _builder()
    text = ("---\nname: worker\ndescription: 'quoted: stays'\ntools: Read, Grep\n"
            "model: inherit\n---\n\nUse `Read` on the file.\n")
    out = mod.rewrite_key(text, "tools", "read_file, grep")
    assert "tools: read_file, grep\n" in out
    assert "description: 'quoted: stays'" in out and "model: inherit" in out
    assert out.endswith("Use `Read` on the file.\n"), "the body is not the frontmatter's business"


def test_a_block_list_tools_value_collapses_to_one_line() -> None:
    mod = _builder()
    text = "---\nname: w\ntools:\n  - Read\n  - Write\nmodel: inherit\n---\nbody\n"
    assert mod.parse_tools(mod.fm_value(text, "tools")) == ["Read", "Write"]
    out = mod.rewrite_key(text, "tools", "read_file, write_file")
    assert "tools: read_file, write_file\n" in out and "- Read" not in out
    assert out.count("tools:") == 1 and "model: inherit" in out


def test_a_folded_description_is_never_split_by_an_added_tool_key(tmp_path) -> None:
    """The live incident. agent-validator.md, vn-author-agent.md and vn-editor-agent.md open
    `description` as a folded multi-line scalar (`description: >`); the indented continuation
    lines belong to that scalar, so a `tools: "*"` line inserted between the opener and them
    becomes a second mapping at the wrong indent — YAML the harness refuses, `bad indentation of
    a mapping entry (4:3)`, printed for every session. An added key may only land where a
    mapping key is legal: after the last complete entry of the block. The fold is built from a
    dedicated source, because only that shape reproduces the split."""
    mod = _builder()
    src = tmp_path / "folded"
    src.mkdir()
    (src / "folded.md").write_text(
        "---\nname: folded\n"
        "description: >\n"
        "  Rigorous validation agent. Use proactively for review.\n"
        "model: inherit\n"
        "---\n\nValidate the plan.\n", encoding="utf-8")
    dest = tmp_path / "mirror"
    mod.build([src], dest, quiet=True)
    mirrored = (dest / "folded.md").read_text(encoding="utf-8")
    start, close = mod.frontmatter_bounds(mirrored)
    lines = mirrored.split("\n")
    col0 = [i for i in range(start, close) if re.match(r"^\S", lines[i]) and ":" in lines[i]]
    assert col0, "the generated frontmatter must still carry mapping keys"
    assert lines[col0[-1]].startswith("tools:"), (
        f"an added key closes the frontmatter block: found {lines[col0[-1]]!r} as the last entry")
    desc = next(i for i in col0 if lines[i].startswith("description:"))
    assert lines[desc].rstrip().endswith(">") and lines[desc + 1].startswith("  "), (
        "a folded scalar's continuation follows its opener directly, never another key")
    block = "\n".join(lines[start:close])
    try:
        import yaml
    except ImportError:  # pragma: no cover - the structural assertion above already bites
        yaml = None
    if yaml is not None:
        parsed = yaml.safe_load(block)
        assert parsed["description"] == "Rigorous validation agent. Use proactively for review.\n"
        assert parsed["tools"] == "*", "the omission still says * out loud"
    assert mod.verify(dest)["ok"], "the mirror exactly as emitted must verify clean"


def test_an_omitted_tools_key_is_written_out_and_an_existing_one_is_never_duplicated() -> None:
    """Claude Code reads a missing `tools:` as "inherit every tool"; Command Code reads it as "no
    tools at all", so the omission itself is the defect and the mirror has to say `*`."""
    mod = _builder()
    text = "---\nname: n\ndescription: d\nmodel: inherit\n---\nbody\n"
    out = mod.add_key(text, "tools", '"*"')
    # appended, never position-shopped: a key line may not interrupt a block scalar
    assert out.split("\n")[:5] == ['---', "name: n", "description: d", "model: inherit",
                                   'tools: "*"']
    existing = "---\nname: n\ntools: Read\n---\nbody\n"
    assert mod.add_key(existing, "tools", '"*"') == existing


@pytest.fixture()
def cc_config(tmp_path, monkeypatch):
    """A named, hermetic Command Code model pool, wired through the bridge's own env override.

    Every id in it is one the user actually picked in /model; the deliberate omission is a whole
    family (`fable`), which is how the no-blind-translate path is exercised.
    """
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "model": "z-ai/glm-5.3-flash",
        "featureModels": {"planning": "meta/muse-spark-1.3-contributor",
                          "implementation": "deepseek/deepseek-v4.1-flash"},
        "reasoningEffort": {"claude-haiku-5-5": "high"},
        "starredModels": ["claude-sonnet-5-5", "claude-opus-4-8", "moonshotai/Kimi-K3"],
    }), encoding="utf-8")
    monkeypatch.setenv("AGENT_BRIDGE_CONFIG", str(cfg))
    return cfg


@pytest.mark.parametrize("value", ["inherit", "claude-opus-4-8", "zai-org/glm-5.2", "gpt-5-6"])
def test_a_model_id_the_harness_knows_is_never_touched(value, cc_config) -> None:
    text = f"---\nname: p\nmodel: {value}\n---\nbody\n"
    out, note = _builder().translate_model(text)
    assert note is None and f"model: {value}\n" in out


@pytest.mark.parametrize("alias,family_id", [("sonnet", "claude-sonnet-5-5"),
                                             ("Sonnet", "claude-sonnet-5-5"),
                                             ("haiku", "claude-haiku-5-5"),
                                             ("opus", "claude-opus-4-8"),
                                             ("claude-opus", "claude-opus-4-8")])
def test_a_tier_alias_resolves_to_the_familys_currently_configured_model(alias, family_id, cc_config) -> None:
    """The user's own pool only: the default model, the feature models, the effort keys, the
    starred models. The alias never invents a catalogue id the user's plan may not grant."""
    text = f"---\nname: p\nmodel: {alias}\n---\nbody\n"
    out, note = _builder().translate_model(text)
    assert f"model: {family_id}\n" in out, f"`{alias}` must land on the user's pinned {family_id}"
    assert note is not None and family_id in note, "the resolution says what it resolved to"


def test_a_family_the_user_does_not_configure_is_never_translated_blindly(cc_config) -> None:
    """No fable-class model in the pool, so the field must not become one: not the newest catalogue
    fable, not the session default underneath it — both would change what the author pinned."""
    text = "---\nname: p\nmodel: fable\n---\nbody\n"
    out, note = _builder().translate_model(text)
    assert "model: inherit\n" in out
    assert "claude-fable-5" not in out, "a catalogue guess is a blind translate"
    assert "z-ai/glm-5.3-flash" not in out, "the session default would silently downgrade the tier"
    assert note is not None and "fable-class" in note and "-> inherit" in note


def test_an_alias_with_no_config_at_all_falls_back_to_inherit(monkeypatch, tmp_path) -> None:
    """No readable config means no pool, so resolution cannot meet its own standard: inherit."""
    monkeypatch.setenv("AGENT_BRIDGE_CONFIG", str(tmp_path / "absent.json"))
    text = "---\nname: p\nmodel: opus\n---\nbody\n"
    out, note = _builder().translate_model(text)
    assert "model: inherit\n" in out and note is not None and "-> inherit" in note


def test_an_absent_model_is_not_invented() -> None:
    assert _builder().translate_model("---\nname: p\n---\nbody\n")[1] is None


# ── body rewrites ─────────────────────────────────────────────────────────────

def test_a_body_tool_token_is_renamed_but_an_english_verb_is_not() -> None:
    mod = _builder()
    text = ("---\nname: w\ntools: Read, WebFetch\n---\n\n"
            "TaskUpdate(status: \"completed\") then WebFetch the page. Read the file. Write it up.\n")
    out, edits = mod.rename_body_tools(text)
    assert edits == {"TaskUpdate": 1, "WebFetch": 1}
    assert "task_update(" in out and "web_fetch the page" in out
    assert "Read the file. Write it up." in out, "single-word tool names are ordinary English too"
    assert "tools: Read, WebFetch" in out, "the frontmatter is never touched by the body pass"


def test_a_delegation_or_messaging_idiom_earns_exactly_one_adapter_note() -> None:
    mod = _builder()
    delegating = "---\nname: w\n---\nUse Task(Explore) for broad scans.\n"
    assert mod.body_needs_note(delegating) == ["Task(<agent>) delegation"]
    out = mod.insert_note(delegating)
    assert out.count(mod.ADAPTER_NOTE) == 1
    assert out.startswith("---\nname: w\n---\n\n"), "the note goes under the frontmatter"
    assert out.rstrip().endswith("Use Task(Explore) for broad scans.")
    assert mod.body_needs_note("---\nname: w\n---\nplain prompt, no idioms\n") == []
    assert mod.body_needs_note("---\nname: w\n---\nMessage the teammates via SendMessage.\n")


# ── build ─────────────────────────────────────────────────────────────────────

def test_build_mirrors_every_agent_with_translated_frontmatter(corpus, tmp_path) -> None:
    mod = _builder()
    dest = tmp_path / "mirror"
    rep = mod.build([corpus], dest, quiet=True)
    assert rep["status"] == "built"
    worker = (dest / "worker.md").read_text()
    assert "tools: read_file, write_file, edit_file, shell_command, glob, grep, " \
           "todo_write\n" in worker, "MultiEdit collapses into edit_file; Task/SendMessage drop"
    assert "TaskUpdate(status:" not in worker and "task_update(status:" in worker
    assert mod.ADAPTER_NOTE in worker
    assert "tools: \"*\"" in (dest / "notools.md").read_text(), "an omitted tools line is written out"
    assert "disallowedTools: shell_command\n" in (dest / "denier.md").read_text()
    assert "model: inherit\n" in (dest / "pinned.md").read_text()
    assert not (dest / "explore.md").exists(), "a reserved agent id is ignored by Command Code"
    assert json.loads((dest / mod.MANIFEST_NAME).read_text())["entries"], "the manifest is written"


def test_the_build_flow_translates_a_pinned_alias_through_the_pool(cc_config, corpus, tmp_path) -> None:
    """The env-configured pool governs the emitted bytes, not just the pure function."""
    mod = _builder()
    dest = tmp_path / "mirror"
    assert mod.build([corpus], dest, quiet=True)["status"] == "built"
    mirrored = (dest / "pinned.md").read_text()
    assert "model: claude-sonnet-5-5\n" in mirrored and "model: sonnet" not in mirrored


def test_no_source_file_is_ever_modified(corpus, tmp_path) -> None:
    before = {p.name: p.read_bytes() for p in corpus.iterdir()}
    _builder().build([corpus], tmp_path / "mirror", quiet=True)
    after = {p.name: p.read_bytes() for p in corpus.iterdir()}
    assert before == after, "every harness reads these files; the bridge must not touch them"


def test_a_wildcard_and_an_mcp_name_survive_untouched(corpus, tmp_path) -> None:
    _agent(corpus, "mcpfan", "*")
    dest = tmp_path / "mirror"
    _builder().build([corpus], dest, quiet=True)
    assert "tools: \"*\"\n" in (dest / "mcpfan.md").read_text()


def test_a_file_the_bridge_did_not_write_is_preserved_and_reported(corpus, tmp_path) -> None:
    dest = tmp_path / "mirror"
    dest.mkdir()
    (dest / "handmade.md").write_text("---\nname: handmade\ntools: read_file\n---\nMine.\n")
    _agent(corpus, "handmade", "Read")                     # same name in both worlds
    rep = _builder().build([corpus], dest, quiet=True)
    assert (dest / "handmade.md").read_text() == \
        "---\nname: handmade\ntools: read_file\n---\nMine.\n", "never clobbered"
    assert [c["file"] for c in rep["collisions"]] == ["handmade.md"]
    assert "handmade.md" in rep["preserved"]


def test_a_second_build_is_a_no_op_and_a_changed_source_rebuilds(corpus, tmp_path) -> None:
    mod = _builder()
    dest = tmp_path / "mirror"
    assert mod.build([corpus], dest, quiet=True)["status"] == "built"
    assert mod.build([corpus], dest, quiet=True)["status"] == "unchanged"
    _agent(corpus, "worker", "Read, Bash")                 # the source changed
    assert mod.build([corpus], dest, quiet=True)["status"] == "built"


def test_an_emitter_version_bump_rebuilds_without_force(corpus, tmp_path) -> None:
    """A fix that changes the bytes the emitter writes must reach the mirror through the ordinary
    no-force path — the session-start hook is that path, and it cannot know about code fixes. The
    live incident: add_key's placement changed and the sources did not, so without this hook the
    incremental build kept the invalid-YAML copies for whole sessions."""
    mod = _builder()
    dest = tmp_path / "mirror"
    mod.EMITTER_VERSION = 7
    rep = mod.build([corpus], dest, quiet=True)
    assert rep["status"] == "built"
    assert mod.build([corpus], dest, quiet=True)["status"] == "unchanged"
    mod.EMITTER_VERSION = 8
    rep = mod.build([corpus], dest, quiet=True)
    assert rep["status"] == "built", "an emitter-version bump must free a rebuild"
    assert mod.build([corpus], dest, quiet=True)["status"] == "unchanged"


def test_a_removed_source_leaves_no_stale_mirror_file(corpus, tmp_path) -> None:
    mod = _builder()
    dest = tmp_path / "mirror"
    mod.build([corpus], dest, quiet=True)
    (corpus / "pinned.md").unlink()
    rep = mod.build([corpus], dest, quiet=True)
    assert not (dest / "pinned.md").exists() and rep["removed"] == ["pinned.md"]


def test_the_mirror_refuses_to_write_through_a_symlinked_destination(corpus, tmp_path) -> None:
    """The exact accident this bridge exists to avoid: writing through the symlink edits the shared
    corpus every harness reads."""
    target = tmp_path / "shared"
    target.mkdir()
    link = tmp_path / "agents"
    link.symlink_to(target)
    r = _run("build", "--root", str(corpus), "--dest", str(link))
    assert r.returncode != 0 and "symlink" in (r.stdout + r.stderr)
    assert list(target.iterdir()) == [], "nothing may be written into the target"
    assert link.is_symlink()


# ── verify / clean ────────────────────────────────────────────────────────────

def test_verify_passes_on_a_fresh_mirror_and_names_a_tampered_copy(corpus, tmp_path) -> None:
    mod = _builder()
    dest = tmp_path / "mirror"
    mod.build([corpus], dest, quiet=True)
    assert mod.verify(dest)["ok"] is True
    (dest / "worker.md").write_text("---\nname: worker\ntools: Read, Whatever\n---\nx\n")
    bad = mod.verify(dest)
    assert bad["ok"] is False
    assert any("Read" in p or "Whatever" in p for p in bad["problems"]), "the untranslated id is named"


def test_verify_reports_a_mirror_file_that_lost_its_tools_line(corpus, tmp_path) -> None:
    mod = _builder()
    dest = tmp_path / "mirror"
    mod.build([corpus], dest, quiet=True)
    (dest / "notools.md").write_text("---\nname: notools\ndescription: d\n---\nbody\n")
    problems = mod.verify(dest)["problems"]
    assert any("no `tools:` line" in p for p in problems), "such an agent launches with no tools"


def test_verify_reports_a_source_that_changed_since_the_build(corpus, tmp_path) -> None:
    mod = _builder()
    dest = tmp_path / "mirror"
    mod.build([corpus], dest, quiet=True)
    _agent(corpus, "denier", "Read, Write, Bash, WebFetch, SendMessage", extra="disallowedTools: Read\n")
    rep = mod.verify(dest)
    assert rep["ok"] is False and any("CHANGED" in p for p in rep["problems"])


def test_clean_removes_only_what_the_bridge_wrote(corpus, tmp_path) -> None:
    mod = _builder()
    dest = tmp_path / "mirror"
    mod.build([corpus], dest, quiet=True)
    (dest / "handmade.md").write_text("---\nname: handmade\n---\nMine.\n")
    rep = mod.clean(dest, quiet=True)
    assert "worker.md" in rep["removed"] and not (dest / "worker.md").exists()
    assert (dest / "handmade.md").is_file(), "a file the manifest does not name is never deleted"
    assert not (dest / mod.MANIFEST_NAME).exists()


def test_list_is_read_only(corpus, tmp_path) -> None:
    dest = tmp_path / "mirror"
    r = _run("list", "--root", str(corpus), "--dest", str(dest))
    assert r.returncode == 0 and "worker.md" in r.stdout
    assert not dest.exists(), "`list` must not create anything"
    assert not (corpus / "worker.md").with_suffix(".md.tmp").exists()


# ── the hook and the installer ────────────────────────────────────────────────

def test_the_hook_selftest_passes() -> None:
    r = subprocess.run([sys.executable, str(HOOK), "--selftest"], capture_output=True, text=True,
                       timeout=120, cwd=ROOT)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "auto-agent-bridge --selftest OK" in r.stdout


def test_the_hook_is_wired_into_the_session_start_set_and_the_smoke_stamp_registry() -> None:
    installer = INSTALLER.read_text(encoding="utf-8")
    assert 'hooks/scripts/auto_agent_bridge.py"' in installer, "the hook is registered on install"
    assert "auto_agent_bridge.py" in installer.split("sc_hook_scripts = (")[1][:200], \
        "and it is part of the verify row"
    smoke = SMOKE.read_text(encoding="utf-8")
    assert ".auto-agent-bridge-stamp" in smoke, \
        "every self-heal stamp is seeded by the smoke run, or the smoke churns live state"


def test_the_installer_owns_the_directory_and_can_put_the_symlink_back() -> None:
    installer = INSTALLER.read_text(encoding="utf-8")
    assert '[ -L "$AGENTS_DIR" ]' in installer, "the symlink case is handled explicitly"
    assert "ln -sfn \"$AGENT_SWAP_TARGET\" \"$AGENTS_DIR\"" in installer, \
        "a failed build must restore the symlink"
    assert "cmd_agent_bridge.py\" clean" in installer, \
        "the rollback uses the bridge's own clean, never a recursive delete"
    r = subprocess.run(["bash", "-n", str(INSTALLER)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
