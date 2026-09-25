"""Behaviour tests for hooks/scripts/skill_exclusions.py — the PostToolUse(Skill) echo of a loaded
skill's own exclusion lines. The positive control is a verbatim copy of compound-to-skill's
"Don't use for" section: the incident skill whose body excluded the task while the agent kept going."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "hooks" / "scripts" / "skill_exclusions.py"

COMPOUND_BODY = """---
name: compound-to-skill
description: Capture, save what we just did as a compounded, reusable skill. Use at the end of a session or an arc (a single unit of work) to capture a workflow, technique, or process that is valuable/helpful.
allowed-tools: Read, Write, AskUserQuestion
---

The user wants to capture & save what was done in this session/arc as a reusable agent skill.

## Important

- Don't include project-specific file paths — use patterns like "src/routes/" not absolute paths

## Don't use for

- Editing or fixing an existing skill — use `/skill-creator` directly.
- Validating a finished skill against the spec — use `/skill-check`.
- Capturing a one-off command with no reusable pattern — not worth a skill.
"""


@pytest.fixture()
def mod(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("skill_exclusions", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    monkeypatch.setattr(m, "_qdrant_path", lambda name: None)
    monkeypatch.setattr(m, "FALLBACK_ROOTS", [tmp_path / "skills"])
    return m


def _install(tmp_path, name, text):
    d = tmp_path / "skills" / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(text, encoding="utf-8")
    return d / "SKILL.md"


def _run(mod, payload):
    return mod.main(json.dumps(payload) if not isinstance(payload, str) else payload)


def test_positive_control_compound_to_skill_exclusions_are_echoed(mod, tmp_path):
    _install(tmp_path, "compound-to-skill", COMPOUND_BODY)
    out = _run(mod, {"tool_name": "Skill", "tool_input": {"skill": "compound-to-skill"}})
    ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert "Editing or fixing an existing skill" in ctx
    assert "Validating a finished skill" in ctx
    # the "Important" section's don't-line is guidance, not an exclusion of the task
    assert "project-specific file paths" not in ctx
    assert "re-rule" in ctx


def test_output_shape_is_exactly_posttooluse_additional_context(mod, tmp_path):
    _install(tmp_path, "compound-to-skill", COMPOUND_BODY)
    d = json.loads(_run(mod, {"tool_name": "Skill", "tool_input": {"skill": "/compound-to-skill"}}))
    assert set(d) == {"hookSpecificOutput"}
    assert set(d["hookSpecificOutput"]) == {"hookEventName", "additionalContext"}
    assert d["hookSpecificOutput"]["hookEventName"] == "PostToolUse"


def test_description_not_for_sentence_is_echoed(mod, tmp_path):
    _install(tmp_path, "cli-builder", "---\nname: cli-builder\ndescription: Build CLIs. "
             "Not for implementing MCP servers. Use when scaffolding a command.\n---\nbody\n")
    ctx = json.loads(_run(mod, {"tool_name": "Skill", "tool_input": {"skill": "cli-builder"}})
                     )["hookSpecificOutput"]["additionalContext"]
    assert "Not for implementing MCP servers" in ctx
    assert "scaffolding" not in ctx


@pytest.mark.parametrize("header", ["## When not to use", "## Not for", "### Do not use for",
                                   "## Don't Use For"])
def test_exclusion_headers_yield_their_bullets(mod, tmp_path, header):
    _install(tmp_path, "s", f"---\nname: s\ndescription: d\n---\n{header}\n\n- first case\n"
             "* second case\n1. third case\n\n## Next\n- not an exclusion\n")
    ctx = json.loads(_run(mod, {"tool_name": "Skill", "tool_input": {"skill": "s"}})
                     )["hookSpecificOutput"]["additionalContext"]
    for c in ("first case", "second case", "third case"):
        assert c in ctx
    assert "not an exclusion" not in ctx


def test_lines_are_capped_in_count_and_length(mod, tmp_path):
    bullets = "".join(f"- case {i} " + "x" * 300 + "\n" for i in range(10))
    _install(tmp_path, "s", f"---\nname: s\ndescription: d\n---\n## Not for\n{bullets}")
    lines = mod.exclusions((tmp_path / "skills" / "s" / "SKILL.md").read_text())
    assert len(lines) == mod.MAX_LINES == 6
    assert all(len(ln) <= mod.MAX_CHARS for ln in lines)


def test_body_without_exclusions_prints_nothing(mod, tmp_path):
    _install(tmp_path, "plain", "---\nname: plain\ndescription: Does a thing.\n---\n## Steps\n- go\n")
    assert _run(mod, {"tool_name": "Skill", "tool_input": {"skill": "plain"}}) is None



def test_namespaced_name_without_index_hit_is_skipped(mod, tmp_path):
    _install(tmp_path, "compound-to-skill", COMPOUND_BODY)
    assert _run(mod, {"tool_name": "Skill", "tool_input": {"skill": "x:compound-to-skill"}}) is None


@pytest.mark.parametrize("payload", [
    "not json",
    {"tool_name": "Bash", "tool_input": {"command": "ls"}},
    {"tool_name": "Skill", "tool_input": {"skill": "no-such-skill"}},
    {"tool_name": "Skill", "tool_input": "oops"},
    {"tool_name": "Skill"},
])
def test_non_matching_or_malformed_input_is_silent(mod, payload):
    assert _run(mod, payload) is None



def test_get_skill_load_path_is_echoed_too(mod, tmp_path):
    _install(tmp_path, "compound-to-skill", COMPOUND_BODY)
    out = _run(mod, {"tool_name": "mcp__plugin_skill-concierge_skill-search__get_skill",
                     "tool_input": {"name": "compound-to-skill"}})
    assert "Editing or fixing an existing skill" in out and "tell the user" in out


def test_bold_label_exclusions_are_echoed(mod, tmp_path):
    _install(tmp_path, "s", "---\nname: s\ndescription: d\n---\n"
             "**When NOT to use:** Backend-only changes with no UI\n\n"
             "**NOT for:**\n- migrations\n- infra\n\n**Steps:**\n- not an exclusion\n")
    ctx = json.loads(_run(mod, {"tool_name": "Skill", "tool_input": {"skill": "s"}})
                     )["hookSpecificOutput"]["additionalContext"]
    for c in ("Backend-only changes with no UI", "migrations", "infra"):
        assert c in ctx
    assert "not an exclusion" not in ctx


def test_code_fences_are_not_read_as_sections(mod, tmp_path):
    _install(tmp_path, "s", "---\nname: s\ndescription: d\n---\n```\n# Not for prod\n- rm -rf x\n```\n")
    assert _run(mod, {"tool_name": "Skill", "tool_input": {"skill": "s"}}) is None


def test_real_qdrant_request_shape_resolves_the_payload_path(tmp_path, monkeypatch):
    import http.server
    import threading
    target = tmp_path / "deep" / "SKILL.md"
    target.parent.mkdir()
    target.write_text(COMPOUND_BODY, encoding="utf-8")
    seen = {}

    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            seen["path"] = self.path
            seen["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            data = json.dumps({"result": [{"payload": {"path": str(target)}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        spec = importlib.util.spec_from_file_location("skill_exclusions_http", SCRIPT)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        monkeypatch.setattr(m, "QDRANT_URL", f"http://127.0.0.1:{srv.server_port}")
        monkeypatch.setattr(m, "COLLECTION", "coll")
        out = m.main(json.dumps({"tool_name": "Skill", "tool_input": {"skill": "plugin:x"}}))
    finally:
        srv.shutdown()
    assert seen["path"] == "/collections/coll/points"
    # the engine's point id: uuid(md5("plugin:x")), hard-coded so the hook cannot drift from it
    assert seen["body"]["ids"] == ["5a0c51f2-71dd-9098-6ba4-284e34556e14"]
    assert "Editing or fixing an existing skill" in out


@pytest.mark.parametrize("py", ["python3", "/usr/bin/python3"])
def test_script_runs_as_a_hook_process_and_always_exits_zero(py, tmp_path):
    import shutil
    import subprocess
    if not shutil.which(py):
        pytest.skip(f"{py} not present")
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "SKILL_QDRANT_URL": "http://127.0.0.1:9",
           "ENFORCER_QDRANT_TIMEOUT": "not-a-number"}
    d = tmp_path / ".claude" / "skills" / "compound-to-skill"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(COMPOUND_BODY, encoding="utf-8")
    ok = subprocess.run([shutil.which(py), str(SCRIPT)], cwd=tmp_path, env=env, text=True,
                        capture_output=True,
                        input=json.dumps({"tool_name": "Skill", "tool_input": {"skill": "compound-to-skill"}}))
    assert ok.returncode == 0 and ok.stderr == ""
    assert "Editing or fixing" in json.loads(ok.stdout)["hookSpecificOutput"]["additionalContext"]
    bad = subprocess.run([shutil.which(py), str(SCRIPT)], cwd=tmp_path, env=env, text=True,
                         capture_output=True, input="{broken")
    assert bad.returncode == 0 and bad.stdout == ""


def test_hooks_json_wires_both_load_paths():
    hooks = json.loads((ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
    entries = [e for e in hooks["PostToolUse"]
               if any("skill_exclusions.py" in h.get("command", "") for h in e.get("hooks", []))]
    assert len(entries) == 1
    import re
    rx = re.compile(f"^(?:{entries[0]['matcher']})$")
    assert rx.match("Skill") and rx.match("mcp__plugin_skill-concierge_skill-search__get_skill")
    assert not rx.match("mcp__plugin_skill-concierge_skill-search__search_skills")


def test_bold_label_with_inline_text_does_not_swallow_the_procedure(mod, tmp_path):
    _install(tmp_path, "s", "---\nname: s\ndescription: d\n---\n**Not for:** tiny edits.\n\n"
             "Workflow:\n1. Read the spec\n2. Write the tests\n")
    lines = mod.exclusions((tmp_path / "skills" / "s" / "SKILL.md").read_text())
    assert lines == ["tiny edits."]


def test_a_bold_sentence_that_merely_starts_with_do_not_use_is_not_a_label(mod, tmp_path):
    _install(tmp_path, "s", "---\nname: s\ndescription: d\n---\n"
             "**Do NOT use `AskUserQuestion` for this selection.** Two rendering constraints\n"
             "- keep the grid\n")
    assert _run(mod, {"tool_name": "Skill", "tool_input": {"skill": "s"}}) is None


def test_curly_apostrophes_are_recognised(mod, tmp_path):
    _install(tmp_path, "s", "---\nname: s\ndescription: Build decks. Don’t use for spreadsheets.\n---\n"
             "## Don’t use for\n- invoices\n")
    ctx = json.loads(_run(mod, {"tool_name": "Skill", "tool_input": {"skill": "s"}})
                     )["hookSpecificOutput"]["additionalContext"]
    assert "spreadsheets" in ctx and "invoices" in ctx


def test_a_blank_line_closes_a_bold_label_list(mod, tmp_path):
    _install(tmp_path, "s", "---\nname: s\ndescription: d\n---\n**When NOT to use:** trivial edits.\n\n"
             "1. Run step one\n2. Run step two\n")
    assert mod.exclusions((tmp_path / "skills" / "s" / "SKILL.md").read_text()) == ["trivial edits."]
    _install(tmp_path, "t", "---\nname: t\ndescription: d\n---\n**NOT for:**\n- a\n\n- step\n")
    assert mod.exclusions((tmp_path / "skills" / "t" / "SKILL.md").read_text()) == ["a"]


# ── v0.49.0: the adapters (OMP / Command Code / Cline / DSH) forward the payload they build for
# ledger.py, so every harness's load shape must echo — and only a skill ROOT counts as a load.
@pytest.mark.parametrize("payload", [
    {"tool_name": "activate_skill", "tool_input": {"name": "compound-to-skill"}},       # Command Code
    {"tool_name": "Skill", "tool_input": {"skill": "compound-to-skill", "args": ""}},  # Cline / DSH, normalized
    {"tool_name": "read", "tool_input": {"path": "skill://compound-to-skill"}},         # OMP
    {"tool_name": "read", "tool_input": {"path": "skill://compound-to-skill/SKILL.md"}},
    {"tool_name": "mcp__skill_concierge_skill_search_get_skill",                        # OMP-minted MCP name
     "tool_input": {"name": "compound-to-skill"}},
    {"tool_name": "skill-search__get_skill", "tool_input": {"name": "compound-to-skill"}},  # Cline flattened
    {"tool_name": "mcp__skill-search__get_skill", "tool_input": {"name": "compound-to-skill"}},  # CC / DSH
])
def test_every_harness_load_shape_echoes(mod, tmp_path, payload):
    _install(tmp_path, "compound-to-skill", COMPOUND_BODY)
    out = _run(mod, payload)
    assert out and "Editing or fixing an existing skill" in out, payload


@pytest.mark.parametrize("path", ["skill://compound-to-skill/references/x.md", "/etc/hosts",
                                  "skill://", "compound-to-skill"])
def test_a_read_that_is_not_a_skill_root_is_silent(mod, tmp_path, path):
    _install(tmp_path, "compound-to-skill", COMPOUND_BODY)
    assert _run(mod, {"tool_name": "read", "tool_input": {"path": path}}) is None


def test_the_echo_names_the_re_rule_marker_with_the_loaded_skill(mod, tmp_path):
    _install(tmp_path, "compound-to-skill", COMPOUND_BODY)
    ctx = json.loads(_run(mod, {"tool_name": "Skill", "tool_input": {"skill": "compound-to-skill"}})
                     )["hookSpecificOutput"]["additionalContext"]
    assert "(re-rule: compound-to-skill)" in ctx


def test_fallback_roots_cover_every_harness_personal_root():
    import skill_exclusions as m
    roots = {str(r) for r in m.FALLBACK_ROOTS}
    for rel in (".codex/skills", ".commandcode/skills", ".omp/agent/skills", ".zcode/skills",
                ".cline/data/settings/skills", ".ohdsh/skills", ".dsh/skills"):
        assert str(Path.home() / rel) in roots, rel


def test_the_loaded_text_wins_over_a_same_named_copy_elsewhere(mod, tmp_path):
    """The echo must quote what the agent read: a harness can load a different same-named copy
    than the index path or the fallback roots would find."""
    _install(tmp_path, "twin", "---\nname: twin\ndescription: Does x. Not for the copy on disk.\n---\n")
    loaded = "---\nname: twin\ndescription: Does y. Not for the copy that was loaded.\n---\nbody\n"
    for resp in (loaded, [{"type": "text", "text": loaded}], {"content": [{"type": "text", "text": loaded}]}):
        out = _run(mod, {"tool_name": "mcp__skill-search__get_skill", "tool_input": {"name": "twin"},
                         "tool_response": resp})
        assert "the copy that was loaded" in out and "the copy on disk" not in out, resp


def test_a_response_that_is_not_a_skill_body_falls_back_to_resolution(mod, tmp_path):
    _install(tmp_path, "compound-to-skill", COMPOUND_BODY)
    out = _run(mod, {"tool_name": "Skill", "tool_input": {"skill": "compound-to-skill"},
                     "tool_response": {"success": True, "commandName": "compound-to-skill"}})
    assert "Editing or fixing an existing skill" in out


@pytest.mark.parametrize("refusal", ['{"error": "skill \'compound-to-skill\' not found"}',
                                     '{"error": "skill \'compound-to-skill\' is on the skill-concierge blocklist"}'])
def test_a_refused_load_echoes_nothing(mod, tmp_path, refusal):
    """get_skill refuses with an error JSON; nothing was loaded, so nothing is echoed — even
    though a same-named SKILL.md resolves by name."""
    _install(tmp_path, "compound-to-skill", COMPOUND_BODY)
    assert _run(mod, {"tool_name": "mcp__skill-search__get_skill",
                      "tool_input": {"name": "compound-to-skill"}, "tool_response": refusal}) is None
