"""OpenCode v2 adapter (ADR-0085): engine roots, enforcer lanes, ledger tool names.

Pins the octa-harness contract end to end, hermetically (no live store, no live
OpenCode): the discovery roots and scopes behind SKILL_OPENCODE_ROOTS, the
one-var revert, the enforcer's opencode branch (foreign scopes, plugin gate,
filesystem twin), the ledger's OpenCode tool lanes, and the env-forwarding
invariant for the new flag.
"""
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def engine():
    """skills_discovery with every harness flag ON and hermetic paths."""
    saved = dict(os.environ)
    os.environ.update({
        "SKILL_CODEX_ROOTS": "1", "SKILL_COMMANDCODE_ROOTS": "1", "SKILL_OMP_ROOTS": "1",
        "SKILL_ZCODE_ROOTS": "1", "SKILL_DSH_ROOTS": "1", "SKILL_CLINE_ROOTS": "1",
        "SKILL_OPENCODE_ROOTS": "1", "SKILL_SYNCED_ROOTS": "0",
    })
    sys.path.insert(0, str(ROOT / "vendor" / "skill-search"))
    try:
        from skill_search import skills_discovery as sd
        importlib.reload(sd)
        yield sd
    finally:
        os.environ.clear()
        os.environ.update(saved)


def test_opencode_roots_default_on_and_scopes_present(engine):
    assert engine.OPENCODE_ROOTS is True
    assert engine.OPENCODE_PERSONAL_ROOT == engine._OPENCODE_HOME / "skills"
    scopes = engine.visible_scopes()
    assert "opencode-personal" in scopes
    assert any(s.startswith("opencode-project:") for s in scopes)
    assert str(engine.OPENCODE_PERSONAL_ROOT) in [str(p) for p in engine.SKILL_DIRS]


def test_opencode_roots_one_var_revert(engine):
    saved = dict(os.environ)
    os.environ["SKILL_OPENCODE_ROOTS"] = "0"
    try:
        import importlib
        from skill_search import skills_discovery as sd
        importlib.reload(sd)
        assert sd.OPENCODE_ROOTS is False
        assert "opencode-personal" not in sd.visible_scopes()
        assert not any(str(p).endswith("opencode/skills") for p in sd.SKILL_DIRS)
    finally:
        os.environ.clear()
        os.environ.update(saved)
        import importlib
        from skill_search import skills_discovery as sd
        importlib.reload(sd)


def test_scope_classification(engine):
    p = str(engine.OPENCODE_PERSONAL_ROOT / "doctor" / "SKILL.md")
    assert engine._scope_for(p) == "opencode-personal"
    proj = engine.OPENCODE_PROJECT_ROOT / "kit" / "SKILL.md"
    assert engine._scope_for(str(proj)) == f"opencode-project:{engine.OPENCODE_PROJECT_ROOT}"


def test_server_origin_head_maps_opencode():
    sys.path.insert(0, str(ROOT / "vendor" / "skill-search"))
    from skill_search import server
    assert server._origin("opencode-personal") == "opencode"
    assert server._origin("opencode-project:/x/.opencode/skills") == "opencode"


@pytest.fixture(scope="module")
def enforcer():
    saved = dict(os.environ)
    os.environ.update({
        "SKILL_CONCIERGE_HARNESS": "opencode",
        "SKILL_QDRANT_URL": "http://127.0.0.1:9",   # never the live store
        "SKILL_TRIGGERS": "/nonexistent-triggers.json",
        "SKILL_CONCIERGE_CATALOG_ROOTS": "/nonexistent-catalogs.json",
    })
    try:
        yield _load(ROOT / "hooks" / "scripts" / "enforcer.py", "enforcer_opencode")
    finally:
        os.environ.clear()
        os.environ.update(saved)


def test_harness_detection(enforcer):
    assert enforcer.RUNNING_HARNESS == "opencode"
    assert "opencode" in enforcer._HARNESS_ORDER
    # scope-head rule (the stdlib twin of server._ORIGIN_HEADS)
    assert enforcer._scope_harness("opencode-personal") == "opencode"
    assert enforcer._scope_harness("opencode-project:/x") == "opencode"


def test_foreign_scopes_personal_invocable_plugin_foreign(enforcer):
    foreign = set(enforcer.FOREIGN_SCOPES)
    # documented compatibility read of ~/.claude/skills -> personal invocable by construction
    assert "personal" not in foreign
    # no plugin-cache read, no other harness's exclusive roots, synced stays claude-only
    for scope in ("plugin", "codex-plugin", "codex-personal", "commandcode-personal",
                  "omp-personal", "omp-managed", "omp-plugin", "zcode-personal", "zcode-plugin",
                  "dsh-personal", "cline-personal", "claude-synced"):
        assert scope in foreign, scope
    # own scopes never foreign
    assert "opencode-personal" not in foreign
    assert not enforcer._scope_is_foreign("opencode-project:/x/.opencode/skills")


def test_plugin_gate_namespaced_rows_never_invocable(enforcer):
    assert enforcer._plugin_gate_ok("skill-concierge:doctor") is False
    assert enforcer._plugin_gate_ok("doctor") is True


def test_invocable_twin_filesystem_rescue(enforcer, tmp_path, monkeypatch):
    kit = tmp_path / "config" / "opencode" / "skills" / "doctor"
    kit.mkdir(parents=True)
    (kit / "SKILL.md").write_text("---\nname: doctor\n---\n", encoding="utf-8")
    monkeypatch.setattr(enforcer, "_OPENCODE_PERSONAL_ROOT", tmp_path / "config" / "opencode" / "skills")
    assert enforcer._invocable_twin("doctor") is True
    assert enforcer._invocable_twin("not-on-the-shelf") is False


def test_ledger_opencode_lanes(tmp_path):
    saved = dict(os.environ)
    os.environ["SKILL_CONCIERGE_LOG"] = str(tmp_path)
    try:
        ledger = _load(ROOT / "hooks" / "scripts" / "ledger.py", "ledger_opencode")
        ledger.LOG_DIR = tmp_path
        ledger.LEDGER = tmp_path / "ledger.log"

        import io
        def feed(payload):
            sys.stdin = io.StringIO(json.dumps(payload))
            ledger.main()

        # native skill tool activation: input key `id`
        feed({"hook_event_name": "PostToolUse", "session_id": "t", "harness": "opencode",
              "tool_name": "skill", "tool_input": {"id": "doctor"}})
        # transform-registered MCP tool ids (single-underscore namespace join)
        feed({"hook_event_name": "PostToolUse", "session_id": "t", "harness": "opencode",
              "tool_name": "skill-search_search_skills", "tool_input": {}})
        feed({"hook_event_name": "PostToolUse", "session_id": "t", "harness": "opencode",
              "tool_name": "skill-search_get_skill", "tool_input": {"name": "kit:seo"}})
        rows = [json.loads(l) for l in
                (tmp_path / "ledger.log").read_text(encoding="utf-8").splitlines() if l.strip()]
        by_ev = {r.get("ev"): r for r in rows}
        assert by_ev["auto"]["name"] == "doctor"
        assert by_ev["auto"]["harness"] == "opencode"
        assert by_ev["search"]["harness"] == "opencode"
        assert by_ev["get_skill"]["name"] == "kit:seo"
    finally:
        os.environ.clear()
        os.environ.update(saved)


@pytest.mark.parametrize("harness_env", [{"SKILL_CONCIERGE_HARNESS": "opencode"},
                                         {"SKILL_CONCIERGE_HARNESS": "open-code"},
                                         {"CLAUDE_PLUGIN_ROOT": "/x/.opencode/plugins/skill-concierge"}])
def test_doctrine_names_opencodes_search_tool(harness_env):
    """The adapter runs doctrine.py with SKILL_CONCIERGE_HARNESS=opencode; the standing order must
    name the tool id OpenCode exposes, not Claude Code's plugin-namespaced id or slash form."""
    import subprocess
    env = {k: v for k, v in os.environ.items()
           if k not in ("SKILL_CONCIERGE_HARNESS", "OMPCODE", "ZCODE_PLUGIN_ROOT", "DSH_SHELL",
                        "CLAUDE_PLUGIN_ROOT")}
    env.update(harness_env, SKILL_JEVD_ENV_CHECK="0")
    r = subprocess.run([sys.executable, str(ROOT / "hooks" / "scripts" / "doctrine.py")],
                       input='{"hook_event_name":"SessionStart","session_id":"s"}',
                       capture_output=True, text=True, env=env)
    ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
    assert ctx.count("skill-search_search_skills") == 1
    assert "mcp__plugin_skill-concierge" not in ctx and "/skill-concierge:skill-search" not in ctx
    assert 'get_skill("<name>")' in ctx


def test_engine_env_and_mcp_pin_the_flag():
    env = _load(ROOT / "scripts" / "engine_env.py", "engine_env_opencode")
    assert "SKILL_OPENCODE_ROOTS" in env.ENGINE_ENV_KEYS
    assert "SKILL_OPENCODE_HOME" in env.ENGINE_ENV_KEYS
    mcp = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))
    assert mcp["mcpServers"]["skill-search"]["env"].get("SKILL_OPENCODE_ROOTS") == "1"


def test_plugin_package_shape():
    pkg = json.loads((ROOT / "adapters" / "opencode" / "plugin" / "package.json").read_text(encoding="utf-8"))
    assert pkg["type"] == "module"
    assert pkg["exports"]["."] == "./index.ts"
    src = (ROOT / "adapters" / "opencode" / "plugin" / "index.ts").read_text(encoding="utf-8")
    # the five parity surfaces + the fail-open doctrine
    assert 'id: "skill-concierge"' in src
    for surface in ("mcp.transform", 'hook("prompt"', 'hook("context"',
                    'hook("evaluate"', 'hook("execute.after"'):
        assert surface in src, surface
    assert "SKILL_CONCIERGE_HARNESS: HARNESS" in src or "SKILL_CONCIERGE_HARNESS" in src
    # v2 local-server env key is `environment` (an `env` field is silently ignored)
    assert "environment: row.env" in src
    # v2 MCP tools default to Code Mode (reachable only via `execute`); the doctrine and the
    # ledger name the native `skill-search_search_skills` tool, so the server must opt out.
    assert "codemode: false" in src


# ── The concierge's own OpenCode skills live in a folder only it owns ─────────────────────
# ~/.config/opencode/skills is often a symlink to ~/.claude/skills (OpenCode reads that folder
# anyway, as a documented compatibility source). Copying the plugin skills there put plain
# `doctor`, `setup`, … into Claude Code's personal shelf. The copies now go to
# ~/.config/opencode/skill-concierge-skills, registered in opencode.json `skills`.

def test_concierge_skills_root_is_indexed_as_opencode_personal(engine):
    root = engine.OPENCODE_CONCIERGE_ROOT
    assert root == engine._OPENCODE_HOME / "skill-concierge-skills"
    assert str(root) in [str(p) for p in engine.SKILL_DIRS]
    assert engine._scope_for(str(root / "doctor" / "SKILL.md")) == "opencode-personal"


def test_concierge_skills_root_is_a_twin_root(enforcer, tmp_path, monkeypatch):
    own = tmp_path / "opencode" / "skill-concierge-skills"
    (own / "doctor").mkdir(parents=True)
    (own / "doctor" / "SKILL.md").write_text("---\nname: doctor\n---\n", encoding="utf-8")
    monkeypatch.setattr(enforcer, "_OPENCODE_CONCIERGE_ROOT", own)
    monkeypatch.setattr(enforcer, "_OPENCODE_PERSONAL_ROOT", tmp_path / "nope")
    assert enforcer._invocable_twin("doctor") is True
