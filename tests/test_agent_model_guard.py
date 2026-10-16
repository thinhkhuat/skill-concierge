"""hooks/scripts/agent_model_guard.py — the PreToolUse(agent) gate that denies a bare
Claude tier alias in an agent-tool call's `model` argument.

The live incident it closes: a Command Code session delegated to vn-editor-agent with
`model: "opus"` in the CALL; the dispatcher (cli.mjs::describeUnknownSubagentModel)
validates a call-arg model against its shipped /model catalog, refuses the bare alias,
and blames the agent FILE in its message even though the file never configured a model —
which is exactly why the refusal read as a definition-layer defect and sent a fix to the
wrong layer. The bridge cannot fix this layer (no config seam in the dispatcher; author
prose may not be rewritten), so the guard denies at generation time and names the exact
id the user's own config pool resolves the alias to.

Each part of the negative contract is asserted on its own: a deny must name the alias AND
not invent a catalogue id; the fail-open path must stay silent; the kill switch must
silence everything; a non-agent tool or a legal model value must pass untouched.
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "hooks" / "scripts" / "agent_model_guard.py"

POOL = ["claude-sonnet-5-5", "claude-opus-4-8", "moonshotai/Kimi-K3"]


def _guard():
    spec = importlib.util.spec_from_file_location("agent_model_guard", GUARD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(payload: dict, env: dict | None = None) -> subprocess.CompletedProcess:
    import os
    e = dict(os.environ)  # inherits AGENT_BRIDGE_CONFIG: /nonexistent by default, the fixture's cfg when set
    e.update(env or {})
    return subprocess.run([sys.executable, str(GUARD)], input=json.dumps(payload),
                          capture_output=True, text=True, timeout=30, env=e)


def _deny_reason(payload: dict) -> str:
    r = _run(payload)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    return out["hookSpecificOutput"]["permissionDecisionReason"]


@pytest.fixture()
def cc_config(tmp_path, monkeypatch):
    """A named, hermetic model pool, wired through the bridge's own env override."""
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"starredModels": ["claude-sonnet-5-5", "claude-opus-4-8"]}),
                   encoding="utf-8")
    monkeypatch.setenv("AGENT_BRIDGE_CONFIG", str(cfg))
    return cfg


# ── the deny contract ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("alias", ["opus", "Opus", "sonnet", "haiku", "fable",
                                   "claude-opus", "claude-sonnet"])
def test_a_bare_tier_alias_in_an_agent_call_is_denied(alias) -> None:
    reason = _deny_reason({"tool_name": "agent",
                           "tool_input": {"subagent_type": "vn-editor-agent",
                                          "model": alias}})
    assert alias.lower().replace("claude-", "") in reason, "the denial names the alias"
    assert "dispatcher" in reason and "exact /model id" in reason, "the reason teaches the fix"


def test_the_opus_denial_names_the_id_the_users_pool_resolves_to(cc_config) -> None:
    """The same resolution the bridge uses: the family's id from the user's OWN pool —
    never a catalogue guess. opus -> claude-opus-4-8, the id the fixture pool pins."""
    reason = _deny_reason({"tool_name": "agent", "tool_input": {"model": "opus"}})
    assert "claude-opus-4-8" in reason


def test_an_unpinned_family_is_denied_without_inventing_a_catalogue_id() -> None:
    """No fable-class model in the pool: the denial must not name one, and must point at
    /model instead — the same no-blind-translate rule the bridge obeys."""
    reason = _deny_reason({"tool_name": "agent", "tool_input": {"model": "fable"}})
    assert "claude-fable-5" not in reason, "a catalogue guess is a blind translate"
    assert "/model" in reason


def test_the_exact_original_failing_call_is_denied() -> None:
    """The live incident's own tool_input shape (vn-editor-agent + model opus)."""
    reason = _deny_reason({"tool_name": "agent",
                           "tool_input": {"description": "Translate incident delta report "
                                                         "to Vietnamese",
                                          "subagent_type": "vn-editor-agent",
                                          "prompt": "x", "model": "opus"}})
    assert "opus" in reason


# ── the allow contract ────────────────────────────────────────────────────────

@pytest.mark.parametrize("payload", [
    {"tool_name": "agent", "tool_input": {"model": "claude-opus-4-8"}},
    {"tool_name": "agent", "tool_input": {"model": "inherit"}},
    {"tool_name": "agent", "tool_input": {"model": "zai-org/glm-5.3-flash"}},
    {"tool_name": "agent", "tool_input": {}},
    {"tool_name": "agent", "tool_input": None},
    {"tool_name": "shell_command", "tool_input": {"command": "git stash", "model": "opus"}},
    {"tool_input": {"model": "opus"}},
])
def test_everything_that_is_not_a_bare_alias_passes_silently(payload) -> None:
    r = _run(payload)
    assert r.returncode == 0 and r.stdout == "", "an allow is silent"


def test_the_kill_switch_silences_the_guard(monkeypatch) -> None:
    import os
    e = dict(os.environ, AGENT_MODEL_GUARD="0")
    r = subprocess.run([sys.executable, str(GUARD)],
                       input=json.dumps({"tool_name": "agent",
                                         "tool_input": {"model": "opus"}}),
                       capture_output=True, text=True, timeout=30, env=e)
    assert r.returncode == 0 and r.stdout == ""


@pytest.mark.parametrize("stdin", ["not json", "", "{}"])
def test_a_malformed_or_empty_payload_fails_open(stdin) -> None:
    import os
    e = dict(os.environ)
    e.pop("AGENT_MODEL_GUARD", None)
    r = subprocess.run([sys.executable, str(GUARD)], input=stdin,
                       capture_output=True, text=True, timeout=30, env=e)
    assert r.returncode == 0 and r.stdout == "", "fail-open stays silent"


def test_a_failed_config_read_still_denies_and_teaches(monkeypatch) -> None:
    """The guard must not go blind when the config is unreadable: the alias is still
    refused; the reason points at /model instead of naming an unresolvable id."""
    mod = _guard()
    monkeypatch.setenv("AGENT_BRIDGE_CONFIG", "/nonexistent/cmd-agent-bridge-tests/cfg.json")
    reason = mod.decide("opus")
    assert reason is not None and "claude-opus-4-8" not in reason and "/model" in reason


def test_the_selftest_contract_passes() -> None:
    r = subprocess.run([sys.executable, str(GUARD), "--selftest"],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0 and "selftest ok" in r.stdout, r.stdout + r.stderr


# ── the type leg ──────────────────────────────────────────────────────────────

def test_an_unregistered_skill_name_is_denied_with_the_skill_form() -> None:
    """The live incident: `subagent_type: pstack-architect` — a SKILL, not an agent. The
    denial must teach the /skill: form instead of the dispatcher's bare refusal."""
    reason = _deny_reason({"tool_name": "agent", "tool_input": {"prompt": "x",
                                                               "subagent_type": "pstack-architect"}})
    assert "/skill:pstack-architect" in reason and "no registered subagent" in reason


def test_a_fully_unknown_type_is_denied_generically_never_a_fake_skill_form() -> None:
    reason = _deny_reason({"tool_name": "agent",
                           "tool_input": {"subagent_type": "agent-guard-test-absent"}})
    assert "no registered subagent" in reason
    assert "/skill:agent-guard-test-absent" not in reason


@pytest.mark.parametrize("subagent_type", ["general", "explore", "plan", "vn-editor-agent"])
def test_a_registered_type_passes_silently(subagent_type) -> None:
    r = _run({"tool_name": "agent", "tool_input": {"prompt": "x", "subagent_type": subagent_type}})
    assert r.returncode == 0 and r.stdout == ""


def test_the_registry_uses_the_frontmatter_name_not_the_filename(tmp_path) -> None:
    """Command Code registers an agent by its frontmatter `name:` (filename is only the
    default). The guard's view must match, and the filename stem stays allowed too
    (fail-open direction: only a verifiably absent name is denied)."""
    mod = _guard()
    d = tmp_path / "agents"
    d.mkdir()
    (d / "a-file.md").write_text("---\nname: alpha\ndescription: d\n---\nbody\n")
    (d / "b-file.md").write_text("---\ndescription: no name field\n---\nbody\n")
    import cmd_agent_bridge as bridge
    from unittest import mock
    with mock.patch.object(bridge, "DEST_DEFAULT", str(d)):
        assert mod.decide_type("alpha") is None, "frontmatter name is registered"
        assert mod.decide_type("b-file") is None, "filename default registers too"
        reason = mod.decide_type("a-file", registry=set())
        assert reason is not None and "a-file" in reason


def test_the_type_leg_runs_before_the_model_leg() -> None:
    reason = _deny_reason({"tool_name": "agent", "tool_input": {"prompt": "x",
                                                               "subagent_type": "pstack-architect",
                                                               "model": "opus"}})
    assert "subagent_type" in reason, "the type denial wins when both trip"


# ── the wiring ────────────────────────────────────────────────────────────────

def test_the_installer_wires_the_guard_on_the_agent_matcher() -> None:
    installer = (ROOT / "adapters" / "commandcode" / "install.sh").read_text("utf-8")
    assert 'with_agent_model_guard(settings, root)' in installer, "the settings pipeline runs it"
    assert '"matcher": "agent"' in installer, "it fires on the agent tool only"
    assert "agent_model_guard.py" in installer, "and points at this guard"


def test_the_wiring_is_idempotent_and_preserves_foreign_hooks() -> None:
    import json
    installer = (ROOT / "adapters" / "commandcode" / "install.sh").read_text("utf-8")
    block = installer[installer.index("def with_agent_model_guard"):
                      installer.index("def atomic_write")]
    ns: dict = {}
    exec(f"import json\n{block}\nns_result = with_agent_model_guard", ns)  # noqa: S102
    fn = ns["ns_result"]
    settings = {"hooks": {"PreToolUse": [
        {"matcher": ".*", "hooks": [{"type": "command",
                                     "command": "palate hook pre-tool-use"}]},
        {"matcher": "agent", "hooks": [{"type": "command",
                                        "command": 'python3 "/stale/agent_model_guard.py"',
                                        "timeout": 5}]},
    ]}}
    out = fn(json.loads(json.dumps(settings)), "/repo")
    pre = out["hooks"]["PreToolUse"]
    assert [p for p in pre if "palate" in json.dumps(p)] == [settings["hooks"]["PreToolUse"][0]], \
        "a foreign PreToolUse hook survives untouched"
    ours = [p for p in pre if "agent_model_guard.py" in json.dumps(p)]
    assert len(ours) == 1 and ours[0]["matcher"] == "agent", "exactly one fresh entry"
    assert "/repo/hooks/scripts/agent_model_guard.py" in ours[0]["hooks"][0]["command"]
