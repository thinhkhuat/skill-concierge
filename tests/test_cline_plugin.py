"""Cline code plugin (adapters/cline/skill-concierge.cline-plugin.ts, ADR-0086).

Each test copies the plugin into a fake repo root whose hooks/scripts/*.py are stubs that
record their stdin payload and print canned hook output, then drives the hooks through
tests/cline_plugin_harness.mjs with contexts shaped like Cline's runtime passes them.
"""
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "adapters" / "cline" / "skill-concierge.cline-plugin.ts"
HARNESS = ROOT / "tests" / "cline_plugin_harness.mjs"
NODE = shutil.which("node")

STUB = '''import json, os, sys, time
name = os.path.basename(__file__)
raw = sys.stdin.read()
with open(os.path.join(os.environ["STUB_LOG"], name + ".jsonl"), "a") as f:
    f.write(json.dumps({"argv": sys.argv[1:], "stdin": raw, "harness": os.environ.get("SKILL_CONCIERGE_HARNESS"),
                        "jev": os.environ.get("ENFORCER_JEV_ROUTER"), "ledger": os.environ.get("ENFORCER_LEDGER"),
                        "tier": os.environ.get("ENFORCER_JEV_TIER")}) + "\\n")
p = json.loads(raw or "{}")
def ctx(text, offer=None):
    out = {"hookSpecificOutput": {"additionalContext": text}}
    if offer and os.environ.get("ENFORCER_LEDGER") == "defer":
        out["skillConciergeOffer"] = offer
    print(json.dumps(out))
if name == "enforcer.py" and os.environ.get("ENFORCER_JEV_ROUTER") == "0":
    ctx("PREVIEW for: " + p["prompt"], {"ev": "offer", "band": "offer", "offered": [["embed-pick", 0.5]]})
elif name == "enforcer.py":
    time.sleep(float(os.environ.get("STUB_ENFORCER_SLEEP", "0")))
    ctx("MENU for: " + p["prompt"], {"ev": "offer", "band": "offer", "offered": [["jev-pick", 0.9]],
                                     "jev": {"ms": 2100}})
elif name == "skill_guard.py":
    if p["tool_input"]["skill"] == "blocked-skill":
        print(json.dumps({"hookSpecificOutput": {"permissionDecision": "deny",
                          "permissionDecisionReason": "blocked by test"}}))
elif name == "skill_exclusions.py":
    ctx("NOT-FOR echo")
elif name == "doctrine.py":
    ctx("SKILL-FIRST doctrine for " + os.environ.get("SKILL_CONCIERGE_HARNESS", "?"))
'''
SCRIPTS = ["enforcer.py", "ledger.py", "skill_guard.py", "skill_exclusions.py", "doctrine.py",
           "auto_reindex.py", "auto_overrides.py", "auto_flywheel.py", "auto_promote.py"]

pytestmark = pytest.mark.skipif(NODE is None, reason="node is required for the Cline plugin tests")


@pytest.fixture()
def fake(tmp_path):
    root, log = tmp_path / "repo", tmp_path / "log"
    (root / "adapters" / "cline").mkdir(parents=True)
    (root / "hooks" / "scripts").mkdir(parents=True)
    log.mkdir()
    shutil.copy(PLUGIN, root / "adapters" / "cline" / PLUGIN.name)
    for name in SCRIPTS:
        (root / "hooks" / "scripts" / name).write_text(STUB)
    (root / "adapters" / "cline" / "agent_plugin.py").write_text(STUB)

    def drive(calls, **env):
        e = {**os.environ, "STUB_LOG": str(log), **env}
        e.pop("SKILL_CONCIERGE_ROOT", None)
        r = subprocess.run([NODE, str(HARNESS), str(root / "adapters" / "cline" / PLUGIN.name)],
                           input=json.dumps({"calls": calls}), capture_output=True, text=True,
                           timeout=60, env=e)
        assert r.returncode == 0, r.stderr
        return json.loads(r.stdout)

    def logged(name, wait_for=0):
        path = log / f"{name}.jsonl"
        deadline = time.time() + 5
        while wait_for and time.time() < deadline:
            if path.exists() and len(path.read_text().splitlines()) >= wait_for:
                break
            time.sleep(0.05)
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    return drive, logged


def msg(mid, role, text, **meta):
    m = {"id": mid, "role": role, "content": [{"type": "text", "text": text}], "createdAt": 1}
    if meta:
        m["metadata"] = meta
    return m


HISTORY = [
    msg("m1", "user", "earlier question"),
    msg("m2", "assistant", "earlier answer"),
    msg("m3", "user", '<user_input mode="act">refactor the auth middleware</user_input>'),
    msg("m4", "user", '<hook_context source="RunStart">other hook text</hook_context>', displayRole="system"),
]


def model_call(run_id="run-1", messages=HISTORY, parent=None):
    snap = {"agentId": "a1", "conversationId": "conv-1", "runId": run_id, "iteration": 1,
            "parentAgentId": parent, "messages": messages}
    return {"hook": "beforeModel", "context": {"snapshot": snap, "request": {"messages": messages}}}


def test_menu_is_added_after_the_prompt_and_nothing_is_dropped(fake):
    drive, logged = fake
    [res] = drive([model_call()])
    out = res["result"]["messages"]
    assert [m["id"] for m in out[:3]] == ["m1", "m2", "m3"]
    assert out[3]["content"][0]["text"] == \
        '<hook_context source="skill-concierge">\nMENU for: refactor the auth middleware\n</hook_context>'
    assert out[4]["id"] == "m4" and len(out) == len(HISTORY) + 1
    # The prompt reached the enforcer without Cline's <user_input> wrapper, tagged as Cline.
    calls = logged("enforcer.py", wait_for=2)
    assert {json.loads(c["stdin"])["prompt"] for c in calls} == {"refactor the auth middleware"}
    assert all(c["harness"] == "cline" for c in calls)
    # One full pass (Jev on) and one fast preview (Jev off); both hand their offer row back.
    assert sorted((c["jev"] or "", c["ledger"] or "") for c in calls) == [("", "defer"), ("0", "defer")]


def test_one_turn_row_per_run_however_many_model_calls(fake):
    drive, logged = fake
    results = drive([model_call(), model_call(), model_call()])
    assert all(r["result"] and len(r["result"]["messages"]) == len(HISTORY) + 1 for r in results)
    assert len(logged("enforcer.py", wait_for=2)) == 2
    rows = logged("ledger.py", wait_for=1)
    time.sleep(0.3)
    rows = logged("ledger.py")
    assert [json.loads(r["stdin"])["hook_event_name"] for r in rows] == ["UserPromptSubmit", "ConciergeOffer"]


def _text(res):
    return res["result"]["messages"][3]["content"][0]["text"]


def test_slow_menu_sends_the_preview_first_then_the_full_menu(fake):
    drive, _ = fake
    first, second = drive([model_call(), {**model_call(), "pauseMs": 2500}], STUB_ENFORCER_SLEEP="3.5")
    assert first["ms"] < 2300
    assert "PREVIEW for: refactor the auth middleware" in _text(first)
    assert "MENU for: refactor the auth middleware" in _text(second)


def test_the_full_pass_runs_on_typesafe_only(fake):
    """The owner's choice (ADR-0087): Cline's Jev route bills one provider, TypeSafe."""
    drive, logged = fake
    drive([model_call()])
    calls = logged("enforcer.py", wait_for=2)
    assert sorted((c["jev"] or "", c["tier"] or "") for c in calls) == [("", "typesafe"), ("0", "")]


def test_subagents_get_no_menu_and_no_turn_row(fake):
    drive, logged = fake
    [res] = drive([model_call(parent="lead")])
    assert res["result"] is None
    time.sleep(0.3)
    assert logged("enforcer.py") == [] and logged("ledger.py") == []


def tool_call(hook, tool, input_, output=None, is_error=False):
    ctx = {"snapshot": {"agentId": "a1", "conversationId": "conv-1", "runId": "run-1"},
           "toolCall": {"type": "tool-call", "toolCallId": "t1", "toolName": tool, "input": input_},
           "input": input_}
    if hook == "afterTool":
        ctx["result"] = {"output": output, "isError": is_error}
    return {"hook": hook, "context": ctx}


def test_blocked_skill_refuses_only_that_call(fake):
    drive, logged = fake
    blocked, blocked_use, allowed, other = drive([
        tool_call("beforeTool", "skills", {"skill": "blocked-skill"}),
        tool_call("beforeTool", "use_skill", {"skill": "blocked-skill"}),
        tool_call("beforeTool", "skills", {"skill": "skill-concierge:doctor"}),
        tool_call("beforeTool", "read_files", {"path": "x"}),
    ])
    assert blocked["result"] == {"skip": True, "reason": "blocked by test"}
    assert blocked_use["result"] == {"skip": True, "reason": "blocked by test"}, \
        "Cline's other skill tool name must be guarded too"
    assert "stop" not in blocked["result"]
    assert allowed["result"] is None and other["result"] is None
    assert len(logged("skill_guard.py")) == 3


def test_get_skill_output_is_kept_and_the_echo_is_appended_as_context(fake):
    drive, logged = fake
    body = {"content": [{"type": "text", "text": "full SKILL.md body"}]}
    # Live Cline 3.0.70 names an Agent Plugin MCP tool <server>__<tool>_<hash>.
    load, search, skill, refused, other = drive([
        tool_call("afterTool", "skill-concierge_skill-search__get_skill_d998a651", {"name": "doctor"}, body),
        tool_call("afterTool", "skill-concierge_skill-search__search_skills_4d64eb2e", {"query": "x"}, body),
        tool_call("afterTool", "skills", {"skill": "doctor"}, "doctor body"),
        tool_call("afterTool", "skills", {"skill": "keep-on"}, {"error": "disabled"}, is_error=True),
        tool_call("afterTool", "read_files", {"path": "x"}, "text"),
    ])
    assert load["result"] == {"appendContext": "NOT-FOR echo"}
    assert skill["result"] == {"appendContext": "NOT-FOR echo"}
    assert search["result"] is None and refused["result"] is None and other["result"] is None
    rows = logged("ledger.py", wait_for=3)
    time.sleep(0.3)
    rows = logged("ledger.py")
    names = sorted(json.loads(r["stdin"])["tool_name"] for r in rows)
    # The refused call writes no row: it was never a use.
    assert names == ["Skill", "skill-search__get_skill", "skill-search__search_skills"]


def test_setup_registers_the_cline_doctrine_and_starts_self_heal(fake):
    drive, logged = fake
    [res] = drive([{"hook": "setup"}])
    assert res["result"]["rules"] == [{"id": "skill-concierge:skill-first",
                                       "content": "SKILL-FIRST doctrine for cline"}]
    for name in ("auto_reindex.py", "auto_overrides.py", "auto_flywheel.py", "auto_promote.py"):
        assert logged(name, wait_for=1), name
    [sync] = logged("agent_plugin.py", wait_for=1)
    assert sync["argv"] == ["sync"]


@pytest.mark.parametrize("harness_env", [{"SKILL_CONCIERGE_HARNESS": "cline"},
                                         {"CLAUDE_PLUGIN_ROOT": "/x/.cline/plugins/skill-concierge"}])
def test_real_doctrine_renders_for_cline(harness_env):
    env = {k: v for k, v in os.environ.items()
           if k not in ("SKILL_CONCIERGE_HARNESS", "OMPCODE", "ZCODE_PLUGIN_ROOT", "DSH_SHELL")}
    env.update(harness_env)
    r = subprocess.run(["python3", str(ROOT / "hooks" / "scripts" / "doctrine.py")],
                       input="{}", capture_output=True, text=True, timeout=30, env=env)
    text = json.loads(r.stdout.strip().splitlines()[-1])["hookSpecificOutput"]["additionalContext"]
    assert text.startswith("## SKILL-FIRST")
    # The Agent Plugin's MCP tool, as Cline names it (ADR-0086), not Claude Code's name.
    assert "skill-concierge_skill-search__search_skills_<suffix>" in text
    assert "mcp__plugin_skill-concierge" not in text


@pytest.mark.parametrize("flag,rows", [("0", 0), ("1", 1), ("defer", 0)])
def test_enforcer_ledger_switch(tmp_path, flag, rows):
    env = {**os.environ, "SKILL_CONCIERGE_LOG": str(tmp_path), "ENFORCER_LEDGER": flag,
           "ENFORCER_JEV_ROUTER": "0", "SKILL_OWNER_AUTOSTART": "0", "SKILL_CONCIERGE_HARNESS": "cline"}
    r = subprocess.run(["python3", str(ROOT / "hooks" / "scripts" / "enforcer.py")],
                       input=json.dumps({"prompt": "write a docker compose file for postgres", "session_id": "t"}),
                       capture_output=True, text=True, timeout=60, env=env)
    assert r.returncode == 0
    ledger = tmp_path / "skill-invocation-ledger.log"
    offers = [l for l in ledger.read_text().splitlines() if '"ev": "offer"' in l] if ledger.exists() else []
    assert len(offers) == rows
    out = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {}
    if flag == "defer":   # the row comes back to the caller instead, in the same one JSON object
        assert out["skillConciergeOffer"]["ev"] == "offer" and out["skillConciergeOffer"]["sid"] == "t"
        assert out["hookSpecificOutput"]["additionalContext"]
    else:
        assert "skillConciergeOffer" not in out


def test_ledger_appends_a_handed_back_offer_row(tmp_path):
    env = {**os.environ, "SKILL_CONCIERGE_LOG": str(tmp_path)}
    offer = {"t": 1.0, "sid": "s", "ev": "offer", "band": "offer", "offered": [["x", 0.5]], "seen": "preview"}
    for payload in ({"hook_event_name": "ConciergeOffer", "offer": offer},
                    {"hook_event_name": "ConciergeOffer", "offer": {**offer, "ev": "turn"}},   # not an offer row
                    {"hook_event_name": "ConciergeOffer", "offer": "junk"}):
        subprocess.run(["python3", str(ROOT / "hooks" / "scripts" / "ledger.py")], input=json.dumps(payload),
                       capture_output=True, text=True, timeout=30, env=env)
    rows = [json.loads(l) for l in (tmp_path / "skill-invocation-ledger.log").read_text().splitlines()]
    assert rows == [offer]


def test_a_runtime_reminder_is_not_mistaken_for_the_prompt(fake):
    drive, logged = fake
    reminder = msg("m5", "user", "[SYSTEM] This run is not complete until you call one of these "
                   "terminal completion tools: attempt_completion.", userRunSpan=0)
    [res] = drive([model_call(messages=HISTORY + [reminder])])
    assert "MENU for: refactor the auth middleware" in res["result"]["messages"][3]["content"][0]["text"]
    assert {json.loads(c["stdin"])["prompt"] for c in logged("enforcer.py", wait_for=2)} == \
        {"refactor the auth middleware"}


def test_a_subagent_skill_use_is_logged_as_a_subagent_row(fake):
    drive, logged = fake
    call = tool_call("afterTool", "skills", {"skill": "doctor"}, "body")
    call["context"]["snapshot"].update({"parentAgentId": "lead", "agentId": "sub-7"})
    drive([call, tool_call("afterTool", "skills", {"skill": "doctor"}, "body")])
    rows = [json.loads(r["stdin"]) for r in logged("ledger.py", wait_for=2)]
    assert sorted(r.get("agent_id", "") for r in rows) == ["", "sub-7"]


@pytest.mark.parametrize("tool,ev", [("skill-search__search_skills", "search"),
                                     ("skill-search__get_skill", "get_skill"), ("Skill", "auto")])
def test_every_skill_lane_marks_a_subagent_row(tmp_path, tool, ev):
    """ADR-0020: a subagent's use carries `sub` on every lane the Cline plugin logs."""
    payload = {"hook_event_name": "PostToolUse", "session_id": "s", "harness": "cline",
               "tool_name": tool, "tool_input": {"query": "x", "name": "doctor", "skill": "doctor"},
               "agent_id": "sub-7"}
    env = {**os.environ, "SKILL_CONCIERGE_LOG": str(tmp_path)}
    subprocess.run(["python3", str(ROOT / "hooks" / "scripts" / "ledger.py")], input=json.dumps(payload),
                   capture_output=True, text=True, timeout=30, env=env)
    rows = [json.loads(l) for l in (tmp_path / "skill-invocation-ledger.log").read_text().splitlines()]
    assert [(r["ev"], r.get("sub")) for r in rows] == [(ev, True)]


def _offer_rows(logged, n):
    return [json.loads(r["stdin"]) for r in logged("ledger.py", wait_for=n)
            if json.loads(r["stdin"])["hook_event_name"] == "ConciergeOffer"]


def test_both_passes_hand_their_offer_row_to_the_plugin(fake):
    drive, logged = fake
    drive([model_call()])
    assert {c["ledger"] for c in logged("enforcer.py", wait_for=2)} == {"defer"}


def test_the_offer_row_is_the_full_menu_when_the_model_saw_it(fake):
    drive, logged = fake
    drive([model_call(), model_call()])
    [row] = _offer_rows(logged, 2)
    assert row["offer"]["offered"] == [["jev-pick", 0.9]] and row["offer"]["seen"] == "full"


def test_the_offer_row_is_the_preview_when_the_model_saw_the_preview(fake):
    """The first call carried the preview: the turn's offer row is the preview's menu, and the late full
    row is kept apart (ev offer_late) so offer counts never use it."""
    drive, logged = fake
    drive([model_call(), {**model_call(), "pauseMs": 2500}], STUB_ENFORCER_SLEEP="3.5")
    rows = _offer_rows(logged, 3)
    assert [(r["offer"]["ev"], r["offer"]["seen"]) for r in rows] == [("offer", "preview"), ("offer_late", "later")]
    assert rows[0]["offer"]["offered"] == [["embed-pick", 0.5]]
    assert rows[1]["offer"]["jev"] == {"ms": 2100}
