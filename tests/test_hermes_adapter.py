"""The Hermes Agent adapter (ADR-0100), driven the way Hermes drives it, against stub hook scripts.

Hermes calls `register(ctx)` once and then fires hook callbacks with keyword arguments. What this
pins is the *mapping* — the part that would silently rot: which Claude Code gate each Hermes hook
stands in for, that a subagent session gets neither doctrine nor a turn row, that a blocklisted
skill turns into Hermes's `{"action": "block"}` shape (not Claude's `permissionDecision`), that a
skill load is logged in the Skill lane, and that the "not for" echo rides
`transform_tool_result` (the only Hermes surface that can change what the model reads).

The real scripts are exercised separately (tests/test_doctrine_text, the enforcer/ledger selftests);
here they are stubs so the mapping is what fails when it breaks.
"""
import importlib.util
import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "adapters" / "hermes" / "plugin" / "__init__.py"

STUB = '''import json, os, sys
name = os.path.basename(__file__)
raw = sys.stdin.read()
with open(os.path.join(os.environ["STUB_LOG"], name + ".jsonl"), "a") as f:
    f.write(json.dumps({"stdin": raw, "harness": os.environ.get("SKILL_CONCIERGE_HARNESS"),
                        "entry": os.environ.get("SKILL_CONCIERGE_HARNESS_ENTRY")}) + "\\n")
p = json.loads(raw or "{}")
def ctx(text):
    print(json.dumps({"hookSpecificOutput": {"additionalContext": text}}))
if name == "enforcer.py":
    ctx("MENU for: " + p.get("prompt", ""))
elif name == "doctrine.py":
    ctx("SKILL-FIRST doctrine")
elif name == "skill_guard.py" and p.get("tool_input", {}).get("skill") == "blocked-skill":
    print(json.dumps({"hookSpecificOutput": {"permissionDecision": "deny",
                      "permissionDecisionReason": "blocked by test"}}))
elif name == "skill_exclusions.py":
    ctx("NOT-FOR echo")
'''
SCRIPTS = ("enforcer.py", "ledger.py", "skill_guard.py", "skill_exclusions.py", "doctrine.py",
           "auto_reindex.py", "auto_overrides.py", "auto_flywheel.py", "auto_promote.py")


@pytest.fixture
def adapter(tmp_path, monkeypatch):
    """The plugin module with PLUGIN_ROOT pointed at a stub checkout, plus its call log."""
    root = tmp_path / "checkout"
    scripts = root / "hooks" / "scripts"
    scripts.mkdir(parents=True)
    for name in SCRIPTS:
        (scripts / name).write_text(STUB, encoding="utf-8")
    log = tmp_path / "stublog"
    log.mkdir()
    monkeypatch.setenv("SKILL_CONCIERGE_ROOT", str(root))
    monkeypatch.setenv("STUB_LOG", str(log))
    monkeypatch.delenv("HERMES_HOME", raising=False)

    spec = importlib.util.spec_from_file_location("sc_hermes_adapter_test", PLUGIN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    class Ctx:
        def __init__(self):
            self.hooks = {}

        def register_hook(self, name, fn):
            self.hooks[name] = fn

    ctx = Ctx()
    mod.register(ctx)
    return mod, ctx, log


def _calls(log: Path, name: str) -> list[dict]:
    path = log / f"{name}.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _wait_calls(log: Path, name: str, count: int = 1, timeout: float = 10.0) -> list[dict]:
    """Ledger writes are fire-and-forget threads; wait for them instead of racing them."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        rows = _calls(log, name)
        if len(rows) >= count:
            return rows
        time.sleep(0.02)
    return _calls(log, name)


def test_registers_one_hook_per_claude_code_gate(adapter):
    _mod, ctx, _log = adapter
    assert set(ctx.hooks) == {"on_session_start", "pre_llm_call", "pre_tool_call",
                              "post_tool_call", "transform_tool_result"}


def test_plugin_root_resolves_the_checkout(tmp_path, monkeypatch):
    root = tmp_path / "checkout"
    (root / "hooks" / "scripts").mkdir(parents=True)
    (root / "hooks" / "scripts" / "enforcer.py").write_text("", encoding="utf-8")
    monkeypatch.setenv("SKILL_CONCIERGE_ROOT", str(root))
    spec = importlib.util.spec_from_file_location("sc_hermes_root_test", PLUGIN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.PLUGIN_ROOT == root


def test_first_turn_injects_doctrine_then_the_menu(adapter):
    mod, ctx, log = adapter
    out = ctx.hooks["pre_llm_call"](session_id="s1", user_message="write a commit message",
                                    is_first_turn=True, model="m", platform="cli",
                                    conversation_history=[])
    text = out["context"]
    assert "SKILL-FIRST doctrine" in text and "MENU for: write a commit message" in text
    # Every child process carries the harness stamp, and none carries a leaked PYTHONPATH.
    for call in _calls(log, "enforcer.py"):
        assert call["harness"] == "hermes"
    # A second turn gets the menu only — doctrine is once per session.
    out = ctx.hooks["pre_llm_call"](session_id="s1", user_message="and now the body",
                                    is_first_turn=False, model="m", platform="cli")
    assert "doctrine" not in out["context"] and "MENU for: and now the body" in out["context"]


def test_a_subagent_session_gets_nothing(adapter):
    _mod, ctx, log = adapter
    out = ctx.hooks["pre_llm_call"](session_id="child", user_message="do the subtask",
                                    is_first_turn=True, parent_session_id="parent")
    assert out is None
    assert _calls(log, "enforcer.py") == [] and _calls(log, "ledger.py") == []
    # …and its tool calls are stamped as subagent rows, never as a main-session use.
    ctx.hooks["post_tool_call"](tool_name="skill_view", args={"name": "chisle"}, result="b",
                                session_id="child", status="ok")
    rows = _wait_calls(log, "ledger.py")
    assert rows and json.loads(rows[-1]["stdin"]).get("agent_id") == "child"


def test_blocklisted_skill_turns_into_hermes_block_shape(adapter):
    _mod, ctx, _log = adapter
    out = ctx.hooks["pre_tool_call"](tool_name="skill_view", args={"name": "blocked-skill"},
                                     task_id="s1")
    assert out == {"action": "block", "message": "blocked by test"}
    # Guard payload uses Claude's Skill-tool lane, the shape skill_guard.py reads.
    # A different tool, or an allowed skill, gets no directive at all.
    assert ctx.hooks["pre_tool_call"](tool_name="terminal", args={}, task_id="s1") is None
    assert ctx.hooks["pre_tool_call"](tool_name="skill_view", args={"name": "fine"},
                                      task_id="s1") is None


def test_skill_load_is_logged_in_the_skill_lane(adapter):
    mod, ctx, log = adapter
    assert mod._skill_load_payload("skill_view", {"name": "chisle"}) == {
        "tool_name": "Skill", "tool_input": {"skill": "chisle"}}
    assert mod._skill_load_payload("terminal", {}) is None
    ctx.hooks["post_tool_call"](tool_name="skill_view", args={"name": "chisle"}, result="body",
                                session_id="s1", status="ok")
    payload = json.loads(_wait_calls(log, "ledger.py")[-1]["stdin"])
    assert payload["hook_event_name"] == "PostToolUse"
    assert payload["tool_name"] == "Skill" and payload["tool_input"] == {"skill": "chisle"}
    assert payload["harness"] == "hermes" and "agent_id" not in payload
    # A blocked/failed call is not a use: Claude Code fires no PostToolUse for one.
    before = len(_wait_calls(log, "ledger.py"))
    ctx.hooks["post_tool_call"](tool_name="skill_view", args={"name": "chisle"}, result="b",
                                session_id="s1", status="error")
    time.sleep(0.3)          # nothing should arrive: the status gate drops it before _fire
    assert len(_calls(log, "ledger.py")) == before


def test_search_rows_are_matched_under_hermes_namespacing(adapter):
    mod, _ctx, _log = adapter
    assert mod._skill_load_payload("mcp_skill_search_search_skills", {"query": "x"}) == {
        "tool_name": "mcp_skill_search_search_skills", "tool_input": {"query": "x"}}
    assert mod._skill_load_payload("mcp_skill_search_get_skill", {"name": "x"}) is not None
    assert mod._skill_load_payload("mcp_exa_web_search_exa", {"query": "x"}) is None


def test_exclusion_echo_rides_transform_tool_result(adapter):
    _mod, ctx, _log = adapter
    out = ctx.hooks["transform_tool_result"](tool_name="skill_view", args={"name": "chisle"},
                                             result="BODY", session_id="s1")
    assert out == "BODY\n\nNOT-FOR echo"
    # A search carries no skill body to echo, and a non-skill tool is left untouched.
    assert ctx.hooks["transform_tool_result"](
        tool_name="mcp_skill_search_search_skills", args={}, result="R", session_id="s1") is None
    assert ctx.hooks["transform_tool_result"](tool_name="terminal", args={}, result="R",
                                              session_id="s1") is None


def test_plugin_root_falls_back_past_a_stale_env_value(tmp_path, monkeypatch):
    """SKILL_CONCIERGE_ROOT pointing at a dead path must not win: the ladder falls through to the
    plugin's own resolved location, which always exists while the checkout does."""
    monkeypatch.setenv("SKILL_CONCIERGE_ROOT", str(tmp_path / "gone"))
    spec = importlib.util.spec_from_file_location("sc_hermes_stale_env_test", PLUGIN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert (mod.SCRIPTS / "enforcer.py").is_file()


def test_a_missing_checkout_fails_open(tmp_path, monkeypatch):
    """Every hook returns "no directive" when the scripts are gone — a broken install must never
    block a Hermes turn (pre_tool_call in particular fails CLOSED in Hermes on a raise)."""
    monkeypatch.setenv("SKILL_CONCIERGE_ROOT", str(tmp_path / "gone"))
    spec = importlib.util.spec_from_file_location("sc_hermes_missing_test", PLUGIN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.SCRIPTS = tmp_path / "nowhere"      # the resolved root, emptied

    class Ctx:
        hooks = {}

        def register_hook(self, name, fn):
            self.hooks[name] = fn

    ctx = Ctx()
    mod.register(ctx)
    assert ctx.hooks["pre_llm_call"](session_id="s", user_message="hi", is_first_turn=True) is None
    assert ctx.hooks["pre_tool_call"](tool_name="skill_view", args={"name": "x"}) is None
    assert ctx.hooks["transform_tool_result"](tool_name="skill_view", args={"name": "x"},
                                              result="R") is None


def test_hermes_identity_resolves_in_the_shared_detector(monkeypatch):
    """hooks/scripts/harness.py is the one detector enforcer, doctrine and ledger share."""
    sys.path.insert(0, str(ROOT / "hooks" / "scripts"))
    try:
        import harness as harness_mod
    finally:
        sys.path.pop(0)
    for alias in ("hermes", "hermes-agent", "Hermes"):
        monkeypatch.setenv("SKILL_CONCIERGE_HARNESS", alias)
        for var in ("OMPCODE", "ZCODE_PLUGIN_ROOT", "DSH_SHELL", "CLAUDE_PLUGIN_ROOT"):
            monkeypatch.delenv(var, raising=False)
        assert harness_mod.running_harness("/x/hooks/scripts/enforcer.py") == "hermes"
    # Install-path marker fallback: a script under ~/.hermes/ with no explicit env var.
    monkeypatch.delenv("SKILL_CONCIERGE_HARNESS", raising=False)
    assert harness_mod.running_harness("/Users/x/.hermes/plugins/skill-concierge/__init__.py") == "hermes"
    # The explicit value never loses to a Claude marker it inherited.
    monkeypatch.setenv("SKILL_CONCIERGE_HARNESS", "hermes")
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", "/Users/x/.claude/plugins/cache/p/p/1")
    assert harness_mod.running_harness("/x/y.py") == "hermes"
