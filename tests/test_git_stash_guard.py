"""scripts/git_stash_guard.py — the PreToolUse(Bash) gate that denies a state-changing
`git stash` in this repo (owner rule: no git stash; ADR-none, added directly in response to
two accidental uses during v0.54.2 release work). Covers the draft's own `_selftest()` case
list directly (import, not subprocess, for speed) plus one real end-to-end invocation through
stdin — the exact shape Claude Code actually feeds a PreToolUse hook — so a wiring mistake in
`main()`'s own JSON handling (not just `decide()`'s logic) is caught too."""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "scripts" / "git_stash_guard.py"

DENY_COMMANDS = [
    "git stash", "git stash -u", "git stash push -m x", "git stash pop", "git stash apply",
    "git stash drop", "git stash clear", "git -C /tmp/x stash", "git add . && git stash -u",
    "FOO=1 git stash save wip", "cd a; git stash branch b",
]
ALLOW_COMMANDS = [
    "git stash list", "git stash show -p", "git status", "echo git stash", "git commit -m 'stash'",
    "ls stash", "git show HEAD:x",
]


@pytest.fixture(scope="module")
def guard():
    spec = importlib.util.spec_from_file_location("git_stash_guard", GUARD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("command", DENY_COMMANDS)
def test_decide_denies_every_state_changing_stash_form(command, guard):
    assert guard.decide(command), f"expected a deny reason for {command!r}"


@pytest.mark.parametrize("command", ALLOW_COMMANDS)
def test_decide_allows_read_only_and_unrelated_commands(command, guard):
    assert guard.decide(command) is None, f"expected no deny for {command!r}"


def test_selftest_entrypoint_reports_ok(guard):
    """The draft's own bundled self-check, run in-process so a failure prints the same
    mismatch list `python3 scripts/git_stash_guard.py --selftest` would on the CLI."""
    assert guard._selftest() == 0


def _run_hook(command, env_overrides=None):
    """Feeds COMMAND to the guard exactly as Claude Code feeds a PreToolUse(Bash) hook:
    the tool_input JSON on stdin, nothing on argv. Runs the REAL file via subprocess, not
    an import, so a stdin/JSON wiring bug in `main()` itself — not just `decide()` — is
    caught too."""
    env = dict(os.environ)
    if env_overrides:
        env.update(env_overrides)
    payload = {"tool_name": "Bash", "tool_input": {"command": command}}
    return subprocess.run([sys.executable, str(GUARD)], input=json.dumps(payload),
                          capture_output=True, text=True, timeout=10, env=env)


def test_real_stdin_invocation_denies_a_stash_push():
    r = _run_hook("git stash push -u")
    assert r.returncode == 0, r.stderr   # the hook itself always exits 0; the verdict is in stdout
    out = json.loads(r.stdout)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "git stash is blocked" in out["hookSpecificOutput"]["permissionDecisionReason"]


def test_real_stdin_invocation_is_silent_for_an_unrelated_command():
    r = _run_hook("git status")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "", "an unrelated command must produce no decision at all"


def test_real_stdin_invocation_is_silent_for_read_only_stash_list():
    r = _run_hook("git stash list")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "", "git stash list must pass through with no decision"


def test_env_override_disables_the_guard():
    r = _run_hook("git stash push -u", env_overrides={"GIT_STASH_GUARD": "0"})
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "", "GIT_STASH_GUARD=0 must silence the guard entirely"


def test_malformed_stdin_fails_open():
    """The openwiki guard's own rule, applied here: a broken guard must never wedge the
    repo. Unparseable stdin must never raise or deny — it must exit 0 with no decision."""
    r = subprocess.run([sys.executable, str(GUARD)], input="not json at all",
                       capture_output=True, text=True, timeout=10)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == ""
