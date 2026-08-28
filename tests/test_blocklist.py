"""ADR-0046 blocklist — the disable tier, pinned at every layer that claims to enforce it.

Covered here:
  • skill_guard.py (PreToolUse deny): subprocess with real stdin JSON — deny a bare
    entry, deny its qualified twin, allow a non-entry, allow when the file is absent
    (the no-op default), allow under the SKILL_BLOCKLIST=0 kill-switch, allow on a
    non-Skill tool_name.
  • enforcer blocklist semantics: fresh import with the env seam pointed at a temp
    file (the module loads BLOCKLIST at import), pinning _blocked / _drop_blocklisted
    and the kill-switch.
  • blocklist.py CLI: add/remove/list round-trip on the env-seamed file.

The engine-side filter (server.py _blocked) shares the exact matcher pinned here and
is additionally exercised live by the deploy-time probe (search_skills for a blocked
indexed skill returns nothing) — it needs the venv + Qdrant, so it is not in this file.
"""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUARD = ROOT / "hooks" / "scripts" / "skill_guard.py"
ENFORCER = ROOT / "hooks" / "scripts" / "enforcer.py"
CLI = ROOT / "scripts" / "blocklist.py"


def _run_guard(payload: dict, env: dict) -> str:
    r = subprocess.run([sys.executable, str(GUARD)], input=json.dumps(payload),
                       env=env, capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr
    return r.stdout


def _skill_call(name: str) -> dict:
    return {"tool_name": "Skill", "tool_input": {"skill": name, "args": ""}}


def _decision(out: str) -> str:
    if not out.strip():
        return "allow"
    d = json.loads(out)["hookSpecificOutput"]["permissionDecision"]
    assert d in ("allow", "deny"), d
    return d


def _env_with(blocklist_path):
    return {**os.environ, "SKILL_CONCIERGE_BLOCKLIST": str(blocklist_path)}


def test_guard_denies_bare_entry_and_qualified_twin(tmp_path):
    bl = tmp_path / "blocklist.json"
    bl.write_text(json.dumps({"blocked": ["resume-session"]}), encoding="utf-8")
    env = _env_with(bl)
    assert _decision(_run_guard(_skill_call("resume-session"), env)) == "deny"
    assert _decision(_run_guard(_skill_call("someplugin:resume-session"), env)) == "deny"
    reason = json.loads(_run_guard(_skill_call("resume-session"), env))[
        "hookSpecificOutput"]["permissionDecisionReason"]
    assert "resume-session" in reason and "blocklist.py remove" in reason


def test_guard_allows_non_entries(tmp_path):
    bl = tmp_path / "blocklist.json"
    bl.write_text(json.dumps({"blocked": ["resume-session"]}), encoding="utf-8")
    env = _env_with(bl)
    assert _decision(_run_guard(_skill_call("save-session"), env)) == "allow"
    # a qualified entry is exact-only: the bare name and other origins pass
    bl.write_text(json.dumps({"blocked": ["skill-concierge:keep-on"]}), encoding="utf-8")
    assert _decision(_run_guard(_skill_call("keep-on"), env)) == "allow"
    assert _decision(_run_guard(_skill_call("ck:keep-on"), env)) == "allow"
    assert _decision(_run_guard(_skill_call("skill-concierge:keep-on"), env)) == "deny"


def test_guard_fail_open_and_kill_switch(tmp_path):
    env = _env_with(tmp_path / "absent.json")   # absent = the no-op default
    assert _decision(_run_guard(_skill_call("resume-session"), env)) == "allow"
    env2 = {**_env_with(tmp_path / "corrupt.json")}
    (tmp_path / "corrupt.json").write_text("{not json", encoding="utf-8")
    assert _decision(_run_guard(_skill_call("x"), env2)) == "allow"
    bl = tmp_path / "bl2.json"
    bl.write_text(json.dumps({"blocked": ["x"]}), encoding="utf-8")
    env3 = {**_env_with(bl), "SKILL_BLOCKLIST": "0"}
    assert _decision(_run_guard(_skill_call("x"), env3)) == "allow", "kill-switch must pass"
    # non-Skill tool calls are not our business
    assert _decision(_run_guard({"tool_name": "Bash", "tool_input": {"command": "ls"}}, env3)) == "allow"


def _load_enforcer(blocklist_path, kill_switch=None):
    env = {**os.environ, "SKILL_CONCIERGE_BLOCKLIST": str(blocklist_path)}
    if kill_switch is not None:
        env["SKILL_BLOCKLIST"] = kill_switch
    old = {k: os.environ.get(k) for k in ("SKILL_CONCIERGE_BLOCKLIST", "SKILL_BLOCKLIST")}
    os.environ.update({k: v for k, v in env.items() if v is not None})
    try:
        spec = importlib.util.spec_from_file_location(
            f"enforcer_test_{abs(hash(str(blocklist_path)))}_{kill_switch}", ENFORCER)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_enforcer_blocks_across_origins(tmp_path):
    bl = tmp_path / "bl.json"
    bl.write_text(json.dumps({"blocked": ["victim", "only:exact"]}), encoding="utf-8")
    en = _load_enforcer(bl)
    assert en._blocked("victim") and en._blocked("antigravity:victim")
    assert en._blocked("only:exact") and not en._blocked("other:exact") and not en._blocked("keep-on")
    surv, drp = en._drop_blocklisted(
        [("a", "", 0.3), ("victim", "", 0.25), ("antigravity:victim", "", 0.2), ("c", "", 0.1)])
    assert [n for n, _, _ in surv] == ["a", "c"] and drp == ["victim", "antigravity:victim"]


def test_enforcer_kill_switch_and_absent_file(tmp_path):
    bl = tmp_path / "bl.json"
    bl.write_text(json.dumps({"blocked": ["victim"]}), encoding="utf-8")
    en_off = _load_enforcer(bl, kill_switch="0")
    assert en_off.BLOCKLIST == frozenset() and not en_off._blocked("victim")
    en_absent = _load_enforcer(tmp_path / "absent.json")
    assert en_absent.BLOCKLIST == frozenset() and not en_absent._blocked("victim")


def test_cli_round_trip(tmp_path):
    bl = tmp_path / "bl.json"
    bl.write_text(json.dumps({"_note": "keep", "blocked": ["b"]}), encoding="utf-8")
    env = {**os.environ, "SKILL_CONCIERGE_BLOCKLIST": str(bl),
           "SKILL_CONCIERGE_KEEPON": str(tmp_path / "keep.json"),
           "SKILL_CONCIERGE_VENV": str(tmp_path / "no-venv")}
    run = lambda *a: subprocess.run([sys.executable, str(CLI), *a], env=env,
                                    capture_output=True, text=True, check=False)
    assert run("add", "resume-session", "b").returncode == 0        # 'b' dedups
    got = json.loads(bl.read_text())
    assert got["blocked"] == ["b", "resume-session"] and got["_note"] == "keep"
    assert "resume-session" in run("list").stdout
    assert run("remove", "resume-session").returncode == 0
    assert json.loads(bl.read_text())["blocked"] == ["b"]
