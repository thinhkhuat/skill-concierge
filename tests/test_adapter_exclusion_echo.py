"""The skill-exclusion echo reaches the model through every non-Claude-format harness adapter.

Each adapter is driven the way its host calls it (tests/adapters/echo_driver.ts for the TS
adapters; the Cline bridge as the real stdin/stdout process Cline spawns) against a throwaway
HOME holding one fixture skill, a dead Qdrant URL (so resolution uses the fallback roots) and a
scratch ledger — nothing live is read or written. Negative controls: a non-skill tool, an OMP
sub-resource read, and a search call must change nothing."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BUN = shutil.which("bun") or str(Path.home() / ".bun" / "bin" / "bun")
FIXTURE = ("---\nname: echo-fixture\ndescription: Builds widgets. Not for editing an existing "
           "widget — use widget-editor.\n---\n# Echo fixture\nbody\n")
MARK = "Not for editing an existing widget"


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    home = tmp_path_factory.mktemp("home")
    skill = home / ".claude" / "skills" / "echo-fixture"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(FIXTURE)
    e = dict(os.environ, HOME=str(home), SKILL_QDRANT_URL="http://127.0.0.1:9",
             SKILL_CONCIERGE_LOG=str(home / "logs"), ENFORCER_QDRANT_TIMEOUT="0.2",
             PYENV_ROOT=os.environ.get("PYENV_ROOT", str(Path.home() / ".pyenv")))
    e.pop("SKILL_CONCIERGE_ROOT", None)
    return e


def _drive(env, adapter, case):
    if not Path(BUN).exists():
        pytest.skip("bun not installed")
    r = subprocess.run([BUN, str(ROOT / "tests" / "adapters" / "echo_driver.ts"), adapter, case],
                       env=env, capture_output=True, text=True, timeout=60, cwd=ROOT)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_omp_appends_the_echo_and_keeps_the_original_result(env):
    out = _drive(env, "omp", "root")
    texts = [b.get("text", "") for b in out["content"]]
    assert texts[0] == "ORIGINAL BODY" and MARK in texts[-1] and "(re-rule: echo-fixture)" in texts[-1]


@pytest.mark.parametrize("case", ["subresource", "other"])
def test_omp_leaves_other_reads_alone(env, case):
    assert _drive(env, "omp", case) is None


@pytest.mark.parametrize("case", ["activate_skill", "get_skill"])
def test_command_code_returns_additional_context(env, case):
    assert MARK in _drive(env, "commandcode", case)["additionalContext"]


def test_command_code_other_tools_get_no_opinion(env):
    assert _drive(env, "commandcode", "other") is None


def test_dsh_prepends_the_echo_and_keeps_downstream(env):
    out = _drive(env, "dsh", "skill")
    texts = [m["content"][0]["text"] for m in out["additionalContexts"]]
    assert MARK in texts[0] and texts[-1] == "DOWNSTREAM" and out["kind"] == "accept"
    echo = out["additionalContexts"][0]
    assert echo["id"] and echo["role"] == "user" and echo["source"]["kind"] == "plugin"   # DSH Message contract


def test_dsh_other_tools_pass_downstream_unchanged(env):
    out = _drive(env, "dsh", "other")
    assert [m["content"][0]["text"] for m in out["additionalContexts"]] == ["DOWNSTREAM"]


def _cline(env, tool, params):
    if not shutil.which("node"):
        pytest.skip("node not installed")
    payload = {"postToolUse": {"toolName": tool, "parameters": params, "success": True},
               "taskId": "t-cline"}
    r = subprocess.run(["node", str(ROOT / "adapters" / "cline" / "skill-concierge.cline-hook.cjs"),
                        "tool_result"], input=json.dumps(payload), env=env,
                       capture_output=True, text=True, timeout=60)
    return json.loads(r.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("tool,params", [("skills", {"skill": "echo-fixture"}),
                                         ("use_skill", {"skill": "echo-fixture"}),
                                         ("skill-search__get_skill", {"name": "echo-fixture"})])
def test_cline_bridge_returns_context_modification(env, tool, params):
    out = _cline(env, tool, params)
    assert out["cancel"] is False and MARK in out["contextModification"]


def test_cline_search_call_adds_no_context(env):
    assert _cline(env, "skill-search__search_skills", {"query": "x"}) == {"cancel": False}


def test_dsh_pre_step_skips_subagents_and_injects_doctrine_once_per_session(env):
    """DSH stamps a subagent's task prompt `kind: "user"`, so the session header is the only way to
    keep subagents out (Claude Code parity); desktop/web hosts run many sessions in one process, so
    the doctrine is per session, not per plugin instance."""
    out = _drive(env, "dsh", "prestep")
    assert out == {"sub": 0, "mainFirst": 1, "mainAgain": 0, "otherSession": 1}, out
