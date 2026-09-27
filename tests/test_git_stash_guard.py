"""scripts/git_stash_guard.py — the PreToolUse(Bash) gate that denies, by default, any
`git stash` invocation that can change state (owner rule: no git stash; added directly in
response to two accidental uses during v0.54.2 release work, then hardened after a round-3
adversarial review found several forms that tokenize as `git ... stash` but slipped past the
first draft). Covers the draft's own `_selftest()` case list directly (import, not subprocess,
for speed), one real end-to-end invocation through stdin — the exact shape Claude Code actually
feeds a PreToolUse hook — and a real-git proof in a throwaway `/tmp` repo that the six
previously-confirmed bypasses really do create a stash when the guard is not in the way."""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "scripts" / "git_stash_guard.py"

# Deny-by-default core: bare/optioned forms, global git options, env prefixes, absolute
# path, backslash escape, and the fused `git-stash` executable name.
DENY_COMMANDS = [
    "git stash", "git stash -u", "git stash push -m x", "git stash pop", "git stash apply",
    "git stash drop", "git stash clear", "git -C /tmp/x stash", "git add . && git stash -u",
    "FOO=1 git stash save wip", "cd a; git stash branch b", "git -c k=v stash",
    "git --git-dir=/x stash", "git --no-pager stash", "GIT_DIR=x git stash",
    "/usr/bin/git stash", "\\git stash", "git-stash push -m x",
]

# Round-3-review bypasses (code-reviewer-260927-2025-v0542-round3-delta.md, finding M-A):
# each of these was confirmed, in a real scratch repo, to create a stash while the prior
# draft allowed it. `test_confirmed_bypass_creates_a_real_stash_without_the_guard` proves
# the first six (the reviewer's own headline list) really do stash; all are denied here.
BYPASS_DENY_COMMANDS = [
    "git stash -m list", "git stash -m show", "git stash -- list",
    "(cd sub && git stash)", "(git stash)", "{ git stash; }",
    "if true; then git stash; fi", "time git stash", "nice git stash", "exec git stash",
    "git stash&", "bash -c 'git stash'", "echo $(git stash)", "eval git stash",
    "xargs git stash",
]

# The six the reviewer named explicitly as MUST-deny proof points.
REQUIRED_BYPASS_COMMANDS = [
    "git stash -m list", "git stash -- list", "(cd sub && git stash)",
    "if true; then git stash; fi", "time git stash", "git stash&",
]

DENY_COMMANDS = DENY_COMMANDS + BYPASS_DENY_COMMANDS

ALLOW_COMMANDS = [
    "git stash list", "git stash show -p", "git status", "echo git stash", "git commit -m 'stash'",
    "ls stash", "git show HEAD:x", "git -C x stash list", "echo 'git stash'",
    "git log --grep stash", "grep stash file",
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


def _make_scratch_repo():
    """A throwaway git repo under /tmp, with one committed file so a later edit gives a
    dirty tree `git stash` can act on, and a `sub/` directory for the subshell-cd form.
    Never touches a real repo or worktree."""
    repo = tempfile.mkdtemp(prefix="stash-guard-proof-")
    run = lambda *a: subprocess.run(a, cwd=repo, check=True, capture_output=True, text=True)
    run("git", "init", "-q")
    run("git", "config", "user.email", "guard-proof@test.local")
    run("git", "config", "user.name", "guard proof")
    (Path(repo) / "f.txt").write_text("a\n")
    # Also tracked as "list": `git stash -- list` reads "list" as a pathspec, which
    # only actually creates a stash if something named "list" is dirty to match it.
    (Path(repo) / "list").write_text("a\n")
    (Path(repo) / "sub").mkdir()
    run("git", "add", "f.txt", "list")
    run("git", "commit", "-q", "-m", "init")
    return repo


def _stash_count(repo):
    r = subprocess.run(["git", "stash", "list"], cwd=repo, capture_output=True, text=True, check=True)
    return len([line for line in r.stdout.splitlines() if line.strip()])


@pytest.mark.parametrize("command", REQUIRED_BYPASS_COMMANDS)
def test_confirmed_bypass_creates_a_real_stash_without_the_guard(command):
    """Proof, not a guard test: in a throwaway `/tmp` repo this test creates and deletes
    (never a real repo or worktree), each of the reviewer's six confirmed bypasses is run
    WITHOUT the guard in the way and really does create exactly one stash entry — the
    evidence `decide()` above is now denying, not a claim about the guard's own behavior."""
    repo = _make_scratch_repo()
    try:
        (Path(repo) / "f.txt").write_text("dirty\n")
        (Path(repo) / "list").write_text("dirty\n")
        before = _stash_count(repo)
        # `; wait` only matters for the backgrounded `git stash&` form; it is a no-op
        # for every other command since there is no background job to wait for.
        r = subprocess.run(command + "\nwait\n", shell=True, executable="/bin/bash",
                           cwd=repo, capture_output=True, text=True, timeout=10)
        after = _stash_count(repo)
        assert after == before + 1, (
            f"expected {command!r} to create exactly one real stash in the scratch repo; "
            f"before={before} after={after} rc={r.returncode} stdout={r.stdout!r} stderr={r.stderr!r}"
        )
    finally:
        shutil.rmtree(repo, ignore_errors=True)
