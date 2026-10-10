"""The OpenCode v2 plugin, driven the way OpenCode's server drives it, against stub hook scripts.

Pins what live OpenCode sessions showed (2026-10-09): the skill-search MCP server must sit on
the native tool list (`codemode: false`), a subagent's child session gets no doctrine, menu or
turn row, a refused skill call is not logged as a use, and another plugin's leading
`<system-context>` block is not part of the prompt the enforcer ranks.
"""
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "adapters" / "opencode" / "plugin"
HARNESS = Path(__file__).with_name("opencode_plugin_harness.mjs")
NODE = shutil.which("node")

STUB = '''import json, os, sys
name = os.path.basename(__file__)
raw = sys.stdin.read()
with open(os.path.join(os.environ["STUB_LOG"], name + ".jsonl"), "a") as f:
    f.write(json.dumps({"stdin": raw, "harness": os.environ.get("SKILL_CONCIERGE_HARNESS")}) + "\\n")
p = json.loads(raw or "{}")
def ctx(text):
    print(json.dumps({"hookSpecificOutput": {"additionalContext": text}}))
if name == "enforcer.py":
    ctx("MENU for: " + p["prompt"])
elif name == "doctrine.py" and not p.get("agent_id"):
    ctx("SKILL-FIRST doctrine")
elif name == "skill_guard.py" and p["tool_input"]["skill"] == "blocked-skill":
    print(json.dumps({"hookSpecificOutput": {"permissionDecision": "deny",
                      "permissionDecisionReason": "blocked by test"}}))
elif name == "skill_exclusions.py":
    ctx("NOT-FOR echo")
'''
SCRIPTS = ["enforcer.py", "ledger.py", "skill_guard.py", "skill_exclusions.py", "doctrine.py",
           "auto_reindex.py", "auto_overrides.py", "auto_flywheel.py", "auto_promote.py"]

def _node_imports_ts() -> bool:
    """Node 22.6+ strips TypeScript types on import; older versions error instead of skipping."""
    if NODE is None:
        return False
    out = subprocess.run([NODE, "--version"], capture_output=True, text=True).stdout.strip().lstrip("v")
    return tuple(int(x) for x in out.split(".")[:2]) >= (22, 6)


pytestmark = pytest.mark.skipif(not _node_imports_ts(),
                                reason="needs node 22.6+ (the OpenCode plugin is imported as .ts)")


@pytest.fixture()
def fake(tmp_path):
    root, log = tmp_path / "repo", tmp_path / "log"
    shutil.copytree(PLUGIN_DIR, root / "adapters" / "opencode" / "plugin")
    (root / "hooks" / "scripts").mkdir(parents=True)
    log.mkdir()
    for name in SCRIPTS:
        (root / "hooks" / "scripts" / name).write_text(STUB)
    shutil.copy(ROOT / ".mcp.json", root / ".mcp.json")

    def drive(calls, sessions=None):
        e = {**os.environ, "STUB_LOG": str(log), "SKILL_CONCIERGE_ROOT": str(root)}
        r = subprocess.run([NODE, str(HARNESS), str(root / "adapters" / "opencode" / "plugin" / "index.ts")],
                           input=json.dumps({"sessions": sessions or {}, "calls": calls}),
                           capture_output=True, text=True, timeout=60, env=e)
        assert r.returncode == 0, r.stderr
        return json.loads(r.stdout)

    def logged(name, wait_for=0):
        path = log / f"{name}.jsonl"
        deadline = time.time() + 5
        while wait_for and time.time() < deadline:
            if path.exists() and len(path.read_text().splitlines()) >= wait_for:
                break
            time.sleep(0.05)
        return [json.loads(x["stdin"]) for x in map(json.loads, path.read_text().splitlines())] \
            if path.exists() else []

    return drive, logged


def prompt(sid, text):
    return {"hook": "prompt", "event": {"sessionID": sid, "prompt": {"text": text}}}


def context(sid, pause=50):
    return {"hook": "context", "pauseMs": pause, "event": {"sessionID": sid, "system": [], "messages": []}}


def texts(res):
    return [p["text"] for p in res["event"]["system"]]


def test_mcp_server_is_native_not_code_mode(fake):
    drive, _ = fake
    server = drive([{"hook": "setup"}])[0]["servers"]["skill-search"]
    assert server["codemode"] is False and server["type"] == "local"
    assert "environment" in server and "env" not in server


def test_top_level_turn_gets_doctrine_menu_and_ledger_row(fake):
    drive, logged = fake
    ctx_block = "<system-context>\n## Session\n- CWD: /x\n</system-context>\n"
    out = drive([{"hook": "setup"}, prompt("s1", ctx_block + "write a commit message"), context("s1"),
                 context("s1")])
    assert texts(out[2]) == ["SKILL-FIRST doctrine", "MENU for: write a commit message"]
    assert texts(out[3]) == []                       # once per turn, doctrine once per session
    turns = [r for r in logged("ledger.py", wait_for=1) if r["hook_event_name"] == "UserPromptSubmit"]
    assert turns == [{"hook_event_name": "UserPromptSubmit", "session_id": "s1",
                      "prompt": "write a commit message", "harness": "opencode"}]


def test_subagent_child_session_gets_no_doctrine_menu_or_turn(fake):
    drive, logged = fake
    out = drive([{"hook": "setup"}, prompt("child", "count the files"), context("child"),
                 prompt("s1", "top-level ask"), context("s1")],
                sessions={"child": {"parentID": "s1"}})
    assert texts(out[2]) == []
    assert [r["prompt"] for r in logged("enforcer.py")] == ["top-level ask"]
    time.sleep(0.5)    # the ledger writes are detached; give the child's (if any) time to land
    turns = [r for r in logged("ledger.py", wait_for=1) if r["hook_event_name"] == "UserPromptSubmit"]
    assert [r["session_id"] for r in turns] == ["s1"]
    assert logged("doctrine.py")[0]["agent_id"] == "child"


def test_a_turn_governed_before_the_parent_lookup_lands_is_marked_parent_lookup_pending(fake):
    drive, logged = fake
    drive([{"hook": "setup"}, prompt("slow", "first ask"), context("slow", pause=0),
           prompt("s1", "second ask"), context("s1")],
          sessions={"slow": {"parentID": "s0", "lookupMs": 400}})
    turns = {r["session_id"]: r for r in logged("ledger.py", wait_for=2)
             if r["hook_event_name"] == "UserPromptSubmit"}
    assert turns["slow"]["parent_lookup"] == "pending"   # the child was governed as top level once
    assert "parent_lookup" not in turns["s1"]
    landed = [r for r in logged("ledger.py", wait_for=3) if r["hook_event_name"] == "ConciergeParentLookup"]
    assert [(r["session_id"], r["child"]) for r in landed] == [("slow", True)]   # counted as misgoverned


def test_two_prompts_before_one_model_call_both_get_turn_rows(fake):
    drive, logged = fake
    out = drive([{"hook": "setup"}, prompt("s1", "first ask"), prompt("s1", "second ask"), context("s1")])
    assert texts(out[3])[-1] == "MENU for: second ask"
    time.sleep(0.3)
    turns = [r["prompt"] for r in logged("ledger.py", wait_for=2) if r["hook_event_name"] == "UserPromptSubmit"]
    assert sorted(turns) == ["first ask", "second ask"]


def test_refused_skill_call_is_not_logged_and_child_use_is_stamped(fake):
    drive, logged = fake
    def ev(sid, status, err=None, meta_err=False):
        return {"hook": "execute.after", "event": {
            "tool": "skill", "sessionID": sid, "input": {"id": "doctor"}, "status": status, "error": err,
            "result": {"content": [{"type": "text", "text": "body"}], "metadata": {"error": meta_err}}}}
    out = drive([{"hook": "setup"}, prompt("child", "x"), context("child"),
                 ev("s1", "error", "blocked"), ev("s1", "completed", meta_err=True),
                 ev("s1", "completed"), ev("child", "completed")],
                sessions={"child": {"parentID": "s1"}})
    time.sleep(0.3)
    rows = [r for r in logged("ledger.py", wait_for=2) if r["hook_event_name"] == "PostToolUse"]
    assert sorted((r["session_id"], r.get("agent_id") or "") for r in rows) == [("child", "child"), ("s1", "")]
    assert out[5]["event"]["result"]["content"][-1] == {"type": "text", "text": "NOT-FOR echo"}
    for refused in (out[3], out[4]):
        assert refused["event"]["result"]["content"] == [{"type": "text", "text": "body"}]


def test_blocklisted_skill_is_denied_only_that_call(fake):
    drive, _ = fake
    perm = lambda skill: {"hook": "evaluate", "event": {"action": "skill", "sessionID": "s1",
                                                         "resources": [skill]}}
    out = drive([{"hook": "setup"}, perm("blocked-skill"), perm("doctor")])
    assert out[1]["event"]["effect"] == "deny" and out[1]["event"]["message"] == "blocked by test"
    assert "effect" not in out[2]["event"]
